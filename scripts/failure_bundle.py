#!/usr/bin/env python3
import argparse, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from workflow.failure_bundle import capture


def main() -> None:
    ap = argparse.ArgumentParser(description="保存失败现场：配置/QC/日志/接触表")
    ap.add_argument("project")
    ap.add_argument("--step", default="manual")
    ap.add_argument("--error", default="manual capture")
    a = ap.parse_args()
    print(capture(Path(a.project).resolve(), a.step, a.error))


if __name__ == "__main__":
    main()
