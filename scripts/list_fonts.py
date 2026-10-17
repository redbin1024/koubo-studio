#!/usr/bin/env python3
"""列出可用字体：`captions.font` 到底能写什么。

「换了字体没反应」十有八九是名字没对上 —— 这个脚本把每个字体**自称的族名**
（英文 + 中文，从文件里的 name 表读出来）连同它所在的目录一起打出来，
`captions.font` 直接抄「族名」那一列就行。

用法：
    python scripts/list_fonts.py              # 全部目录
    python scripts/list_fonts.py PROJECT_DIR  # 标出工程 fonts/ 里的（优先命中）
    python scripts/list_fonts.py --cjk-only   # 只看带汉字的
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _common import (  # noqa: E402
    FONT_SEARCH_DIRS, extra_font_dirs, has_cjk_glyphs, _font_entry,
)


def collect(dirs: list[Path], cjk_only: bool) -> list[tuple[str, Path]]:
    rows: list[tuple[str, str, str, Path]] = []
    for d in dirs:
        if not d.is_dir():
            continue
        for f in sorted(d.rglob("*")):
            if f.suffix.lower() not in (".otf", ".ttf", ".ttc"):
                continue
            try:
                e = _font_entry(f)
            except Exception:
                continue
            if cjk_only and not has_cjk_glyphs(f):
                continue
            zh = next((a for a in sorted(e.families)
                       if any("\u4e00" <= c <= "\u9fff" for c in a)), "")
            rows.append((e.display, e.style_display, zh, f))
    return rows


def main() -> None:
    ap = argparse.ArgumentParser(description="列出可用字体族名")
    ap.add_argument("project", nargs="?", default=None)
    ap.add_argument("--cjk-only", action="store_true", help="只列带汉字的字体")
    ap.add_argument("--all", action="store_true", help="连系统目录也扫（默认只扫工程/自定义目录）")
    a = ap.parse_args()

    project = a.project
    own = extra_font_dirs(project)
    dirs = own + (list(FONT_SEARCH_DIRS) if a.all else [])
    if not dirs:
        print("没有可扫的字体目录（工程里没有 fonts/，也没设 KOUBO_FONT_DIRS）")
        return

    for d in dirs:
        rows = collect([d], a.cjk_only)
        if not rows:
            continue
        tag = "  ← 优先命中" if d in own else ""
        print(f"\n{d}{tag}")
        print(f"  {'族名(英文)':<26}{'字重':<11}{'中文名':<12}captions.font 写")
        for fam, sty, zh, f in rows:
            sug = fam if sty.lower() in ("", "regular", "plain", "book") else f"{fam} {sty}"
            print(f"  {fam:<26}{sty:<11}{zh or '—':<12}{sug}")
        print(f"  （{len(rows)} 个）")

    print("\n「captions.font 写」那一列直接抄进 config.json 即可 —— 中英文族名都认。")
    print("例：\"font\": \"Alimama ShuHeiTi\"   或   \"font\": \"阿里妈妈数黑体\"")
    if not a.all:
        print("（加 --all 连系统字体目录一起列；--cjk-only 只看带汉字的）")


if __name__ == "__main__":
    main()
