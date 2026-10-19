#!/usr/bin/env python3
"""生成包装层视觉审查包（Gate C 的轻量版）。

对每个非原生 beat：抽 72% 稳定帧 + 完整 beat 片段；
原生特效/滤镜/转场：mp4 预览不包含，标记 requires-capcut-export，
不拿底层视频冒充原生效果证据。

产物：
  work/packaging-review/frames/*.png
  work/packaging-review/clips/*.mp4
  work/packaging-review/contact-sheet.jpg
  work/packaging-review.json   status=pending，等人工逐项填写
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from _common import find_ffmpeg, load_config, project_paths, write_json  # noqa: E402
from workflow.delivery import current_output  # noqa: E402


def _sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def _run(args: list[str]) -> None:
    subprocess.run(args, check=True, capture_output=True)


def build(cfg: dict, project: Path, *, force: bool = False) -> dict:
    p = project_paths(project)
    contract_path = p["work"] / "visual-contract.json"
    if not contract_path.is_file():
        raise FileNotFoundError("没有 work/visual-contract.json；先跑 make_jianying_draft.py")
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    movie, detail = current_output(project, cfg)
    if movie is None:
        raise ValueError(f"视觉审查需要本轮成片：{detail}")
    out = p["work"] / "packaging-review"
    frames_dir, clips_dir = out / "frames", out / "clips"
    for directory in (frames_dir, clips_dir):
        if directory.exists() and force:
            for child in directory.iterdir():
                child.unlink()
        directory.mkdir(parents=True, exist_ok=True)

    ff = find_ffmpeg()
    beats = []
    frame_paths = []
    for beat in contract.get("beats") or []:
        start, end = float(beat["start"]), float(beat["end"])
        draft_only = bool(beat.get("native") or beat.get("draft_only"))
        row = {"id": beat["id"], "kind": beat["kind"], "native": bool(beat.get("native")),
               "draft_only": draft_only, "start": start, "end": end,
               "still": None, "clip": None, "checks": {}, "status": "pending"}
        checks = (["native_loaded", "native_visible", "style_fit"] if draft_only
                  else ["visible", "readable", "semantic_fit", "style_fit", "occlusion"])
        row["checks"] = {name: {"status": "pending", "observation": ""} for name in checks}
        if draft_only:
            row["status"] = "requires-capcut-export"
            row["note"] = ("草稿专属资源不在 mp4 预览里；需在剪映打开/导出后审查"
                           if not beat.get("native") else
                           "原生资源不在 mp4 预览里；需在剪映打开/导出后审查")
            beats.append(row)
            continue
        mid = start + max(0.0, end - start) * 0.72
        still = frames_dir / f"{beat['id']}.png"
        _run([ff, "-y", "-v", "error", "-ss", f"{mid:.3f}", "-i", str(movie),
              "-frames:v", "1", str(still)])
        clip = clips_dir / f"{beat['id']}.mp4"
        _run([ff, "-y", "-v", "error", "-ss", f"{start:.3f}", "-i", str(movie),
              "-t", f"{max(0.05, end - start):.3f}", "-c:v", "libx264",
              "-preset", "veryfast", "-crf", "20", "-c:a", "aac", "-b:a", "128k",
              "-movflags", "+faststart", str(clip)])
        row.update({"still": str(still), "clip": str(clip),
                    "still_sha256": _sha(still), "clip_sha256": _sha(clip)})
        frame_paths.append(still)
        beats.append(row)

    sheet = out / "contact-sheet.jpg"
    if frame_paths:
        try:
            from PIL import Image
            thumbs = [Image.open(path).convert("RGB").resize((270, 480)) for path in frame_paths]
            cols = min(4, len(thumbs))
            rows = (len(thumbs) + cols - 1) // cols
            canvas = Image.new("RGB", (cols * 270, rows * 480), (11, 19, 37))
            for i, image in enumerate(thumbs):
                canvas.paste(image, ((i % cols) * 270, (i // cols) * 480))
            canvas.save(sheet, quality=90)
        except Exception:
            sheet = None

    review = {
        "version": 1,
        "status": "pending",
        "project": contract.get("project"),
        "movie": str(movie),
        "movie_sha256": _sha(movie),
        "contact_sheet": str(sheet) if sheet else None,
        "beats": beats,
        "note": "status 保持 pending；实际观看后逐项填写 observation，全部 pass 后再改 status=pass。",
    }
    write_json(p["work"] / "packaging-review.json", review)
    pending = sum(1 for b in beats if b["status"] == "requires-capcut-export")
    print(f"  视觉审查包 {len(beats)} 个 beat → {out}")
    if pending:
        print(f"  其中 {pending} 个原生资源需在剪映导出后审查")
    return review


def main() -> None:
    ap = argparse.ArgumentParser(description="生成包装层视觉审查包")
    ap.add_argument("project")
    ap.add_argument("--force", action="store_true", help="清空旧的帧/片段")
    args = ap.parse_args()
    project = Path(args.project).resolve()
    cfg = load_config(project_paths(project)["config"])
    build(cfg, project, force=args.force)


if __name__ == "__main__":
    main()
