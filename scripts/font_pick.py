#!/usr/bin/env python3
"""按参考片分析自动选字体，并可写进工程 config。

    koubo font-pick my-video --reference my-video/work/reference --apply
    koubo font-pick my-video --no-llm --library local
    koubo font-pick my-video --reference ref/reference-profile.json --commercial

候选字体来自：
- 本机 CJK 字体：工程 `fonts/` → 安装目录 `fonts/` → `KOUBO_FONT_DIRS` → 系统字体；
- emfont 在线库：复用 emfont-mcp 的 `/list` `/info` `/g` 接口，接口不可用就只用本地。

AI 只从候选闭集里选；没有 Key / 调用失败 / 输出不合格时回退本地风格打分，
并在 `work/font-selection.json` 里写明 `mode=ai|fallback`。
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS))

from workflow import font_picker  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser(description="按参考片分析选字幕字体（可用 emfont 字体库）")
    ap.add_argument("project", help="工程目录（含 config.json）")
    ap.add_argument("--reference", help="参考片档案：目录 / reference-profile.json / "
                                        "拆解 JSON；默认读 <工程>/work/reference")
    ap.add_argument("--library", choices=("auto", "local", "emfont"), default="auto",
                    help="字体库：local 只用本机，emfont 只用在线，auto 两者合并")
    ap.add_argument("--apply", action="store_true", help="把选中的字体写进 config.captions.font")
    ap.add_argument("--force", action="store_true",
                    help="允许替换 style-lock 锁定的字体（会让 koubo style check 变红）")
    ap.add_argument("--no-llm", action="store_true", help="不调用 DeepSeek，只用本地打分")
    ap.add_argument("--model", default=font_picker.DEFAULT_MODEL)
    ap.add_argument("--commercial", action="store_true",
                    help="商用场景：降低 NC/非商业授权字体的分数")
    ap.add_argument("--strict-license", action="store_true",
                    help="只保留明确 OFL/Apache/MIT/免费商用 的字体（系统字体会被排除）")
    ap.add_argument("--max-candidates", type=int, default=font_picker.MAX_CANDIDATES)
    ap.add_argument("--json", action="store_true", help="只打印 font-selection.json 路径")
    args = ap.parse_args()

    project = Path(args.project).resolve()
    if not project.is_dir():
        raise SystemExit(f"工程目录不存在：{project}")
    log = (lambda *_: None) if args.json else print
    try:
        result = font_picker.select(
            project, args.reference, library=args.library, no_llm=args.no_llm,
            model=args.model, commercial=args.commercial,
            strict_license=args.strict_license, force=args.force,
            max_candidates=max(1, args.max_candidates), log=log)
        if args.apply:
            result = font_picker.apply_selection(project, result, force=args.force,
                                                 log=log)
        else:
            font_picker.save_result(project, result)
    except (font_picker.FontPickerError, font_picker.emfont.EmfontError) as exc:
        raise SystemExit(f"选字体失败：{exc}") from exc

    target = font_picker.report_path(project)
    if args.json:
        print(target)
        return
    selected = result.get("selected") or {}
    print("")
    print(f"  选中：{selected.get('name')}（{selected.get('source')} / "
          f"{selected.get('category')}）")
    print(f"  方式：{'AI' if result.get('mode') == 'ai' else '本地规则回退'} / "
          f"置信度 {result.get('confidence')}")
    print(f"  理由：{result.get('reason')}")
    print(f"  授权：{selected.get('license') or 'unknown'}")
    print(f"  结果：{target}")
    applied = result.get("applied")
    blocked = result.get("apply_blocked")
    if applied:
        print(f"  已写入 captions.font = {applied.get('font')}")
    elif blocked:
        print(f"  未应用：{blocked.get('reason')}")
        print(f"  处理：{blocked.get('hint')}")
    else:
        print("  未写入 config；确认后加 --apply 重跑（或直接改 config.captions.font）")


if __name__ == "__main__":
    main()
