#!/usr/bin/env python3
"""Offline, word-timed speech transcription for the finished rough cut."""
from __future__ import annotations

import argparse
import json
import math
import os
import tempfile
from pathlib import Path


def normalize_words(words: list[dict], duration: float) -> list[dict]:
    """Reject impossible timings instead of inventing subtitle positions."""
    out = []
    previous = 0.0
    for word in words:
        try:
            text = str(word["text"]).strip()
            start, end = float(word["start"]), float(word["end"])
            confidence = float(word["confidence"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("转写词缺少有效的文案、时间或置信度") from exc
        if not text or not all(math.isfinite(v) for v in (start, end, confidence)):
            raise ValueError("转写词含空文案或无效数值")
        if start == end and 0 <= start <= duration:
            start = max(0.0, start - 0.02) if start >= duration else start
            end = min(duration, start + 0.02)
        if start < previous - 0.001 or start < 0 or end <= start or end > duration + 0.02:
            raise ValueError(f"转写词 {text!r} 的时间超出或不按顺序")
        if not 0 <= confidence <= 1:
            raise ValueError(f"转写词 {text!r} 的置信度不在 0-1")
        out.append({"text": text, "start": round(start, 3),
                    "end": round(end, 3), "confidence": round(confidence, 3)})
        previous = start
    return out


def _load_model(name: str):
    try:
        from faster_whisper import WhisperModel
    except ImportError as exc:
        raise RuntimeError("缺少 faster-whisper；请使用已安装该库的 Python 环境运行") from exc
    return WhisperModel(name, device="cpu", compute_type="int8")


def transcribe(media: Path, output: Path, model_name: str = "large-v3",
               model_factory=None) -> dict:
    """Transcribe a media file; an empty word list explicitly means no speech."""
    media, output = Path(media).resolve(), Path(output)
    if not media.is_file():
        raise FileNotFoundError(f"找不到待转写媒体：{media}")
    model = (model_factory or _load_model)(model_name)
    segments, info = model.transcribe(
        str(media), language="zh", word_timestamps=True, vad_filter=True,
        vad_parameters={"min_silence_duration_ms": 300}, beam_size=5)
    raw = []
    for segment in segments:
        for word in segment.words or []:
            raw.append({"text": word.word, "start": word.start, "end": word.end,
                        "confidence": word.probability})
    duration = float(info.duration)
    if not math.isfinite(duration) or duration <= 0:
        raise ValueError("ASR 返回的媒体时长无效")
    words = normalize_words(raw, duration)
    result = {"source": str(media), "model": model_name,
              "language": info.language, "language_probability": info.language_probability,
              "duration": round(duration, 3),
              "status": "ok" if words else "no_speech", "words": words}
    output.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=".transcript-", suffix=".json", dir=output.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(result, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        os.replace(name, output)
    finally:
        Path(name).unlink(missing_ok=True)
    return result


def main() -> None:
    ap = argparse.ArgumentParser(description="用本地 faster-whisper 转写粗剪")
    ap.add_argument("media")
    ap.add_argument("output")
    ap.add_argument("--model", default="large-v3")
    args = ap.parse_args()
    result = transcribe(Path(args.media), Path(args.output), args.model)
    print(f"{result['status']}：{len(result['words'])} 词 → {args.output}")


if __name__ == "__main__":
    main()
