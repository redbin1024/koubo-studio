#!/usr/bin/env python3
"""字幕层：用 Pillow 把 SRT 逐帧画成透明图层，合成阶段直接贴上去。

为什么不继续用 libass 烧字幕：macOS 上 ffmpeg 链的 libass 只带 CoreText
provider，而 CoreText provider **不支持 fontsdir**（它只认系统已安装字体）。
于是「把字体丢进工程 fonts/ 就能换」这条最该有的能力在 macOS 上直接失效 ——
字体没装进系统，字幕就整屏方框。

字体一旦从「系统已安装」变成「工程自带」，几何、描边、投影、动画就都得自己管：
所以这里按 ASS 那套语义复刻一遍（字号自适应 / 双强调色 / 硬描边 / 明显投影 /
入场动效），渲出来的观感和卡片、金色大字是同一套字体、同一套视觉。

**逐条样式从 `work/style-plan.json` 读**（正本 `workflow/caption_plan.py`）：
尺寸 / 描边 / 投影 / 字距 / 版式 / 动效都是逐条的，草稿侧读同一份。
没有指令、没有自定义样式时，逐条行为与加这套东西之前一致（首句 hook + 其余淡入淡出）。

用法：由 build_frames.py 调用，不单独执行。
"""
from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, str(Path(__file__).parent))
from _common import (  # noqa: E402
    clamp01, find_font, parse_caption_text, project_paths, strip_punct,
)
from workflow import caption_plan  # noqa: E402

LINE_PITCH = 1.30        # 行高 = 字号 × 1.30（ASS 默认行距偏大，竖屏字幕要更紧）
DESCENT_EM = 1.34        # 「ascent 顶 → 字身下沿(含描边)」的实测系数，见 _render_line
SHADOW_ALPHA = 0.52      # ASS 样式里 BackColour 是 &H7A000000 —— 约 52% 黑
SIDE_WIDTH = 0.62        # side 版式占画面宽度
SIDE_Y = 0.60            # side 版式的垂直位置（画面高度比例）
RISE_PX = 64             # rise 的起步位移


def _ease_out(p: float) -> float:
    return 1.0 - (1.0 - p) ** 3


