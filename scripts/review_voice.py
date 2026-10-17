#!/usr/bin/env python3
"""Record a human decision for one narration line, or show current review status."""
from __future__ import annotations

import argparse
from pathlib import Path

from _common import load_config
from workflow.voice_review import CRITERIA, record_decision, refresh_review


def main() -> None:
    ap = argparse.ArgumentParser(description="登记逐句旁白人工验收；不带 --line 时只刷新并显示状态")
    ap.add_argument("project", type=Path)
    ap.add_argument("--line", type=int, help="听审清单中的句号")
    ap.add_argument("--reviewer", help="实际审核人")
    ap.add_argument("--note", default="", help="问题或复审说明；有 fail 时必填")
    for key, label in CRITERIA.items():
        ap.add_argument(f"--{key}", choices=("pass", "fail"), help=label)
    args = ap.parse_args()
    project = args.project.resolve()
    cfg = load_config(project / "config.json")
    checks = {key: getattr(args, key) for key in CRITERIA}
    if args.line is None and (args.reviewer or args.note or any(checks.values())):
        ap.error("登记结果时须指定 --line")
    try:
        status = (record_decision(cfg, project, args.line, checks, args.reviewer, args.note)
                  if args.line is not None else refresh_review(cfg, project))
    except ValueError as exc:
        ap.error(str(exc))
    print(f"听审状态 → {status['label']}")
    if "summary" in status:
        counts = status["summary"]
        print(f"  {counts['passed']} 句通过 / {counts['failed']} 句需修改 / {counts['pending']} 句待审")
    if status.get("detail"):
        print(f"  {status['detail']}")
    if status.get("directory"):
        print(f"  清单 → {Path(status['directory']) / '听审清单.md'}")


if __name__ == "__main__":
    main()
