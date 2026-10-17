"""Validate a reusable edit plan and render its shots into a rough cut."""
from __future__ import annotations

import math
import os
import subprocess
import tempfile
from pathlib import Path

from _common import find_ffmpeg, probe_media


def validate_plan(plan: dict, durations: dict[str, float]) -> float:
    """Return the planned duration, rejecting invalid source ranges."""
    if plan.get("version") != 1 or plan.get("mode") not in ("talking-head", "vlog"):
        raise ValueError("不支持的镜头表版本或素材模式")
    shots = plan.get("shots")
    if not isinstance(shots, list) or not shots:
        raise ValueError("镜头表不能为空")
    total = 0.0
    for index, shot in enumerate(shots, 1):
        transition = shot.get("transition", "cut")
        if transition not in ("cut", "dip") or (index == 1 and transition != "cut"):
            raise ValueError(f"第 {index} 镜头的转场无效")
        try:
            source = Path(shot["source"]).resolve()
            start, duration = float(shot["in"]), float(shot["duration"])
            source_duration = float(durations[str(source)])
            audio_gain = float(shot.get("audio_gain", 1.0))
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(f"第 {index} 镜头缺少有效素材或时间范围") from exc
        if not source.is_file() or not all(map(math.isfinite, (start, duration, source_duration))):
            raise ValueError(f"第 {index} 镜头素材不存在或时长无效")
        if start < 0 or duration <= 0 or start + duration > source_duration + 0.02:
            raise ValueError(f"第 {index} 镜头超出 {source.name} 的 {source_duration:.3f}s")
        if not math.isfinite(audio_gain) or not 0 <= audio_gain <= 2:
            raise ValueError(f"第 {index} 镜头的原声音量须在 0–2 之间")
        total += duration
    return round(total, 3)


def render_plan(plan: dict, output: Path, width: int, height: int, fps: int) -> dict:
    """Render only after validating every input; replace the old cut on success."""
    if min(width, height, fps) <= 0:
        raise ValueError("画布尺寸与帧率必须大于 0")
    sources = {str(Path(s["source"]).resolve()) for s in plan.get("shots", [])}
    info = {source: probe_media(source) for source in sources if Path(source).is_file()}
    total = validate_plan(plan, {source: meta["duration"] for source, meta in info.items()})
    output = Path(output).resolve()
    if str(output) in sources:
        raise ValueError("粗剪输出不能覆盖镜头表中的输入素材")
    args, filters = [], []
    for i, shot in enumerate(plan["shots"]):
        source = str(Path(shot["source"]).resolve())
        start, duration = float(shot["in"]), float(shot["duration"])
        args.extend(["-ss", f"{start:.3f}", "-t", f"{duration:.3f}", "-i", source])
        video_filter = (f"[{i}:v]setpts=PTS-STARTPTS,"
                        f"scale={width}:{height}:force_original_aspect_ratio=increase,"
                        f"crop={width}:{height},fps={fps},setsar=1")
        if info[source]["has_audio"]:
            audio_filter = (f"[{i}:a]atrim=duration={duration:.3f},asetpts=PTS-STARTPTS,"
                            f"aresample=48000,aformat=channel_layouts=stereo,"
                            f"volume={float(shot.get('audio_gain', 1.0)):.4f}")
        else:
            audio_filter = (f"anullsrc=r=48000:cl=stereo,atrim=duration={duration:.3f},"
                            "asetpts=PTS-STARTPTS")
        if shot.get("transition") == "dip":
            fade = min(0.12, duration / 3)
            video_filter += f",fade=t=in:st=0:d={fade:.3f}"
            audio_filter += f",afade=t=in:st=0:d={fade:.3f}"
        if i + 1 < len(plan["shots"]) and plan["shots"][i + 1].get("transition") == "dip":
            fade = min(0.12, duration / 3)
            video_filter += f",fade=t=out:st={duration - fade:.3f}:d={fade:.3f}"
            audio_filter += f",afade=t=out:st={duration - fade:.3f}:d={fade:.3f}"
        filters.extend([video_filter + f"[v{i}]", audio_filter + f"[a{i}]"])
    n = len(plan["shots"])
    filters.append("".join(f"[v{i}][a{i}]" for i in range(n))
                   + f"concat=n={n}:v=1:a=1[v][a]")
    output.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=".rough-cut-", suffix=".mp4", dir=output.parent)
    os.close(fd)
    tmp = Path(name)
    try:
        cmd = [find_ffmpeg(), "-v", "error", "-y", *args, "-filter_complex", ";".join(filters),
               "-map", "[v]", "-map", "[a]", "-c:v", "libx264", "-preset", "medium",
               "-crf", "17", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k",
               "-ar", "48000", "-movflags", "+faststart", str(tmp)]
        subprocess.run(cmd, check=True, capture_output=True)
        produced = probe_media(tmp)
        if abs(produced["duration"] - total) > max(0.15, n / fps):
            raise ValueError(f"粗剪时长 {produced['duration']:.3f}s 与计划 {total:.3f}s 不符")
        os.replace(tmp, output)
    finally:
        tmp.unlink(missing_ok=True)
    return {"output": str(output), "duration": produced["duration"], "shots": n}
