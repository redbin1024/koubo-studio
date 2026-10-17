#!/usr/bin/env python3
"""成片：烧字幕 + 混音（人声 + 音效）+ 响度归一，输出可交付的 mp4。

顺序有讲究，别调换：
  1) 字幕默认已经由 build_frames 的 Pillow 字幕层烘进 body-anim-silent.mp4，
     且压在收尾淡黑之上 —— 这是为了绕开 macOS libass 不支持 fontsdir 的限制。
     captions.burn = "ass" 时才在这里用滤镜烧 ASS（同样烧在包装层之上）。
  2) 人声与音效**分开进 amix**，用 normalize=0 保住各自调好的相对电平。
     直接 amix 两路原始音频会被自动归一化，音效全部被压小。
  3) loudnorm 放最后，目标 −14 LUFS / TP −2.6，这是流媒体的交付基准。

字幕滤镜的 fontsdir 必须是**真的装了 CJK 字体的目录**；指到 /System/Library/Fonts
会让中文全变方框。

用法：python scripts/render.py PROJECT_DIR
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _common import (  # noqa: E402
    find_ffmpeg, find_fonts_dir, load_config, project_paths, probe_media, resolve_video,
    resolve_duration,
)


def _esc(path: str) -> str:
    """ffmpeg 滤镜里的路径转义：反斜杠、冒号、单引号都要处理。"""
    return path.replace("\\", "\\\\").replace(":", "\\:").replace("'", "\\'")


def build(cfg: dict, project: Path, total: float | None = None) -> dict:
    from workflow.speech_policy import require_speech_ready
    require_speech_ready(cfg, project)
    p = project_paths(project)
    body = p["work"] / "body-anim-silent.mp4"
    if not body.is_file():
        raise SystemExit(f"缺 {body}，先跑 scripts/build_frames.py")

    src = resolve_video(cfg, project)
    actual = resolve_duration(cfg, project)
    if total is not None and abs(float(total) - actual) > 0.25:
        raise SystemExit("成片时长与当前粗剪不一致；请先修改镜头表，不按旧片长截断素材")
    total = actual
    if abs(float(probe_media(body)["duration"]) - total) > 0.25:
        raise SystemExit("包装层与当前粗剪时长不符；请重新运行 build_frames.py")
    sfx = p["work"] / "sfx-track.wav"
    # 可选干轨：存在就进混音，不存在就跟以前完全一样（老工程不用改一个字）
    narration = p["work"] / "voice.wav"      # 旁白（tools/make_voiceover.py 出）
    bgm = p["work"] / "bgm.wav"              # 音乐床垫（tools/make_bgm.py 出）
    ass = p["captions"] / "final.ass"
    if cfg["sfx"].get("events") and not sfx.is_file():
        raise SystemExit(f"缺 {sfx}，先跑 scripts/make_sfx.py")

    audio = cfg["audio"]
    ln = audio["loudness"]
    duck = audio["duck"]
    fc = []
    # 默认字幕已经烘在 body-anim-silent.mp4 里（build_frames 用 Pillow 画的），
    # 这里再烧一遍 ASS 会叠字。captions.burn = "ass" 才走回 libass。
    if ass.is_file() and cfg["captions"].get("burn", "layer") == "ass":
        fc.append(f"[0:v]subtitles=filename={_esc(str(ass))}:fontsdir={_esc(find_fonts_dir(project))}[v]")
    else:
        fc.append("[0:v]null[v]")

    # ---- 配输入：按固定顺序 body / [现场声] / [音效] / [旁白] / [BGM]，索引跟着走
    has_voice = probe_media(src)["has_audio"]
    cmd_in, idx, streams = [], 1, []
    if has_voice:
        cmd_in += ["-i", str(src)]
        streams.append((idx, f"volume={audio['voice_volume']}", "amb", True))
        idx += 1
    if sfx.is_file():
        cmd_in += ["-i", str(sfx)]
        streams.append((idx, f"volume={audio['sfx_volume']}", "sfx", False))
        idx += 1
    if narration.is_file():
        cmd_in += ["-i", str(narration)]
        streams.append((idx, f"volume={audio['narration_volume']}", "vo", False))
        idx += 1
    if bgm.is_file():
        cmd_in += ["-i", str(bgm)]
        streams.append((idx, f"volume={audio['bgm_volume']}", "bgm", True))
        idx += 1

    if not streams:
        raise SystemExit("没有任何音频输入（现场声/音效/旁白/BGM 全缺），没法出片")

    # ---- 旁白做侧链：现场声和 BGM 都要给它让位（duck=True 的那几路）
    need_duck = narration.is_file() and any(s[3] for s in streams)
    labels = []
    for i, (si, vol, name, duckable) in enumerate(streams):
        fc.append(f"[{si}:a]aresample=48000,aformat=channel_layouts=stereo,{vol}[{name}]")
        labels.append(name)
    if need_duck:
        ducked = [n for n in labels if n in ("amb", "bgm")]
        # 旁白分裂成「侧链键」+「本体」；键要几路就分几路
        keys = "".join(f"[vokey{k}]" for k in range(len(ducked)))
        fc.append(f"[vo]asplit={len(ducked) + 1}{keys}[vomix]")
        for k, n in enumerate(ducked):
            fc.append(f"[{n}][vokey{k}]sidechaincompress="
                      f"threshold={duck['threshold']}:ratio={duck['ratio']}:"
                      f"attack={duck['attack']}:release={duck['release']}[{n}d]")
            labels[labels.index(n)] = f"{n}d"
        labels[labels.index("vo")] = "vomix"

    if len(labels) == 1:
        fc.append(f"[{labels[0]}]anull[mix]")
    else:
        fc.append("".join(f"[{n}]" for n in labels) +
                  f"amix=inputs={len(labels)}:duration=longest:dropout_transition=0:"
                  f"normalize=0[mix]")
    # loudnorm 的**单遍**模式不保证真峰：它内部的限制器按采样峰值工作，
    # 低频撞击（impact-bass-2 那类）实测会冲出 +2dB 的 inter-sample 过冲
    # （采样峰 −3.6dBFS / 真峰 −1.6dBTP），verify 的 true-peak 一项必红。
    # 所以在它后面补一级 lookahead 限制器，阈值比 TP 再留 1.4dB 余量；
    # `level=disabled` 是关键 —— 不然它会做补偿增益，安静段会被整体抬起来。
    lim = 10 ** ((ln["TP"] - 1.4) / 20)
    fc.append(f"[mix]loudnorm=I={ln['I']}:TP={ln['TP']}:LRA={ln['LRA']}:print_format=summary,"
              f"alimiter=level_in=1:level_out=1:limit={lim:.4f}:attack=5:release=50:"
              f"level=disabled[out]")

    W, H = cfg["canvas"]["width"], cfg["canvas"]["height"]
    tag = f"{W}x{H}" if W <= H else f"{H}x{W}"
    out = p["output"] / f"final-{tag}.mp4"
    cmd = [find_ffmpeg(), "-v", "error", "-y", "-i", str(body), *cmd_in]
    cmd += ["-filter_complex", ";".join(fc), "-map", "[v]", "-map", "[out]"]
    if total:
        cmd += ["-t", f"{total:.3f}"]
    cmd += ["-c:v", "libx264", "-preset", "medium", "-crf", "17", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-movflags", "+faststart"]
    p["output"].mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=".render-", suffix=".mp4", dir=p["output"])
    os.close(fd)
    staged = Path(name)
    try:
        subprocess.run([*cmd, str(staged)], check=True)
        from workflow.loudness import normalize_final_audio
        try:
            final_loudness = normalize_final_audio(staged, ln)
        except ValueError as exc:
            raise SystemExit(str(exc)) from exc
        os.replace(staged, out)
    finally:
        staged.unlink(missing_ok=True)
    from workflow.delivery import record_render
    record_render(project, out, cfg)

    info = probe_media(out)
    print(f"  output/{out.name}  {info['duration']:.3f}s  "
          f"{info['width']}x{info['height']}  {out.stat().st_size / 1e6:.1f}MB")
    return {"file": str(out), "duration": info["duration"], "loudness": final_loudness}


def main() -> None:
    project = Path(sys.argv[1] if len(sys.argv) > 1 else ".").resolve()
    total = float(sys.argv[2]) if len(sys.argv) > 2 else None
    build(load_config(project_paths(project)["config"]), project, total)


if __name__ == "__main__":
    main()
