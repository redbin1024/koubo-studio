#!/usr/bin/env python3
"""粗剪（可选）：把一条或多条素材按「静音切点」剪成一条锁定时间轴的口播片。

适用场景：手上是几段分开录的素材（1.mp4 / 2.mp4），要先拼成一条干净的粗剪，
再交给包装流程。不做转写、不做字幕——时间轴锁死后字幕由上层（agent 或 ASR 技能）
写进 input/captions.srt。

判据：ffmpeg silencedetect 找 −34dB 以下的静音段，切点落在静音正中，
再 pad 出去一点，保证不切掉字头字尾。相邻语音段间隔很小就合并，避免碎切。

用法：
    python scripts/merge_cut.py PROJECT_DIR                 # 读 config 的 input.clips
    python scripts/merge_cut.py PROJECT_DIR --noise -34 --min-sil 0.30
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _common import (  # noqa: E402
    find_ffmpeg, load_config, probe_media, project_paths, run, swapped_for, write_json,
)

SIL_RE = re.compile(r"silence_(start|end): ([\d.]+)")


def silences(path: Path, noise_db: float, min_dur: float) -> list[tuple[float, float]]:
    proc = run([find_ffmpeg(), "-hide_banner", "-nostats", "-i", str(path),
                "-af", f"silencedetect=noise={noise_db}dB:d={min_dur}",
                "-f", "null", "-"])
    out, start = [], None
    for m in SIL_RE.finditer(proc.stderr):
        kind, val = m.group(1), float(m.group(2))
        if kind == "start":
            start = val
        elif start is not None:
            out.append((start, val))
            start = None
    return out


def speech_blocks(dur: float, sils: list[tuple[float, float]], pad: float,
                  merge_gap: float, min_len: float) -> list[tuple[float, float]]:
    """静音段的补集 = 说话段。切点落在静音里，两边各留 pad。"""
    blocks, cur = [], 0.0
    for a, b in sils:
        if a - cur > 0.02:
            blocks.append((cur, a))
        cur = b
    if dur - cur > 0.02:
        blocks.append((cur, dur))

    padded = [(max(0.0, a - pad), min(dur, b + pad)) for a, b in blocks]
    merged: list[list[float]] = []
    for a, b in padded:
        if merged and a - merged[-1][1] < merge_gap:
            merged[-1][1] = b
        else:
            merged.append([a, b])
    return [(a, b) for a, b in merged if b - a >= min_len]


def narration_slots(dur: float, sils: list[tuple[float, float]],
                    min_slot: float, limit: int) -> list[tuple[float, float]]:
    """可用来放解说的**静音窗口**：取最长的 limit 段（按时间顺序返回）。

    为什么取最长的：解说要真的说得完一句话。一条 0.4s 的缝隙放不下任何东西，
    留下它只会让成片多一次莫名其妙的停顿。留槽取长段，是为了让旁白有地方站。
    """
    candidates = [(a, b) for a, b in sils if b - a >= min_slot]
    if not candidates or limit <= 0:
        return []
    picked = sorted(candidates, key=lambda s: s[0] - s[1])[:limit]   # 长的优先
    return sorted(picked)


def build(cfg: dict, project: Path, noise_db: float, min_sil: float,
          pad: float, merge_gap: float, min_len: float) -> dict:
    p = project_paths(project)
    clips = [p["input"] / c for c in (cfg["input"].get("clips") or [])]
    # 配了外录的批次，align 步骤已经把换轨产物记进 work/align-report.json；
    # 这里查表换成外录声，画面不变 —— 粗剪的切点自然同步作用到外录上。
    clips = [swapped_for(c, project) for c in clips]
    if not clips:
        raise SystemExit("config 里 input.clips 为空，没什么可粗剪的")
    for c in clips:
        if not c.is_file():
            raise SystemExit(f"找不到素材：{c}")

    W, H = cfg["canvas"]["width"], cfg["canvas"]["height"]
    fps = cfg["canvas"]["fps"]
    plan, parts, cursor, total = [], [], 0.0, 0.0
    for clip in clips:
        info = probe_media(clip)
        if not info["has_audio"]:
            raise SystemExit(f"{clip.name} 没有音轨，粗剪要靠人声切点，请先补音轨")
        blocks = speech_blocks(info["duration"], silences(clip, noise_db, min_sil),
                               pad, merge_gap, min_len)
        print(f"  {clip.name}  {info['duration']:.2f}s → {len(blocks)} 段说话")
        for i, (a, b) in enumerate(blocks, 1):
            plan.append({"id": f"{clip.stem}-{i:02d}", "path": str(clip),
                         "in": round(a, 3), "duration": round(b - a, 3)})
            parts.append((clip, a, b - a))
            cursor += b - a
        total += sum(b - a for a, b in blocks)

    # 逐段 trim + 统一缩放 + concat。逐段 -ss/-t 比先切文件再拼更少一次编解码。
    args, filters = [], []
    for i, (clip, a, d) in enumerate(parts):
        args += ["-ss", f"{a:.3f}", "-t", f"{d:.3f}", "-i", str(clip)]
        filters.append(
            f"[{i}:v]scale={W}:{H}:force_original_aspect_ratio=increase,"
            f"crop={W}:{H},fps={fps},setsar=1[v{i}];"
            f"[{i}:a]aresample=48000,aformat=channel_layouts=stereo[a{i}]")
    concat = "".join(f"[v{i}][a{i}]" for i in range(len(parts)))
    fc = ";".join(filters) + f";{concat}concat=n={len(parts)}:v=1:a=1[vo][ao]"

    out = p["input"] / "clean-cut.mp4"
    run([find_ffmpeg(), "-v", "error", "-y", *args, "-filter_complex", fc,
         "-map", "[vo]", "-map", "[ao]",
         "-c:v", "libx264", "-preset", "medium", "-crf", "17", "-pix_fmt", "yuv420p",
         "-c:a", "aac", "-b:a", "192k", "-ar", "48000", str(out)])

    total = float(probe_media(out)["duration"])
    cfg["duration"] = round(total, 3)
    cfg["input"]["video"] = "clean-cut.mp4"
    write_json(p["config"], cfg)

    write_json(p["work"] / "rough-cut.json", {
        "noise_db": noise_db, "min_silence": min_sil, "pad": pad,
        "clips": [str(c) for c in clips], "shots": plan, "duration": round(total, 3),
        "output": str(out),
        "note": "切点全部落在实测静音区。时间轴锁定后不要再改，字幕要跟这条对齐。",
    })
    print(f"  input/clean-cut.mp4  {total:.3f}s（{len(plan)} 段）")
    return {"duration": round(total, 3), "shots": len(plan)}


def main() -> None:
    ap = argparse.ArgumentParser(description="按静音切点把多段素材拼成一条粗剪")
    ap.add_argument("project")
    ap.add_argument("--noise", type=float, default=-34.0, help="静音门限 dBFS")
    ap.add_argument("--min-sil", type=float, default=0.30, help="最短静音时长")
    ap.add_argument("--pad", type=float, default=0.10, help="切点两边保留量")
    ap.add_argument("--merge-gap", type=float, default=0.45, help="小于此间隔的语音段合并")
    ap.add_argument("--min-len", type=float, default=0.40, help="短于此的语音段丢弃")
    a = ap.parse_args()
    project = Path(a.project).resolve()
    build(load_config(project_paths(project)["config"]), project,
          a.noise, a.min_sil, a.pad, a.merge_gap, a.min_len)


if __name__ == "__main__":
    main()
