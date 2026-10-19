#!/usr/bin/env python3
"""成片/参考片的节奏与切点分析（自适应 scene score）。"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from workflow.pacing import report  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser(description="自适应切点 + 镜头统计 + VFR/响度")
    ap.add_argument("video")
    ap.add_argument("-o", "--output", help="输出 JSON")
    ap.add_argument("--min-gap", type=float, default=0.25)
    ap.add_argument("--mad-k", type=float, default=3.0)
    ap.add_argument("--summary", action="store_true")
    args = ap.parse_args()
    data = report(Path(args.video), min_gap=args.min_gap, mad_k=args.mad_k)
    if args.output:
        Path(args.output).write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n",
                                     encoding="utf-8")
    else:
        print(json.dumps(data, ensure_ascii=False, indent=2))
    if args.summary:
        p = data["pacing"]
        print(f"{data['duration']}s / {data['width']}x{data['height']} / "
              f"{data['avg_fps']}fps{' VFR?' if data['vfr_suspect'] else ''}")
        print(f"镜头 {p['shot_count']} | 切点 {p['cut_count']} | 每分钟 {p['cuts_per_minute']} 切")
        if p["median_shot_duration"] is not None:
            print(f"平均 {p['avg_shot_duration']}s / 中位 {p['median_shot_duration']}s / "
                  f"最短 {p['min_shot_duration']}s / 最长 {p['max_shot_duration']}s")
        if data.get("loudness"):
            ln = data["loudness"]
            print(f"响度 {ln.get('input_i')} LUFS / 真峰 {ln.get('input_tp')} dBTP")


if __name__ == "__main__":
    main()
