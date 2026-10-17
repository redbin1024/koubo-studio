#!/usr/bin/env python3
"""解说旁白：`work/narration-lines.json` → `work/voice.wav` + 逐句时窗 + 旁白字幕。

这套是给**口播加解说**用的（`audio.speech_mode = mixed`）：现场人声不动，另配一条
解说轨，解说只落在粗剪时留出来的 `narration-slot`（原素材真实静音）里。

三条纪律：

1. **装不下就报错，不截断。** 文案比槽长时先按阶梯升速（默认 −5% → +30%），
   还装不下就抛错让你改稿 —— 自动截断会把一句话说半截，是这行里最难发现的事故。
2. **同一句同一速率只合成一次**，按 `(音色, 速率, 文案)` 哈希缓存；重跑逐字节一致。
3. **逐句写镜头锚点**：镜头表一动，旧旁白就不能再用（`speech_policy` 会当场拒收）。

用法：
    ../.venv/bin/python scripts/tts.py PROJECT            # 生成
    ../.venv/bin/python scripts/tts.py PROJECT --probe    # 只报装不装得下，不合成
    ../.venv/bin/python scripts/tts.py PROJECT --replace  # 已有旁白字幕时显式替换

需要装了 edge-tts 的 Python 环境（本机 film_editing/.venv 已装）。
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _common import (  # noqa: E402
    find_ffmpeg, find_ffprobe, load_config, project_paths, write_json,
)
from auto_captions import write_cues  # noqa: E402
from story_audio import build_voice  # noqa: E402

VOICE = "zh-CN-XiaoxiaoNeural"
RATES = ("-5%", "+5%", "+15%", "+30%")   # 装不下就一级一级提，提出去还不行就报错
LEAD = 0.15                              # 解说比槽口晚起一点，不要顶着上一句的字尾
TAIL_SLACK = 0.08                        # 与 build_voice 的窗口余量保持一致

NR_TRIM = ("silenceremove=start_periods=1:start_duration=0.02:start_threshold=-45dB,"
           "areverse,silenceremove=start_periods=1:start_duration=0.02:"
           "start_threshold=-45dB,areverse,loudnorm=I=-18:TP=-4:LRA=7")


class NarrationError(ValueError):
    """文案、槽位或素材对不上 —— 这类问题必须炸出来，不能悄悄降级。"""


def narration_spans(shots: list[dict], fps: int = 30) -> list[tuple[float, float, int]]:
    """解说槽在时间轴上的区间（按帧对齐）—— 正本在 workflow/narration.py，这里转发。"""
    from workflow.narration import narration_spans as spans
    return spans(shots, fps)


def _line_path(cache: Path, index: int, text: str, rate: str) -> Path:
    identity = hashlib.sha256(f"{VOICE}|{rate}|{text}".encode()).hexdigest()[:12]
    return cache / f"line-{index:02d}-{identity}.wav"


def synth_line(text: str, rate: str, target: Path) -> Path:
    """合成一句：edge-tts → 裁掉首尾静音 → 响度对齐 −18 LUFS → 48k/16bit/立体声。"""
    try:
        import edge_tts
    except ImportError as exc:  # pragma: no cover - 取决于运行环境
        raise NarrationError(
            "缺少 edge-tts；用装了它的环境跑，例如 ../.venv/bin/python scripts/tts.py") from exc
    if target.is_file():
        return target
    mp3 = target.with_suffix(".mp3")
    asyncio.run(edge_tts.Communicate(text, VOICE, rate=rate).save(str(mp3)))
    try:
        subprocess.run([find_ffmpeg(), "-v", "error", "-y", "-i", str(mp3), "-af", NR_TRIM,
                        "-ar", "48000", "-ac", "2", "-c:a", "pcm_s16le", str(target)],
                       check=True)
    finally:
        mp3.unlink(missing_ok=True)
    return target


def _duration(path: Path) -> float:
    probe = subprocess.run([find_ffprobe(), "-v", "error", "-show_entries",
                            "format=duration", "-of", "csv=p=0", str(path)],
                           check=True, capture_output=True, text=True)
    return float(probe.stdout.strip())


def fit_line(text: str, budget: float, cache: Path, index: int
             ) -> tuple[Path | None, str, float]:
    """把一句装进 budget 秒：够就停，不够就升速，都不行就抛错（绝不截断）。

    「装不装得下」只能靠实测时长回答，所以试装也要真的合成一句 —— 单句结果按
    `(音色, 速率, 文案)` 缓存，试装过的速率在正式生成时直接复用，不白跑。
    """
    attempts = []
    for rate in RATES:
        path = synth_line(text, rate, _line_path(cache, index, text, rate))
        length = _duration(path)
        attempts.append((rate, length))
        if length + TAIL_SLACK <= budget:
            return path, rate, length
    best = [f"{rate}→{length:.2f}s" for rate, length in attempts]
    raise NarrationError(
        f"旁白 {text!r} 装不进 {budget:.2f}s 的解说槽（试过 {'、'.join(best)}）；"
        "把文案改短，或在粗剪时多留一个更长的槽 —— 脚本不会替你截断")


def build(cfg: dict, project: Path, *, probe_only: bool = False,
          replace: bool = False) -> dict:
    p = project_paths(project)
    script_path = p["work"] / "narration-lines.json"
    try:
        script = json.loads(script_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise NarrationError(f"读不到 {script_path}（{exc}）；先写解说文案再配音") from exc
    lines = script.get("lines") or []
    if not lines:
        raise NarrationError(f"{script_path} 里没有 lines")

    plan_path = p["work"] / "edit-plan.json"
    try:
        shots = json.loads(plan_path.read_text(encoding="utf-8"))["shots"]
    except (OSError, ValueError, KeyError) as exc:
        raise NarrationError(f"镜头表读不出来（{exc}），判不了解说槽在哪") from exc
    spans = narration_spans(shots, int(cfg.get("canvas", {}).get("fps", 30)))
    if not spans:
        raise NarrationError("镜头表里没有 narration-slot；先用 auto_edit --narration-slots N 重剪")

    total = float(cfg.get("duration") or 0.0)
    subtitle = p["input"] / str(cfg["audio"].get("voice_subtitle") or "voice-captions.srt")
    if subtitle.exists() and not replace and not probe_only:
        raise NarrationError(f"已有 {subtitle.name}；确认替换时加 --replace")

    cache = p["work"] / "tts-cache"
    cache.mkdir(parents=True, exist_ok=True)
    windows, report = [], []
    for i, line in enumerate(lines, 1):
        text = str(line.get("text") or "").strip()
        if not text:
            raise NarrationError(f"第 {i} 句没有 text")
        slot = int(line.get("slot") or 0)
        match = [s for s in spans if s[2] == slot]
        if not match:
            raise NarrationError(f"第 {i} 句指向解说槽 {slot}，但镜头表里只有 "
                                 f"{len(spans)} 个槽；槽序号按时间顺序从 1 起")
        slot_start, slot_end, _ = match[0]
        start = round(float(line.get("at", slot_start + LEAD)), 3)
        budget = round(slot_end - start, 3)
        if budget <= 0.3:
            raise NarrationError(f"第 {i} 句的起点 {start:.2f}s 已经贴到槽尾 "
                                 f"{slot_end:.2f}s，没有可用的时长")
        path, rate, length = fit_line(text, budget, cache, i)
        windows.append({"start": start, "end": round(start + budget, 3), "text": text})
        report.append({"index": i, "slot": slot, "text": text, "start": start,
                       "budget": budget, "rate": rate,
                       "spoken": round(length, 3) if length else None})
        print(f"  解说 {i}（槽 {slot} {slot_start:.2f}–{slot_end:.2f}s）{rate} "
              f"{text}" + (f"  {length:.2f}s" if length else "  （未合成）"))

    if probe_only:
        return {"lines": report, "probe": True}

    by_text = {}
    for i, line in enumerate(lines, 1):
        by_text[str(line["text"]).strip()] = _line_path(cache, i, str(line["text"]).strip(),
                                                        report[i - 1]["rate"])
    voice = p["work"] / "voice.wav"
    cues = build_voice(windows, total, voice, synth=lambda text, _t: by_text[text])

    # 逐句钉在镜头上：镜头表一动，这些锚点就对不上，旧旁白会被拒收。
    cursor, shot_spans = 0.0, []
    for i, shot in enumerate(shots, 1):
        shot_spans.append((cursor, cursor + float(shot["duration"]), i, shot))
        cursor += float(shot["duration"])
    for cue in cues:
        _, _, index, shot = next((s for s in shot_spans if s[0] <= cue["start"] < s[1]),
                                 (0, 0, 1, shots[0]))
        cue.update(shot_index=index,
                   shot_ref={key: shot[key] for key in ("source", "in", "duration")})
    write_cues(cues, subtitle, force=True)
    write_json(p["work"] / "voice-cues.json", {
        "version": 1, "duration": total, "subtitle": subtitle.name, "voice": VOICE,
        "rate_mode": "阶梯升速，装不下报错", "lines": cues})
    # 装槽结果另存一份：**不要写回 narration-lines.json** ——
    # 那是作者手写的稿子，也是渲染指纹的输入之一，写回去会让凭据自己失效。
    write_json(p["work"] / "narration-resolved.json",
               {"version": 1, "voice": VOICE, "lines": report})
    print(f"  work/voice.wav（{len(cues)} 句）+ {subtitle.name}")
    return {"lines": report, "voice": str(voice), "subtitle": str(subtitle)}


def main() -> None:
    ap = argparse.ArgumentParser(description="解说旁白：文案装槽 → TTS → voice.wav + 旁白字幕")
    ap.add_argument("project")
    ap.add_argument("--probe", action="store_true", help="只报装不装得下，不合成不改文件")
    ap.add_argument("--replace", action="store_true", help="替换已有的旁白字幕")
    a = ap.parse_args()
    project = Path(a.project).resolve()
    try:
        build(load_config(project_paths(project)["config"]), project,
              probe_only=a.probe, replace=a.replace)
    except NarrationError as exc:
        raise SystemExit(str(exc)) from exc


if __name__ == "__main__":
    main()
