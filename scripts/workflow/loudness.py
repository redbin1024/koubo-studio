"""Measure the final mixed signal and correct loudness after peak limiting."""
from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
from pathlib import Path

from _common import find_ffmpeg


def measure_loudness(path: Path, target: dict | None = None) -> dict:
    target = target or {"I": -14, "TP": -2.6, "LRA": 11}
    effect = (f"loudnorm=I={target['I']}:TP={target['TP']}:LRA={target['LRA']}:print_format=json")
    result = subprocess.run([find_ffmpeg(), "-hide_banner", "-nostats", "-i", str(path),
                             "-vn", "-af", effect, "-f", "null", "-"],
                            check=True, capture_output=True, text=True)
    blocks = re.findall(r"\{[^{}]*input_i[^{}]*\}", result.stderr, re.S)
    if not blocks:
        return {}
    return {key: float(value) for key, value in json.loads(blocks[-1]).items()
            if key != "normalization_type" and value not in ("", None)}


def normalize_final_audio(path: Path, target: dict) -> dict:
    """Keep video unchanged; use measured final audio when the first mix is too quiet."""
    measured = measure_loudness(path, target)
    if not measured:
        raise ValueError("无法测量最终混音响度")
    if (abs(measured["input_i"] - target["I"]) <= 0.5 and
            measured["input_tp"] <= target["TP"] + 0.1):
        return measured
    effect = (f"loudnorm=I={target['I']}:TP={target['TP']}:LRA={target['LRA']}:"
              f"measured_I={measured['input_i']}:measured_TP={measured['input_tp']}:"
              f"measured_LRA={measured['input_lra']}:measured_thresh={measured['input_thresh']}:"
              f"offset={measured['target_offset']}:linear=true")
    fd, temporary = tempfile.mkstemp(prefix=".audio-normalized-", suffix=".mp4", dir=path.parent)
    os.close(fd)
    try:
        subprocess.run([find_ffmpeg(), "-v", "error", "-y", "-i", str(path),
                        "-map", "0:v:0", "-map", "0:a:0", "-c:v", "copy", "-af", effect,
                        "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2",
                        "-movflags", "+faststart", temporary], check=True, capture_output=True)
        corrected = measure_loudness(Path(temporary), target)
        if (not corrected or abs(corrected["input_i"] - target["I"]) > 1.0 or
                corrected["input_tp"] > target["TP"] + 0.3):
            raise ValueError(f"最终混音响度校准未达标：{corrected}")
        os.replace(temporary, path)
        return corrected
    finally:
        Path(temporary).unlink(missing_ok=True)
