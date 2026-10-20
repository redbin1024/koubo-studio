"""全自动片子的旁白轨：无声素材自动写好的逐句文案 → edge-tts → 48k 立体声。

和 `tts.py` 的区别：`tts.py` 是“口播 + 解说槽”的 path，必须有真实静音槽；
全自动 Vlog 没有槽，旁白可以跨镜头。这里的每句仍然：
- 只在一段可写的时间窗内合成，装不下就跳过该句并记录，不截断半句话；
- 写入 `work/voice-cues.json` 与 `input/voice-captions.srt`，让 `speech_policy` 逐句复核；
- 输出 48kHz/16bit/立体声，长度严格等于成片时长。
"""
from __future__ import annotations

import importlib.util
import wave
from pathlib import Path

from _common import project_paths, write_json
from auto_captions import write_cues


SR = 48000


class AutoVoiceError(RuntimeError):
    """旁白轨无法生成；调用方应回退到无旁白 + BGM，而不是伪造静音。"""


def _read_wav(path: Path) -> tuple[bytes, int]:
    try:
        with wave.open(str(path), "rb") as sound:
            if (sound.getframerate(), sound.getnchannels(), sound.getsampwidth()) != (
                    SR, 2, 2):
                raise AutoVoiceError(f"TTS 产物不是 48kHz/16bit/立体声：{path.name}")
            return sound.readframes(sound.getnframes()), sound.getnframes()
    except (OSError, EOFError, wave.Error) as exc:
        raise AutoVoiceError(f"读不了 TTS 产物 {path.name}：{exc}") from exc


def _prepare_windows(windows: list[dict], total: float) -> list[dict]:
    """把文案窗口按时间排序并夹到片长内；装不下的留给 fit_line 决定。"""
    prepared = []
    for index, line in enumerate(windows, 1):
        text = str(line.get("text") or "").strip()
        if not text:
            continue
        try:
            start, end = float(line["start"]), float(line["end"])
        except (KeyError, TypeError, ValueError) as exc:
            raise AutoVoiceError(f"第 {index} 句旁白缺少有效起止时间") from exc
        start, end = max(0.0, start), min(float(total), end)
        if end - start < 0.35:
            continue
        prepared.append({**line, "text": text, "start": start, "end": end})
    prepared.sort(key=lambda item: (item["start"], item["end"]))
    return prepared


def build_narration(project: str | Path, cfg: dict, windows: list[dict],
                    *, total: float | None = None) -> dict:
    """合成旁白并落盘；返回 {lines, skipped, voice}。"""
    from tts import fit_line
    if importlib.util.find_spec("edge_tts") is None:
        raise AutoVoiceError("缺少 edge-tts；先安装 requirements-narration.txt，"
                             "或加 --no-narration 只出 BGM")

    project = Path(project).resolve()
    total = float(total if total is not None else cfg.get("duration") or 0.0)
    if total <= 0:
        raise AutoVoiceError("片长无效，无法生成旁白")
    prepared = _prepare_windows(windows, total)
    voice = str((cfg.get("audio") or {}).get("narration_voice") or "zh-CN-XiaoxiaoNeural")
    if not prepared:
        raise AutoVoiceError("没有可用的旁白窗口")

    work = project_paths(project)["work"]
    cache = work / "tts-cache"
    cache.mkdir(parents=True, exist_ok=True)
    track = bytearray(int(round(total * SR)) * 4)
    cues, kept, skipped = [], [], []
    for index, line in enumerate(prepared, 1):
        budget = round(line["end"] - line["start"], 3)
        try:
            path, rate, length = (
                fit_line(line["text"], budget, cache, index)
                if voice == "zh-CN-XiaoxiaoNeural"
                else fit_line(line["text"], budget, cache, index, voice))
        except Exception as exc:                                # noqa: BLE001
            # edge-tts 的网络错误/429 不能把整条自动流程炸掉：跳过这句，
            # 全句都失败时由下面统一抛 AutoVoiceError，让调用方回退无旁白。
            skipped.append({"text": line["text"], "start": line["start"],
                            "budget": budget,
                            "reason": f"{type(exc).__name__}: {str(exc)[:160]}"})
            continue
        if length is None or length + 0.08 > budget:
            skipped.append({"text": line["text"], "start": line["start"],
                            "budget": budget, "reason": "TTS 实际时长超出窗口"})
            continue
        content, frames = _read_wav(Path(path))
        position = int(round(line["start"] * SR))
        if position < 0 or position + frames > len(track) // 4:
            skipped.append({"text": line["text"], "start": line["start"],
                            "budget": budget, "reason": "旁白越过片长"})
            continue
        track[position * 4:(position + frames) * 4] = content
        cue = {
            "start": round(line["start"], 3),
            "end": round(line["start"] + frames / SR, 3),
            "text": line["text"],
        }
        if line.get("shot_index") is not None and line.get("shot_ref"):
            cue["shot_index"] = line["shot_index"]
            cue["shot_ref"] = line["shot_ref"]
        cues.append(cue)
        kept.append({"index": index, "start": cue["start"], "end": cue["end"],
                     "text": line["text"], "rate": rate, "spoken": round(length, 3)})

    if not cues:
        raise AutoVoiceError("所有旁白都装不进窗口；已回退到无旁白")

    voice = work / "voice.wav"
    with wave.open(str(voice), "wb") as sound:
        sound.setnchannels(2)
        sound.setsampwidth(2)
        sound.setframerate(SR)
        sound.writeframes(bytes(track))

    subtitle = project_paths(project)["input"] / str(
        cfg.get("audio", {}).get("voice_subtitle") or "voice-captions.srt")
    write_cues(cues, subtitle, force=True)
    write_json(work / "voice-cues.json", {
        "version": 1,
        "duration": round(total, 3),
        "subtitle": subtitle.name,
        "lines": cues,
        "skipped": skipped,
    })
    print(f"  旁白 {len(cues)} 句 / 跳过 {len(skipped)} 句 → {voice.name}")
    return {"voice": str(voice), "subtitle": str(subtitle),
            "lines": cues, "skipped": skipped,
            "total": round(total, 3)}
