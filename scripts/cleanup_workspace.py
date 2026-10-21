#!/usr/bin/env python3
"""工作区清理清单。默认只出 dry-run，不删项目/模型/成片。

--apply-cache 只删可再生缓存：
  work/auto-edit-pro、__pycache__、*.pyc
不碰 work/models、项目目录、output、draft-store。
"""
from __future__ import annotations
import argparse
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CACHE_DIRS = ("work/auto-edit-pro",)


def size(path: Path) -> int:
    if path.is_file():
        return path.stat().st_size
    return sum(p.stat().st_size for p in path.rglob("*") if p.is_file())


def human(n: int) -> str:
    for unit in ("B", "K", "M", "G"):
        if n < 1024 or unit == "G":
            return f"{n:.1f}{unit}" if unit != "B" else f"{n}{unit}"
        n /= 1024
    return f"{n:.1f}G"


def inventory() -> list[tuple[str, str, str]]:
    rows: list[tuple[str, str, str]] = []
    for path in sorted(ROOT.iterdir(), key=lambda p: -size(p) if p.is_dir() else 0):
        if not path.is_dir() or path.name in {".git", ".venv", "scripts", "tests", "docs", "references", "assets"}:
            continue
        n = size(path)
        if n < 50 * 1024 * 1024:
            continue
        if path.name in {".agent", "work"}:
            continue
        kind = "项目/素材：建议归档，不自动删"
        rows.append((str(path.relative_to(ROOT)), human(n), kind))
    for rel, kind in (("work/models", "ASR 模型缓存：建议移到 ~/.cache/koubo/models"),
                      ("work/auto-edit-pro", "可再生的参考工具缓存：可删"),
                      ("work/segments", "中间片段：可删"),
                      ("work/tests", "测试产物：可删")):
        path = ROOT / rel
        if path.exists():
            rows.append((rel, human(size(path)), kind))
    return rows


def main() -> None:
    ap = argparse.ArgumentParser(description="工作区清理清单/安全缓存清理")
    ap.add_argument("--apply-cache", action="store_true", help="只删可再生的参考工具缓存和 __pycache__")
    a = ap.parse_args()
    rows = inventory()
    lines = ["# 工作区清理清单", "", "| 路径 | 大小 | 建议 |", "| --- | --- | --- |"]
    lines += [f"| `{p}` | {s} | {k} |" for p, s, k in rows]
    lines += ["", "默认不删项目、模型、成片、draft-store。"]
    out = ROOT / "work" / "cleanup-inventory.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
    print(f"\n清单 → {out}")
    if a.apply_cache:
        for rel in CACHE_DIRS:
            path = ROOT / rel
            if path.is_dir():
                shutil.rmtree(path)
                print(f"删除 {rel}")
        for cache in ROOT.rglob("__pycache__"):
            if ".venv" in cache.parts or ".git" in cache.parts:
                continue
            shutil.rmtree(cache, ignore_errors=True)
        print("已清理可再生缓存；项目/模型未动。")
    else:
        print("dry-run：加 --apply-cache 才清理可再生缓存。")


if __name__ == "__main__":
    main()
