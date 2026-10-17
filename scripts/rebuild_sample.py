#!/usr/bin/env python3
"""Import the reviewed short sample once, then rebuild it through the normal pipeline.

The legacy 镜头方案.json is an interchange format, not a second editing engine.
After import, work/edit-plan.json is the editable source of truth.
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

from _common import ensure_dirs, load_config, write_json
from new_project import build_config
from workflow.edit_plan import render_plan
from workflow.speech_policy import require_speech_ready


def import_legacy_plan(sample: Path) -> dict:
    legacy = json.loads((sample / "镜头方案.json").read_text(encoding="utf-8"))
    shots, cursor = [], 0.0
    for number, row in enumerate(legacy["shots"], 1):
        start, duration = float(row["start"]), float(row["duration"])
        source = Path(row["source"]).resolve()
        if abs(start - cursor) > 0.02 or duration <= 0 or not source.is_file():
            raise ValueError(f"旧镜头表第 {number} 条不连续、时长无效或源素材缺失：{source}")
        shots.append({"source": str(source), "in": float(row["source_in"]),
                      "duration": duration, "transition": "cut",
                      "reason": "reviewed-sample", "score": 1.0,
                      "caption": row.get("caption", ""),
                      "chapter": row.get("chapter", ""),
                      "original_shot": row.get("original_shot")})
        cursor = round(cursor + duration, 3)
    if abs(cursor - float(legacy["duration"])) > 0.02:
        raise ValueError("旧镜头表总时长与镜头之和不符")
    return {"version": 1, "mode": "vlog", "shots": shots}


def anchor_for_time(plan: dict, start: float) -> dict:
    cursor = 0.0
    for index, shot in enumerate(plan["shots"], 1):
        end = cursor + float(shot["duration"])
        if cursor - 0.02 <= start < end - 0.02:
            return {"shot_index": index,
                    "shot_ref": {"source": shot["source"], "in": shot["in"],
                                 "duration": shot["duration"]}}
        cursor = end
    raise ValueError(f"旁白锚点 {start:.3f}s 没落在任何镜头上")


def prepare(sample: Path, project: Path) -> None:
    """Create a standard project without overwriting an edited one."""
    sample, project = sample.resolve(), project.resolve()
    config_path, plan_path = project / "config.json", project / "work/edit-plan.json"
    if config_path.exists() or plan_path.exists():
        if not config_path.is_file() or not plan_path.is_file():
            raise ValueError("工程只有 config.json 或 edit-plan.json，无法安全续跑")
        return

    # Validate every source before writing anything into the new project.
    plan = import_legacy_plan(sample)
    cues = json.loads((sample / "旁白时码.json").read_text(encoding="utf-8"))
    if not isinstance(cues.get("lines"), list) or not cues["lines"]:
        raise ValueError("旁白时码中没有逐句证据")
    total = round(sum(s["duration"] for s in plan["shots"]), 3)
    for number, line in enumerate(cues["lines"], 1):
        if (not isinstance(line.get("text"), str) or not line["text"].strip() or
                not 0 <= float(line["start"]) < float(line["end"]) <= total + 0.02):
            raise ValueError(f"旁白时码第 {number} 句无效或超出片长")
    required = {"字幕.srt": "input/captions.srt",
                "旁白字幕.srt": "input/voice-captions.srt",
                "中文旁白.wav": "work/voice.wav",
                "原创节奏BGM.wav": "work/bgm.wav"}
    for source in required:
        if not (sample / source).is_file():
            raise FileNotFoundError(sample / source)

    cfg = build_config("legacy-sample_主流程", "9:16", "clean-cut.mp4", [], None,
                       mode="vlog")
    cfg["canvas"].update({"width": 720, "height": 1280, "fps": int(
        json.loads((sample / "镜头方案.json").read_text(encoding="utf-8"))["fps"])})
    cfg["duration"] = total
    cfg["captions"].update({"size": 62, "margin_lr": 45, "margin_v": 128,
                            "max_width": 630})
    cfg["audio"].update({"speech_mode": "narration", "voice_cues": "voice-cues.json",
                         "voice_subtitle": "voice-captions.srt", "voice_volume": 0.35})
    cfg["jianying"]["name"] = "legacy-sample_主流程"
    p = ensure_dirs(project)
    for source, target in required.items():
        destination = project / target
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(sample / source, destination)
    write_json(plan_path, plan)
    write_json(p["work"] / "voice-cues.json", {
        "version": 1, "duration": cfg["duration"], "subtitle": "voice-captions.srt",
        "lines": [{"start": row["start"], "end": row["end"], "text": row["text"],
                   **anchor_for_time(plan, float(row["start"]))}
                  for row in cues["lines"]]})
    write_json(config_path, cfg)
    require_speech_ready(cfg, project)


def main() -> None:
    ap = argparse.ArgumentParser(description="把旧镜头表样片导入标准工程并重建 MP4 与剪映草稿")
    ap.add_argument("sample", type=Path, help="包含镜头方案.json、已审核配音与字幕的样片目录")
    ap.add_argument("--project", type=Path, help="标准工程目录，默认样片目录下的 主流程工程")
    args = ap.parse_args()
    sample = args.sample.resolve()
    project = (args.project or sample / "主流程工程").resolve()
    if project == sample:
        ap.error("工程目录不能与旧样片目录相同，以免覆盖原样片")
    prepare(sample, project)
    cfg = load_config(project / "config.json")
    plan = json.loads((project / "work/edit-plan.json").read_text(encoding="utf-8"))
    canvas = cfg["canvas"]
    result = render_plan(plan, project / "input/clean-cut.mp4",
                         canvas["width"], canvas["height"], canvas["fps"])
    cfg["duration"] = round(result["duration"], 3)
    write_json(project / "config.json", cfg)
    require_speech_ready(cfg, project)
    subprocess.run([sys.executable, str(Path(__file__).parent / "run_all.py"),
                    str(project)], check=True)


if __name__ == "__main__":
    main()
