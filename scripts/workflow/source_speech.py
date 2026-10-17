"""Locally transcribed evidence that source audio actually contains speech."""
from __future__ import annotations

import json
import math
import os
import tempfile
from pathlib import Path

from _common import probe_media, resolve_video


EVIDENCE_NAME = "source-speech.json"


def source_signature(path: Path, duration: float) -> dict:
    source = Path(path).resolve()
    stat = source.stat()
    return {"source": str(source), "size": stat.st_size, "mtime_ns": stat.st_mtime_ns,
            "duration": round(float(duration), 3)}


def evidence_status(record: dict, signature: dict) -> tuple[bool, str]:
    """Treat music hallucinations and stale transcripts as failed evidence."""
    if not isinstance(record, dict) or record.get("signature") != signature:
        return False, "原声转写证据与当前素材不匹配或已过期，需要重新识别"
    if record.get("source") != signature["source"]:
        return False, "原声转写对应的素材路径不正确"
    try:
        duration = float(record["duration"])
        probability = float(record["language_probability"])
    except (KeyError, TypeError, ValueError):
        return False, "原声转写缺少有效的时长或语言置信度"
    if not math.isfinite(duration) or abs(duration - signature["duration"]) > 0.25:
        return False, "原声转写时长与当前素材不符"
    if record.get("status") == "no_speech":
        return False, "离线 ASR 返回 no_speech，未检测到人声；音乐不能代替口播"
    if record.get("status") != "ok" or record.get("language") != "zh" or (
            not math.isfinite(probability) or probability < 0.60):
        return False, "原声语言或转写状态不可靠，请人工听审素材"
    words = record.get("words")
    if not isinstance(words, list):
        return False, "原声转写缺少逐词时间记录"
    credible = []
    for word in words:
        if not isinstance(word, dict):
            return False, "原声转写词记录格式不正确"
        try:
            start, end = float(word["start"]), float(word["end"])
            confidence = float(word["confidence"])
            text = word["text"]
        except (KeyError, TypeError, ValueError):
            return False, "原声转写词记录格式不正确"
        if (not isinstance(text, str) or not text.strip() or
                not all(math.isfinite(v) for v in (start, end, confidence)) or
                start < 0 or end <= start or end > duration + 0.25 or
                not 0 <= confidence <= 1):
            return False, "原声转写词时间或置信度无效"
        if confidence >= 0.60:
            credible.append((start, end))
    if len(credible) < 3:
        return False, f"原声只有 {len(credible)} 个可信词，可能是音乐误识别或过短口播"
    # Merge overlaps before measuring speech coverage, rather than counting the same
    # seconds repeatedly when Whisper emits overlapping word boundaries.
    merged = []
    for start, end in sorted(credible):
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    spoken = sum(end - start for start, end in merged)
    coverage = spoken / duration
    if spoken < max(0.35, duration * 0.08):
        return False, (f"原声可信语音仅覆盖 {coverage:.1%} / {spoken:.2f}s，"
                       "不足以确认是口播素材")
    return True, (f"离线 ASR 检出 {len(credible)} 个可信词，语音覆盖 {coverage:.1%}；"
                  "仍需人工听审内容与字幕")


def prepare_source_evidence(cfg: dict, project: Path, *, transcriber=None) -> dict:
    """Cache ASR by exact source identity; promote new evidence only on success."""
    source = resolve_video(cfg, project).resolve()
    info = probe_media(source)
    if not info["has_audio"]:
        raise SystemExit(f"{source} 无音轨，不能作为口播原声")
    signature = source_signature(source, info["duration"])
    work = Path(project) / "work"
    evidence = work / EVIDENCE_NAME
    if evidence.is_file():
        try:
            old = json.loads(evidence.read_text(encoding="utf-8"))
            if old.get("signature") == signature and old.get("source") == str(source):
                return old
        except (ValueError, OSError, AttributeError):
            pass
    from transcribe_audio import transcribe
    work.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".source-speech-", dir=work) as directory:
        staged = Path(directory) / EVIDENCE_NAME
        result = (transcriber or transcribe)(source, staged, "large-v3")
        if (not isinstance(result, dict) or result.get("source") != str(source) or
                not isinstance(result.get("words"), list)):
            raise ValueError("ASR 返回无效或不对应当前素材的转写记录")
        record = {**result, "signature": signature}
        staged.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n",
                          encoding="utf-8")
        os.replace(staged, evidence)
    return record


def import_source_evidence(cfg: dict, project: Path, transcript: Path) -> dict:
    """Bind a checked offline transcript to the current source without rendering."""
    source = resolve_video(cfg, project).resolve()
    info = probe_media(source)
    if not info["has_audio"]:
        raise ValueError(f"{source} 无音轨，不能作为口播原声")
    signature = source_signature(source, info["duration"])
    result = json.loads(Path(transcript).read_text(encoding="utf-8"))
    if not isinstance(result, dict) or result.get("source") != str(source):
        raise ValueError("导入转写的素材路径与当前素材不匹配")
    record = {**result, "signature": signature}
    ready, detail = evidence_status(record, signature)
    if not ready:
        raise ValueError(f"导入转写未通过检查：{detail}")
    if source_signature(source, info["duration"]) != signature:
        raise ValueError("导入期间素材发生变化，请重新转写")
    work = Path(project) / "work"
    work.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".source-speech-", dir=work) as directory:
        staged = Path(directory) / EVIDENCE_NAME
        staged.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n",
                          encoding="utf-8")
        os.replace(staged, work / EVIDENCE_NAME)
    return record
