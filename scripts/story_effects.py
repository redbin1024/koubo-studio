#!/usr/bin/env python3
"""Map approved story beats onto the existing, licensed SFX cue library."""
from __future__ import annotations

import argparse
import json
import os
import tempfile
from pathlib import Path

from story_audio import validate_audio_story


def suggest_events(story: dict) -> list[dict]:
    if story.get("status") != "proposal" or story.get("review_required") is not True:
        raise ValueError("音效节点需要可审核的故事方案")
    order = story.get("order", [])
    refs = story.get("shot_refs", {})
    beats = story.get("beats", [])
    if not isinstance(beats, list) or len(beats) > 3:
        raise ValueError("音效节拍最多三个")
    starts, cursor = {}, 0.0
    for ident in order:
        if ident not in refs or ident in starts:
            raise ValueError("镜头来源映射无效")
        starts[ident] = round(cursor, 3)
        cursor += float(refs[ident]["duration"])
    events, seen = [], set()
    for beat in beats:
        ident, cue = beat.get("shot_id"), beat.get("cue")
        if ident not in starts or ident in seen or cue not in ("wipe", "reveal", "cut"):
            raise ValueError("音效节拍引用了未知/重复镜头或不支持的提示")
        seen.add(ident)
        if starts[ident] > 0:
            events.append({"t": starts[ident], "cue": cue})
    return sorted(events, key=lambda event: event["t"])


def main() -> None:
    ap = argparse.ArgumentParser(description="将审核过的叙事节拍写入音效事件")
    ap.add_argument("project")
    ap.add_argument("--approve-story", action="store_true")
    ap.add_argument("--replace-events", action="store_true")
    args = ap.parse_args()
    if not args.approve_story:
        ap.error("需显式加 --approve-story，先审核故事方案")
    project = Path(args.project).resolve()
    work = project / "work"
    story = json.loads((work / "storyboard.json").read_text(encoding="utf-8"))
    plan = json.loads((work / "edit-plan.json").read_text(encoding="utf-8"))
    validate_audio_story(story, plan)
    events = suggest_events(story)
    if not events:
        print("没有有依据的转场音效节拍；配置未改变")
        return
    config_path = project / "config.json"
    cfg = json.loads(config_path.read_text(encoding="utf-8"))
    if cfg.setdefault("sfx", {}).get("events") and not args.replace_events:
        ap.error("已有人工音效事件；确认替换时加 --replace-events")
    cfg["sfx"]["events"] = events
    fd, name = tempfile.mkstemp(prefix=".config-sfx-", suffix=".json", dir=project)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(cfg, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
        os.replace(name, config_path)
    finally:
        Path(name).unlink(missing_ok=True)
    print(f"已设置 {len(events)} 处音效；运行 scripts/run_all.py 生成音效轨")


if __name__ == "__main__":
    main()
