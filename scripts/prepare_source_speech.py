#!/usr/bin/env python3
"""Prepare source-speech evidence independently of video rendering."""
from __future__ import annotations

import argparse
from pathlib import Path

from _common import load_config
from workflow.source_speech import EVIDENCE_NAME, import_source_evidence, prepare_source_evidence


def main() -> None:
    ap = argparse.ArgumentParser(description="为口播原声准备离线转写证据，不渲染成片")
    ap.add_argument("project")
    ap.add_argument("--transcript", type=Path, help="导入现有 transcribe_audio.py 的 JSON")
    args = ap.parse_args()
    project = Path(args.project).resolve()
    cfg = load_config(project / "config.json")
    if cfg["audio"]["speech_mode"] != "source":
        ap.error("仅适用于 audio.speech_mode=source 的工程")
    if args.transcript:
        try:
            record = import_source_evidence(cfg, project, args.transcript)
        except (ValueError, OSError) as exc:
            ap.error(str(exc))
    else:
        record = prepare_source_evidence(cfg, project)
    from workflow.speech_policy import require_speech_ready
    require_speech_ready(cfg, project)
    print(f"原声证据已就绪：{project / 'work' / EVIDENCE_NAME}"
          f"（{len(record['words'])} 词）；未渲染成片")


if __name__ == "__main__":
    main()
