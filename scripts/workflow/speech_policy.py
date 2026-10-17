"""Delivery contract for spoken audio, separate from music and ambience."""
from __future__ import annotations

import wave
import json
from array import array
from pathlib import Path

from _common import probe_media, resolve_video, resolve_duration


# mixed = 现场人声 + 解说旁白同时成立：两边的证据都要齐。
MODES = {"narration", "source", "mixed", "none"}

# 解说句允许向相邻说话段外溢多少秒。现场声在那一段由 render.py 侧链压低，
# 所以短暂的「压过字头」是允许的；不允许的是整句压在人家说话上。
SLOT_BLEED = 0.5


def _audible_voice(path: Path, duration: float) -> tuple[bool, str]:
    if not path.is_file():
        return False, (f"缺少 {path}；Vlog 旁白走 scripts/story_audio.py PROJECT --approve-story，"
                       "口播加解说走 scripts/tts.py PROJECT（先写好 work/narration-lines.json）")
    try:
        with wave.open(str(path), "rb") as sound:
            channels, rate, width = sound.getnchannels(), sound.getframerate(), sound.getsampwidth()
            actual = sound.getnframes() / rate
            if (channels, rate, width) != (2, 48000, 2):
                return False, "work/voice.wav 应为 48kHz/16bit/立体声 PCM"
            if duration <= 0 or abs(actual - duration) > 0.25:
                return False, (f"work/voice.wav 长 {actual:.2f}s，与当前工程片长 "
                               f"{duration:.2f}s 不匹配；请重新生成旁白")
            active = 0
            while True:
                data = sound.readframes(8192)
                if not data:
                    break
                samples = array("h")
                samples.frombytes(data)
                active += sum(abs(value) > 150 for value in samples)
                if active >= rate * channels // 10:
                    return True, "旁白文件有有效采样且与片长匹配；仍需人工听审语义及音画同步"
    except (OSError, EOFError, ValueError, wave.Error) as exc:
        return False, f"work/voice.wav 无法读取：{exc}"
    return False, "work/voice.wav 全静音或近乎静音；不能用 BGM 代替旁白"


def _parse_srt(path: Path) -> list[dict]:
    """Read cue index/start/end/text; tolerate BOM, CRLF, padding and a missing
    trailing blank line — otherwise the last cue is silently dropped."""
    cues: list[dict] = []
    try:
        raw = path.read_text(encoding="utf-8-sig").splitlines()
    except (OSError, ValueError):
        return cues
    pending: dict | None = None

    def flush() -> None:
        nonlocal pending
        if pending is not None:
            pending["text"] = " ".join(pending["text"]).strip()
            cues.append(pending)
            pending = None

    index, text = None, []
    for line in raw:
        stripped = line.strip()
        if "-->" in stripped:
            flush()
            try:
                left, right = stripped.split("-->")
                pending = {"index": index, "start": _clock(left), "end": _clock(right),
                           "text": []}
            except ValueError:
                pending = {"index": index, "start": -1.0, "end": -1.0, "text": []}
            index, text = None, []
            continue
        if not stripped:
            flush()
            index, text = None, []
            continue
        # A bare number starts a cue only when we're not already holding its text:
        # caption text like “第一句” is itself all digits, and must not be eaten.
        if index is None and not text and pending is None and stripped.isdigit():
            index = int(stripped)
            continue
        if pending is not None:
            pending["text"].append(stripped)
        else:
            text.append(stripped)
    flush()
    return cues


def _clock(value: str) -> float:
    parts = value.strip().replace(",", ".").split(":")
    if len(parts) != 3:
        raise ValueError("时间码格式不正确")
    return int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])


