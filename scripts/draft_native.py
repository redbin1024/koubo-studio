#!/usr/bin/env python3
"""原生草稿适配层的命令行入口。

    # 看当前环境有没有可用的 jianying-tool 桥
    python scripts/draft_native.py info

    # 建独立环境（需要 uv）；装到 vendor/jytool-venv，不动 .venv
    python scripts/draft_native.py setup

    # 看一份草稿（可以是剪映保存过的加密草稿）
    python scripts/draft_native.py info "draft-store/片名"
    python scripts/draft_native.py doctor "draft-store/片名" --json

    # 把活动文件（剪映真正读的那份）镜像成明文副本，给 audit/verify 看
    python scripts/draft_native.py sync "draft-store/片名"

    # 驱动剪映自己的导出对话框（GUI；先退出草稿再试）
    python scripts/draft_native.py export --draft "片名" --title "片名_导出" \
        --output-dir output --resolution 1080P --framerate 30 --close

退出码：0 = 成功 / 无红项；1 = 有错误或不可读；2 = 缺 jianying-tool 桥。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from workflow import draft_native  # noqa: E402


def _print_json(data) -> None:
    print(json.dumps(data, ensure_ascii=False, indent=2))


def cmd_info(args) -> int:
    data = draft_native.info(args.draft)
    if args.json:
        _print_json(data)
        return 0
    bridge = data["bridge"]
    if bridge.get("available"):
        print(f"jianying-tool  {bridge.get('version')}  "
              f"(Python {bridge.get('python_version')})")
        print(f"  解释器  {bridge.get('python')}")
    else:
        print("jianying-tool  未安装（可选）")
        if bridge.get("error"):
            print(f"  原因    {bridge['error']}")
        print(f"  安装    {bridge.get('hint')}")
    draft = data.get("draft")
    if draft:
        if not draft.get("readable"):
            print(f"草稿    {draft['path']}  ✗ {draft.get('error')}")
            return 1
        print(f"草稿    {draft['path']}")
        print(f"  文件    {draft['file']}（{draft['format']}"
              f"{'，已解密' if draft.get('codec') else ''}）")
        print(f"  时长    {draft.get('duration', 0):.3f}s")
        for track in draft.get("tracks") or []:
            print(f"  {track.get('type'):<6} {track.get('name')!r}  "
                  f"{track.get('segments')} 段")
        twin = draft.get("twin") or {}
        if twin.get("twin_exists"):
            state = {True: "同内容", False: "不一致",
                     None: "无法比较（一份加密且桥不可用）"}.get(twin.get("equal"))
            print(f"  副本    {Path(twin['twin']).name}：{state}")
        else:
            print(f"  副本    缺 {Path(twin.get('twin', '?')).name}")
    return 0


def cmd_doctor(args) -> int:
    report = draft_native.doctor(args.draft)
    if args.json:
        _print_json(report)
    else:
        source = report.get("source")
        label = {"jianying-tool": "jianying-tool 深度诊断",
                 "basic": "基础检查（未装 jianying-tool）",
                 "unavailable": "无法诊断（加密草稿且没有 jianying-tool）",
                 "none": "草稿不存在"}.get(source, str(source))
        ok = report.get("ok")
        mark = {True: "✓", False: "✗", None: "…"}.get(ok, "?")
        print(f"{mark} {args.draft}")
        print(f"  来源    {label}")
        counts = report.get("counts") or {}
        if counts:
            print(f"  规模    轨道 {counts.get('tracks', '?')} / "
                  f"片段 {counts.get('segments', '?')} / 素材 {counts.get('materials', '?')}")
        for error in report.get("errors") or []:
            print(f"  ✗ {error}")
        for warning in report.get("warnings") or []:
            print(f"  ⚠ {warning}")
        if source == "unavailable" and report.get("hint"):
            print(f"  提示    {report['hint']}")
    if report.get("ok") is False:
        return 1
    if report.get("source") == "unavailable":
        return 2
    return 0


def cmd_sync(args) -> int:
    try:
        result = draft_native.sync_twin(args.draft, force=args.force, source=args.source)
    except draft_native.DraftNativeError as exc:
        if args.json:
            _print_json({"ok": False, "error": str(exc)})
        else:
            print(f"✗ {exc}", file=sys.stderr)
        return 1
    if args.json:
        _print_json({"ok": True, **result})
        return 0
    if not result.get("written"):
        print(f"= 已是同步状态：{result.get('twin')}")
        return 0
    print(f"✓ {result.get('from') or Path(result['active']).name} → "
          f"{result.get('to') or Path(result['twin']).name}")
    print(f"  {result['bytes']} 字节；来源格式 {result['active_format']}")
    if result.get("backup"):
        print(f"  备份 {result['backup']}")
    return 0


def cmd_export(args) -> int:
    try:
        result = draft_native.export(
            draft=args.draft, title=args.title, output_dir=args.output_dir,
            root=args.root, resolution=args.resolution, framerate=args.framerate,
            close=args.close,
        )
    except draft_native.DraftNativeError as exc:
        if args.json:
            _print_json({"ok": False, "error": str(exc)})
        else:
            print(f"✗ {exc}", file=sys.stderr)
        return 2 if isinstance(exc, draft_native.BridgeUnavailable) else 1
    if args.json:
        _print_json({"ok": True, **result})
    else:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def cmd_setup(args) -> int:
    try:
        result = draft_native.setup(python_version=args.python, force=args.force)
    except draft_native.DraftNativeError as exc:
        if args.json:
            _print_json({"ok": False, "error": str(exc)})
        else:
            print(f"✗ {exc}", file=sys.stderr)
        return 1
    if args.json:
        _print_json({"ok": True, **result})
    else:
        state = "已安装" if result.get("created") else "已存在"
        print(f"✓ jianying-tool {state}：{result['python']}")
        probe = result.get("probe") or {}
        if probe.get("version"):
            print(f"  版本 {probe['version']}（Python {probe.get('python_version')}）")
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="剪映原生草稿适配层")
    sub = parser.add_subparsers(dest="command", required=True)

    info = sub.add_parser("info", help="环境与草稿信息")
    info.add_argument("draft", nargs="?", help="草稿目录（可选）")
    info.add_argument("--json", action="store_true")
    info.set_defaults(func=cmd_info)

    doctor = sub.add_parser("doctor", help="诊断草稿完整性")
    doctor.add_argument("draft", help="草稿目录")
    doctor.add_argument("--json", action="store_true")
    doctor.set_defaults(func=cmd_doctor)

    sync = sub.add_parser("sync", help="对齐活动草稿与明文副本")
    sync.add_argument("draft", help="草稿目录")
    sync.add_argument("--from", dest="source", choices=("auto", "active", "twin"),
                      default="auto",
                      help="auto=较新的一份为准；active=活动文件→副本；twin=副本→活动文件")
    sync.add_argument("--force", action="store_true",
                      help="时间相同/目标加密时仍然覆盖（默认活动文件优先）")
    sync.add_argument("--json", action="store_true")
    sync.set_defaults(func=cmd_sync)

    export = sub.add_parser("export", help="驱动剪映导出（GUI）")
    export.add_argument("--draft", required=True, help="剪映首页显示的草稿名")
    export.add_argument("--title", required=True, help="导出文件名")
    export.add_argument("--output-dir", required=True)
    export.add_argument("--root", help="草稿箱根目录（默认剪映草稿箱）")
    export.add_argument("--resolution", help="480P/720P/1080P/2K/4K/8K/原始")
    export.add_argument("--framerate", help="24/25/29.97/30/50/59.94/60/120")
    export.add_argument("--close", action="store_true", help="完成后关闭成功弹窗")
    export.add_argument("--json", action="store_true")
    export.set_defaults(func=cmd_export)

    setup = sub.add_parser("setup", help="在 vendor/ 里装 jianying-tool（需要 uv）")
    setup.add_argument("--python", default="3.12", help="桥环境用的 Python 版本")
    setup.add_argument("--force", action="store_true", help="已存在也重建")
    setup.add_argument("--json", action="store_true")
    setup.set_defaults(func=cmd_setup)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
