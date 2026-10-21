"""音频真重音检测：80ms RMS + 邻域中位数 + 绝对阈值，输出帧/秒。

这不是 BPM 检测；目标是口播里的重读、停顿后的起音、promo 的鼓点。
默认 16kHz 单声道，不依赖 librosa/scipy。
"""
from __future__ import annotations
import json
import subprocess
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from _common import find_ffmpeg, project_paths, resolve_duration, write_json  # noqa: E402

SR = 16000


def extract_pcm(media: Path) -> np.ndarray:
    proc = subprocess.run([find_ffmpeg(), "-v", "error", "-i", str(media),
                           "-vn", "-ac", "1", "-ar", str(SR), "-f", "s16le", "-"],
                          capture_output=True, check=True)
    return np.frombuffer(proc.stdout, dtype=np.int16).astype(np.float32) / 32768.0


def detect(audio: np.ndarray, *, fps: int = 30, window_ms: int = 80,
           rolling_ms: int = 800, rel_thresh: float = 1.6,
           abs_thresh: float = 0.015, min_gap_frames: int = 12) -> dict:
    window = max(1, int(SR * window_ms / 1000))
    n = len(audio) // window
    if n < 3:
        return {"beats": [], "windows": n}
    rms = np.sqrt(np.array([np.mean(audio[i * window:(i + 1) * window] ** 2)
                            for i in range(n)], dtype=np.float64) + 1e-12)
    half = max(1, int(rolling_ms / window_ms)) // 2
    peaks: list[tuple[int, float]] = []
    for i in range(1, n - 1):
        if rms[i] <= rms[i - 1] or rms[i] <= rms[i + 1]:
            continue
        if rms[i] < abs_thresh:
            continue
        med = float(np.median(rms[max(0, i - half):min(n, i + half + 1)]) + 1e-12)
        if rms[i] / med < rel_thresh:
            continue
        sec = i * window / SR
        peaks.append((int(round(sec * fps)), float(rms[i])))
    # 相邻峰去重：保留更强的
    dedup: list[tuple[int, float]] = []
    for frame, energy in peaks:
        if dedup and frame - dedup[-1][0] < min_gap_frames:
            if energy > dedup[-1][1]:
                dedup[-1] = (frame, energy)
        else:
            dedup.append((frame, energy))
    return {
        "beats": [{"frame": f, "time": round(f / fps, 3), "energy": round(e, 4)}
                  for f, e in dedup],
        "windows": n,
        "window_ms": window_ms,
        "fps": fps,
    }


def build(project: Path, media: Path | None = None, fps: int | None = None) -> dict:
    p = project_paths(project)
    cfg = json.loads(p["config"].read_text(encoding="utf-8")) if p["config"].is_file() else {}
    fps = int(fps or (cfg.get("canvas") or {}).get("fps") or 30)
    src = Path(media) if media else p["input"] / (cfg.get("input", {}).get("video") or "clean-cut.mp4")
    if not src.is_file():
        raise SystemExit(f"找不到音频源 {src}")
    audio = extract_pcm(src)
    result = detect(audio, fps=fps)
    result["source"] = str(src)
    result["duration"] = round(len(audio) / SR, 3)
    write_json(p["work"] / "beats.json", result)
    return result


def nearest(result: dict, time: float) -> dict | None:
    beats = result.get("beats") or []
    return min(beats, key=lambda b: abs(b["time"] - time)) if beats else None
