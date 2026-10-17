#!/usr/bin/env python3
"""Generate reviewed narration and a simple original music bed."""
from __future__ import annotations

import argparse
import json
import math
import os
import subprocess
import tempfile
import wave
from array import array
from pathlib import Path

from auto_captions import write_cues
from _common import find_ffmpeg
from workflow.storyboard import MOODS


SR = 48000


def validate_audio_story(story: dict, plan: dict) -> dict:
    """Do not place voice against an unapproved or differently ordered timeline."""
    shots = plan.get("shots", [])
    expected = story.get("order", [])
    if not shots or story.get("status") != "proposal" or story.get("review_required") is not True:
        raise ValueError("需要完整的待审核故事方案")
    refs = story.get("shot_refs", {})
    if (not isinstance(expected, list) or len(expected) != len(shots) or
            len(set(expected)) != len(shots) or not isinstance(refs, dict)):
        raise ValueError("故事排序或镜头来源映射无效")
    for ident, shot in zip(expected, shots):
        ref = refs.get(ident)
        if (not isinstance(ref, dict) or
                Path(ref["source"]).resolve() != Path(shot["source"]).resolve() or
                abs(float(ref["in"]) - float(shot["in"])) > 0.02 or
                abs(float(ref["duration"]) - float(shot["duration"])) > 0.02):
            raise ValueError("故事镜头与当前镜头表不一致，先调整镜头表并重新生成字幕")
    if story.get("music_mood") not in MOODS:
        raise ValueError("未知的音乐情绪")
    starts, cursor = {}, 0.0
    for ident, shot in zip(expected, shots):
        duration = float(shot["duration"])
        if not math.isfinite(duration) or duration <= 0:
            raise ValueError("镜头时长无效")
        starts[ident] = cursor
        cursor += duration
    if abs(float(story.get("duration", -1)) - cursor) > 0.05:
        raise ValueError("故事方案片长与当前镜头表不一致")
    lines = story.get("narration")
    if not isinstance(lines, list):
        raise ValueError("旁白列表必须明确")
    if plan["mode"] == "talking-head" and lines:
        # 口播只在**解说槽**镜头（现场人声的空隙）上叠旁白，判据是镜头 kind。
        # 排序约定：expected 与 shots 位置一一对应（采纳排序时镜头表已同步重排）。
        slots = {ident for ident, shot in zip(expected, shots)
                 if (shot.get("kind") or "speech") == "narration-slot"}
        stray = [line for line in lines
                 if not isinstance(line, dict) or line.get("shot_id") not in slots]
        if stray or not slots:
            raise ValueError("口播不叠加旁白：旁白只能落在解说槽（narration-slot）镜头上")
    windows, anchors, seen = [], [], set()
    for line in lines:
        ident = line.get("shot_id")
        if ident not in starts or ident in seen or ident not in line.get("evidence", []):
            raise ValueError("旁白缺少有效且唯一的镜头证据")
        text = line.get("text")
        if not isinstance(text, str) or not 0 < len(text.strip()) <= 30:
            raise ValueError("旁白文案须为 1-30 字")
        start = starts[ident]
        if abs(float(line["start"]) - start) > 0.02:
            raise ValueError("旁白锚点与当前画面不一致")
        index = expected.index(ident)
        windows.append({"start": round(start, 3),
                        "end": round(start + float(shots[index]["duration"]), 3),
                        "text": text.strip()})
        anchors.append({"start": round(start, 3), "shot_index": index + 1,
                        "shot_ref": {"source": str(Path(shots[index]["source"]).resolve()),
                                     "in": float(shots[index]["in"]),
                                     "duration": float(shots[index]["duration"])}})
        seen.add(ident)
    return {"duration": round(cursor, 3),
            "windows": sorted(windows, key=lambda item: item["start"]),
            "anchors": sorted(anchors, key=lambda item: item["start"]),
            "music_mood": story["music_mood"]}


def _say(text: str, target: Path) -> Path:
    aiff = target.with_suffix(".aiff")
    subprocess.run(["say", "-v", "Tingting", "-o", str(aiff), text],
                   check=True, capture_output=True)
    try:
        subprocess.run([find_ffmpeg(), "-v", "error", "-y", "-i", str(aiff),
                        "-ar", str(SR), "-ac", "2", "-c:a", "pcm_s16le", str(target)],
                       check=True, capture_output=True)
    finally:
        aiff.unlink(missing_ok=True)
    return target


def build_voice(windows: list[dict], total: float, output: Path, synth=None) -> list[dict]:
    """Place complete spoken lines only when they fit the assigned shot."""
    if not windows or total <= 0:
        raise ValueError("无有效旁白或成片时长")
    frames = int(round(total * SR))
    track = bytearray(frames * 4)
    cues = []
    with tempfile.TemporaryDirectory(prefix="thsp-voice-") as tmp:
        for i, line in enumerate(windows):
            path = (synth or _say)(line["text"], Path(tmp) / f"line-{i}.wav")
            with wave.open(str(path), "rb") as source:
                if (source.getframerate(), source.getnchannels(), source.getsampwidth()) != (
                        SR, 2, 2):
                    raise ValueError("旁白必须为 48k/16bit/立体声 WAV")
                samples = source.getnframes()
                content = source.readframes(samples)
            pos = int(round(float(line["start"]) * SR))
            max_frames = int(round((float(line["end"]) - float(line["start"]) - 0.08) * SR))
            if pos < 0 or samples > max_frames or pos + samples > frames:
                raise ValueError(f"旁白 {line['text']!r} 放不进镜头窗口，请缩短文案")
            track[pos * 4:(pos + samples) * 4] = content
            cues.append({"start": round(pos / SR, 3), "end": round(
                (pos + samples) / SR, 3), "text": line["text"]})
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(output), "wb") as wav:
        wav.setnchannels(2)
        wav.setsampwidth(2)
        wav.setframerate(SR)
        wav.writeframes(track)
    return cues


