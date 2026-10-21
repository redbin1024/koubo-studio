#!/usr/bin/env python3
"""把一条参考片量成可抄的数值：切点、强调色、卡片几何、画中画位置、字幕带。

这是本 skill 的核心动作 —— **先量，再抄**。凭肉眼对着网格线猜几何会差 30%，
所以这里全部走像素统计，每条判据都在真实参考片上验证过：

  卡片   = 「长时段稳定的单色大块」。多帧中位图 → 众数色掩膜 → 连通 → 补洞 → 矩形状确认。
  画中画 = 「清晰度显著高于周边」的最大矩形。卡段背景是模糊放大的真人，
           所以把梯度能量图（粗尺度）拿去做「平均能量 ≥ 阈值」的最大矩形搜索。
  字幕带 = 「亮像素 + 紧邻深色硬描边」。自动字幕一定是白字黑硬边。
  强调色 = 高饱和高亮像素聚类，按色相去重，方便直接抄成配置。

用法：
    python scripts/analyze_reference.py REF.mp4 --out work/reference-teardown.json \\
        [--frames work/ref-frames] [--fps 4] [--scene-threshold 0.15]

输出坐标全部归一化到 0-1，换画布尺寸直接乘。
"""
from __future__ import annotations

import argparse
import sys
from collections import Counter, deque
from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter

sys.path.insert(0, str(Path(__file__).parent))
from _common import (  # noqa: E402
    find_ffmpeg, probe_media, rgb_to_hex, run, run_bytes, write_json,
)

AW, AH = 270, 480          # 分析分辨率（竖屏基准；横屏按比例缩）
PIP_SCALE = 6              # 画中画搜索用的粗尺度（1/6 分辨率）
HUE_NAMES = (
    (0, "red"), (18, "orange"), (45, "yellow"), (70, "green"),
    (165, "cyan"), (200, "azure"), (240, "blue"), (280, "violet"),
    (315, "magenta"), (345, "red"),
)


def hue_name(r: float, g: float, b: float) -> str:
    """粗略色相命名，让 agent 一眼看出「哪个是黄、哪个是粉」。"""
    mx, mn = max(r, g, b), min(r, g, b)
    d = mx - mn
    if d < 1e-6:
        return "gray"
    if mx == r:
        h = (60 * ((g - b) / d)) % 360
    elif mx == g:
        h = 60 * ((b - r) / d) + 120
    else:
        h = 60 * ((r - g) / d) + 240
    name = "red"
    for lo, n in HUE_NAMES:
        if h >= lo:
            name = n
    # 粉/品红单独归一类：它的色相落在 340-355，和「砖红 / 肤色」同一段，
    # 只按色相分会被皮肤色挤掉（参考片里「99%」的粉就是这么丢的）。
    # 判据用通道关系：蓝比绿高、红又比蓝高 —— 肤色永远不满足（肤色蓝<绿）。
    if b > g and r > b and (r - g) > 60:
        return "pink"
    return name


# ------------------------------------------------------------------ 基础工具

def decode(path: Path, fps: float, w: int, h: int) -> np.ndarray:
    """抽帧成 int16 数组。显式 -map 0:v：竖屏 HEVC 常把音频排在 index 0。"""
    buf = np.frombuffer(run_bytes([
        find_ffmpeg(), "-v", "error", "-i", str(path), "-map", "0:v",
        "-vf", f"fps={fps},scale={w}:{h}:flags=area",
        "-f", "rawvideo", "-pix_fmt", "rgb24", "-",
    ]), dtype=np.uint8)
    n = len(buf) // (w * h * 3)
    return buf[: n * w * h * 3].reshape(n, h, w, 3).astype(np.int16)