class CaptionLayer:
    """把 SRT 渲成「一条字幕一张透明底片」，逐帧只算 alpha、缩放与位移。"""

    def __init__(self, cfg: dict, project: Path):
        self.cfg = cfg
        self.cap = cfg["captions"]
        self.W = cfg["canvas"]["width"]
        self.H = cfg["canvas"]["height"]
        self.FPS = cfg["canvas"]["fps"]
        self.plan = caption_plan.load(cfg, project)
        self.strip_punct = bool(self.cap["strip_punctuation"])
        p = project_paths(project)
        self.font_path = find_font(self.cap["font"], project)
        self.fonts: dict[int, ImageFont.FreeTypeFont] = {}
        self.cues = self._build(p["input"] / (cfg["input"]["subtitle"] or "captions.srt"))

    # ---------------------------------------------------------------- 准备
    def _font(self, size: int) -> ImageFont.FreeTypeFont:
        if size not in self.fonts:
            self.fonts[size] = ImageFont.truetype(str(self.font_path), max(int(size), 8))
        return self.fonts[size]

    def _measure(self, text: str, font, tracking: float) -> float:
        if tracking <= 0:
            return font.getlength(text)
        return sum(font.getlength(ch) for ch in text) + tracking * max(0, len(text) - 1)

    def _draw_text(self, d, xy, text, font, fill, stroke, tracking):
        x, y = xy
        if tracking <= 0:
            d.text((x, y), text, font=font, fill=fill,
                   stroke_width=stroke, stroke_fill=(0, 0, 0, 255), anchor="la")
            return
        for ch in text:
            d.text((x, y), ch, font=font, fill=fill,
                   stroke_width=stroke, stroke_fill=(0, 0, 0, 255), anchor="la")
            x += font.getlength(ch) + tracking

    def _render_line(self, spans, size: int, look: dict):
        """一行 → 一张贴片（含硬描边 + 右下投影），返回 (RGBA, y_offset)。"""
        outline, shadow = int(look["outline"]), int(look["shadow"])
        tracking = float(look["tracking"])
        pal = look["palette"]
        font = self._font(size)
        pad = outline + shadow + max(4, size // 8)
        plain_w = sum(self._measure(t, font, tracking) for t, _ in spans)
        lh = int(round(size * LINE_PITCH))
        w = int(plain_w + pad * 2)
        # 贴片高度必须装得下「投影 + 描边 + 真正的字身下沿」，不能按 1.05em 估。
        # Pillow 的 anchor="la" 把 y 定位在**字体 ascent**上，而 CJK 字体的 ascent 比
        # 汉字墨迹顶高出一截（Noto Sans CJK 实测 ≈0.14em），汉字墨迹底又在基线下
        # ≈0.28em。于是「ascent 顶 → 墨迹底」≈1.28em，比 LINE_PITCH(1.30em) 还大，
        # 按 1.05em 开画布会把每个字的底横直接削平（两行字幕的第一行尤其明显）。
        glyph_h = int(round(size * DESCENT_EM)) + pad * 2 + shadow
        h = max(lh, glyph_h)

        layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        d = ImageDraw.Draw(layer)
        x = pad
        baseline = pad + int(round(size * 0.10))
        for text, role in spans:
            color = (255, 255, 255, 255) if not role else _rgba(pal[role])
            self._draw_text(d, (x, baseline), text, font, color, outline, tracking)
            x += self._measure(text, font, tracking) + tracking

        if shadow > 0:
            sh = Image.new("RGBA", (w, h), (0, 0, 0, 0))
            sh.paste((0, 0, 0, int(255 * SHADOW_ALPHA)), (0, 0), layer.getchannel("A"))
            out = Image.new("RGBA", (w, h), (0, 0, 0, 0))
            out.alpha_composite(sh, (shadow, shadow))
            out.alpha_composite(layer)
            layer = out
        return layer, baseline

    def _fit_size(self, lines: list[str], look: dict) -> int:
        """按**实测字宽**收缩字号，而不是按字数估。

        同样字号下不同字体的字身宽能差 20%+（得意黑只有 0.8em，常规黑体是 1.0em），
        按「max_width / 字数」估会在宽字身上直接把行顶出画面。这里从**本条**的字号上限
        起步实测，够放就停 —— 换成任何字体、任何样式都不需要重新手算字号。
        """
        size = int(look["size"])
        budget = self._budget(look)
        while size > 12:
            font = self._font(size)
            if max(self._measure(ln, font, float(look["tracking"])) for ln in lines) <= budget:
                return size
            size -= 2
        return size

    def _budget(self, look: dict) -> int:
        if look["layout"] == "side":
            return int(self.W * SIDE_WIDTH) - int(self.cap["margin_lr"])
        return int(look["max_width"])

    def _render_block(self, lines, size: int, look: dict, width: int | None = None):
        """整条字幕 → 一张贴片。

        高度按「前 n-1 行各占一个行距 + 最后一行占它自己的整高」算。
        原来写的是 `lh * len(pieces)`：行距(1.30em) 小于贴片真高(≈1.34em + padding)，
        每一行的下半截都会被画布底边削掉 —— 单行字幕的下沿、双行字幕的第一行都缺一截。
        """
        width = width or self.W
        spans_per_line = [parse_caption_text(ln) for ln in lines]
        pieces = [self._render_line(sp, size, look) for sp in spans_per_line]
        lh = int(round(size * LINE_PITCH))
        h = lh * (len(pieces) - 1) + max(piece.height for piece, _ in pieces)
        strip = Image.new("RGBA", (width, h), (0, 0, 0, 0))
        left = 0 if look["layout"] == "side" else None
        for i, (piece, _) in enumerate(pieces):
            # x 允许是负数：hook 把整行放大到 330% 时字宽超出画幅，
            # 靠这个负偏移左右对称地裁掉，看起来才是「从中间放大收回」。
            x = (width - piece.width) // 2 if left is None else left
            strip.alpha_composite(piece, (x, i * lh))
        return strip

    def _anchor_y(self, look: dict, height: int) -> int:
        layout = look["layout"]
        if layout == "top":
            return int(look["margin_v"])
        if layout == "center":
            return (self.H - height) // 2
        if layout == "side":
            return int(self.H * SIDE_Y)
        return self.H - int(look["margin_v"]) - height

    # ---------------------------------------------------------------- 动效
    def _anim_frames(self, lines, size: int, look: dict, width: int, anim: str):
        """按逐条动效预渲染入场帧。返回 [(底片, dx, dy)]，空表示只有淡入淡出。"""
        if anim == "hook":
            hook = look.get("hook") or self.cap["hook"]
            n = max(1, int(round(hook["ms"] / 1000.0 * self.FPS)))
            scale = hook["scale"] / 100.0
            frames = []
            for k in range(n + 1):
                p = clamp01(k / n)
                # 复刻 ASS 的 \\t(t1,t2,accel)：progress = p^accel，accel 2.6 是
                # 「前段几乎保持超大、末尾快速收回」。描边也跟着一起收，否则
                # 330% 的大字配厚描边会糊成一团黑。
                f = scale + (1.0 - scale) * (p ** float(hook["accel"]))
                thin = max(1, int(round(look["outline"] * (0.25 + 0.75 * p))))
                small = {**look, "outline": thin}
                frames.append((self._render_block(lines, max(8, int(round(size * f))),
                                                  small, width), 0, 0))
            return frames
        ms = max(1, int(look.get("anim_ms") or 0))
        n = max(1, int(round(ms / 1000.0 * self.FPS)))
        if anim == "pop":
            return [(self._render_block(lines, max(8, int(round(size * (0.78 + 0.22 * _ease_out(k / n))))),
                                        look, width), 0, 0) for k in range(n + 1)]
        if anim == "rise":
            frames = []
            for k in range(n + 1):
                p = _ease_out(k / n)
                img = self._render_block(lines, size, look, width).copy()
                img.putalpha(img.getchannel("A").point(lambda v, p=p: int(v * p)))
                frames.append((img, 0, int(round(RISE_PX * (1 - p)))))
            return frames
        if anim == "wipe":
            base = self._render_block(lines, size, look, width)
            frames = []
            for k in range(n + 1):
                img = base.copy()
                keep = int(base.width * _ease_out(k / n))
                mask = Image.new("L", base.size, 0)
                mask.paste(255, (0, 0, max(1, keep), base.height))
                img.putalpha(Image.composite(img.getchannel("A"),
                                             Image.new("L", base.size, 0), mask))
                frames.append((img, 0, 0))
            return frames
        return []

    def _karaoke_frames(self, lines, size: int, look: dict, width: int):
        """逐字上色：把每一行按字符累积上色成一张底片。

        按 cue 时长**均分**推进，不假装逐词对时 —— 逐词对时要求文案与转写逐字一致，
        本工程允许人工改字幕（人名、术语），那条前提不成立，所以不去猜。
        """
        total = sum(len("".join(t for t, _ in parse_caption_text(ln))) for ln in lines)
        if total <= 0:
            return []
        spans = [parse_caption_text(ln) for ln in lines]
        frames = []
        for step in range(total):
            counter, painted = 0, []
            for line_spans in spans:
                out = []
                for text, role in line_spans:
                    head = max(0, min(len(text), step + 1 - counter))
                    if head:
                        out.append((text[:head], role or "accent"))
                    if head < len(text):
                        out.append((text[head:], role))
                    counter += len(text)
                painted.append(out)
            frames.append((self._render_block_lines(painted, size, look, width), 0, 0))
        return frames

    def _render_block_lines(self, painted, size: int, look: dict, width: int):
        pieces = [self._render_line(sp, size, look) for sp in painted]
        lh = int(round(size * LINE_PITCH))
        h = lh * (len(pieces) - 1) + max(piece.height for piece, _ in pieces)
        strip = Image.new("RGBA", (width, h), (0, 0, 0, 0))
        left = 0 if look["layout"] == "side" else None
        for i, (piece, _) in enumerate(pieces):
            # x 允许是负数：hook 把整行放大到 330% 时字宽超出画幅，
            # 靠这个负偏移左右对称地裁掉，看起来才是「从中间放大收回」。
            x = (width - piece.width) // 2 if left is None else left
            strip.alpha_composite(piece, (x, i * lh))
        return strip

    # ---------------------------------------------------------------- 构建
    def _build(self, srt: Path) -> list[dict]:
        cues = []
        for meta in self.plan["cues"]:
            look = dict(meta)
            lines = [ln for ln in meta["lines"] if ln.strip()]
            if not lines:
                continue
            # 量宽度用的是**脱掉标点**后的文本（房规要求 SRT 本来就不带标点，
            # 但量字宽这一层不能假定它干净），渲染仍用原文，和以前一致。
            measured = [strip_punct("".join(t for t, _ in parse_caption_text(ln)))
                        if self.strip_punct else ln for ln in lines]
            size = self._fit_size(measured, look)
            width = int(self.W * SIDE_WIDTH) if look["layout"] == "side" else self.W
            strip = self._render_block(lines, size, look, width)
            anim = look["anim"]
            frames = (self._karaoke_frames(lines, size, look, width) if anim == "karaoke"
                      else self._anim_frames(lines, size, look, width, anim))
            # 逐字上色按 cue 时长均分；其余动效按自己的入场时长。
            span = (meta["end"] - meta["start"]) if anim == "karaoke" else \
                max(0.05, (meta["anim_ms"] or 0) / 1000.0)
            cues.append({
                "start": meta["start"], "end": meta["end"], "strip": strip,
                "anim": anim, "layout": look["layout"], "margin_v": look["margin_v"],
                "frames": frames, "frames_span": span,
                "fade_in": meta["fade_in_ms"] / 1000.0,
                "fade_out": meta["fade_out_ms"] / 1000.0,
            })
        return cues

    # ---------------------------------------------------------------- 合成
    def draw(self, base: Image.Image, t: float):
        for cue in self.cues:
            if not (cue["start"] <= t < cue["end"]):
                continue
            if cue["frames"]:
                elapsed = t - cue["start"]
                if cue["anim"] == "karaoke":
                    p = clamp01(elapsed / max(1e-3, cue["frames_span"]))
                    index = min(len(cue["frames"]) - 1, int(p * len(cue["frames"])))
                else:
                    index = min(len(cue["frames"]) - 1,
                                int(elapsed * self.FPS))
                strip, dx, dy = cue["frames"][index]
                a = clamp01(elapsed / max(0.05, cue["fade_in"]))
                if cue["anim"] == "karaoke":
                    a = min(a, clamp01((cue["end"] - t) / max(1e-3, cue["fade_out"])))
            else:
                a = min(clamp01((t - cue["start"]) / max(1e-3, cue["fade_in"])),
                        clamp01((cue["end"] - t) / max(1e-3, cue["fade_out"])))
                strip, dx, dy = cue["strip"], 0, 0
            if a <= 0.004:
                return base
            y = self._anchor_y(cue, strip.height) + dy
            if a < 0.996:
                strip = strip.copy()
                strip.putalpha(strip.getchannel("A").point(lambda v: int(v * a)))
            out = base.copy()
            # y 同样允许是负数（hook 的巨字比画幅还高，靠负偏移裁上下）。
            out.alpha_composite(strip, (dx, y))
            return out
        return base


def _rgba(value: str):
    v = value.lstrip("#")
    return (int(v[0:2], 16), int(v[2:4], 16), int(v[4:6], 16), 255)
