#!/usr/bin/env python3
"""jianying-tool 的 JSON 桥：用 3.10+ 的外部解释器读/诊断剪映原生草稿。

为什么需要它：`jianying-tool` 声明 `requires-python >= 3.10`，而本仓库的运行环境
可能是 3.9（例如安装器建的 `.venv`）。把原生解码放进独立进程，既不用升级主环境，
也不用把别人的 ctypes 代码抄进仓库。

调用方是 `scripts/workflow/draft_native.py`；协议很简单：
stdin 不传参，argv 选子命令，stdout **只**输出一个 JSON 对象。

    python jytool_bridge.py info
    python jytool_bridge.py read --draft "/path/to/draft"
    python jytool_bridge.py doctor --draft "/path/to/draft"

失败时输出 `{"ok": false, "error": "..."}` 并 exit 1 —— 调用方据此区分
「没装」和「装了但读失败」，不会把两者混成一个沉默的空结果。
"""
from __future__ import annotations

import argparse
import json
import platform
import sys
from pathlib import Path


def _emit(payload: dict) -> None:
    sys.stdout.write(json.dumps(payload, ensure_ascii=False))
    sys.stdout.write("\n")
    sys.stdout.flush()


def _version() -> str:
    try:
        from importlib.metadata import version
        return version("jianying-tool")
    except Exception:                                        # noqa: BLE001
        try:
            import jianying_tool
            return str(getattr(jianying_tool, "__version__", "unknown"))
        except Exception:                                    # noqa: BLE001
            return "unknown"


def cmd_info(_args) -> dict:
    import jianying_tool  # noqa: F401  —— 只验证能导入
    return {
        "ok": True,
        "version": _version(),
        "python": platform.python_version(),
        "executable": sys.executable,
        "platform": sys.platform,
    }


def cmd_read(args) -> dict:
    from jianying_tool.native_codec import decode_file, project_content_path

    draft = Path(args.draft).expanduser().resolve()
    if not draft.is_dir():
        raise FileNotFoundError(f"草稿目录不存在：{draft}")
    path = project_content_path(draft)
    if not path.is_file():
        raise FileNotFoundError(f"草稿里没有时间线文件：{path}")
    content, format_name = decode_file(path)
    return {"ok": True, "path": str(path), "format": format_name, "content": content}


def cmd_doctor(args) -> dict:
    from jianying_tool.inspect import diagnose_draft

    draft = Path(args.draft).expanduser().resolve()
    if not draft.is_dir():
        raise FileNotFoundError(f"草稿目录不存在：{draft}")
    report = diagnose_draft(draft)
    # 外层 ok 表示“这次调用跑完了”；草稿本身红不红在 report.ok 里。
    # 两者混用一个键会让调用方把“诊断出红项”误判成“桥挂了”。
    return {"ok": True, "report": report}


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")

    parser = argparse.ArgumentParser(description="jianying-tool JSON bridge")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("info", help="报告 jianying-tool / Python 版本")

    read = sub.add_parser("read", help="解码活动草稿并输出内容")
    read.add_argument("--draft", required=True)

    doctor = sub.add_parser("doctor", help="诊断草稿完整性")
    doctor.add_argument("--draft", required=True)

    args = parser.parse_args(argv)
    handler = {"info": cmd_info, "read": cmd_read, "doctor": cmd_doctor}[args.command]
    try:
        payload = handler(args)
    except Exception as exc:                                 # noqa: BLE001
        _emit({"ok": False, "error": f"{type(exc).__name__}: {exc}"})
        return 1
    _emit(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
