#!/usr/bin/env python3
"""Extract a real still from the project's clean cut for an editorial card window."""
from __future__ import annotations
import argparse, json, subprocess, sys
from pathlib import Path
import numpy as np
from PIL import Image, ImageOps
sys.path.insert(0, str(Path(__file__).parent))
from _common import find_ffmpeg, project_paths, probe_media, write_json


def _clarity(path: Path) -> tuple[float, float, float]:
    with Image.open(path) as image:
        gray = np.asarray(ImageOps.grayscale(image), dtype=np.float64)
    if gray.ndim != 2 or min(gray.shape) < 3:
        return 0.0, 0.0, 0.0
    lap = (gray[1:-1, 1:-1] * 4 - gray[:-2, 1:-1] - gray[2:, 1:-1]
           - gray[1:-1, :-2] - gray[1:-1, 2:])
    return float(lap.var()), float(gray.mean()), float(gray.std())


def _faces(path: Path) -> int:
    try:
        import cv2
        cascade = cv2.CascadeClassifier(
            str(Path(cv2.data.haarcascades) / "haarcascade_frontalface_default.xml"))
        image = cv2.imdecode(np.fromfile(str(path), dtype=np.uint8), cv2.IMREAD_COLOR)
        if image is None:
            return 0
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        return len(cascade.detectMultiScale(gray, 1.2, 4, minSize=(80, 80)))
    except Exception:
        return 0


def _extract(src: Path, t: float, dest: Path) -> bool:
    subprocess.run([find_ffmpeg(), "-v", "error", "-y", "-ss", f"{t:.3f}",
                    "-i", str(src), "-frames:v", "1", "-q:v", "2", str(dest)], check=True)
    return dest.is_file() and dest.stat().st_size > 0


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("project")
    ap.add_argument("--time", type=float, help="指定秒数；不填则 --scan")
    ap.add_argument("--scan", type=int, default=0, help="自动扫 N 帧，按清晰度/亮度挑最佳")
    ap.add_argument("--out", default=None, help="relative assets/stills/name.jpg")
    ap.add_argument("--source", default="clean-cut.mp4")
    ap.add_argument("--focus", default="0.5,0.5")
    a = ap.parse_args()
    project = Path(a.project).resolve()
    p = project_paths(project)
    src = p["input"] / a.source
    if not src.is_file():
        raise SystemExit(f"找不到 {src}")
    if a.time is None and not a.scan:
        raise SystemExit("需要 --time 或 --scan N")
    dest = p["assets"] / str(Path(a.out or (f"stills/best-{a.scan}.jpg" if a.scan else f"stills/still-{a.time:.2f}.jpg")))
    dest.parent.mkdir(parents=True, exist_ok=True)
    rel = str(dest.relative_to(p["assets"]))
    picked_time = a.time or 0.0
    candidates = []
    if a.scan:
        total = float(probe_media(src)["duration"])
        count = max(1, a.scan)
        times = [total * (0.08 + 0.84 * i / max(1, count - 1)) for i in range(count)]
        cand_dir = p["work"] / "still-candidates"
        cand_dir.mkdir(parents=True, exist_ok=True)
        for i, t in enumerate(times):
            path = cand_dir / f"cand-{i:02d}-{t:.2f}.jpg"
            if not _extract(src, t, path):
                continue
            clarity, mean, std = _clarity(path)
            bright = 20 < mean < 235 and std > 15
            faces = _faces(path)
            score = float(np.log1p(max(clarity, 1.0)) * 10
                          + (100 if faces else 0) + (20 if bright else 0))
            candidates.append({"time": round(t, 3), "file": str(path),
                               "clarity": round(clarity, 2), "brightness": round(mean, 2),
                               "faces": faces, "score": round(score, 2)})
        if not candidates:
            raise SystemExit("没有抽到可用候选帧")
        candidates.sort(key=lambda x: x["score"], reverse=True)
        best = candidates[0]
        dest.write_bytes(Path(best["file"]).read_bytes())
        picked_time = float(best["time"])
    else:
        _extract(src, float(a.time), dest)
    manifest = dest.parent / "manifest.json"
    try:
        data = json.loads(manifest.read_text())
    except (OSError, ValueError):
        data = {"version": 1, "items": []}
    data["items"] = [x for x in data["items"] if x.get("file") != rel]
    data["items"].append({"id": dest.stem, "file": rel,
                          "tier": "still", "source": f"{a.source}@{picked_time:.3f}s",
                          "note": "从用户提供的源片抽帧；商用权利随源片",
                          "focus": [float(x) for x in a.focus.split(",")],
                          "license": "project-input",
                          "score": candidates[0]["score"] if candidates else None,
                          "candidates": candidates[:5]})
    write_json(manifest, data)
    print(dest)


if __name__ == "__main__":
    main()
