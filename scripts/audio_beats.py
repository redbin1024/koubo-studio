#!/usr/bin/env python3
import argparse, json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from workflow.audio_beats import build


def main() -> None:
    ap = argparse.ArgumentParser(description="检测口播真重音，写 work/beats.json")
    ap.add_argument("project")
    ap.add_argument("--media")
    ap.add_argument("--fps", type=int)
    a = ap.parse_args()
    result = build(Path(a.project).resolve(), Path(a.media) if a.media else None, a.fps)
    print(json.dumps({"source": result["source"], "duration": result["duration"],
                      "beats": len(result["beats"]),
                      "first": result["beats"][:8]}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
