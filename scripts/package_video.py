#!/usr/bin/env python3
"""package-only：已经剪好的口播视频 + SRT，只做包装，不重剪。

和 auto_film 的边界：
  auto_film     从原始素材粗剪 → 字幕/声音/包装 → 草稿
  package_video 保留用户已经剪好的画面/声音/顺序，只叠加卡片/字幕/插图/贴纸/原生资源

输入视频必须已经是最终剪辑；这里不会调用 auto_edit/merge_cut，也不会重排镜头。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from _common import (apply_defaults, ensure_dirs, input_path, load_config,  # noqa: E402
                     probe_media, project_paths, write_json)
from new_project import build_config  # noqa: E402


def _sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def prepare(project: Path, video: Path, srt: Path, *,
            captions: str = "generated", force: bool = False,
            name: str | None = None) -> dict:
    video = video.expanduser().resolve()
    srt = srt.expanduser().resolve()
    if not video.is_file():
        raise SystemExit(f"找不到成片：{video}")
    if not srt.is_file():
        raise SystemExit(f"找不到 SRT：{srt}")
    info = probe_media(video)
    aspect = "9:16" if int(info["height"] or 0) >= int(info["width"] or 0) else "16:9"
    p = ensure_dirs(project)
    if p["config"].is_file() and not force:
        cfg = load_config(p["config"])
    else:
        cfg = build_config(name or project.name, aspect, str(video), [], None,
                           mode="talking-head")
    cfg["name"] = name or project.name
    cfg["mode"] = "talking-head"
    cfg["input"]["video"] = str(video)
    cfg["input"]["clips"] = []
    cfg["input"]["subtitle"] = "captions.srt"
    cfg["duration"] = round(float(info["duration"]), 3)
    cfg["audio"]["speech_mode"] = "source" if info["has_audio"] else "none"
    # package-only 保留原声，但没有粗剪的解说槽；必须有 BGM 填静音，
    # 否则 verify 的 long-silence 会红。
    cfg["audio"]["bgm"] = {"enabled": True, "mood": "warm"}
    cfg["audio"]["bgm_volume"] = min(float(cfg["audio"].get("bgm_volume", 0.30)), 0.30)
    cfg.setdefault("captions", {})["mode"] = captions
    cfg.setdefault("jianying", {})["name"] = name or project.name
    cfg["jianying"]["install"] = True
    cfg = apply_defaults(cfg)
    shutil.copyfile(srt, p["input"] / "captions.srt")
    write_json(p["config"], cfg)
    write_json(p["work"] / "package-only.json", {
        "version": 1, "video": str(video), "srt": str(srt),
        "video_sha256": _sha(video), "srt_sha256": _sha(srt),
        "captions_mode": captions,
        "note": "package-only：不粗剪、不重排、不改原声；只做包装层",
    })
    print(f"  package-only：{video.name} + {srt.name}")
    print(f"  画布 {cfg['canvas']['width']}x{cfg['canvas']['height']} / "
          f"语音 {cfg['audio']['speech_mode']} / 字幕 {captions}")
    return cfg


def main() -> None:
    ap = argparse.ArgumentParser(description="package-only：已剪好的成片 + SRT 只做包装")
    ap.add_argument("project")
    ap.add_argument("--video", required=True, help="已经剪好的成片")
    ap.add_argument("--srt", required=True, help="与成片时间轴一致的 SRT")
    ap.add_argument("--name", default=None, help="工程/草稿名")
    ap.add_argument("--captions", choices=("generated", "burned-in", "none"),
                    default="generated")
    ap.add_argument("--force", action="store_true", help="覆盖已有 config 的输入与画布")
    ap.add_argument("--prepare-only", action="store_true", help="只建工程/配置，不跑流水线")
    args = ap.parse_args()
    project = Path(args.project).resolve()
    prepare(project, Path(args.video), Path(args.srt),
            captions=args.captions, force=args.force, name=args.name)
    if args.prepare_only:
        print(f"  下一步：编辑 {project_paths(project)['config']} 后运行 "
              f"python scripts/run_all.py {project}")
        return
    cmd = [sys.executable, str(Path(__file__).parent / "run_all.py"),
           str(project), "--auto"]
    print("  跑包装流水线（不粗剪）")
    raise SystemExit(subprocess.call(cmd))


if __name__ == "__main__":
    main()
