#!/usr/bin/env python3
"""Export one reviewable movie per declared narration line from the current render."""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from _common import find_ffmpeg, load_config, probe_media, write_json
from workflow.delivery import current_output, receipt_digest
from workflow.speech_policy import _declared_lines, require_speech_ready
from workflow.voice_review import (REVIEW_VERSION, file_digest, load_review, refresh_review,
                                   review_directory)


def _point_to_latest(root: Path, target: Path) -> None:
    pointer = root / "latest"
    if pointer.exists() and not pointer.is_symlink():
        raise ValueError(f"{pointer} 不是本工具创建的链接，不能覆盖")
    pointer.unlink(missing_ok=True)
    pointer.symlink_to(target.name, target_is_directory=True)


def shot_spans(project: Path) -> list[dict]:
    path = Path(project) / "work/edit-plan.json"
    if not path.is_file():
        return []
    plan = json.loads(path.read_text(encoding="utf-8"))
    cursor, result = 0.0, []
    for number, shot in enumerate(plan.get("shots", []), 1):
        duration = float(shot["duration"])
        if duration <= 0:
            raise ValueError(f"镜头表第 {number} 条时长无效")
        result.append({"index": number, "start": round(cursor, 3),
                       "end": round(cursor + duration, 3),
                       "source": str(Path(shot["source"]).resolve()),
                       "source_in": float(shot["in"])})
        cursor += duration
    return result


def relevant_shots(start: float, end: float, spans: list[dict]) -> list[dict]:
    """Show exactly which source ranges are on screen while a line is spoken."""
    matches = []
    for shot in spans:
        overlap_start, overlap_end = max(start, shot["start"]), min(end, shot["end"])
        if overlap_end - overlap_start <= 0.001:
            continue
        matches.append({"index": shot["index"], "source": shot["source"],
                        "timeline_start": round(overlap_start, 3),
                        "timeline_end": round(overlap_end, 3),
                        "source_in": round(shot["source_in"] + overlap_start - shot["start"], 3),
                        "source_out": round(shot["source_in"] + overlap_end - shot["start"], 3)})
    return matches


def export_review(cfg: dict, project: Path) -> dict:
    project = Path(project).resolve()
    from workflow.voice_review import review_required
    if not review_required(cfg):
        raise ValueError("仅对已声明 audio.voice_cues 的旁白工程导出逐句样张")
    require_speech_ready(cfg, project)
    movie, detail = current_output(project, cfg)
    if movie is None:
        raise ValueError(f"没有可供听审的本轮成片：{detail}")
    windows, _, _, problem = _declared_lines(cfg, project)
    if problem:
        raise ValueError(problem)
    identity = receipt_digest(project)
    if not identity:
        raise ValueError("本轮渲染凭据不可读取")
    total = float(probe_media(movie)["duration"])
    spans = shot_spans(project)
    review_root = project / "work/voice-review"
    review_root.mkdir(parents=True, exist_ok=True)
    target = review_directory(project, identity)
    if target.exists():
        load_review(cfg, project)
        status = refresh_review(cfg, project)
        _point_to_latest(review_root, target)
        return {"directory": str(target), "lines": len(windows),
                "manifest": str(target / "manifest.json"), "reused": True,
                "human_review": status["status"]}

    stage = Path(tempfile.mkdtemp(prefix=".voice-review-", dir=review_root))
    try:
        lines = []
        for number, (start, end, spoken_text) in enumerate(windows, 1):
            clip_start = max(0.0, start - 0.35)
            clip_end = min(total, end + 0.45)
            if clip_end <= clip_start:
                raise ValueError(f"第 {number} 句时间范围无效")
            filename = f"line-{number:02d}.mp4"
            command = [find_ffmpeg(), "-v", "error", "-y", "-ss", f"{clip_start:.3f}",
                       "-i", str(movie), "-t", f"{clip_end - clip_start:.3f}",
                       "-map", "0:v:0", "-map", "0:a:0", "-c:v", "libx264",
                       "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p",
                       "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart",
                       str(stage / filename)]
            subprocess.run(command, check=True, capture_output=True)
            shots = relevant_shots(start, end, spans)
            lines.append({"index": number, "text": spoken_text,
                          "start": start, "end": end, "clip": filename,
                          "clip_start": round(clip_start, 3),
                          "clip_end": round(clip_end, 3), "shots": shots,
                          "clip_sha256": file_digest(stage / filename)})
        record = {"version": REVIEW_VERSION, "render_receipt_sha256": identity,
                  "source_video": str(movie),
                  "lines": lines}
        write_json(stage / "manifest.json", record)
        os.replace(stage, target)
        status = refresh_review(cfg, project)
        _point_to_latest(review_root, target)
    finally:
        if stage.exists():
            shutil.rmtree(stage)
    return {"directory": str(target), "lines": len(lines),
            "manifest": str(target / "manifest.json"), "reused": False,
            "human_review": status["status"]}


def main() -> None:
    ap = argparse.ArgumentParser(description="从本轮成片导出逐句旁白听审视频")
    ap.add_argument("project", type=Path)
    args = ap.parse_args()
    project = args.project.resolve()
    result = export_review(load_config(project / "config.json"), project)
    print(f"听审样张 {result['lines']} 句 → {result['directory']}")
    print(f"清单 → {Path(result['directory']) / '听审清单.md'}")


if __name__ == "__main__":
    main()
