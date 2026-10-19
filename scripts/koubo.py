#!/usr/bin/env python3
"""口播工坊 Koubo Studio 的命令行入口。

    koubo new my-video --video input.mp4 --reference ref.mp4
    koubo run my-video
    koubo doctor

`koubo new` / `koubo run` 只是把参数转给 `scripts/new_project.py` / `scripts/run_all.py`，
不改流水线本身；其余常用脚本提供短别名。想直接跑某个脚本：

    koubo script auto_edit.py my-video --mode talking-head --clips talk.mp4
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = Path(__file__).resolve().parent
VERSION = (ROOT / "VERSION").read_text(encoding="utf-8").strip() if (ROOT / "VERSION").is_file() else "unknown"

ALIASES = {
    "auto": "auto_film.py",
    "package": "package_video.py",
    "new": "new_project.py",
    "init": "new_project.py",
    "run": "run_all.py",
    "analyze": "analyze_reference.py",
    "auto-edit": "auto_edit.py",
    "captions": "make_captions.py",
    "render": "render.py",
    "draft": "make_jianying_draft.py",
    "visual-review": "make_visual_review.py",
    "verify": "verify.py",
    "fonts": "list_fonts.py",
    "tts": "tts.py",
    "bgm": "make_bgm.py",
    "sfx": "make_sfx.py",
    "pick-audio": "pick_audio.py",
    "align": "align_audio.py",
    "speech-rate": "speech_rate.py",
    "recalibrate": "recalibrate.py",
    "measured": "check_measured.py",
    "review": "review_voice.py",
    "export-review": "export_voice_review.py",
    "transcribe": "transcribe_audio.py",
    "rebuild": "rebuild_sample.py",
}

DESCRIPTIONS = {
    "auto": "一条命令全自动：素材 → mp4 + 剪映草稿",
    "package": "package-only：已剪好的成片 + SRT 只做包装，不重剪",
    "new": "建工程（可顺手量参考片）",
    "init": "new 的别名",
    "run": "跑完整流水线：成片 + 剪映草稿 + 质检",
    "doctor": "环境自检",
    "analyze": "量参考片",
    "auto-edit": "自动粗剪 / 镜头表",
    "captions": "SRT → ASS / 字幕层",
    "render": "烧字幕、混音、响度归一",
    "draft": "装配剪映草稿 + draft-spec/audit",
    "visual-review": "生成包装层视觉审查包（待人工观看）",
    "verify": "质检（pass / fail / unchecked）",
    "fonts": "列出可用字体族名",
    "tts": "解说旁白合成",
    "bgm": "本地合成 BGM",
    "sfx": "音效轨",
    "pick-audio": "判断外录配哪条毛片",
    "align": "外录对轨",
    "speech-rate": "量语速 / 反查字数预算",
    "recalibrate": "重量实测常量",
    "measured": "校验实测常量登记表",
    "review": "登记逐句人工判读",
    "export-review": "导出逐句听审样张",
    "transcribe": "离线语音转写",
    "rebuild": "把旧镜头表工程导入标准工程",
    "update": "拉取最新版本并更新依赖",
    "scripts": "列出全部脚本",
    "version": "版本号",
}


def _python() -> str:
    """优先安装目录里的 venv，保证和安装时装的依赖是同一套。"""
    venv = ROOT / ".venv" / "bin" / "python"
    return str(venv) if venv.is_file() else sys.executable


def _run_script(filename: str, args: list[str]) -> int:
    script = SCRIPTS / filename
    if not script.is_file():
        print(f"找不到脚本：{script}", file=sys.stderr)
        return 2
    env = os.environ.copy()
    vendor = ROOT / "vendor/npm/node_modules/.bin"
    if vendor.is_dir():
        env["PATH"] = f"{vendor}{os.pathsep}{env.get('PATH', '')}"
    return subprocess.call([_python(), str(script), *args], env=env)


def _update(args: list[str]) -> int:
    if not (ROOT / ".git").is_dir():
        print("当前不是 git checkout；请重新跑一键安装脚本更新。", file=sys.stderr)
        return 1
    print(f"  更新 {ROOT}")
    rc = subprocess.call(["git", "-C", str(ROOT), "pull", "--ff-only"])
    if rc != 0:
        print("  ⚠ git pull 失败（可能有本地修改）；先处理后再试。", file=sys.stderr)
        return rc
    if "--no-deps" not in args:
        if (ROOT / ".venv/bin/python").is_file():
            print("  更新 Python 依赖")
            for name in ("requirements.txt", "requirements-narration.txt",
                         "requirements-transcribe.txt"):
                req = ROOT / name
                if not req.is_file():
                    continue
                rc = subprocess.call([_python(), "-m", "pip", "install", "-q",
                                      "--disable-pip-version-check", "-r", str(req)])
                if rc != 0:
                    print(f"  ⚠ {name} 更新失败；现有环境仍可尝试使用。",
                          file=sys.stderr)
                    break
    print("  ✓ 已更新")
    return 0


def _list_scripts() -> None:
    print("\n  命令别名：")
    for name, script in ALIASES.items():
        print(f"    koubo {name:<14} {script:<26} {DESCRIPTIONS.get(name, '')}")
    print("\n  直接跑脚本：koubo script <文件名> [参数...]")
    print("  环境自检：  koubo doctor\n")


def help_text() -> str:
    lines = [
        f"口播工坊 Koubo Studio  {VERSION}",
        "",
        "用法：koubo <命令> [参数...]",
        "",
        "最常用：",
        "  koubo auto DIR --video 口播.mp4 [--reference 参考片.mp4]",
        "  koubo new DIR --video 口播.mp4 [--reference 参考片.mp4]",
        "  koubo run DIR",
        "  koubo doctor",
        "",
        "全部命令：",
    ]
    for name in ("auto", "new", "run", "doctor", "update", "scripts", "version"):
        lines.append(f"  {name:<12}{DESCRIPTIONS.get(name, '')}")
    lines.append("")
    lines.append("脚本别名：koubo scripts 查看；或 koubo script auto_edit.py ...")
    return "\n".join(lines)


def main() -> int:
    argv = sys.argv[1:]
    if not argv or argv[0] in ("-h", "--help", "help"):
        print(help_text())
        return 0
    cmd, rest = argv[0], argv[1:]
    if cmd in ("-V", "--version", "version"):
        print(VERSION)
        return 0
    if cmd == "doctor":
        return _run_script("doctor.py", rest)
    if cmd == "scripts":
        _list_scripts()
        return 0
    if cmd == "update":
        return _update(rest)
    if cmd == "script":
        if not rest:
            print("用法：koubo script <文件名> [参数...]", file=sys.stderr)
            return 2
        return _run_script(rest[0], rest[1:])
    if cmd in ALIASES:
        return _run_script(ALIASES[cmd], rest)
    print(f"不认识的命令：{cmd}\n（koubo --help 看可用命令）", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
