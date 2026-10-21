#!/usr/bin/env python3
"""环境自检：python / ffmpeg / 字体 / 剪映 / 可选模型逐项报告。

一条命令回答「为什么跑不起来」：

    koubo doctor
    python scripts/doctor.py
    python scripts/doctor.py --json

退出码：0 = 没有 fail（warn 不算失败）；1 = 至少一项 fail。
三态沿用全仓的规矩：**没查 ≠ 通过**，装不了的项明确写 warn 或 fail，不静默跳过。
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import shutil
import subprocess
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import _common  # noqa: E402

OK, WARN, FAIL = "ok", "warn", "fail"


@dataclass
class Check:
    name: str
    status: str
    detail: str
    hint: str = ""


@dataclass
class Report:
    version: str
    root: str
    platform: str
    checks: list[Check] = field(default_factory=list)

    def add(self, name: str, status: str, detail: str, hint: str = "") -> None:
        self.checks.append(Check(name, status, detail, hint))

    @property
    def summary(self) -> dict:
        return {s: sum(1 for c in self.checks if c.status == s)
                for s in (OK, WARN, FAIL)}


def _version_of(package: str) -> str:
    try:
        from importlib.metadata import version
        return version(package)
    except Exception:                                        # noqa: BLE001
        return "?"


def check_python(report: Report) -> None:
    v = sys.version_info
    detail = f"{v.major}.{v.minor}.{v.micro} ({sys.executable})"
    if v >= (3, 10):
        report.add("python", OK, detail)
    else:
        report.add("python", FAIL, detail + " —— 需要 3.10+",
                   "macOS: brew install python@3.12；Ubuntu: sudo apt install python3.12")


def check_python_deps(report: Report) -> None:
    for module, package, required in (("numpy", "numpy", True),
                                      ("PIL", "Pillow", True)):
        if importlib.util.find_spec(module) is None:
            report.add(f"python:{package}", FAIL, "未安装",
                       f"{sys.executable} -m pip install {package}")
        else:
            report.add(f"python:{package}", OK, _version_of(package))


def check_ffmpeg(report: Report) -> None:
    try:
        ffmpeg = _common.find_ffmpeg()
    except SystemExit as exc:
        report.add("ffmpeg", FAIL, str(exc), "macOS: brew install ffmpeg-full；Ubuntu: sudo apt install ffmpeg")
        return
    try:
        p = subprocess.run([ffmpeg, "-version"], capture_output=True, text=True, timeout=15)
        first = (p.stdout or p.stderr or "").splitlines()[0] if p.returncode == 0 else ""
        report.add("ffmpeg", OK, first or ffmpeg)
    except Exception as exc:                                 # noqa: BLE001
        report.add("ffmpeg", FAIL, f"{ffmpeg} 跑不起来：{exc}")
        return
    try:
        filters = subprocess.run([ffmpeg, "-hide_banner", "-filters"],
                                 capture_output=True, text=True, timeout=30).stdout
        if " subtitles " in filters or " ass " in filters:
            report.add("ffmpeg:libass", OK, "带 subtitles/ass 滤镜")
        else:
            report.add("ffmpeg:libass", WARN, "没有 libass；只影响 captions.burn=ass",
                       "默认 burn=layer 不受影响；要用 libass 请装 ffmpeg-full")
    except Exception as exc:                                 # noqa: BLE001
        report.add("ffmpeg:libass", WARN, f"查不了：{exc}")
    try:
        probe = _common.find_ffprobe()
        report.add("ffprobe", OK if Path(probe).exists() or shutil.which(probe) else FAIL,
                   probe)
    except Exception as exc:                                 # noqa: BLE001
        report.add("ffprobe", FAIL, str(exc))


def check_font(report: Report) -> None:
    project = _common.repo_root()
    try:
        path = _common.find_font("Noto Sans CJK SC Black", project=project)
        report.add("font", OK, f"{path.name}（{_common.font_display_name(path)}）")
        return
    except SystemExit:
        pass
    try:
        path = _common.find_font(None, project=project)
        report.add("font", WARN,
                   f"没有默认 Noto Sans CJK SC Black，但有 {path.name}；"
                   f"config 里的 captions.font 要写这一族",
                   "或重跑 install.sh 下载默认字体")
    except SystemExit as exc:
        report.add("font", FAIL, "找不到可用中文字体", str(exc))


def check_capcut(report: Report) -> None:
    from make_jianying_draft import JY_STORE_DEFAULT, find_capcut

    try:
        capcut = find_capcut()
    except SystemExit as exc:
        report.add("capcut", WARN, "未安装 —— 仍可出 mp4，但出不了剪映草稿",
                   "bash install.sh --full；或 npm install -g capcut-cli")
        capcut = None
    if capcut:
        try:
            p = subprocess.run([capcut, "--version"], capture_output=True, text=True, timeout=30)
            text = (p.stdout or p.stderr or "").strip().splitlines()
            report.add("capcut", OK if p.returncode == 0 else WARN,
                       f"{capcut}" + (f" · {text[0]}" if text else ""))
        except Exception as exc:                             # noqa: BLE001
            report.add("capcut", WARN, f"{capcut} 调不起来：{exc}")

    if sys.platform != "darwin":
        report.add("jianying-store", WARN, "剪映草稿箱只支持 macOS；当前系统只出 mp4")
        return
    store = Path(_common.env_get("JY_STORE", JY_STORE_DEFAULT)).expanduser()
    if not store.is_dir():
        report.add("jianying-store", WARN, f"草稿箱不存在：{store}",
                   "装好剪映并至少打开一次；或设置 KOUBO_JY_STORE")
    elif not os.access(store, os.W_OK):
        # macOS 会把「能 ls 不能写」的目录也报成不可写；权限位可写时先给 warn，
        # 真到装配草稿那一步还会再检查一次。
        mode_ok = bool(store.stat().st_mode & 0o200)
        report.add("jianying-store", WARN if mode_ok else FAIL,
                   f"当前进程不可写：{store}" + ("（权限位看起来可写，可能是沙箱/ACL）" if mode_ok else ""),
                   "给终端/壳层完全磁盘访问权限，或设置 KOUBO_JY_STORE 到可写目录")
    else:
        report.add("jianying-store", OK, str(store))


def check_optional(report: Report) -> None:
    for module, package, purpose, hint in (
        ("edge_tts", "edge-tts", "解说旁白（tts.py）", "pip install edge-tts"),
        ("faster_whisper", "faster-whisper", "离线语音转写（自动字幕 / koubo auto 口播）", "bash install.sh 或 pip install faster-whisper"),
    ):
        if importlib.util.find_spec(module) is None:
            report.add(f"optional:{package}", WARN, f"未安装 —— {purpose}不可用",
                       f"{sys.executable} -m pip install {package}")
        else:
            report.add(f"optional:{package}", OK, _version_of(package))
    exe = shutil.which("yt-dlp")
    if exe:
        report.add("optional:yt-dlp", OK, exe)
    elif importlib.util.find_spec("yt_dlp") is not None:
        report.add("optional:yt-dlp", OK, "python -m yt_dlp")
    else:
        report.add("optional:yt-dlp", WARN,
                   "未安装 —— 抖音链接下载只能在分享页可用时工作",
                   "pip install -U yt-dlp；或先把视频下载到本地传给 koubo reference")


def check_install(report: Report) -> None:
    root = _common.repo_root()
    report.add("repo", OK, str(root))
    venv = root / ".venv/bin/python"
    if venv.is_file():
        report.add("venv", OK, str(venv))
    else:
        report.add("venv", WARN, "没有安装目录内的 .venv；正在用当前 Python",
                   "bash install.sh 会建一个")
    cli = Path.home() / ".local/bin/koubo"
    if cli.exists():
        report.add("cli", OK, str(cli))
    else:
        report.add("cli", WARN, "~/.local/bin/koubo 不存在",
                   "bash install.sh 会创建；也可直接跑 bin/koubo")


def run_checks() -> Report:
    version = (Path(__file__).parent.parent / "VERSION")
    report = Report(
        version=version.read_text(encoding="utf-8").strip() if version.is_file() else "unknown",
        root=str(_common.repo_root()),
        platform=f"{sys.platform} / {os.uname().machine if hasattr(os, 'uname') else '?'}",
    )
    for fn in (check_python, check_python_deps, check_ffmpeg, check_font,
               check_capcut, check_optional, check_install):
        try:
            fn(report)
        except Exception as exc:                             # noqa: BLE001
            report.add(fn.__name__.removeprefix("check_"),
                       FAIL, f"自检本身出错：{type(exc).__name__}: {exc}")
    return report


def main() -> None:
    ap = argparse.ArgumentParser(description="口播工坊环境自检")
    ap.add_argument("--json", action="store_true", help="机器可读输出")
    a = ap.parse_args()
    report = run_checks()
    summary = report.summary

    if a.json:
        print(json.dumps({"version": report.version, "root": report.root,
                          "platform": report.platform, "summary": summary,
                          "checks": [asdict(c) for c in report.checks]},
                         ensure_ascii=False, indent=2))
    else:
        marks = {OK: "✓", WARN: "⚠", FAIL: "✗"}
        print(f"\n  口播工坊 Koubo Studio  {report.version}")
        print(f"  {report.root}")
        print(f"  {report.platform}\n")
        width = max(len(c.name) for c in report.checks)
        for c in report.checks:
            print(f"    {marks[c.status]} {c.name:<{width}}  {c.detail}")
            if c.hint and c.status != OK:
                print(f"      {' ' * width}  → {c.hint}")
        print(f"\n  {summary[OK]} 通过 / {summary[WARN]} 警告 / {summary[FAIL]} 失败")
        if summary[WARN]:
            print("  ⚠ 警告项对应能力不可用，但不一定挡住 mp4 渲染。")
        if summary[FAIL]:
            print("  ✗ 失败项会让对应步骤直接报错；先按上面的 → 修好再跑。")

    raise SystemExit(1 if summary[FAIL] else 0)


if __name__ == "__main__":
    main()
