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
    temp_path = Path(temporary)

    def attempt(audio_filter: str) -> dict:
        subprocess.run([find_ffmpeg(), "-v", "error", "-y", "-i", str(path),
                        "-map", "0:v:0", "-map", "0:a:0", "-c:v", "copy",
                        "-af", audio_filter,
                        "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2",
                        "-movflags", "+faststart", str(temp_path)],
                       check=True, capture_output=True)
        return measure_loudness(temp_path, target)

    def good(value: dict | None) -> bool:
        return bool(value) and abs(value["input_i"] - target["I"]) <= 1.0 and \
            value["input_tp"] <= target["TP"] + 0.3

    try:
        best = None
        corrected = attempt(effect)
        if good(corrected):
            best = corrected
        else:
            # 实测：带 offset 的线性二次校准偶尔只走 0.16dB（BGM+短旁白尤其明显）。
            # 先去掉 offset 再试一次，仍不达标就用一次确定性 volume 增益 + 限峰。
            no_offset = effect.replace(f":offset={measured['target_offset']}", "")
            candidate = attempt(no_offset)
            best = candidate if good(candidate) else None
            if best is None:
                basis = measured
                gain = target["I"] - float(basis["input_i"])
                limit = 10 ** ((target["TP"] - 0.2) / 20)
                candidate = attempt(f"volume={gain:.2f}dB,"
                                    f"alimiter=level_in=1:level_out=1:limit={limit:.4f}:"
                                    "attack=5:release=50:level=disabled")
                best = candidate if good(candidate) else None
        if best is None:
            raise ValueError(f"最终混音响度校准未达标：{corrected}")
        os.replace(temp_path, path)
        return best
    finally:
        temp_path.unlink(missing_ok=True)