def scene_cuts(path: Path, threshold: float) -> list[dict]:
    """镜头切点。用 metadata=print 抓 lavfi.scene_score —— showinfo 抓不到这个值。"""
    proc = run([
        find_ffmpeg(), "-hide_banner", "-nostats", "-i", str(path),
        "-vf", f"select='gt(scene,{threshold})',metadata=print", "-an", "-f", "null", "-",
    ])
    # ffmpeg 先打印 `pts_time:`，下一行才是 `lavfi.scene_score`。
    # 早期版本按相反顺序配对，导致切点整体错位到下一刀；这里显式记住 pts。
    cuts, at = [], None
    for line in proc.stderr.splitlines():
        if "pts_time:" in line:
            at = round(float(line.split("pts_time:")[1].split()[0]), 3)
        elif "lavfi.scene_score" in line and at is not None:
            score = float(line.rsplit("=", 1)[1])
            cuts.append({"t": at, "score": round(score, 4)})
            at = None
    return cuts


def _shift(mask: np.ndarray, dy: int, dx: int) -> np.ndarray:
    out = np.zeros_like(mask)
    h, w = mask.shape
    ys0, ys1 = max(dy, 0), min(h + dy, h)
    xs0, xs1 = max(dx, 0), min(w + dx, w)
    out[ys0:ys1, xs0:xs1] = mask[ys0 - dy:ys1 - dy, xs0 - dx:xs1 - dx]
    return out


def erode(mask: np.ndarray, k: int = 1) -> np.ndarray:
    out = mask.copy()
    for dy in range(-k, k + 1):
        for dx in range(-k, k + 1):
            if dy or dx:
                out &= _shift(mask, dy, dx)
    return out


def dilate(mask: np.ndarray, k: int = 1) -> np.ndarray:
    out = mask.copy()
    for dy in range(-k, k + 1):
        for dx in range(-k, k + 1):
            if dy or dx:
                out |= _shift(mask, dy, dx)
    return out


def label_largest(mask: np.ndarray) -> dict | None:
    """四连通域，返回最大那块。纯 numpy + deque，不依赖 scipy。"""
    h, w = mask.shape
    seen = np.zeros_like(mask, dtype=bool)
    best: list[tuple[int, int]] = []
    for sy, sx in zip(*[a.tolist() for a in np.nonzero(mask)]):
        if seen[sy, sx]:
            continue
        comp = []
        dq = deque([(sy, sx)])
        seen[sy, sx] = True
        while dq:
            cy, cx = dq.popleft()
            comp.append((cy, cx))
            for ny, nx in ((cy + 1, cx), (cy - 1, cx), (cy, cx + 1), (cy, cx - 1)):
                if 0 <= ny < h and 0 <= nx < w and mask[ny, nx] and not seen[ny, nx]:
                    seen[ny, nx] = True
                    dq.append((ny, nx))
        if len(comp) > len(best):
            best = comp
    if not best:
        return None
    a = np.array(best)
    y0, x0 = a.min(0).tolist()
    y1, x1 = a.max(0).tolist()
    return {"cells": len(best), "y0": y0, "x0": x0, "y1": y1, "x1": x1}


def fill_holes(mask: np.ndarray) -> np.ndarray:
    """从画框边界泛洪补洞。卡片上的文字/图标会打出很多洞，不补的话矩形度算不出来。"""
    h, w = mask.shape
    inv = ~mask
    reach = np.zeros_like(inv)
    dq = deque()
    for y in range(h):
        for x in (0, w - 1):
            if inv[y, x] and not reach[y, x]:
                reach[y, x] = True
                dq.append((y, x))
    for x in range(w):
        for y in (0, h - 1):
            if inv[y, x] and not reach[y, x]:
                reach[y, x] = True
                dq.append((y, x))
    while dq:
        cy, cx = dq.popleft()
        for ny, nx in ((cy + 1, cx), (cy - 1, cx), (cy, cx + 1), (cy, cx - 1)):
            if 0 <= ny < h and 0 <= nx < w and inv[ny, nx] and not reach[ny, nx]:
                reach[ny, nx] = True
                dq.append((ny, nx))
    return mask | (inv & ~reach)


def _edge_extent(profile: np.ndarray, thr: float, gap: int = 3) -> int:
    """从内向外扫一条剖面，返回「亮边」延伸了多少像素。连续 gap 个暗像素才停。"""
    n, low = 0, 0
    for k, v in enumerate(profile):
        if v > thr:
            n, low = k + 1, 0
        else:
            low += 1
            if low >= gap:
                break
    return n


