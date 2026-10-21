#!/usr/bin/env python3
"""Extract a real still from the project's clean cut for an editorial card window."""
from __future__ import annotations
import argparse, json, subprocess, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from _common import find_ffmpeg, project_paths, write_json


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("project")
    ap.add_argument("--time", type=float, required=True)
    ap.add_argument("--out", default=None, help="relative assets/stills/name.jpg")
    ap.add_argument("--source", default="clean-cut.mp4")
    ap.add_argument("--focus", default="0.5,0.5")
    a = ap.parse_args()
    project = Path(a.project).resolve()
    p = project_paths(project)
    src = p["input"] / a.source
    if not src.is_file():
        raise SystemExit(f"找不到 {src}")
    out = str(Path(a.out or f"stills/still-{a.time:.2f}.jpg"))
    dest = p["assets"] / out
    rel = str(Path(out))
    dest.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run([find_ffmpeg(), "-v", "error", "-y", "-ss", f"{a.time:.3f}",
                    "-i", str(src), "-frames:v", "1", "-q:v", "2", str(dest)], check=True)
    manifest = dest.parent / "manifest.json"
    try:
        data = json.loads(manifest.read_text())
    except (OSError, ValueError):
        data = {"version": 1, "items": []}
    data["items"] = [x for x in data["items"] if x.get("file") != rel]
    data["items"].append({"id": dest.stem, "file": rel, "tier": "still",
                          "source": f"{a.source}@{a.time:.3f}s",
                          "focus": [float(x) for x in a.focus.split(",")],
                          "license": "project-owned"})
    write_json(manifest, data)
    print(dest)


if __name__ == "__main__":
    main()