def _spoken_lines(path: Path, windows: list[tuple[float, float]]) -> tuple[bool, str]:
    """Check each declared narration window really carries samples, line by line."""
    try:
        with wave.open(str(path), "rb") as sound:
            channels, rate, width = (sound.getnchannels(), sound.getframerate(),
                                     sound.getsampwidth())
            if (channels, rate, width) != (2, 48000, 2):
                return False, "work/voice.wav 应为 48kHz/16bit/立体声 PCM"
            total = sound.getnframes()
            for start, end, text in windows:
                first = max(0, int(round(start * rate)))
                frames = int(round((end - start) * rate))
                if frames <= 0:
                    return False, f"旁白逐句时窗无效：{text}"
                sound.setpos(min(first, total))
                samples = array("h")
                samples.frombytes(sound.readframes(frames))
                active = sum(1 for i in range(0, len(samples) - channels + 1, channels)
                             if any(abs(value) > 150
                                    for value in samples[i:i + channels]))
                # A declared line with no audible sample is a delivery gap, not a detail.
                if active < rate // 20:
                    return False, (f"旁白 {text!r} 声明的 {start:.2f}–{end:.2f}s "
                                   "窗口里没有有效语音；该句没出声")
    except (OSError, EOFError, ValueError, wave.Error) as exc:
        return False, f"work/voice.wav 无法读取：{exc}"
    return True, f"{len(windows)} 句声明的时窗都有实际语音；仍需人工听审语义"