def integral(a: np.ndarray) -> np.ndarray:
    """二维前缀和，带一行一列的 0 边，方便做 O(1) 矩形求和。"""
    return np.pad(a.cumsum(0).cumsum(1), ((1, 0), (1, 0)))


def otsu(values: np.ndarray, bins: int = 64) -> float:
    hist, edges = np.histogram(values, bins=bins)
    p = hist / max(hist.sum(), 1)
    c = (edges[:-1] + edges[1:]) / 2
    w0 = np.cumsum(p)
    w1 = 1 - w0
    m0 = np.cumsum(p * c) / np.maximum(w0, 1e-9)
    m1 = (np.cumsum((p * c)[::-1])[::-1]) / np.maximum(w1, 1e-9)
    return float(c[int(np.nanargmax(w0 * w1 * (m0 - m1) ** 2))])


def max_subarray(v: np.ndarray) -> tuple[float, int, int]:
    """Kadane：和最大的连续子区间。用来在固定 x 跨度下找画中画的 y 范围。"""
    best_score, best = None, (0, 0)
    cur, start = 0.0, 0
    for i, x in enumerate(v):
        if cur <= 0:
            cur, start = float(x), i
        else:
            cur += float(x)
        if best_score is None or cur > best_score:
            best_score, best = cur, (start, i + 1)
    return (0.0, 0, 0) if best_score is None else (best_score, best[0], best[1])


def grow_box(grad: np.ndarray, x0: int, y0: int, x1: int, y1: int,
             thr: float, rel: float = 0.35, floor: float = 0.5) -> tuple[int, int, int, int]:
    """从「最密的核」往外长到整块画中画。

    每次只收一条边，条件是那一条的自身均值 ≥ rel × 当前均值（且不低于 floor × 阈值）。
    这个相对判据是关键：只看「加进去之后整体均值还够不够」的话，画中画够密，
    能一路把旁边的空白背景甚至卡片吃进来；看「新增这条自己够不够密」才收得住。
    """
    gh, gw = grad.shape
    while True:
        cur = float(grad[y0:y1, x0:x1].mean())
        opts = []
        if x0 > 0:
            opts.append(("l", float(grad[y0:y1, x0 - 1].mean()), y1 - y0))
        if x1 < gw:
            opts.append(("r", float(grad[y0:y1, x1].mean()), y1 - y0))
        if y0 > 0:
            opts.append(("u", float(grad[y0 - 1, x0:x1].mean()), x1 - x0))
        if y1 < gh:
            opts.append(("d", float(grad[y1, x0:x1].mean()), x1 - x0))
        pick = None
        for side, m, cnt in opts:
            if m >= rel * cur and m >= floor * thr:
                if pick is None or cnt > pick[1]:
                    pick = (side, cnt)
        if pick is None:
            break
        side = pick[0]
        if side == "l":
            x0 -= 1
        elif side == "r":
            x1 += 1
        elif side == "u":
            y0 -= 1
        else:
            y1 += 1
    return x0, y0, x1, y1


# ------------------------------------------------------------------ 强调色

