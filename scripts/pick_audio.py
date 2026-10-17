#!/usr/bin/env python3
"""扫素材目录，判「哪条外录配哪条毛片」——**用测量，不用猜**。

真实口播常是双轨收音：相机内录只是参考声，领夹麦/录音笔的外录才是成片要用的。
但一个目录里往往同时躺着视频、外录、BGM、花絮音频，**光看文件名会配错**。

所以这里给的是**证据**，不是结论：每条候选都真跑一次互相关，报出实测置信度。
判定分三档，含义固定：

| 判定 | 含义 | 该怎么办 |
|---|---|---|
| `use` | 唯一的强候选，且置信度达标 | 直接用，仍要**说一句你用了哪条** |
| `ask` | 有多个像的，或有像的但置信度不够 | **问用户**，把候选和置信度一起给他 |
| `reject` | 明确不是外录（时长离谱、纯音乐、置信度低到底） | 别用 |

⚠️ **不要只看文件名就配对。** 文件名配对只是「值得一试」的排序依据；
真正定案的是互相关的实测置信度。命名规约不统一的素材到处都是。

用法：
    python scripts/pick_audio.py DIR [DIR...]
    python scripts/pick_audio.py DIR --json          # 给 agent 读
    python scripts/pick_audio.py DIR --skip-measure  # 只按文件名粗筛，不跑互相关
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _common import probe_media  # noqa: E402
from make_jianying_draft import find_capcut  # noqa: E402
from align_audio import confidence, measure_offset  # noqa: E402

VIDEO_EXT = (".mp4", ".mov", ".mkv", ".m4v", ".avi", ".MP4", ".MOV")
AUDIO_EXT = (".wav", ".mp3", ".m4a", ".flac", ".aac", ".WAV", ".MP3", ".M4A", ".FLAC")
# 名字里带这些的，基本不是口播外录
NOT_EXTERNAL = ("bgm", "music", "配乐", "伴奏", "背景", "instrumental", "karaoke",
                "accompaniment", "音效", "sfx", "环境", "ambience", "room")


def norm_tokens(stem: str) -> set[str]:
    """把文件名拆成可比的词元：去日期、去拍摄批次尾号、去设备后缀。"""
    s = stem.lower()
    s = re.sub(r"20\d{6}[_\- ]?\d{0,6}", " ", s)          # 20260919_134312
    s = re.sub(r"\b\d{6,}\b", " ", s)                     # 长数字串
    s = re.sub(r"(_v\d+|_ext(audio)?|_audio|_mic|_lav|_rec|-?\d{3,})$", " ", s)
    s = re.sub(r"[^0-9a-z\u4e00-\u9fff]+", " ", s)
    return {t for t in s.split() if len(t) > 1}


def name_score(video: Path, audio: Path) -> float:
    a, b = norm_tokens(video.stem), norm_tokens(audio.stem)
    if not a or not b:
        return 0.0
    inter = len(a & b)
    return inter / max(len(a), len(b))


def scan(dirs: list[Path]) -> tuple[list[Path], list[Path]]:
    vids, auds = [], []
    for d in dirs:
        for f in sorted(d.rglob("*")):
            if not f.is_file():
                continue
            if f.suffix in VIDEO_EXT:
                vids.append(f)
            elif f.suffix in AUDIO_EXT:
                auds.append(f)
    return vids, auds


def judge(pairs: list[dict], threshold: float) -> None:
    """给每对定 `verdict` + `reason`，再给每条视频挑一个 best。"""
    for p in pairs:
        conf, ns = p["confidence"], p["name_score"]
        a, b = p["audio_sec"], p["video_sec"]
        if p.get("not_external"):
            p["verdict"], p["reason"] = "reject", "文件名看着像 BGM/音效/环境声，不是口播外录"
        elif b and a > b * 2.5:
            p["verdict"], p["reason"] = "reject", f"外录 {a:.0f}s 比视频 {b:.0f}s 长两倍以上，多半是整轨音乐"
        elif b and a < b * 0.35:
            p["verdict"], p["reason"] = "reject", f"外录只有视频的 {a / b:.0%}，对不上"
        elif conf >= threshold:
            p["verdict"], p["reason"] = "use", f"实测置信度 {conf:.2f}，同源"
        elif conf >= threshold * 0.5:
            p["verdict"], p["reason"] = "ask", f"置信度 {conf:.2f} 偏低，可能同源也可能不是，要人看一眼"
        else:
            p["verdict"], p["reason"] = "reject", f"置信度 {conf:.2f}，基本不同源"

    for v in {p["video"] for p in pairs}:
        cand = sorted([p for p in pairs if p["video"] == v],
                      key=lambda p: (-p["confidence"], -p["name_score"]))
        strong = [p for p in cand if p["verdict"] == "use"]
        weak = [p for p in cand if p["verdict"] == "ask"]
        for p in cand:
            p["best"] = False
        if len(strong) == 1:
            strong[0]["best"] = True
        elif len(strong) > 1:
            # 多个都达标 → 不能自己拍板，降级成 ask
            for p in strong:
                p["verdict"], p["reason"] = "ask", \
                    f"有 {len(strong)} 条都测出同源，选哪条得问用户（本条置信度 {p['confidence']:.2f}）"
        elif weak:
            pass  # 已是 ask


def main() -> None:
    ap = argparse.ArgumentParser(description="扫目录，判哪条外录配哪条毛片")
    ap.add_argument("dirs", nargs="+")
    ap.add_argument("--threshold", type=float, default=0.35, help="置信度阈值（默认 0.35）")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--skip-measure", action="store_true", help="不跑互相关，只按文件名粗筛")
    a = ap.parse_args()

    dirs = [Path(d).resolve() for d in a.dirs]
    for d in dirs:
        if not d.is_dir():
            raise SystemExit(f"不是目录：{d}")
    vids, auds = scan(dirs)
    if not vids:
        raise SystemExit(f"在 {'、'.join(str(d) for d in dirs)} 里没找到视频文件")
    if not auds:
        print(json.dumps({"videos": len(vids), "audios": 0,
                          "note": "没找到独立音频文件 —— 走**单轨**，用视频自带的声音"},
                         ensure_ascii=False, indent=2) if a.json else
              f"  找到 {len(vids)} 条视频，**没有独立音频文件** → 走单轨（用视频自带声音）")
        return

    pairs: list[dict] = []
    for v in vids:
        vm = probe_media(v)
        for au in auds:
            ns = name_score(v, au)
            not_ext = any(k in au.stem.lower() for k in NOT_EXTERNAL)
            # 粗筛：名字完全不沾边、又不是唯一候选的，不必花时间跑互相关
            if not a.skip_measure and (ns > 0 or len(auds) <= 2):
                m = measure_offset(v, au)
                conf = confidence(m)
                off = m.get("offset", 0.0)
                psr = m.get("psr", 0.0)
            else:
                conf, off, psr = 0.0, 0.0, 0.0
            pairs.append({
                "video": str(v), "video_sec": round(vm["duration"], 2),
                "audio": str(au), "audio_sec": round(probe_media(au)["duration"], 2),
                "name_score": round(ns, 2), "confidence": round(conf, 3),
                "offset_sec": round(off, 3), "psr": round(psr, 1),
                "not_external": not_ext, "measured": not a.skip_measure and conf > 0,
            })
    # 只留有戏的（名字沾边 / 唯一候选 / 名字像 BGM 的要留下来说明为什么不能用）
    keep = [p for p in pairs if p["name_score"] > 0 or p["not_external"] or len(auds) <= 2]
    judge(keep, a.threshold)

    result = {
        "dirs": [str(d) for d in dirs],
        "videos": len(vids), "audios": len(auds),
        "pairs": sorted(keep, key=lambda p: (p["video"], -p["confidence"])),
        "capcut": bool(find_capcut()),
        "note": ("低置信的配对不自动换轨，会产一份剪映对齐草稿让用户在时间线上拖"
                 if find_capcut() else
                 "没装 capcut CLI，低置信时产不了对齐草稿，只能手工对"),
    }
    if a.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return

    print(f"  {len(vids)} 条视频 / {len(auds)} 条音频\n")
    if not keep:
        print("  没有任何候选音频与视频沾边 —— 走**单轨**")
        return
    print(f"  {'视频':<34}{'外录':<30}{'名字':>5}{'置信':>6}{'偏移':>8}  判定")
    for p in result["pairs"]:
        v, au = Path(p["video"]).name, Path(p["audio"]).name
        mark = {"use": "✓用", "ask": "?问", "reject": "✗弃"}[p["verdict"]]
        star = " ★" if p.get("best") else ""
        # 没实测的（名字完全不沾边，省了互相关）显示 `—`：
        # 显示 0.00 会被读成「测过，确实不同源」——那是另一件事
        conf = f"{p['confidence']:6.2f}" if p["measured"] else f"{'—':>6}"
        off = f"{p['offset_sec']:+8.2f}" if p["measured"] else f"{'—':>8}"
        print(f"  {v[:32]:<34}{au[:28]:<30}{p['name_score']:5.2f}{conf}{off}  {mark}{star}")
    print()
    for p in result["pairs"]:
        if p.get("best") or p["verdict"] == "ask":
            print(f"  {Path(p['video']).name} → {Path(p['audio']).name}：{p['reason']}")
    print(f"\n  {result['note']}")


if __name__ == "__main__":
    main()
