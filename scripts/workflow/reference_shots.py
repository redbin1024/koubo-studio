"""参考片镜头层：切点 → 镜头表 → 首/中/尾三联图 → 接触表 → ≤15s 分段。

为什么不只用一次 `scdet`：
- 固定阈值对「等亮度换色」会漏；本项目 `workflow.pacing` 已用中位数 + MAD 自适应，
  这里直接复用它的切点，不再另造一套阈值。
- 长镜头会被拆成 ≤5s 的 beat，否则一张三联图代表不了整段动作；
  镜头太多时再合并最短的相邻镜头，避免一次拆解把提示词预算打爆。

方法参考 `Joho6666/video-replicate-studio` 的 strip / segment 设计，代码为本项目重写。
"""
from __future__ import annotations

import subprocess
from pathlib import Path

MAX_BEAT = 5.0
MIN_SHOT = 0.4
MAX_SHOTS = 30


class ReferenceShotsError(RuntimeError):
    """切镜或抽帧失败；消息要能直接给用户看。"""


def _cut_time(item) -> float | None:
    if isinstance(item, dict):
        value = item.get("t", item.get("time"))
    else:
        value = item
    try:
        return round(float(value), 3)
    except (TypeError, ValueError):
        return None


def build_shots(cuts, duration: float, *, min_shot: float = MIN_SHOT,
                max_beat: float = MAX_BEAT, max_shots: int = MAX_SHOTS,
                start: float = 0.0, end: float | None = None) -> list[dict]:
    """把切点变成镜头表：过滤过近切点 → 拆长镜头 → 超限时合并最短邻居。"""
    duration = float(duration)
    if duration <= 0:
        raise ReferenceShotsError("参考片时长为 0，无法切镜")
    stop = min(duration, float(end)) if end is not None else duration
    begin = max(0.0, float(start))
    if stop - begin < 0.2:
        raise ReferenceShotsError("分析区间不足 0.2 秒")
    times = sorted({t for t in (_cut_time(c) for c in cuts or [])
                    if t is not None and begin + 0.2 < t < stop - 0.2})
    bounds = [begin]
    for t in times:
        if t - bounds[-1] >= min_shot:
            bounds.append(t)
    if stop - bounds[-1] < min_shot and len(bounds) > 1:
        bounds.pop()
    bounds.append(stop)

    shots: list[dict] = []
    for left, right in zip(bounds, bounds[1:]):
        span = right - left
        pieces = max(1, int(span // max_beat) + (1 if span % max_beat else 0))
        for p in range(pieces):
            shots.append({
                "start": round(left + span * p / pieces, 3),
                "end": round(left + span * (p + 1) / pieces, 3),
                "cut": "hard" if p == 0 else "beat",
            })
    merged = 0
    while len(shots) > max(1, int(max_shots)):
        if len(shots) <= 1:
            break
        i = min(range(len(shots)), key=lambda k: shots[k]["end"] - shots[k]["start"])
        if i == 0:
            j = 1
        elif i == len(shots) - 1:
            j = i - 1
        else:
            before = shots[i]["start"] - shots[i - 1]["start"]
            after = shots[i + 1]["end"] - shots[i]["end"]
            j = i - 1 if before <= after else i + 1
        a, b = sorted((i, j))
        shots[a:b + 1] = [{
            "start": shots[a]["start"],
            "end": shots[b]["end"],
            "cut": shots[a]["cut"],
        }]
        merged += 1
    for index, shot in enumerate(shots, 1):
        shot["id"] = f"s{index:02d}"
        shot["index"] = index
        shot["duration"] = round(shot["end"] - shot["start"], 3)
        shot["split"] = "beat" if shot["cut"] == "beat" else "cut"
    return shots


def strip_times(shot: dict) -> list[float]:
    """首/中/尾三格，离切点留一点余量，避免解到转场帧。"""
    start, end = float(shot["start"]), float(shot["end"])
    duration = max(0.0, end - start)
    pad = min(0.12, duration / 6)
    values = [start + pad, start + duration / 2, end - pad]
    return [round(min(max(value, start), end), 3) for value in values]


def plan_segments(shots: list[dict], max_sec: float = 15.0) -> list[dict]:
    """按镜头边界分组，每段 ≤ max_sec；单镜头超长时独占一段并标注。"""
    segments: list[dict] = []
    current: dict | None = None
    for shot in shots:
        start, end = float(shot["start"]), float(shot["end"])
        if current is not None and end - current["start"] > max_sec:
            segments.append(current)
            current = None
        if current is None:
            current = {"start": start, "end": end, "shots": []}
        current["end"] = end
        current["shots"].append(shot["id"])
    if current is not None:
        segments.append(current)
    out = []
    for index, seg in enumerate(segments, 1):
        duration = round(seg["end"] - seg["start"], 3)
        out.append({
            "index": index,
            "start": round(seg["start"], 3),
            "end": round(seg["end"], 3),
            "duration": duration,
            "shots": seg["shots"],
            "oversize": duration > max_sec + 0.01,
        })
    return out


def _ffmpeg() -> str:
    from _common import find_ffmpeg
    return find_ffmpeg()


def _grab(video: Path, at: float, output: Path, vf: str, floor: float) -> bool:
    """抽一帧；seek 超过最后一帧时逐次回退，最多 4 次。"""
    output.parent.mkdir(parents=True, exist_ok=True)
    at = max(floor, float(at))
    for attempt in range(5):
        if output.exists():
            output.unlink()
        proc = subprocess.run([
            _ffmpeg(), "-hide_banner", "-loglevel", "error", "-y",
            "-ss", f"{at:.3f}", "-i", str(video), "-frames:v", "1",
            "-vf", vf, "-q:v", "3", str(output),
        ], capture_output=True, text=True)
        if proc.returncode == 0 and output.is_file() and output.stat().st_size > 0:
            return True
        if at <= floor + 1e-6:
            break
        at = max(floor, at - 0.2)
    output.unlink(missing_ok=True)
    return False


def extract_strips(video: str | Path, shots: list[dict], out_dir: str | Path,
                   *, log=print) -> list[dict]:
    """每个镜头抽首/中/尾三格拼成 strip，另存中点 keyframe。

    失败只把该镜头标成 `unchecked` 并写原因，不让整条参考片分析失败。
    """
    video = Path(video).resolve()
    out = Path(out_dir)
    frames = out / "frames"
    frames.mkdir(parents=True, exist_ok=True)
    for shot in shots:
        ident = shot["id"]
        times = strip_times(shot)
        shot["strip_times"] = times
        parts = [frames / f".{ident}-{i}.jpg" for i in range(3)]
        ok = all(_grab(video, at, part, "scale=-2:360", shot["start"])
                 for at, part in zip(times, parts))
        strip = frames / f"strip-{shot['index']:02d}.jpg"
        keyframe = frames / f"shot-{shot['index']:02d}.jpg"
        made = False
        if ok:
            proc = subprocess.run([
                _ffmpeg(), "-hide_banner", "-loglevel", "error", "-y",
                *[item for part in parts for item in ("-i", str(part))],
                "-filter_complex", "[0][1][2]hstack=inputs=3,format=yuvj420p",
                "-q:v", "3", str(strip),
            ], capture_output=True, text=True)
            made = proc.returncode == 0 and strip.is_file() and strip.stat().st_size > 0
        if made:
            _grab(video, times[1], keyframe, "scale=640:-2", shot["start"])
            shot["strip"] = str(strip.relative_to(out))
            shot["keyframe"] = (str(keyframe.relative_to(out))
                                if keyframe.is_file() else None)
            shot["keyframe_at"] = times[1]
            shot["status"] = "ok"
        else:
            shot["strip"] = None
            shot["keyframe"] = None
            shot["status"] = "unchecked"
            shot["reason"] = "三联图抽取失败（seek 超出视频末尾或解码失败）"
            log(f"    {ident}: 三联图抽取失败，标 unchecked")
        for part in parts:
            part.unlink(missing_ok=True)
    return shots


def contact_sheet(shots: list[dict], out_dir: str | Path, *, cols: int = 2,
                  cell_width: int = 560) -> str | None:
    """把每镜 strip 拼成一张总览图，方便人一眼看完所有镜头。"""
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError:
        return None
    out = Path(out_dir)
    rows = []
    for shot in shots:
        rel = shot.get("strip")
        if not rel:
            continue
        path = out / rel
        if not path.is_file():
            continue
        try:
            image = Image.open(path).convert("RGB")
        except OSError:
            continue
        scale = cell_width / image.width
        rows.append((shot, image.resize((cell_width, max(1, round(image.height * scale))),
                                        Image.Resampling.LANCZOS)))
    if not rows:
        return None
    cell_height = max(image.height for _, image in rows)
    label_height = 26
    row_height = cell_height + label_height + 8
    rows_count = (len(rows) + cols - 1) // cols
    header = 34
    sheet = Image.new("RGB", (cols * cell_width + (cols + 1) * 8,
                              header + rows_count * row_height + 8), (18, 18, 18))
    draw = ImageDraw.Draw(sheet)
    font = ImageFont.load_default()
    draw.text((10, 10), "REFERENCE SHOTS  start | middle | end", fill=(230, 230, 230), font=font)
    for position, (shot, image) in enumerate(rows):
        col, row = position % cols, position // cols
        x = 8 + col * (cell_width + 8)
        y = header + row * row_height
        sheet.paste(image, (x, y))
        draw.rectangle([x, y + cell_height, x + cell_width, y + cell_height + label_height],
                       fill=(34, 34, 34))
        label = (f"{shot['id']}  {shot['start']:.2f}-{shot['end']:.2f}s"
                 f"  ({shot['duration']:.2f}s)")
        draw.text((x + 8, y + cell_height + 7), label, fill=(235, 235, 235), font=font)
    target = out / "contact-sheet.jpg"
    sheet.save(target, quality=85)
    return str(target)
