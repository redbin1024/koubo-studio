#!/usr/bin/env python3
"""Render transparent caption PNGs for a draft fallback when CapCut ignores font fields."""
from __future__ import annotations
import argparse, sys
from pathlib import Path
from PIL import Image
sys.path.insert(0, str(Path(__file__).parent))
from _common import load_config, project_paths
from caption_layer import CaptionLayer


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("project")
    ap.add_argument("--out", default="caption-overlays")
    a = ap.parse_args()
    project = Path(a.project).resolve()
    p = project_paths(project)
    cfg = load_config(p["config"])
    W, H = int(cfg["canvas"]["width"]), int(cfg["canvas"]["height"])
    layer = CaptionLayer(cfg, project)
    out = p["work"] / a.out
    out.mkdir(parents=True, exist_ok=True)
    for i, cue in enumerate(layer.cues, 1):
        mid = (float(cue["start"]) + float(cue["end"])) / 2
        image = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        image = layer.draw(image, mid)
        dest = out / f"cue-{i:02d}.png"
        image.save(dest)
        print(dest, f"{cue['start']:.3f}-{cue['end']:.3f}")


if __name__ == "__main__":
    main()
