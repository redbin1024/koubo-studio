#!/usr/bin/env python3
"""按配置生成信息卡的整屏素材（PNG）：卡底、标题、条目、图标、结尾发光大字。

几何全部来自 config 的归一化坐标 × 画布，所以换画布尺寸不用改代码。

素材渲染踩过的坑：
  - PIL 渲染 Apple Color Emoji **只接受固定点阵尺寸**（160 可以，164 直接抛
    `OSError: invalid pixel size`）。要别的尺寸只能先渲 160 再 resize。
  - 金色发光字要把「描边」和「字身」拆成两张 mask：画在同一层里，渐变会把描边
    也填成金色，字糊成一团；而且渐变必须覆盖整幅高度，否则字会被横向切掉一半。

用法：python scripts/make_assets.py PROJECT_DIR
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont

sys.path.insert(0, str(Path(__file__).parent))
from _common import (  # noqa: E402
    CARD_WIPE_X, card_layout, find_emoji_font, find_font, hex_to_rgba, match_font,
    load_config, project_paths, write_json,
)

REF_W = 1080                    # 配置里的字号都是按 1080 宽写死的，其它宽度等比缩
EMOJI_PX = 160                  # Apple Color Emoji 唯一可用的点阵尺寸
INK = (18, 14, 10, 255)

# 卡面主题。缺省 flat = 参考片量出来的样子（浅灰底 + 粗白边 + 黑描边字）。
# theme.skin = "glass" 换成深色磨砂卡：浅灰底配金字最显廉价（金色要暗底才亮得
# 起来），磨砂底 + 发丝边 + 金色点缀才是「精致」那一档。
FLAT_THEME: dict = {}
GLASS_THEME = {
    "skin": "glass",
    "top": "#1C1E25", "bottom": "#0B0C10",
    "top_alpha": 0.94, "bottom_alpha": 0.55,
    "border": "#FFFFFF", "border_alpha": 0.16, "border_width": 2,
    "shadow_alpha": 0.38, "shadow_blur": 46, "shadow_dy": 26,
    "radius": 44,
    "divider_alpha": 0.10,
    "divider_width": 2,
    "icon_tile_alpha": 0.07, "icon_tile_border_alpha": 0.10,
    "icon_tile_size": 132, "icon_size": 92,
    "title_size": 58, "title_rule_w": 160, "title_rule_h": 5, "title_rule_gap": 52,
    "footnote_size": 30, "footnote_color": "#C9B47A",
    "text_shadow_alpha": 0.55, "text_shadow_blur": 11, "text_shadow_dy": 3,
    "num_size": 62, "num_color": "",
    "main_size": 54, "sub_size": 32, "sub_color": "#96A0AE",
}


def card_theme(card: dict) -> dict:
    """卡面主题 = 内置默认 + 配置里的 card.theme 覆盖。"""
    base = dict(GLASS_THEME) if card.get("theme") else dict(FLAT_THEME)
    base.update(card.get("theme") or {})
    return base


def _font(path: Path, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(path), max(int(size), 8))


def _stroked(d: ImageDraw.ImageDraw, xy, text, font, fill, stroke, sw, anchor="la", tracking=0.0):
    if tracking <= 0:
        d.text(xy, text, font=font, fill=fill, anchor=anchor, stroke_width=sw, stroke_fill=stroke)
        return
    x, y = xy
    for ch in text:
        d.text((x, y), ch, font=font, fill=fill, anchor=anchor, stroke_width=sw, stroke_fill=stroke)
        x += d.textlength(ch, font=font) + tracking


def _vgrad_line(d, y, W, c0, c1, t):
    d.line((0, y, W, y),
           fill=tuple(int(c0[i] + (c1[i] - c0[i]) * t) for i in range(3))
           + (int(c0[3] + (c1[3] - c0[3]) * t),))


def _fade_down(layer, y0, y1, W, keep, drop):
    """按竖向渐变收一层的 alpha：卡底和描边往下淡出，底部就不会留一块死板的实心。"""
    fade = Image.new("L", layer.size, 0)
    fd = ImageDraw.Draw(fade)
    for y in range(y0, y1 + 1):
        fd.line((0, y, W, y),
                fill=int(255 * (keep + (drop - keep) * (y - y0) / max(1, y1 - y0))))
    layer.putalpha(ImageChops.multiply(layer.getchannel("A"), fade))


def drop_shadow(layer, blur, alpha, dy):
    """给一整层（透明底）垫一层柔和投影，返回「投影 + 原层」。

    条目的正文横坐标到 0.55 画布宽，会压到右下角的画中画上；玻璃卡面没有黑描边，
    白字落在白大褂上就糊了。硬描边救得回来但一眼廉价，这里改成一点柔投影——既
    保可读性，又不破坏干净的版面。
    """
    a = layer.getchannel("A")
    sh = Image.new("RGBA", layer.size, (0, 0, 0, 0))
    sh.putalpha(a.filter(ImageFilter.GaussianBlur(max(1, blur)))
                .point(lambda v: int(v * alpha)))
    out = Image.new("RGBA", layer.size, (0, 0, 0, 0))
    out.alpha_composite(sh, (0, dy))
    out.alpha_composite(layer)
    return out


def glass_card(W, H, box, th, k, accent, font_path):
    """深色磨砂卡：外阴影 + 竖向渐变底 + 发丝描边（往下淡出）+ 左下金色短条。"""
    x0, y0, x1, y1 = box
    radius = round(th["radius"] * k)
    out = Image.new("RGBA", (W, H), (0, 0, 0, 0))

    dy = round(th["shadow_dy"] * k)
    sh = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ImageDraw.Draw(sh).rounded_rectangle((x0, y0 + dy, x1, y1 + dy), radius=radius,
                                         fill=(0, 0, 0, int(255 * th["shadow_alpha"])))
    out = Image.alpha_composite(
        out, sh.filter(ImageFilter.GaussianBlur(max(1, round(th["shadow_blur"] * k)))))

    top, bot = hex_to_rgba(th["top"]), hex_to_rgba(th["bottom"])
    top = top[:3] + (int(255 * th["top_alpha"]),)
    bot = bot[:3] + (int(255 * th["bottom_alpha"]),)
    grad = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    gd = ImageDraw.Draw(grad)
    for y in range(y0, y1 + 1):
        _vgrad_line(gd, y, W, top, bot, (y - y0) / max(1, y1 - y0))
    mask = Image.new("L", (W, H), 0)
    ImageDraw.Draw(mask).rounded_rectangle(box, radius=radius, fill=255)
    body = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    body.paste(grad, (0, 0), mask)
    out = Image.alpha_composite(out, body)

    edge = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ImageDraw.Draw(edge).rounded_rectangle(
        box, radius=radius, width=max(1, round(th["border_width"] * k)),
        outline=hex_to_rgba(th["border"], int(255 * th["border_alpha"])))
    _fade_down(edge, y0, y1, W, 1.0, 0.35)
    out = Image.alpha_composite(out, edge)

    bar_w, bar_h = round(48 * k), max(2, round(4 * k))
    bx = x0 + round((x1 - x0) * CARD_WIPE_X[0])
    by = y1 - round(96 * k)
    ImageDraw.Draw(out).rounded_rectangle((bx, by - bar_h, bx + bar_w, by),
                                          radius=bar_h // 2, fill=accent)

    note = cfg_footnote(th)
    if note:
        _stroked(ImageDraw.Draw(out),
                 (bx + bar_w + round(24 * k), by - bar_h / 2), note,
                 _font(font_path, round(th["footnote_size"] * k)),
                 hex_to_rgba(th["footnote_color"]), None, 0, anchor="lm", tracking=2 * k)
    return out


def cfg_footnote(th: dict) -> str:
    """落款：卡底部那一条小字。空着就只留金色短条。"""
    return (th.get("footnote") or "").strip()


def glass_icon(glyph, bold_path, emoji_path, k, th, accent):
    """磨砂圆角方块托住 emoji。

    flat 时期图标是「emoji + 40% 黑阴影」，压在深色磨砂卡上会脏成一团；玻璃风格里
    给它一个白色 7% 的圆角托底 + 发丝描边，它才是浮在卡面上的一个「图标位」。
    emoji 也顺手收小一圈：160px 的 emoji 在条目里比正文还重，比例是歪的。
    """
    px = EMOJI_PX
    box_px = int(px * 1.5)
    ic = Image.new("RGBA", (box_px, box_px), (0, 0, 0, 0))
    di = ImageDraw.Draw(ic)
    ok = False
    if emoji_path and not glyph.isdigit():
        try:
            di.text((box_px // 2, box_px // 2), glyph,
                    font=ImageFont.truetype(str(emoji_path), px), anchor="mm",
                    embedded_color=True)
            ok = True
        except Exception:
            ok = False
    if not ok:
        di.text((box_px // 2, box_px // 2), glyph, font=_font(bold_path, px - 30),
                anchor="mm", fill=accent)

    tile = max(24, round(th["icon_tile_size"] * k))
    glyph_px = max(16, round(th["icon_size"] * k))
    spr = Image.new("RGBA", (tile, tile), (0, 0, 0, 0))
    ImageDraw.Draw(spr).rounded_rectangle(
        (0, 0, tile - 1, tile - 1), radius=round(tile * 0.30),
        fill=(255, 255, 255, int(255 * th["icon_tile_alpha"])),
        outline=(255, 255, 255, int(255 * th["icon_tile_border_alpha"])),
        width=max(1, round(1.5 * k)))
    bbox = ic.getbbox()
    if bbox:
        g = ic.crop(bbox)
        s = glyph_px / max(1, max(g.width, g.height))
        g = g.resize((max(1, round(g.width * s)), max(1, round(g.height * s))), Image.LANCZOS)
        spr.alpha_composite(g, ((tile - g.width) // 2, (tile - g.height) // 2))
    return spr


def _fit_text(d, text, font_path, size, budget, floor=18):
    """按实测宽度收缩字号，装不下就一路缩到下限（调用方保证文案本身别太长）。"""
    size = max(int(size), floor)
    while size > floor:
        font = _font(font_path, size)
        if d.textlength(text, font=font) <= budget:
            return font
        size -= 2
    return _font(font_path, floor)


def _insert_icon(d: ImageDraw.ImageDraw, cx, cy, size, name, color, bg=None):
    """插图图标：全部用几何图形现画 —— 不引图标库、不依赖 emoji 字体。"""
    r = size / 2
    lw = max(2, int(size * 0.11))
    if name == "clock":
        d.ellipse((cx - r, cy - r, cx + r, cy + r), outline=color, width=lw)
        d.line((cx, cy, cx, cy - r * 0.52), fill=color, width=lw)
        d.line((cx, cy, cx + r * 0.44, cy + r * 0.24), fill=color, width=lw)
    elif name == "bowl":                       # 营养餐：碗身 + 碗沿 + 筷子
        d.pieslice((cx - r * 0.86, cy - r * 0.28, cx + r * 0.86, cy + r * 1.12),
                   0, 180, fill=color)
        d.rectangle((cx - r * 0.96, cy - r * 0.40, cx + r * 0.96, cy - r * 0.14), fill=color)
        for dx in (-r * 0.16, r * 0.16):       # 斜插的两根筷子比冒热气更像一餐
            d.line((cx + dx - r * 0.30, cy - r * 1.02, cx + dx + r * 0.16, cy - r * 0.46),
                   fill=color, width=max(2, int(lw * 0.8)))
    elif name == "leaf":
        # 尖头叶（两端收尖的透镜形）沿 45° 轴生长：按参数方程取点，比堆多边形准。
        angle = math.radians(45)
        ax, ay = math.cos(angle), math.sin(angle)      # 沿叶脉方向
        px, py = -math.sin(angle), math.cos(angle)     # 垂直叶脉
        edge_out, edge_back = [], []
        for i in range(25):
            s = math.sin(math.pi * i / 24)              # 0 → 1 → 0
            t = (i / 24) * 2 - 1                        # -1 → 1 沿轴
            half = r * 0.40 * (1 - t * t)               # 两端收尖
            bx, by = cx + ax * r * t, cy + ay * r * t
            edge_out.append((bx + px * half, by + py * half))
            edge_back.append((bx - px * half, by - py * half))
        d.polygon(edge_out + edge_back[::-1], fill=color)
        d.line((cx - ax * r * 0.86, cy - ay * r * 0.86, cx + ax * r * 0.86, cy + ay * r * 0.86),
               fill=(255, 255, 255, 255), width=max(1, int(size * 0.05)))
    elif name == "heart":
        lobe = r * 0.52
        d.ellipse((cx - r, cy - r * 0.92, cx - r + lobe * 2, cy - r * 0.92 + lobe * 2),
                  fill=color)
        d.ellipse((cx + r - lobe * 2, cy - r * 0.92, cx + r, cy - r * 0.92 + lobe * 2),
                  fill=color)
        d.polygon([(cx - r * 0.99, cy - r * 0.20), (cx + r * 0.99, cy - r * 0.20),
                   (cx, cy + r)], fill=color)
    elif name == "star":                       # 五角星：外/内半径交替取点，
        points = []                            # regular_polygon 只给正多边形
        for i in range(10):
            angle = -math.pi / 2 + i * math.pi / 5
            radius = r if i % 2 == 0 else r * 0.44
            points.append((cx + radius * math.cos(angle), cy + radius * math.sin(angle)))
        d.polygon(points, fill=color)
    elif name == "home":
        # 屋顶不超出屋身，再加一扇用底色「挖」出来的门 —— 不然整块读成一支箭头。
        d.polygon([(cx, cy - r * 0.92), (cx + r * 0.74, cy - r * 0.10),
                   (cx - r * 0.74, cy - r * 0.10)], fill=color)
        d.rectangle((cx - r * 0.70, cy - r * 0.10, cx + r * 0.70, cy + r), fill=color)
        if bg is not None:
            d.rectangle((cx - r * 0.22, cy + r * 0.30, cx + r * 0.22, cy + r), fill=bg)
    elif name == "shield":
        d.rounded_rectangle((cx - r * 0.82, cy - r * 0.92, cx + r * 0.82, cy + r * 0.06),
                            radius=r * 0.26, fill=color)
        d.polygon([(cx - r * 0.82, cy - r * 0.15), (cx + r * 0.82, cy - r * 0.15),
                   (cx, cy + r)], fill=color)
    else:                                      # check
        d.line((cx - r * 0.74, cy + r * 0.04, cx - r * 0.16, cy + r * 0.62),
               fill=color, width=int(lw * 1.5))
        d.line((cx - r * 0.16, cy + r * 0.62, cx + r * 0.8, cy - r * 0.6),
               fill=color, width=int(lw * 1.5))



def _insert_card_editorial(W, H, box_px, spec, theme, font_path, med_path, radius):
    """inserts.theme.skin = "editorial"：细描边卡片 + 淡色圆底图标 + 字距标题。

    和 flat 的区别只在「脸」：不动框位、不动触发规则、不动版式语义。
    flat 是参考片量出来的样式（实心色块 + 粗边），留作默认；当插图要压在真人口播
    画面上时，实心块会像一条系统通知 —— editorial 用发丝边和 13% 的淡色圆底把
    它压回「设计过的图形」那一档。
    """
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    x0, y0, x1, y1 = box_px
    bw, bh = x1 - x0, y1 - y0
    bg = hex_to_rgba(theme["bg"])
    fg = hex_to_rgba(theme["fg"])
    accent = hex_to_rgba(theme["accent"])
    r = min(int(radius * bh / 260), int(bh * 0.20))

    shadow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ImageDraw.Draw(shadow).rounded_rectangle(
        (x0, y0 + int(bh * 0.035), x1, y1 + int(bh * 0.035)), radius=r, fill=(0, 0, 0, 46))
    shadow = shadow.filter(ImageFilter.GaussianBlur(max(2, int(bh * 0.045))))
    layer = Image.alpha_composite(layer, shadow)

    # ImageDraw 在 RGBA 上是**替换像素**不是混合：半透明填色会在卡面上挖出透光洞。
    # 所以这里先把「淡色」按卡底实算出来再画，画上去的每个像素都是不透明的。
    def mix(over, t):
        return tuple(int(bg[i] + (over[i] - bg[i]) * t) for i in range(3)) + (255,)

    d = ImageDraw.Draw(layer)
    d.rounded_rectangle((x0, y0, x1, y1), radius=r, fill=bg)
    d.rounded_rectangle((x0, y0, x1, y1), radius=r,
                        outline=mix(fg, 0.10), width=max(1, int(bh * 0.007)))

    pad = int(bh * 0.17)
    disc = bh - pad * 2
    cx, cy = x0 + pad + disc / 2, y0 + bh / 2
    d.ellipse((cx - disc / 2, cy - disc / 2, cx + disc / 2, cy + disc / 2),
              fill=mix(accent, 0.14))
    _insert_icon(d, cx, cy, disc * 0.46, spec["icon"], accent, bg)

    tx = x0 + pad + disc + int(pad * 0.85)
    tb = x1 - pad - tx
    title_size = bh * 0.27
    body_size = bh * 0.185
    title_font = _fit_text(d, spec["title"], font_path, title_size, tb)
    body = _fit_text(d, spec["text"], med_path, body_size, tb) if spec["text"] else None
    block = title_size * 1.02 + (body_size * 1.45 if body else 0)
    top = y0 + (bh - block) / 2
    _stroked(d, (tx, top), spec["title"], title_font, fg, None, 0,
             anchor="la", tracking=bh * 0.014)
    if body:
        _stroked(d, (tx, top + title_size * 1.28), spec["text"], body,
                 mix(fg, 0.72), None, 0, anchor="la", tracking=bh * 0.005)
    return layer


def insert_card(W, H, box_px, spec, theme, font_path, med_path, radius):
    """画一张插图卡（整幅画布尺寸，和 card-base.png 一样，合成时直接贴）。

    四种版式都由脚本现画：图标+标签 / 要点列表 / 大字数据 / 引语。
    颜色、圆角、留白全部走 config，不写死在代码里。
    """
    if (theme or {}).get("skin") == "editorial":
        return _insert_card_editorial(W, H, box_px, spec, theme, font_path,
                                      med_path, radius)
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    x0, y0, x1, y1 = box_px
    bw, bh = x1 - x0, y1 - y0
    bg, fg, accent = (hex_to_rgba(theme["bg"]), hex_to_rgba(theme["fg"]),
                      hex_to_rgba(theme["accent"]))
    pad = int(bh * 0.16)
    radius = max(4, int(radius * bh / 260))

    shadow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ImageDraw.Draw(shadow).rounded_rectangle(
        (x0 + int(bh * 0.03), y0 + int(bh * 0.05), x1 + int(bh * 0.03), y1 + int(bh * 0.05)),
        radius=radius, fill=(0, 0, 0, 90))
    shadow = shadow.filter(ImageFilter.GaussianBlur(max(1, int(bh * 0.05))))
    layer = Image.alpha_composite(layer, shadow)

    d = ImageDraw.Draw(layer)
    d.rounded_rectangle((x0, y0, x1, y1), radius=radius, fill=bg)
    d.rounded_rectangle((x0, y0, x0 + max(4, int(bw * 0.012)), y1), radius=radius, fill=accent)

    inner_x = x0 + pad
    budget = bw - pad * 2
    kind = spec["kind"]
    if kind == "icon-label":
        tile = int(bh - pad * 2)
        d.rounded_rectangle((inner_x, y0 + pad, inner_x + tile, y0 + pad + tile),
                            radius=int(tile * 0.28), fill=accent)
        _insert_icon(d, inner_x + tile / 2, y0 + pad + tile / 2, tile * 0.52,
                     spec["icon"], fg, accent)
        tx = inner_x + tile + int(pad * 0.8)
        tb = x1 - pad - tx
        title_font = _fit_text(d, spec["title"], font_path, bh * 0.30, tb)
        d.text((tx, y0 + pad - int(bh * 0.02)), spec["title"], font=title_font, fill=fg)
        if spec["text"]:
            body = _fit_text(d, spec["text"], med_path, bh * 0.20, tb)
            d.text((tx, y0 + pad + int(bh * 0.34)), spec["text"], font=body, fill=fg)
    elif kind == "stat":
        num_font = _fit_text(d, spec["title"], font_path, bh * 0.52, budget * 0.5)
        d.text((inner_x, y0 + bh * 0.14), spec["title"], font=num_font, fill=accent)
        nw = d.textlength(spec["title"], font=num_font)
        if spec["text"]:
            body = _fit_text(d, spec["text"], med_path, bh * 0.24, budget - nw - pad)
            d.text((inner_x + nw + pad * 0.5, y0 + bh * 0.14 + bh * 0.22),
                   spec["text"], font=body, fill=fg)
    elif kind == "list":
        if spec["title"]:
            title_font = _fit_text(d, spec["title"], font_path, bh * 0.26, budget)
            d.text((inner_x, y0 + pad * 0.6), spec["title"], font=title_font, fill=fg)
        rows = spec["rows"][:3]
        row_h = (bh - pad * 1.8) / max(1, len(rows))
        for i, row in enumerate(rows):
            ry = y0 + pad * 1.4 + row_h * (i + 0.5)
            _insert_icon(d, inner_x + row_h * 0.20, ry, row_h * 0.30, spec["icon"], accent, bg)
            body = _fit_text(d, row, med_path, row_h * 0.44, budget - row_h * 0.5)
            d.text((inner_x + row_h * 0.45, ry - row_h * 0.22), row, font=body, fill=fg)
    else:                                       # quote
        body = _fit_text(d, spec["text"] or spec["title"], font_path, bh * 0.34, budget)
        d.text((inner_x, y0 + bh * 0.30), spec["text"] or spec["title"],
               font=body, fill=fg)
    return layer


def build(cfg: dict, project: Path) -> dict:
    p = project_paths(project)
    out = p["assets"]
    out.mkdir(parents=True, exist_ok=True)
    W, H = cfg["canvas"]["width"], cfg["canvas"]["height"]
    k = W / REF_W
    card, pal = cfg["card"], cfg["captions"]["palette"]

    # 三个字重都从**同一个 family** 里取。同族只有单一字重时（阿里妈妈数黑体就是
    # 只有 Bold）整张卡面就用它 —— 以前这里按「Bold」「Medium」全局找，卡面会混进
    # 另一个家族的字，看着就像没做完。
    family = cfg["captions"]["font"]
    black = find_font(family, project)
    bold = match_font(family, "Bold", project) or black
    med = match_font(family, "Medium", project) or black
    emoji_path = find_emoji_font()

    box = [round(v * s) for v, s in zip(card["box"], (W, H, W, H))]
    x0, y0, x1, y1 = box
    radius = round(card["radius"] * k)
    edge_w = max(1, round(card["edge_width"] * k))
    fill = hex_to_rgba(card["fill"])
    edge = hex_to_rgba(card["edge"])

    def canvas():
        im = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        return im, ImageDraw.Draw(im)

    def save(im, name):
        im.save(out / name)
        return name

    written = []

    theme = card_theme(card)
    glass = theme.get("skin") == "glass"
    accent = hex_to_rgba(theme.get("accent") or pal["gold"])
    hair = (255, 255, 255, int(255 * theme.get("divider_alpha", 0.10)))
    hair_w = max(1, round(theme.get("divider_width", 2) * k))

    # 卡底
    if glass:
        written.append(save(glass_card(W, H, box, theme, k, accent, med), "card-base.png"))
    else:
        im, d = canvas()
        d.rounded_rectangle(box, radius=radius, fill=fill, outline=edge, width=edge_w)
        written.append(save(im, "card-base.png"))

    lay = card_layout(cfg)
    cx = (x0 + x1) // 2
    if card["title"]:
        im, d = canvas()
        if glass:
            ty, tx = round(lay["title_y"] * H), round(lay["title_x"] * W)
            _stroked(d, (tx, ty), card["title"],
                     _font(black, round(theme["title_size"] * k)), accent, None, 0,
                     anchor="lm", tracking=4 * k)
            # 标题下面一条发丝线，左端压一段金色短线。用竖条容易和「I」混淆，
            # 横线做「活动项」才是这一类版式里更稳的做法。
            ly = ty + round(theme["title_rule_gap"] * k)
            d.line((tx, ly, round(x0 + (x1 - x0) * CARD_WIPE_X[1]), ly), fill=hair, width=hair_w)
            rw, rh = round(theme["title_rule_w"] * k), max(2, round(theme["title_rule_h"] * k))
            d.rounded_rectangle((tx, ly - rh // 2, tx + rw, ly + rh // 2),
                                radius=rh // 2, fill=accent)
            im = drop_shadow(im, round(theme["text_shadow_blur"] * k),
                             theme["text_shadow_alpha"], round(theme["text_shadow_dy"] * k))
        else:
            _stroked(d, (cx, round(lay["title_y"] * H)), card["title"],
                     _font(black, round(84 * k)), hex_to_rgba(pal["gold"]), INK,
                     max(1, round(6 * k)), anchor="mm", tracking=6 * k)
        written.append(save(im, "card-title.png"))

    # 条目：左序号右正文，下面一行小字副标。
    # 正文中心在 cy-30、副标中心在 cy+24：这个间距是量出来的，再挤就会叠在一起。
    for i, row in enumerate(card["rows"]):
        cy = round(lay["row_y"][i] * H)
        num_r, txt_x = round(lay["num_x"] * W), round(lay["text_x"] * W)
        im, d = canvas()
        if glass:
            num_c = hex_to_rgba(theme["num_color"]) if theme["num_color"] else accent
            _stroked(d, (num_r, cy), str(row["num"]),
                     _font(black, round(theme["num_size"] * k)), num_c, None, 0, anchor="rm")
            _stroked(d, (txt_x, cy - 30 * k), row["main"],
                     _font(black, round(theme["main_size"] * k)), (255, 255, 255, 255),
                     None, 0)
            if row.get("sub"):
                _stroked(d, (txt_x + 2, cy + 26 * k), row["sub"],
                         _font(med, round(theme["sub_size"] * k)),
                         hex_to_rgba(theme["sub_color"]), None, 0)
            if i < len(card["rows"]) - 1:      # 最后一行下面不再画线，收在卡里更干净
                ly = round((lay["row_y"][i] + lay["pitch"] / 2) * H)
                d.line((round(lay["title_x"] * W), ly,
                        round(x0 + (x1 - x0) * CARD_WIPE_X[1]), ly), fill=hair, width=hair_w)
            im = drop_shadow(im, round(theme["text_shadow_blur"] * k),
                             theme["text_shadow_alpha"], round(theme["text_shadow_dy"] * k))
        else:
            _stroked(d, (num_r, cy), str(row["num"]), _font(black, round(74 * k)),
                     (255, 255, 255, 255), INK, max(1, round(6 * k)), anchor="rm")
            _stroked(d, (txt_x, cy - 30 * k), row["main"], _font(black, round(56 * k)),
                     (255, 255, 255, 255), INK, max(1, round(6 * k)))
            if row.get("sub"):
                _stroked(d, (txt_x + 2, cy + 24 * k), row["sub"], _font(med, round(34 * k)),
                         (226, 226, 226, 255), INK, max(1, round(4 * k)))
        written.append(save(im, f"card-row-{i + 1}.png"))

        # 图标：emoji 优先，没有 emoji 字体就退回「序号色块」
        gl = row.get("icon") or str(row["num"])
        if glass:
            written.append(save(glass_icon(gl, bold, emoji_path, k, theme, accent),
                                f"card-icon-{i + 1}.png"))
            continue
        px = EMOJI_PX
        box_px = int(px * 1.5)
        ic = Image.new("RGBA", (box_px, box_px), (0, 0, 0, 0))
        di = ImageDraw.Draw(ic)
        ok = False
        if emoji_path and not gl.isdigit():
            try:
                di.text((box_px // 2, box_px // 2), gl,
                        font=ImageFont.truetype(str(emoji_path), px), anchor="mm",
                        embedded_color=True)
                ok = True
            except Exception:
                ok = False
        if not ok:
            di.text((box_px // 2, box_px // 2), gl, font=_font(bold, px - 30),
                    anchor="mm", fill=hex_to_rgba(pal["gold"]))
        target = max(24, round(160 * k))
        ic = ic.resize((target, target), Image.LANCZOS)
        sh = ic.split()[3].point(lambda v: int(v * 0.4))
        shadow = Image.new("RGBA", ic.size, (0, 0, 0, 255))
        shadow.putalpha(sh)
        pad = max(4, round(14 * k))
        spr = Image.new("RGBA", (ic.width + pad * 2, ic.height + pad * 2), (0, 0, 0, 0))
        spr.alpha_composite(shadow, (pad + pad // 3, pad + pad // 2))
        spr.alpha_composite(ic, (pad, pad))
        written.append(save(spr, f"card-icon-{i + 1}.png"))

    # 结尾金色发光大字
    if cfg["gold"]["enabled"] and cfg["gold"]["text"]:
        text = cfg["gold"]["text"]
        size = round(cfg["gold"].get("size", 120) * k)
        font = _font(black, size)
        pad = round(220 * k)
        probe = ImageDraw.Draw(Image.new("RGBA", (10, 10)))
        tw = int(probe.textlength(text, font=font)) + round(40 * k)
        size_px = (tw + pad * 2, round(300 * k) + pad * 2)
        cxg, cyg = (tw + pad * 2) // 2, round(150 * k) + pad

        mask = Image.new("L", size_px, 0)
        ImageDraw.Draw(mask).text((cxg, cyg), text, font=font, anchor="mm",
                                  fill=255, stroke_width=round(14 * k), stroke_fill=255)
        glyph = Image.new("L", size_px, 0)
        ImageDraw.Draw(glyph).text((cxg, cyg), text, font=font, anchor="mm", fill=255)

        grad = Image.new("RGBA", size_px, (0, 0, 0, 0))
        gd = ImageDraw.Draw(grad)
        gy0, gy1 = cyg - round(84 * k), cyg + round(84 * k)
        for y in range(size_px[1]):     # 渐变必须铺满整幅高度，否则字会被横向切断
            t = min(1.0, max(0.0, (y - gy0) / max(1, gy1 - gy0)))
            gd.line((0, y, size_px[0], y),
                    fill=(int(255 - 30 * t), int(238 - 70 * t), int(126 - 86 * t), 255))
        grad.putalpha(glyph)

        edge_layer = Image.new("RGBA", size_px, INK)
        edge_layer.putalpha(ImageChops.subtract(mask, glyph))

        glow = Image.new("RGBA", size_px, (0, 0, 0, 0))
        for r, a in ((26 * k, 0.34), (13 * k, 0.36), (5 * k, 0.42)):
            layer = Image.new("RGBA", size_px, (255, 216, 96, 255))
            layer.putalpha(mask.filter(ImageFilter.GaussianBlur(max(1, round(r))))
                           .point(lambda v, a=a: int(v * a)))
            glow = Image.alpha_composite(glow, layer)

        star = Image.new("RGBA", size_px, (0, 0, 0, 0))
        sd = ImageDraw.Draw(star)
        for sx, sy, sr in ((cxg - tw // 2 - 6, cyg - 108 * k, 12 * k),
                           (cxg + tw // 2 + 10, cyg - 84 * k, 9 * k),
                           (cxg - tw // 2 + 54, cyg + 96 * k, 8 * k)):
            sd.regular_polygon((sx, sy, max(2, round(sr))), 4, rotation=0,
                               fill=(255, 248, 210, 235))
        g = Image.alpha_composite(glow, edge_layer)
        g = Image.alpha_composite(g, grad)
        written.append(save(Image.alpha_composite(g, star), "gold-flash.png"))

    # 插图画面：全部现画。计划里的每一条都已经被扣过一遍（触发词必须在字幕里、
    # 框位不许压字幕带），这里只负责把它画出来 —— 校验和绘制不混在一处。
    from workflow.caption_plan import load as load_caption_plan
    inserts = load_caption_plan(cfg, project)["inserts"]
    ins_cfg = cfg["inserts"]
    for item in inserts["items"]:
        box_px = [round(v * s) for v, s in zip(item["box"], (W, H, W, H))]
        art = insert_card(W, H, box_px, item, ins_cfg["theme"], black, med,
                          float(ins_cfg["radius"]))
        written.append(save(art, item["asset"]))

    write_json(p["work"] / "assets.json", {"canvas": [W, H], "files": written,
                                           "card_box_px": box, "scale": round(k, 4),
                                           "inserts": inserts["items"]})
    print(f"  assets/  {len(written)} 张（画布 {W}x{H}，卡盒 {box}）")
    return {"files": written}


def main() -> None:
    project = Path(sys.argv[1] if len(sys.argv) > 1 else ".").resolve()
    build(load_config(project_paths(project)["config"]), project)


if __name__ == "__main__":
    main()
