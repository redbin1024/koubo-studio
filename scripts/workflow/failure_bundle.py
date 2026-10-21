"""失败现场包：把本轮配置、日志、QC 和接触表收進 work/failures/。"""
from __future__ import annotations
import json, shutil, time
from pathlib import Path
from _common import project_paths, write_json

FILES = (
    "config.json",
    "work/qc-report.json", "work/pipeline.json", "work/review-report.json",
    "work/jianying-draft.json", "work/draft-qc.json", "work/draft-spec.json",
    "work/visual-contract.json", "work/mixkit.json", "work/font-selection.json",
    "work/beats.json", "work/audio-clean.json",
)
DIRS = ("work/check", "work/still-candidates", "work/packaging-review")


def capture(project: Path, step: str, error: str) -> Path:
    p = project_paths(project)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    dest = p["work"] / "failures" / f"{stamp}-{step}"
    dest.mkdir(parents=True, exist_ok=True)
    copied = []
    for rel in FILES:
        src = project / rel
        if src.is_file():
            target = dest / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, target)
            copied.append(rel)
    for rel in DIRS:
        src = project / rel
        if src.is_dir():
            target = dest / rel
            shutil.copytree(src, target, dirs_exist_ok=True)
            copied.append(rel)
    write_json(dest / "failure.json", {
        "step": step, "error": str(error), "copied": copied,
        "at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
    })
    return dest