CHORDS = {
    "calm": ((48, 52, 55, 59), 72), "warm": ((48, 52, 55, 57), 88),
    "upbeat": ((48, 52, 55, 60), 112), "tense": ((45, 48, 52, 56), 96),
}


def build_bgm(total: float, mood: str, output: Path) -> bool:
    """Write a low-level chord bed; silence is an explicit `none` choice."""
    if mood == "none":
        return False
    if mood not in CHORDS or not math.isfinite(total) or total <= 0:
        raise ValueError("无效的音乐情绪或时长")
    notes, bpm = CHORDS[mood]
    length = int(round(total * SR))
    beat = 60.0 / bpm
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(output), "wb") as wav:
        wav.setnchannels(2)
        wav.setsampwidth(2)
        wav.setframerate(SR)
        batch = array("h")
        for i in range(length):
            t = i / SR
            chord = (int(t / (4 * beat)) % 4)
            offsets = (0, -3, 5, 7)
            sound = sum(math.sin(2 * math.pi * 440 *
                                2 ** ((midi + offsets[chord] - 69) / 12) * t)
                        for midi in notes) / 4
            fade = min(1.0, t / 0.3, (total - t) / 0.6)
            sample = int(32767 * 0.12 * max(0.0, fade) * sound)
            batch.extend((sample, sample))
            if len(batch) >= 8192:
                wav.writeframes(batch.tobytes())
                batch = array("h")
        if batch:
            wav.writeframes(batch.tobytes())
    return True


def _atomic_json(path: Path, data: dict) -> None:
    """Write evidence atomically: a half-written cues file must never validate."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=f".{path.stem}-", suffix=".json", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(data, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)


def main() -> None:
    ap = argparse.ArgumentParser(description="从已审核故事方案生成旁白与原创音乐干轨")
    ap.add_argument("project")
    ap.add_argument("--approve-story", action="store_true", help="确认已审核故事建议")
    ap.add_argument("--replace-audio", action="store_true", help="显式替换已有音轨")
    ap.add_argument("--replace-captions", action="store_true", help="显式替换已有旁白字幕")
    args = ap.parse_args()
    if not args.approve_story:
        ap.error("需显式加 --approve-story，先审核文案和镜头顺序")
    project = Path(args.project).resolve()
    work = project / "work"
    story = json.loads((work / "storyboard.json").read_text(encoding="utf-8"))
    plan = json.loads((work / "edit-plan.json").read_text(encoding="utf-8"))
    scheduled = validate_audio_story(story, plan)
    voice, bgm = work / "voice.wav", work / "bgm.wav"
    cfg_path = project / "config.json"
    cfg = json.loads(cfg_path.read_text(encoding="utf-8")) if cfg_path.exists() else {}
    subtitle_name = cfg.get("input", {}).get("subtitle") or "captions.srt"
    # 旁白逐字稿是**另一条轨**，不该盖住画面提示文字。老工程没声明 voice_subtitle
    # 时仍然写回 input.subtitle，行为和以前一模一样。
    narration_name = cfg.get("audio", {}).get("voice_subtitle") or subtitle_name
    captions = project / "input" / narration_name
    if not args.replace_audio and (voice.exists() or bgm.exists()):
        ap.error("已有音轨；确认替换时加 --replace-audio")
    if scheduled["windows"] and captions.exists() and not args.replace_captions:
        ap.error(f"已有 {narration_name}；确认替换时加 --replace-captions")
    if not scheduled["windows"] and voice.exists():
        ap.error("新方案没有旁白，但旧 voice.wav 仍在；请先处理旧音轨")
    if scheduled["music_mood"] == "none" and bgm.exists():
        ap.error("新方案不需要音乐，但旧 bgm.wav 仍在；请先处理旧音轨")
    with tempfile.TemporaryDirectory(prefix="thsp-story-audio-") as tmp:
        stage = Path(tmp)
        if scheduled["windows"]:
            cues = build_voice(scheduled["windows"], scheduled["duration"], stage / "voice.wav")
            # 旁白逐字稿按「一句一条」写，交给 ASR 的分句逻辑会把相邻两句并成一条。
            write_cues(cues, stage / "captions.srt")
            # 落盘审核过的逐句时窗，出片前才有人能逐句核对「这句真出声了吗」。
            _atomic_json(work / "voice-cues.json", {
                "version": 1, "duration": scheduled["duration"],
                "subtitle": narration_name,
                "lines": [{"start": cue["start"], "end": cue["end"], "text": cue["text"],
                           "shot_index": anchor["shot_index"],
                           "shot_ref": anchor["shot_ref"]}
                          for cue, anchor in zip(cues, scheduled["anchors"])]})
        else:
            # 新方案没有旁白：留着旧时窗会让预检去核对一条已经不存在的旁白。
            (work / "voice-cues.json").unlink(missing_ok=True)
        if scheduled["music_mood"] != "none":
            build_bgm(scheduled["duration"], scheduled["music_mood"], stage / "bgm.wav")
        work.mkdir(parents=True, exist_ok=True)
        for name in ("voice.wav", "bgm.wav"):
            built = stage / name
            if built.exists():
                os.replace(built, work / name)
        if scheduled["windows"]:
            captions.parent.mkdir(parents=True, exist_ok=True)
            os.replace(stage / "captions.srt", captions)
    print(f"音轨生成完成；请运行 python3 scripts/run_all.py {project}")


if __name__ == "__main__":
    main()
