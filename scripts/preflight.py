#!/usr/bin/env python3
import argparse, json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from workflow.preflight import check


def main() -> None:
    ap = argparse.ArgumentParser(description="frames 前预检")
    ap.add_argument("project")
    a = ap.parse_args()
    result = check(Path(a.project).resolve())
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if not result["ok"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