def accent_colors(frames: np.ndarray, per_hue: int = 3) -> list[dict]:
    """高饱和 + 高亮的像素聚类 = 强调色候选。

    按色相去重再返回：参考片里橙色（肤色、木纹）数量碾压一切，直接取 top N 会把
    真正的黄和粉挤掉。去重后每种色相只留最强的一个，黄和粉才浮得上来。
    """
    counter: Counter = Counter()
    for f in frames:
        mx, mn = f.max(2), f.min(2)
        m = ((mx - mn) > 80) & (mx > 180)
        if m.any():
            counter.update(map(tuple, (f[m] // 8 * 8).tolist()))
    merged: list[dict] = []
    for (r, g, b), n in counter.most_common(400):
        for item in merged:
            if (abs(item["rgb"][0] - r) <= 24 and abs(item["rgb"][1] - g) <= 24
                    and abs(item["rgb"][2] - b) <= 24):
                item["count"] += n
                break
        else:
            merged.append({"rgb": [int(r), int(g), int(b)], "count": n})
    merged.sort(key=lambda d: -d["count"])
    picked: list[dict] = []
    per_hue_count: Counter = Counter()
    for it in merged:
        r, g, b = it["rgb"]
        hue = hue_name(r, g, b)
        if per_hue_count[hue] >= per_hue:
            continue
        per_hue_count[hue] += 1
        picked.append({"hex": rgb_to_hex((r, g, b)), "rgb": [r, g, b],
                       "hue": hue, "count": it["count"]})
    return picked


# ------------------------------------------------------------------ 卡片

def frame_flat_color(f: np.ndarray, bin_size: int = 8, tol: int = 16):
    """一帧里最大的「近似单色」占比。卡片填充就是靠这个冒出来的。

    两步走而不是直接拿直方图桶当结果：先量化定位候选，再把桶内像素的真实中位色取出来
    当参考色，最后重新数一次。直接拿桶底当参考色会踩「填充色落在桶边界」的坑 ——
    参考片卡片实际是 #A0A09F，量化到 #A09090 后蓝通道差 15，一整块卡片全被漏掉。
    """
    q = f // bin_size * bin_size
    cnt = Counter(map(tuple, q.reshape(-1, 3).tolist()))
    ref = np.array(cnt.most_common(1)[0][0], dtype=np.int16)
    m = np.abs(f - ref).max(2) <= tol
    if not m.any():
        return [int(v) for v in ref], 0.0
    ref = np.median(f[m], axis=0).astype(np.int16)
    m = np.abs(f - ref).max(2) <= tol
    return [int(v) for v in ref], float(m.mean())


def card_mask(med: np.ndarray, tol: int = 14) -> tuple[np.ndarray, list[int]]:
    """在中位图里取卡片填充色的掩膜（含腐蚀去噪）。"""
    ref, _ = frame_flat_color(med)
    ref_a = np.array(ref, dtype=np.int16)
    return erode(np.abs(med - ref_a).max(2) <= tol, 1), ref


def find_card(frames: np.ndarray, fps: float) -> dict | None:
    """卡片 = 长时段里稳定出现的「大片单色矩形」。"""
    cand = [frame_flat_color(f) for f in frames]
    # 排除纯黑/纯白帧（淡入淡出、闪白）—— 它们的「单色占比」恒为 1.0，
    # 会把相对阈值顶到天上，真正的卡段一个都选不出来。
    usable = [35 <= sum(col) / 3.0 <= 228 for col, _ in cand]
    fracs = [fr for u, (_, fr) in zip(usable, cand) if u]
    peak = max(fracs) if fracs else 0.0
    thr = max(0.15, 0.60 * peak)
    flags = [u and fr >= thr for u, (_, fr) in zip(usable, cand)]

    runs, cur = [], []
    for i, ok in enumerate(flags):
        if ok:
            cur.append(i)
        elif cur:
            runs.append(cur)
            cur = []
    if cur:
        runs.append(cur)
    runs = [r for r in runs if len(r) >= max(2, int(1.0 * fps))]
    if not runs:
        return None
    run = max(runs, key=len)

    # 时序中位图：静态卡片被保留，运动的背景被抹成中间调
    med = np.median(frames[run[0]:run[-1] + 1].astype(np.float32), axis=0).astype(np.int16)
    h, w = med.shape[:2]
    mask, ref = card_mask(med)
    filled = fill_holes(mask)
    comp = label_largest(filled)
    if comp is None:
        return None

    x0, y0, x1, y1 = comp["x0"], comp["y0"], comp["x1"], comp["y1"]
    bw, bh = x1 - x0 + 1, y1 - y0 + 1
    area = comp["cells"] / (h * w)
    rect = comp["cells"] / (bw * bh)
    # 贴边数 ≥3 说明它是背景（墙/桌面），不是嵌在画面里的卡片
    borders = sum((x0 == 0, y0 == 0, x1 == w - 1, y1 == h - 1))
    if area < 0.12 or rect < 0.45 or borders >= 3:
        return None

    # 白描边：往外扩出亮边。不能「一步一亮就扩、一暗就停」—— 掩膜边缘常有一两像素
    # 抗锯齿过渡，那样会在描边内侧就收住，框比实际小一圈。改成「连续 3 个暗像素才停」。
    fill_luma = float(np.mean(ref))
    probe = np.asarray(med.mean(2), dtype=np.float32)
    y0 -= _edge_extent(probe[max(y0 - 10, 0):y0, x0:x1 + 1].mean(1)[::-1], fill_luma + 22)
    y1 += _edge_extent(probe[y1 + 1:y1 + 11, x0:x1 + 1].mean(1), fill_luma + 22)
    x0 -= _edge_extent(probe[y0:y1 + 1, max(x0 - 10, 0):x0].mean(0)[::-1], fill_luma + 22)
    x1 += _edge_extent(probe[y0:y1 + 1, x1 + 1:x1 + 11].mean(0), fill_luma + 22)

    inner = med[y0:y1 + 1, x0:x1 + 1]
    fill = np.median(inner.reshape(-1, 3), axis=0)
    return {
        "start": round(run[0] / fps, 3),
        "end": round(run[-1] / fps, 3),
        "samples": len(run),
        "bbox_norm": [round(x0 / w, 4), round(y0 / h, 4),
                      round((x1 + 1) / w, 4), round((y1 + 1) / h, 4)],
        "area": round(float(area), 4),
        "rectangularity": round(float(rect), 3),
        "fill_hex": rgb_to_hex(fill),
        "fill_rgb": [int(v) for v in fill],
        "note": "bbox_norm 是含亮描边的外沿；圆角与描边宽度量不出来，按画布短边 2-3% / 1.4% 目测取。",
    }


# ------------------------------------------------------------------ 画中画

def find_pip(seg: np.ndarray, card: np.ndarray | None = None) -> dict | None:
    """画中画 = 卡段里「清晰度显著高于周边」的最大矩形。

    判据不是拉普拉斯高频（卡片的粗体字比人脸的拉普拉斯还高），而是**粗尺度梯度**：
    卡段背景是「模糊放大的真人」，模糊把低频结构也抹掉了，所以粗尺度梯度接近 0；
    画中画没模糊，粗尺度梯度仍然很高。再用「区间均值 ≥ 阈值」的最大矩形搜索定框。
    """
    if len(seg) == 0:
        return None
    med = np.median(seg.astype(np.float32), axis=0).astype(np.int16)
    h, w = med.shape[:2]
    if card is None:
        card, _ = card_mask(med)
    card = dilate(card, 12)         # 连白描边一起排除，免得卡框的强边缘把搜索带偏

    gw, gh = w // PIP_SCALE, h // PIP_SCALE
    gray = med.mean(2).astype(np.float32)
    small = np.asarray(
        Image.fromarray(gray.astype(np.uint8)).resize((gw, gh), Image.BOX), dtype=np.float32)
    grad = np.zeros_like(small)
    grad[:-1, :] += np.abs(np.diff(small, axis=0))
    grad[:, :-1] += np.abs(np.diff(small, axis=1))

    skip = np.asarray(
        Image.fromarray((card * 255).astype(np.uint8)).resize((gw, gh), Image.BOX),
        dtype=np.float32) > 20
    grad = np.where(skip, 0.0, grad)
    outside = grad[~skip]
    if outside.size < 20:
        return None
    # Otsu 的阈值偏高（它分的是「卡片图形 vs 其它」），实测取 0.4 倍刚好分开
    # 「模糊背景」与「未模糊的真人」。
    thr = otsu(outside) * 0.40
    if not np.isfinite(thr) or thr <= 1.0:
        return None

    # 第一步：扫所有 x 跨度，在每个跨度里用 Kadane 找最密的 y 区间，留下最密的那个核。
    # 用「和最大」而不是「面积最大」：面积最大对阈值极度敏感，阈值差 1 就换一个答案。
    ii = integral(grad)
    core = None
    for x0 in range(gw):
        for x1 in range(x0 + 2, gw + 1):
            rowsum = np.diff(ii[:, x1] - ii[:, x0]) / (x1 - x0)
            score, y0, y1 = max_subarray(rowsum - thr)
            if score <= 0 or (x1 - x0) * (y1 - y0) < 0.10 * gw * gh:
                continue
            if core is None or score > core[0]:
                core = (score, x0, y0, x1, y1)
    if core is None:
        return None

    # 第二步：从核往外长到画中画的真实外沿
    x0, y0, x1, y1 = grow_box(grad, core[1], core[2], core[3], core[4], thr)
    box = np.zeros_like(grad, dtype=bool)
    box[y0:y1, x0:x1] = True
    inside_mean = float(grad[box].mean())
    # 框的膨胀区一起排除：框边上「清晰→模糊」的突变本身是强梯度，算进背景会虚高
    rest = grad[~dilate(box, 2) & ~skip]
    rest_mean = float(rest.mean()) if rest.size else 0.0
    contrast = inside_mean / max(rest_mean, 1e-6)
    # 全屏都清晰（没有卡段的普通镜头）时 inside/outside 会接近 1，用这条否掉
    box_area = (x1 - x0) * (y1 - y0) / (gw * gh)
    if box_area > 0.62 or box_area < 0.10 or contrast < 2.2:
        return None

    return {
        "bbox_norm": [round(x0 * PIP_SCALE / w, 4), round(y0 * PIP_SCALE / h, 4),
                      round(min(x1 * PIP_SCALE, w) / w, 4),
                      round(min(y1 * PIP_SCALE, h) / h, 4)],
        "area": round(float(box_area), 4),
        "aspect": round(float((x1 - x0) / max(y1 - y0, 1)), 3),
        "sharpness_contrast": round(float(contrast), 2),
        "note": ("返回的是画中画的**保守内框**（一定落在画中画里）：低对比的暗部边缘长不过去，"
                 "实测比真值内缩 5-10%。外沿按构图微调；框贴到 1.0 说明画中画越出了画面边缘。"),
    }


# ------------------------------------------------------------------ 字幕带

def caption_band(frames: np.ndarray) -> dict:
    """字幕 = 亮像素且 3px 内有深色硬描边。只扫下半屏。"""
    boxes = []
    for f in frames:
        lum = np.asarray(Image.fromarray(f.astype(np.uint8)).convert("L"))
        bright = lum > 190
        # 必须先把「深色掩膜」膨胀，再和亮点求交。反过来对灰度图做 MaxFilter
        # 会把紧挨白字的黑边一起吞掉，永远查不到字。
        dark = np.asarray(
            Image.fromarray(((lum < 70) * 255).astype(np.uint8)).filter(ImageFilter.MaxFilter(5)),
            dtype=np.int16) > 0
        text = bright & dark
        hit = np.nonzero(text.sum(1) > max(6, f.shape[1] // 40))[0]
        if len(hit) < 3:
            continue
        top, bot = int(hit.min()), int(hit.max())
        if bot / f.shape[0] < 0.45 or top / f.shape[0] < 0.30:
            continue
        cols = np.nonzero(text[top:bot + 1].sum(0) > 1)[0]
        if len(cols) < 3:
            continue
        boxes.append((top / f.shape[0], bot / f.shape[0],
                      cols.min() / f.shape[1], cols.max() / f.shape[1]))
    if not boxes:
        return {"detected": False}
    a = np.array(boxes)
    return {
        "detected": True,
        "samples": len(boxes),
        "y_top_norm": round(float(np.percentile(a[:, 0], 10)), 4),
        "y_bottom_norm": round(float(np.percentile(a[:, 1], 90)), 4),
        "x_min_norm": round(float(np.percentile(a[:, 2], 10)), 4),
        "x_max_norm": round(float(np.percentile(a[:, 3], 90)), 4),
        "note": "按 10/90 分位取，避开个别溢出帧。MarginV = (1 - y_bottom_norm) × 画布高。",
    }


def flat_bands(frames: np.ndarray, bins: int = 20) -> list[dict]:
    """每行的横向梯度均值：越小越平，字幕放这里最干净。"""
    g = np.abs(np.diff(frames.astype(np.float32), axis=2)).mean(axis=(0, 2, 3))
    n = len(g)
    return [{"y_from": round(int(i * n / bins) / n, 3),
             "y_to": round(int((i + 1) * n / bins) / n, 3),
             "gradient": round(float(g[int(i * n / bins):int((i + 1) * n / bins)].mean()), 2)}
            for i in range(bins)]


def main() -> None:
    ap = argparse.ArgumentParser(description="把参考片量成可抄的数值")
    ap.add_argument("reference")
    ap.add_argument("--out", default="work/reference-teardown.json")
    ap.add_argument("--frames", default=None, help="可选：把抽到的帧存成 png 供人眼复核")
    ap.add_argument("--fps", type=float, default=4.0)
    ap.add_argument("--scene-threshold", type=float, default=0.15)
    args = ap.parse_args()

    ref = Path(args.reference).resolve()
    if not ref.is_file():
        raise SystemExit(f"找不到参考片：{ref}")

    info = probe_media(ref)
    w, h = info["width"] or 1080, info["height"] or 1920
    aw = AW if h >= w else AH
    ah = AH if h >= w else int(round(AH * h / w))
    print(f"  参考片 {w}x{h} / {info['duration']:.3f}s / {info['fps']}fps / "
          f"{info['video_codec']}+{info['audio_codec']}")

    frames = decode(ref, args.fps, aw, ah)
    print(f"  抽帧 {len(frames)} 帧 @ {aw}x{ah}")

    card = find_card(frames, args.fps)
    pip = None
    if card:
        i0 = int(round(card["start"] * args.fps))
        i1 = max(i0 + 1, int(round(card["end"] * args.fps)) + 1)
        seg = frames[i0:i1]
        med = np.median(seg.astype(np.float32), axis=0).astype(np.int16)
        pip = find_pip(seg, card_mask(med)[0])

    report = {
        "version": 1,
        "reference": str(ref),
        "probe": info,
        "scene_cuts": scene_cuts(ref, args.scene_threshold),
        "accent_colors": accent_colors(frames),
        "card": card,
        "pip": pip,
        "caption_band": caption_band(frames),
        "flat_bands": flat_bands(frames),
        "how_to_use": [
            "accent_colors 里 hue=yellow 的是正向强调色，hue=magenta/red 的是反差强调色 → captions.palette。",
            "card.bbox_norm → card.box；fill_hex → card.fill；card.start/end 直接抄成卡段起止。",
            "pip.bbox_norm → pip.box（贴到 1.0 就是出血边）。",
            "captions.margin_v = (1 - caption_band.y_bottom_norm) × canvas 高；size 按 x 跨度反推。",
            "scene_cuts 里 score 高的才是真镜头切换，字幕变化也会被计入，别当成切点。",
            "flat_bands 里 gradient 最小的几段是画面最平的安全带，字幕优先放这里。",
        ],
    }

    write_json(args.out, report)
    print(f"  → {args.out}")
    if args.frames:
        fd = Path(args.frames)
        fd.mkdir(parents=True, exist_ok=True)
        for i, f in enumerate(frames):
            Image.fromarray(f.astype(np.uint8)).save(fd / f"t{i / args.fps:06.2f}.png")
        print(f"  → {fd}（{len(frames)} 张）")

    print(f"  切点 {len(report['scene_cuts'])} / 卡段 "
          f"{('%.2f-%.2fs' % (card['start'], card['end'])) if card else '未检出'} / 画中画 "
          f"{'有' if pip else '无'} / 字幕带 "
          f"{'有' if report['caption_band'].get('detected') else '无'}")
    if report["accent_colors"]:
        print("  强调色 " + "  ".join(f"{c['hex']}({c['hue']})" for c in report["accent_colors"][:6]))


if __name__ == "__main__":
    main()
