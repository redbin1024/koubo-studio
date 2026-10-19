"""节奏分析：自适应切点 + 镜头统计 + VFR/时长诊断 + 响度。

固定 `scdet=10` / `scene>0.35` 对「等亮度换色」会漏判；这里先拿全量 scene score，
再用中位数 + MAD 自适应阈值，并在 min_gap 内做非极大抑制。
这是从 Edit-Skill 的 analyze_film 方法里吸收的，不复制其代码。
"""
from __future__ import annotations

import json
import re
import statistics
import subprocess
from pathlib import Path

from _common import find_ffmpeg, probe_media


def _ffprobe(path: Path) -> dict:
    proc = subprocess.run([
        "ffprobe", "-v", "error", "-select_streams", "v:0",
        "-show_entries", "stream=r_frame_rate,avg_frame_rate,duration,nb_frames,width,height",
        "-show_entries", "format=duration", "-of", "json", str(path)],
        capture_output=True, text=True)
    try:
        return json.loads(proc.stdout or "{}")
    except json.JSONDecodeError:
        return {}


def scene_scores(path: Path) -> list[tuple[float, float]]:
    """全量 scene score：[(秒, score)]。字幕/闪烁会产生低分，交给自适应阈值压掉。"""
    proc = subprocess.run([
        find_ffmpeg(), "-hide_banner", "-nostats", "-i", str(path), "-an",
        "-vf", "select='gt(scene,0)',metadata=print", "-f", "null", "-"],
        capture_output=True, text=True)
    scores: list[tuple[float, float]] = []
    t = None
    for line in proc.stderr.splitlines():
        m = re.search(r"pts_time:([\d.]+)", line)
        if m:
            t = float(m.group(1))
            continue
        m = re.search(r"lavfi\.scene_score=([\d.]+)", line)
        if m and t is not None:
            scores.append((round(t, 3), float(m.group(1))))
            t = None
    return scores


def adaptive_cuts(scores: list[tuple[float, float]], *,
                  min_gap: float = 0.25, mad_k: float = 3.0,
                  floor: float = 0.06) -> list[dict]:
    if not scores:
        return []
    values = [s for _, s in scores]
    med = statistics.median(values)
    mad = statistics.median(abs(v - med) for v in values)
    threshold = max(floor, med + mad_k * 1.4826 * mad)
    peaks = [(t, s) for t, s in scores if s >= threshold]
    # 非极大抑制：min_gap 内保留最高分。
    kept: list[dict] = []
    for t, s in peaks:
        if kept and t - kept[-1]["t"] < min_gap:
            if s > kept[-1]["score"]:
                kept[-1] = {"t": t, "score": round(s, 3)}
            continue
        kept.append({"t": t, "score": round(s, 3)})
    return kept


def _loudness(path: Path) -> dict | None:
    proc = subprocess.run([
        find_ffmpeg(), "-hide_banner", "-nostats", "-i", str(path),
        "-af", "loudnorm=I=-14:TP=-2.6:LRA=11:print_format=json",
        "-f", "null", "-"], capture_output=True, text=True)
    text = proc.stderr or ""
    marker = text.find('"input_i"')
    start = text.rfind("{", 0, marker) if marker >= 0 else -1
    if start < 0:
        return None
    try:
        data, _ = json.JSONDecoder().raw_decode(text[start:])
    except json.JSONDecodeError:
        return None
    return {k: float(data[k]) for k in ("input_i", "input_tp", "input_lra")
            if k in data}


def report(path: Path, *, min_gap: float = 0.25, mad_k: float = 3.0) -> dict:
    path = Path(path)
    info = probe_media(path)
    meta = _ffprobe(path)
    stream = (meta.get("streams") or [{}])[0]
    ratio = stream.get("r_frame_rate") or "0/1"
    avg = stream.get("avg_frame_rate") or ratio

    def num(value: str) -> float:
        try:
            a, b = value.split("/")
            return float(a) / float(b) if float(b) else 0.0
        except (ValueError, ZeroDivisionError):
            return 0.0

    r_fps, avg_fps = num(ratio), num(avg)
    stream_dur = float(stream.get("duration") or 0)
    container_dur = float(info.get("duration") or 0)
    vfr = bool(r_fps and avg_fps and abs(r_fps - avg_fps) / max(r_fps, 1e-9) > 0.01)
    duration = stream_dur or container_dur
    scores = scene_scores(path)
    cuts = adaptive_cuts(scores, min_gap=min_gap, mad_k=mad_k)
    bounds = [0.0] + [c["t"] for c in cuts if 0 < c["t"] < duration] + [duration]
    durs = [round(b - a, 3) for a, b in zip(bounds, bounds[1:]) if b - a > 0.001]
    pacing = {
        "shot_count": len(durs),
        "cut_count": max(0, len(durs) - 1),
        "cuts_per_minute": round(max(0, len(durs) - 1) / duration * 60, 2) if duration else None,
        "avg_shot_duration": round(statistics.mean(durs), 3) if durs else None,
        "median_shot_duration": round(statistics.median(durs), 3) if durs else None,
        "min_shot_duration": round(min(durs), 3) if durs else None,
        "max_shot_duration": round(max(durs), 3) if durs else None,
        "stdev_shot_duration": round(statistics.pstdev(durs), 3) if len(durs) > 1 else 0.0,
    }
    return {
        "video": str(path),
        "duration": round(duration, 3),
        "container_duration": round(container_dur, 3),
        "width": info.get("width"), "height": info.get("height"),
        "r_fps": round(r_fps, 3), "avg_fps": round(avg_fps, 3),
        "vfr_suspect": vfr,
        "stream_duration_delta": round(container_dur - stream_dur, 3) if stream_dur else None,
        "scene_scores": len(scores),
        "cuts": cuts,
        "pacing": pacing,
        "loudness": _loudness(path) if info.get("has_audio") else None,
    }
