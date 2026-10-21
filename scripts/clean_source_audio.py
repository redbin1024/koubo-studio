#!/usr/bin/env python3
"""Clean a talking-head source: mute non-speech gaps and lightly denoise.

Usage:
  python scripts/clean_source_audio.py PROJECT --mute 9.49:9.95 --mute 26.45:26.91
Writes input/clean-cut-clean.mp4 (video stream copied) and updates config.input.video.
"""
from __future__ import annotations
import argparse, json, subprocess, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from _common import find_ffmpeg, load_config, project_paths, write_json


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("project")
    ap.add_argument("--mute", action="append", default=[], help="start:end seconds")
    ap.add_argument("--source", default="clean-cut.mp4")
    ap.add_argument("--out", default="clean-cut-clean.mp4")
    a = ap.parse_args()
    project = Path(a.project).resolve()
    p = project_paths(project)
    src = p["input"] / a.source
    if not src.is_file():
        raise SystemExit(f"找不到 {src}")
    intervals = []
    for raw in a.mute:
        start, end = (float(x) for x in raw.split(":"))
        if end <= start:
            raise SystemExit(f"无效区间 {raw}")
        intervals.append((start, end))
    enable = "+".join(f"between(t,{s:.3f},{e:.3f})" for s, e in intervals) or "0"
    af = f"afftdn=nf=-25,volume=volume=0:enable='{enable}'"
    dest = p["input"] / a.out
    subprocess.run([find_ffmpeg(), "-v", "error", "-y", "-i", str(src),
                    "-c:v", "copy", "-af", af, "-c:a", "aac", "-b:a", "192k",
                    "-movflags", "+faststart", str(dest)], check=True)
    cfg = load_config(p["config"])
    cfg["input"]["video"] = a.out
    write_json(p["config"], cfg)
    write_json(p["work"] / "audio-clean.json", {
        "source": str(src), "output": str(dest), "muted": intervals,
        "filter": "afftdn + volume=0 on non-speech gaps",
    })
    print(dest)


if __name__ == "__main__":
    main()
