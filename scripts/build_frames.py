#!/usr/bin/env python3
"""逐帧合成「包装层」：卡段（模糊底 + 圆角卡 + 画中画 + 逐行擦出）+ 结尾发光字 + 收尾淡黑
+ 字幕层（caption_layer 用 Pillow 画，压在淡黑之上）。

设计上的三条硬约束：
  1. **慢操作挪出逐帧循环**。整屏高斯模糊在 1080×1920 上千帧里根本跑不动，
     所以先用 ffmpeg 出两条中间片 work/graded.mp4（调色）与 work/blurred.mp4
     （放大→模糊→压暗），逐帧只读不算。
  2. **不缩人**。正片全程满屏真人，不做「缩人 + 垫模糊底」；只有卡段例外。
  3. **图层顺序**：底 → 卡 → 画中画 → 标题/条目 → 图标。
     参考片里第二行的图标明显盖在画中画上，顺序错了会看起来像贴纸浮着。

无片头封面、无常驻标题、无片尾卡：全片没有任何元素横跨整条时间轴。

用法：python scripts/build_frames.py PROJECT_DIR
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).parent))
from caption_layer import CaptionLayer  # noqa: E402
from workflow import caption_plan  # noqa: E402
from _common import (  # noqa: E402
    card_layout, clamp01, ease, ease_out, find_ffmpeg, load_config, probe_media,
    project_paths, resolve_video,
)

SKILL_ROOT = Path(__file__).resolve().parent.parent


def norm_box(box, W, H):
    x0, y0, x1, y1 = box
    return (round(x0 * W), round(y0 * H), round(x1 * W), round(y1 * H))


class Compositor:
    def __init__(self, cfg: dict, project: Path):
        self.cfg = cfg
        self.project = project
        self.p = project_paths(project)
        self.W = cfg["canvas"]["width"]
        self.H = cfg["canvas"]["height"]
        self.FPS = cfg["canvas"]["fps"]
        self.card = cfg["card"]
        self.pip = cfg["pip"]
        self.gold = cfg["gold"]
        self.fade_from = None        # 由 main 按总时长设定
        self.total = 0.0
        self.assets: dict[str, Image.Image] = {}
        self.rows: list[Image.Image] = []
        self.icons: list[Image.Image] = []
        self.captions = None
        # 插图的时间窗与框位来自样式计划（正本 workflow/caption_plan.py），
        # 素材来自 assets 步画出来的 insert-*.png。
        self.inserts = caption_plan.load(cfg, project)["inserts"]

    # ---------------------------------------------------------------- 素材
    def load(self):
        a = self.p["assets"]
        need = ["card-base.png"]
        if self.card["title"]:
            need.append("card-title.png")
        need += [f"card-row-{i}.png" for i in range(1, len(self.card["rows"]) + 1)]
        need += [f"card-icon-{i}.png" for i in range(1, len(self.card["rows"]) + 1)]
        if self.gold["enabled"] and self.gold["text"]:
            need.append("gold-flash.png")
        if self.inserts["enabled"]:
            need += [item["asset"] for item in self.inserts["items"]]
        for name in need:
            f = a / name
            if not f.is_file():
                raise SystemExit(f"缺素材 {f}，先跑 scripts/make_assets.py")
            self.assets[name] = Image.open(f).convert("RGBA")
        self.rows = [self.assets[f"card-row-{i}.png"] for i in range(1, len(self.card["rows"]) + 1)]
        self.icons = [self.assets[f"card-icon-{i}.png"] for i in range(1, len(self.card["rows"]) + 1)]

        # 字幕层：默认自己画（caption_layer），字体会跟工程 fonts/ 走
        if self.cfg["captions"].get("burn", "layer") == "layer":
            try:
                self.captions = CaptionLayer(self.cfg, self.project)
                print(f"  字幕层：{self.captions.font_path.name} / "
                      f"{len(self.captions.cues)} 条", file=sys.stderr)
            except (OSError, SystemExit) as e:
                print(f"  ⚠ 字幕层没建起来（{e}），改由 render.py 走 libass", file=sys.stderr)

    # ---------------------------------------------------------------- 绘制原语
    def _canvas(self):
        return Image.new("RGBA", (self.W, self.H), (0, 0, 0, 0))

    def reveal(self, base, layer, p, x0, x1, dy=0.0, scale=1.0):
        """横向擦出：只显示 x < x0+(x1-x0)*p 的部分（参考片条目就是这么出来的）。
        dy / scale 是可选的落位感——纯擦出像一块板子被推出来，加一点点上浮和缩放
        才不会显得板。"""
        if p <= 0.004:
            return base
        xr = x0 + (x1 - x0) * min(p, 1.0)
        cropped = layer if xr >= layer.width else layer.crop((0, 0, max(int(xr), 1), layer.height))
        if abs(dy) < 0.5 and abs(scale - 1.0) <= 0.004:
            if cropped is layer:
                return Image.alpha_composite(base, layer)
            canvas = self._canvas()
            canvas.paste(cropped, (0, 0))
            return Image.alpha_composite(base, canvas)
        if abs(scale - 1.0) > 0.004:
            nw, nh = max(1, int(cropped.width * scale)), max(1, int(cropped.height * scale))
            cropped = cropped.resize((nw, nh), Image.LANCZOS)
        canvas = self._canvas()
        canvas.paste(cropped, (0, int(round(dy)) + (layer.height - cropped.height) // 2))
        return Image.alpha_composite(base, canvas)

    def _scaled_about(self, layer, k, cx, cy):
        """整幅层绕 (cx, cy) 缩放 k 倍。k=1 时原样返回，不复制。"""
        if abs(k - 1.0) <= 0.004:
            return layer
        nw, nh = max(1, int(self.W * k)), max(1, int(self.H * k))
        out = self._canvas()
        out.paste(layer.resize((nw, nh), Image.LANCZOS),
                  (int(cx - cx * k), int(cy - cy * k)))
        return out

    def _with_alpha(self, layer, a):
        if a >= 0.996:
            return layer
        out = layer.copy()
        out.putalpha(out.getchannel("A").point(lambda v: int(v * a)))
        return out

    def place_row(self, base, layer, e, style, wipe_x, row_y, settle=1.0):
        """把一行按入场进度 e（0..1）落位。

        参考片里三行都是同一种「从左擦出、同一个位置」，逐行看没问题，连起来看就是
        一块板子刷三遍——所以这里让每行可以有自己的一套动作：
          wipe       从左擦出（参考片原样）
          wipe-right 从右擦出（wipe 的镜像，和上一行形成来回）
          rise       从下 52px 淡入上浮
          pop        0.88 → 1.0 缩放弹入 + 淡入
        任何样式落位后都带一次 1.4% 的「落定微弹」（settle 0→1 收掉），
        这样条目是「落」下来而不是「贴」上去的。
        """
        if e <= 0.004:
            return base
        k = 1.0 + 0.014 * (1.0 - min(settle, 1.0))
        cx, cy = self.W / 2, row_y * self.H
        if style in ("wipe", "wipe-right"):
            x0, x1 = wipe_x[0] * self.W, wipe_x[1] * self.W
            if style == "wipe":
                left, right = 0, max(int(x0 + (x1 - x0) * e), 1)
            else:
                left, right = min(int(x1 + (x0 - x1) * e), layer.width), layer.width
            if right - left >= layer.width:
                out = layer
            else:
                out = self._canvas()
                out.paste(layer.crop((left, 0, right, layer.height)), (left, 0))
            return Image.alpha_composite(base, self._scaled_about(out, k, cx, cy))
        if style == "rise":
            out = self._with_alpha(self._scaled_about(layer, k, cx, cy), e)
            canvas = self._canvas()
            canvas.paste(out, (0, int(round((1 - e) * 52))))
            return Image.alpha_composite(base, canvas)
        if style == "pop":
            out = self._scaled_about(layer, (0.88 + 0.12 * e) * k, cx, cy)
            return Image.alpha_composite(base, self._with_alpha(out, e))
        raise SystemExit(f"card.rows[].enter 只认 wipe / wipe-right / rise / pop，收到 {style!r}")

    def add(self, base, layer, alpha=1.0, scale=1.0, cx=None, cy=None):
        if alpha <= 0.004:
            return base
        if (abs(scale - 1.0) > 0.004) or layer.size != (self.W, self.H):
            nw = max(1, int(layer.width * scale))
            nh = max(1, int(layer.height * scale))
            small = layer.resize((nw, nh), Image.LANCZOS) if (nw, nh) != layer.size else layer
            canvas = self._canvas()
            canvas.paste(small, (int((cx or self.W / 2) - nw / 2), int((cy or self.H / 2) - nh / 2)), small)
            layer = canvas
        if alpha < 0.996:
            layer = layer.copy()
            layer.putalpha(layer.getchannel("A").point(lambda v: int(v * alpha)))
        return Image.alpha_composite(base, layer)

    def pip_box(self, person):
        px0, py0, px1, py1 = norm_box(self.pip["box"], self.W, self.H)
        bw, bh = px1 - px0, py1 - py0
        ch = round(self.pip["crop_height"] * self.H / 1920)
        cw = max(2, int(round(ch * bw / bh)))
        cx, cy = round(self.pip["center"][0] * self.W), round(self.pip["center"][1] * self.H)
        crop = person.crop((cx - cw // 2, cy - ch // 2, cx - cw // 2 + cw, cy - ch // 2 + ch))
        crop = crop.resize((bw, bh), Image.LANCZOS)
        radius = round(self.pip["radius"] * self.W / 1080)
        mask = Image.new("L", (bw, bh), 0)
        ImageDraw.Draw(mask).rounded_rectangle((0, 0, bw - 1, bh - 1), radius=radius, fill=255)
        box = Image.new("RGBA", (bw, bh), (0, 0, 0, 0))
        box.paste(crop, (0, 0), mask)
        return box, mask, (px0, py0)

    # ---------------------------------------------------------------- 段落
    def compose_card(self, t, person, blur):
        base = blur.copy()
        box_px = norm_box(self.card["box"], self.W, self.H)
        # 卡框单独一条时间：0.22s 的纯横推太快，来不及被看到，就只剩「一块灰板子
        # 突然在那儿」。给框自己的时长 + 上浮 + 从 0.955 放大到位，它才是「落」下来的。
        box_dur = float(self.card.get("box_dur", self.card["wipe"]))
        p_box = ease_out(clamp01((t - self.card["start"]) / box_dur))
        base = self.reveal(base, self.assets["card-base.png"], p_box,
                           box_px[0], box_px[2] + 40,
                           dy=(1 - p_box) * 72, scale=0.955 + 0.045 * p_box)

        # 画中画先落，条目与图标压在它上面（参考片的第二行图标就是盖在画中画上的）
        # pip.enabled=false 时必须真的不画；否则卡片里会永远挂着一个关不掉的 PiP。
        if self.pip.get("enabled") and float(self.pip.get("dur") or 0) > 0:
            box, mask, (px0, py0) = self.pip_box(person)
            p_pip = ease_out(clamp01((t - self.pip["at"]) / self.pip["dur"]))
            if p_pip > 0:
                dx = int((1 - p_pip) * (box.width + 80))
                shadow = Image.new("RGBA", box.size, (0, 0, 0, 130))
                canvas = self._canvas()
                canvas.paste(shadow, (px0 - 18 + dx, py0 + 20), mask)
                canvas.paste(box, (px0 + dx, py0), mask)
                base = Image.alpha_composite(base, canvas)

        lay = card_layout(self.cfg)
        if self.card["title"]:
            p = ease(clamp01((t - self.card["title_at"]) / 0.20))
            base = self.add(base, self.assets["card-title.png"], alpha=p,
                            scale=1.0 + 0.10 * (1 - p),
                            cx=lay.get("title_cx", self.W / 2),
                            cy=lay["title_y"] * self.H)

        icon_delay, icon_dur = 0.10, 0.22
        default_enter = self.card.get("row_enter", "wipe")
        for i, row in enumerate(self.card["rows"]):
            at = float(row["at"])
            e = ease(clamp01((t - at) / self.card["wipe"]))
            settle = clamp01((t - at - self.card["wipe"]) / 0.30)   # 落位后的微弹进度
            base = self.place_row(base, self.rows[i], e, row.get("enter", default_enter),
                                  lay["wipe_x"], lay["row_y"][i], settle)
            p = ease(clamp01((t - at - icon_delay) / icon_dur))
            base = self.add(base, self.icons[i], alpha=p, scale=0.55 + 0.45 * p,
                            cx=lay["icon_x"] * self.W, cy=lay["row_y"][i] * self.H)
        return base

    def compose_gold(self, t, base):
        g = self.gold
        if not (g["enabled"] and g["text"]) or not (g["in"] <= t <= g["out"]):
            return base
        p_in = ease(clamp01((t - g["in"]) / 0.28))
        p_out = ease(clamp01((g["out"] - t) / 0.30))
        a = min(p_in, p_out)
        scrim = Image.new("RGBA", (self.W, self.H), (0, 0, 0, int(96 * a)))
        base = Image.alpha_composite(base, scrim)
        return self.add(base, self.assets["gold-flash.png"], alpha=a,
                        scale=1.0 + 0.22 * (1 - p_in), cx=self.W / 2, cy=self.H * 0.469)

    def compose_inserts(self, t, base):
        """插图落在**人物层之上、字幕层之下**：字幕永远压在最上面。

        入场是「上浮 + 微放大 + 淡入」，出场只淡出 —— 和卡片条目的落位感一致。
        """
        if not self.inserts["enabled"]:
            return base
        for item in self.inserts["items"]:
            if not (item["start"] <= t <= item["end"]):
                continue
            art = self.assets[item["asset"]]
            rise = ease_out(clamp01((t - item["start"]) / 0.34))
            fade_out = ease(clamp01((item["end"] - t) / 0.22))
            x0, y0, x1, y1 = item["box"]
            cx, cy = (x0 + x1) / 2 * self.W, (y0 + y1) / 2 * self.H
            scaled = self._scaled_about(art, 0.94 + 0.06 * rise, cx, cy)
            canvas = self._canvas()
            canvas.paste(scaled, (0, int(round((1 - rise) * 42))))
            alpha = min(rise, fade_out)
            if item["layout"] == "panel":
                # 整屏图形段：先把底下的画面压暗，图形才立得住。
                base = Image.alpha_composite(
                    base, Image.new("RGBA", (self.W, self.H),
                                    (0, 0, 0, int(112 * alpha))))
            base = Image.alpha_composite(base, self._with_alpha(canvas, alpha))
        return base

    def compose(self, t, person, blur):
        if self.card["enabled"] and self.card["start"] <= t <= self.card["end"]:
            base = self.compose_card(t, person, blur)
        else:
            base = person
        base = self.compose_inserts(t, base)
        base = self.compose_gold(t, base)
        if t > self.fade_from:
            k = 1.0 - (t - self.fade_from) / max(self.total - self.fade_from, 1e-6)
            base = Image.alpha_composite(
                base, Image.new("RGBA", (self.W, self.H), (0, 0, 0, int(255 * (1 - k)))))
        # 字幕压在淡黑之上：收尾淡黑不许把最后一句一起吃掉
        if self.captions is not None:
            base = self.captions.draw(base, t)
        return base


def build_intermediates(cfg: dict, project: Path) -> tuple[Path, Path | None, float]:
    p = project_paths(project)
    src = resolve_video(cfg, project)
    W, H, fps = cfg["canvas"]["width"], cfg["canvas"]["height"], cfg["canvas"]["fps"]
    ff = find_ffmpeg()
    graded = p["work"] / "graded.mp4"
    g = cfg["grade"]
    vf = (f"scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},fps={fps},setsar=1"
          + (f",{g['eq']}" if g["enabled"] and g["eq"] else ""))
    subprocess.run([ff, "-v", "error", "-y", "-i", str(src), "-map", "0:v", "-vf", vf,
                    "-an", "-c:v", "libx264", "-preset", "medium", "-crf", "16",
                    "-pix_fmt", "yuv420p", str(graded)], check=True)

    blurred = None
    if cfg["card"]["enabled"]:
        blurred = p["work"] / "blurred.mp4"
        bvf = (f"scale={int(W * 1.12)}:{int(H * 1.12)}:force_original_aspect_ratio=increase,"
               f"crop={W}:{H},fps={fps},{g['blur']},"
               f"eq=brightness=-{g['darken']}:contrast=1.02,setsar=1")
        subprocess.run([ff, "-v", "error", "-y", "-i", str(src), "-map", "0:v", "-vf", bvf,
                        "-an", "-c:v", "libx264", "-preset", "medium", "-crf", "18",
                        "-pix_fmt", "yuv420p", str(blurred)], check=True)
    return graded, blurred, probe_media(graded)["duration"]


def build(cfg: dict, project: Path, total: float | None = None) -> dict:
    p = project_paths(project)
    graded, blurred, dur = build_intermediates(cfg, project)
    if total is not None and abs(float(total) - dur) > 0.25:
        raise SystemExit("包装时长与当前粗剪不一致；请修改镜头表重新粗剪，不能用旧片长截取画面")
    total = float(dur)
    nframes = int(round(total * cfg["canvas"]["fps"]))

    comp = Compositor(cfg, project)
    comp.load()
    comp.total = total
    comp.fade_from = total - float(cfg["segments"]["fade_out"])
    W, H, fps = comp.W, comp.H, comp.FPS

    ff = find_ffmpeg()
    dec_p = subprocess.Popen([ff, "-v", "error", "-i", str(graded), "-map", "0:v",
                              "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                             stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    dec_b = None
    if blurred is not None:
        dec_b = subprocess.Popen([ff, "-v", "error", "-i", str(blurred), "-map", "0:v",
                                  "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                                 stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    out = p["work"] / "body-anim-silent.mp4"
    enc = subprocess.Popen([ff, "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24",
                            "-s", f"{W}x{H}", "-r", str(fps), "-i", "-", "-an",
                            "-c:v", "libx264", "-preset", "medium", "-crf", "17",
                            "-pix_fmt", "yuv420p", str(out)],
                           stdin=subprocess.PIPE, stderr=subprocess.DEVNULL)

    fb = W * H * 3
    written = 0
    for f in range(nframes):
        raw_p = dec_p.stdout.read(fb)
        if len(raw_p) < fb:
            break
        person = Image.frombytes("RGB", (W, H), raw_p).convert("RGBA")
        blur = person
        if dec_b is not None:
            raw_b = dec_b.stdout.read(fb)
            if len(raw_b) == fb:
                blur = Image.frombytes("RGB", (W, H), raw_b).convert("RGBA")
        enc.stdin.write(comp.compose(f / fps, person, blur).convert("RGB").tobytes())
        written += 1
        if f % 150 == 0:
            print(f"  frame {f}/{nframes}", file=sys.stderr, flush=True)

    enc.stdin.close()
    dec_p.stdout.close()
    if dec_b is not None:
        dec_b.stdout.close()
    dec_p.wait()
    if dec_b is not None:
        dec_b.wait()
    if enc.wait() != 0:
        raise SystemExit("逐帧编码失败")
    print(f"  work/body-anim-silent.mp4  {written} 帧 / {total:.3f}s")
    return {"frames": written, "duration": round(total, 3)}


def main() -> None:
    project = Path(sys.argv[1] if len(sys.argv) > 1 else ".").resolve()
    total = float(sys.argv[2]) if len(sys.argv) > 2 else None
    build(load_config(project_paths(project)["config"]), project, total)


if __name__ == "__main__":
    main()
