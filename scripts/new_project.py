#!/usr/bin/env python3
"""开一个新项目：建目录、写 config.json（含房规默认值）、放一版字幕模板。

给了 --reference 就顺手把参考片量一遍，把量出来的卡片几何 / 画中画 / 强调色
直接写进 config —— 这是「先量再抄」的落地方式，省掉手工填坐标。

用法：
    python scripts/new_project.py PROJECT_DIR --video /abs/in.mp4
    python scripts/new_project.py PROJECT_DIR --clips a.mp4 b.mp4
    python scripts/new_project.py PROJECT_DIR --video in.mp4 --reference ref.mp4
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _common import apply_defaults, ensure_dirs, project_paths, write_json  # noqa: E402

SRT_TEMPLATE = """1
00:00:00,000 --> 00:00:02,500
开场第一句 这里放钩子

2
00:00:02,600 --> 00:00:06,000
关键词用双层方括号标 | 反差词用双层圆括号标
"""


def build_config(name: str, aspect: str, video: str | None, clips: list[str],
                 teardown: dict | None, mode: str | None = None) -> dict:
    w, h = (1080, 1920) if aspect == "9:16" else (1920, 1080)
    cfg = {
        "name": name,
        "canvas": {"width": w, "height": h, "fps": 30},
        "input": {"video": video, "subtitle": "captions.srt", "clips": clips},
        "captions": {"font": "Noto Sans CJK SC Black", "size": round(90 * w / 1080)},
        "card": {"enabled": False},
        "gold": {"enabled": False},
        "sfx": {"events": []},
        "constraints": {},
        "jianying": {"name": name, "install": True, "ratio": aspect},
    }
    if mode:
        cfg["mode"] = mode
    apply_defaults(cfg)

    if not teardown:
        return cfg
    band = teardown.get("caption_band") or {}
    if band.get("detected"):
        cfg["captions"]["margin_v"] = int(round((1 - band["y_bottom_norm"]) * h))
        span = band["x_max_norm"] - band["x_min_norm"]
        cfg["captions"]["max_width"] = int(round(span * w))
        cfg["captions"]["margin_lr"] = int(round(band["x_min_norm"] * w))
    colors = teardown.get("accent_colors") or []
    by_hue = {}
    for c in colors:
        by_hue.setdefault(c["hue"], c)
    yellow = by_hue.get("yellow")
    contrast = (by_hue.get("pink") or by_hue.get("magenta")
                or by_hue.get("violet") or by_hue.get("red"))
    if yellow:
        cfg["captions"]["palette"]["accent"] = yellow["hex"]
    if contrast:
        cfg["captions"]["palette"]["contrast"] = contrast["hex"]
    card = teardown.get("card")
    if card:
        cfg["card"].update({"enabled": True, "start": card["start"], "end": card["end"],
                            "box": card["bbox_norm"], "fill": card["fill_hex"]})
        cfg["card"]["title_at"] = round(card["start"] + 0.12, 3)
        pip = teardown.get("pip")
        if pip:
            cfg["pip"].update({"enabled": True, "box": pip["bbox_norm"],
                               "at": round(card["start"] + 0.02, 3)})
    return cfg


def main() -> None:
    ap = argparse.ArgumentParser(description="新建一个口播工坊项目")
    ap.add_argument("project")
    ap.add_argument("--name", default=None)
    ap.add_argument("--video", default=None, help="主口播视频路径（相对 input/ 或绝对路径）")
    ap.add_argument("--clips", nargs="*", default=[], help="需要粗剪拼接的素材")
    ap.add_argument("--mode", choices=("talking-head", "vlog"),
                    help="素材类型；Vlog 默认要求旁白，口播默认要求现场人声")
    ap.add_argument("--reference", default=None, help="参考片，量完自动填卡片/画中画/配色")
    ap.add_argument("--aspect", default="9:16", choices=["9:16", "16:9"])
    ap.add_argument("--force", action="store_true", help="覆盖已存在的 config.json")
    a = ap.parse_args()

    project = Path(a.project).resolve()
    p = ensure_dirs(project)
    if p["config"].exists() and not a.force:
        raise SystemExit(f"{p['config']} 已存在，加 --force 才会覆盖")

    teardown = None
    if a.reference:
        out = p["work"] / "reference-teardown.json"
        print(f"  量参考片 → {out}")
        subprocess.run([sys.executable, str(Path(__file__).parent / "analyze_reference.py"),
                        a.reference, "--out", str(out),
                        "--frames", str(p["work"] / "ref-frames")], check=True)
        teardown = json.loads(out.read_text(encoding="utf-8"))

    cfg = build_config(a.name or project.name, a.aspect, a.video, a.clips, teardown,
                       mode=a.mode or ("talking-head" if a.video else None))
    write_json(p["config"], cfg)
    srt = p["input"] / "captions.srt"
    if not srt.exists():
        srt.write_text(SRT_TEMPLATE, encoding="utf-8")
    print(f"  {p['config']}")
    print(f"  {srt}（占位，记得换成真实字幕）")
    if cfg["audio"]["speech_mode"] is None:
        print("  ⚠ config.json 未声明语音目标；粗剪前请用 --mode 指定素材类型，"
              "或明确填写 audio.speech_mode")
    if cfg["audio"]["speech_mode"] == "narration":
        print("  下一步：先粗剪并审核 work/storyboard.json 的旁白与镜头证据；"
              f"再运行 python scripts/story_audio.py {project} --approve-story")
        print(f"  旁白生成后：python scripts/run_all.py {project}"
              "（缺旁白会在出片前停止）")
    else:
        print(f"  下一步：编辑 config.json → python scripts/run_all.py {project}")
    print(f"  跑完出两条产物：{project}/output/final-*.mp4 + {project}/draft-store/"
          f"{cfg['jianying']['name']}（后者同时登记进剪映草稿箱）")


if __name__ == "__main__":
    main()