def _declared_lines(cfg: dict, project: Path) -> tuple[list[tuple[float, float, str]],
                                                       Path | None, bool, str]:
    """Load the optional per-line declaration; absent means the whole-file check."""
    audio = cfg.get("audio", {})
    name = audio.get("voice_cues")
    if not name:
        return [], None, False, ""
    cues_path = Path(project) / "work" / str(name)
    if not cues_path.is_file():
        return [], None, True, f"缺少声明的逐句时窗 {cues_path}"
    try:
        payload = json.loads(cues_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return [], None, True, f"{cues_path} 无法读取，逐句校验做不下去"
    lines = payload.get("lines") if isinstance(payload, dict) else None
    if not isinstance(lines, list) or not lines:
        return [], None, True, f"{cues_path} 缺少有效的 lines 数组"
    anchor_problem = _check_shot_anchors(lines, project)
    if anchor_problem:
        return [], None, True, anchor_problem
    windows: list[tuple[float, float, str]] = []
    for line in lines:
        try:
            start, end, text = float(line["start"]), float(line["end"]), line["text"]
        except (KeyError, TypeError, ValueError):
            return [], None, True, "逐句时窗缺少有效的 start/end/text"
        if (not isinstance(text, str) or not text.strip() or start < 0 or end <= start):
            return [], None, True, "逐句时窗的起止或文案无效"
        windows.append((start, end, text.strip()))
    return windows, cues_path.parent.parent / "input" / str(
        audio.get("voice_subtitle") or "captions.srt"), True, ""


def _check_shot_anchors(lines: list[dict], project: Path) -> str:
    """Optional source-range declarations stop a shifted plan reusing old voice."""
    marked = [isinstance(line, dict) and ("shot_index" in line or "shot_ref" in line)
              for line in lines]
    if not any(marked):
        return ""  # Old projects retain the original file/line gate.
    if not all(marked):
        return "逐句镜头锚点只声明了一部分；每句都需 shot_index 和 shot_ref"
    plan_path = Path(project) / "work/edit-plan.json"
    try:
        shots = json.loads(plan_path.read_text(encoding="utf-8"))["shots"]
    except (OSError, ValueError, TypeError, KeyError):
        return "已声明逐句镜头锚点，但镜头表无法读取"
    cursor, spans = 0.0, []
    try:
        for shot in shots:
            duration = float(shot["duration"])
            spans.append((cursor, cursor + duration, shot))
            cursor += duration
        for number, line in enumerate(lines, 1):
            index = int(line["shot_index"])
            ref = line["shot_ref"]
            start = float(line["start"])
            if index < 1 or index > len(spans):
                return f"第 {number} 句的镜头锚点超出当前镜头表"
            shot_start, shot_end, shot = spans[index - 1]
            if (not isinstance(ref, dict) or
                    Path(ref["source"]).resolve() != Path(shot["source"]).resolve() or
                    abs(float(ref["in"]) - float(shot["in"])) > 0.02 or
                    abs(float(ref["duration"]) - float(shot["duration"])) > 0.02 or
                    not shot_start - 0.02 <= start < shot_end + 0.02):
                return f"第 {number} 句 {line.get('text', '')!r} 的镜头锚点与当前镜头表不符"
    except (KeyError, TypeError, ValueError, IndexError):
        return "逐句镜头锚点格式无效"
    return ""


def _subtitled_lines(path: Path, windows: list[tuple[float, float, str]]) -> tuple[bool, str]:
    """Every declared line needs a matching subtitle; visuals alone don't count.

    The cue must start at the declared time and stay inside the declared window:
    finished speech is naturally shorter than the window it was scheduled into.
    """
    cues = _parse_srt(path) if path.is_file() else []
    if not cues:
        return False, f"读不到 {path.name} 或其中没有可解析的字幕；旁白没有对应字幕"
    for start, end, text in windows:
        if not any(abs(cue["start"] - start) <= 0.12 and cue["end"] <= end + 0.12
                   and text in cue["text"] for cue in cues):
            return False, (f"旁白 {text!r} 在 {path.name} 里没有匹配的字幕"
                           f"（期望 {start:.2f}–{end:.2f}s）")
    return True, f"{len(windows)} 句旁白在 {path.name} 里都有时间与文案匹配的字幕"


def _in_silence_slots(windows: list[tuple[float, float, str]], project: Path,
                      fps: int = 30) -> tuple[bool, str]:
    """每句解说都必须落在 `narration-slot` 镜头里（现场人声的空隙）。

    这是「解说只落在空隙里」这条规矩的**唯一执行点**：槽是粗剪时从真实静音里留出来的，
    所以「有没有地方说话」是镜头表说了算，不是旁白文件说了算。
    """
    plan_path = Path(project) / "work" / "edit-plan.json"
    try:
        shots = json.loads(plan_path.read_text(encoding="utf-8"))["shots"]
    except (OSError, ValueError, TypeError, KeyError):
        return False, "声明了解说旁白，但镜头表读不出来，判不了每句是不是落在解说槽里"
    from .narration import shot_spans
    spans = [(a, b, (shot.get("kind") or "speech")) for a, b, shot in shot_spans(shots, fps)]
    if not any(kind == "narration-slot" for _, _, kind in spans):
        return False, ("镜头表里没有任何 narration-slot（解说槽）；"
                       "用 auto_edit --narration-slots N 重剪，或不要把语音目标设成 mixed")
    for start, end, text in windows:
        inside = any(a - SLOT_BLEED <= start and end <= b + SLOT_BLEED
                     for a, b, kind in spans if kind == "narration-slot")
        if not inside:
            return False, (f"解说 {text!r} 的 {start:.2f}–{end:.2f}s 不落在任何解说槽里；"
                           "解说只能放在现场人声的空隙，不许压在人说话上")
    return True, f"{len(windows)} 句解说都落在解说槽里（外溢上限 {SLOT_BLEED}s）"


def _narration_readiness(cfg: dict, project: Path, require_slots: bool
                         ) -> tuple[bool, str]:
    voice = Path(project) / "work" / "voice.wav"
    duration = resolve_duration(cfg, project)
    ready, detail = _audible_voice(voice, duration)
    if not ready:
        return False, detail
    windows, subtitle, declared, problem = _declared_lines(cfg, project)
    if problem:
        return False, problem
    if not declared:
        # Old projects declare nothing; keep the file-level check only.
        if require_slots:
            return False, ("mixed 模式必须声明 audio.voice_cues 逐句时窗，"
                           "否则判不了解说有没有压到现场人声")
        return True, detail
    # An empty list still means "declared": don't let a missing entry turn into a pass.
    if not windows:
        return False, "已声明 audio.voice_cues，但没有任何逐句时窗可校验"
    spoken, detail = _spoken_lines(voice, windows)
    if not spoken:
        return False, detail
    subtitled, detail = _subtitled_lines(subtitle, windows)
    if not subtitled:
        return False, detail
    from .caption_timing import overlap_status
    timing_ok, timing_detail = overlap_status(
        subtitle, int(cfg.get("canvas", {}).get("fps", 30)))
    if timing_ok is not True:
        return False, f"旁白字幕预检未通过：{timing_detail}"
    if require_slots:
        slotted, slot_detail = _in_silence_slots(
            windows, project, int(cfg.get("canvas", {}).get("fps", 30)))
        if not slotted:
            return False, slot_detail
        detail = slot_detail
    return True, detail


def _source_readiness(cfg: dict, project: Path) -> tuple[bool, str]:
    try:
        source = resolve_video(cfg, project)
        info = probe_media(source)
    except (OSError, ValueError, SystemExit) as exc:
        return False, f"原声素材不可读取：{exc}"
    if not info["has_audio"]:
        return False, f"{source} 无音轨，无法作为口播原声"
    from .source_speech import EVIDENCE_NAME, evidence_status, source_signature
    evidence = Path(project) / "work" / EVIDENCE_NAME
    if not evidence.is_file():
        return False, (f"缺少 {evidence} 原声转写证据；运行 scripts/run_all.py "
                       "自动执行本地离线转写，音乐不能代替口播")
    try:
        record = json.loads(evidence.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return False, "原声转写证据无法读取，请重新运行 scripts/run_all.py"
    return evidence_status(record, source_signature(source, info["duration"]))


def speech_readiness(cfg: dict, project: Path) -> tuple[bool, str]:
    """Check the declared delivery intent without assuming any audio is speech."""
    mode = cfg.get("audio", {}).get("speech_mode")
    if mode not in MODES:
        return False, ("请在 config.json 的 audio.speech_mode 明确设置 narration（配音）、"
                       "source（原声）、mixed（原声 + 解说）或 none（确认无需语音）")
    if mode == "none":
        return True, "已明确选择无语音；保留音乐/环境声即可"
    if mode in ("narration", "mixed"):
        # mixed 是两条腿：解说这半查不出结果也要把原声那半查完，报告里才说得清缺哪一半。
        narration_ok, narration_detail = _narration_readiness(
            cfg, project, require_slots=(mode == "mixed"))
        if mode == "narration":
            return narration_ok, narration_detail
        source_ok, source_detail = _source_readiness(cfg, project)
        parts = []
        if not source_ok:
            parts.append(f"原声证据：{source_detail}")
        if not narration_ok:
            parts.append(f"旁白：{narration_detail}")
        if parts:
            return False, " / ".join(parts)
        return True, f"现场人声与解说旁白都在（{source_detail}；{narration_detail}）"
    return _source_readiness(cfg, project)


def narration_slot_status(cfg: dict, project: Path) -> tuple[bool | None, str]:
    """给质检用的三态：解说到底有没有落在空隙里。

    判不了就返回 None 并写清为什么 —— 不是 mixed 的工程不该因为「没有解说槽」而报红，
    也不该因为「这项没跑」而从报告里消失。
    """
    audio = cfg.get("audio") or {}
    if audio.get("speech_mode") != "mixed":
        return None, f"不是 mixed 模式（当前 {audio.get('speech_mode')!r}），本项没查"
    windows, _subtitle, declared, problem = _declared_lines(cfg, project)
    if problem:
        return False, problem
    if not declared or not windows:
        return None, "未声明逐句旁白时窗，判不了解说落在哪"
    return _in_silence_slots(windows, project,
                             int(cfg.get("canvas", {}).get("fps", 30)))


def require_speech_ready(cfg: dict, project: Path) -> None:
    ready, detail = speech_readiness(cfg, project)
    if not ready:
        raise SystemExit(f"语音交付检查未通过：{detail}")
