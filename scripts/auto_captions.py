#!/usr/bin/env python3
"""Turn verified word timestamps into editable SRT captions."""
from __future__ import annotations

import argparse
import json
import os
import tempfile
from pathlib import Path

from _common import strip_punct, ts_srt
from transcribe_audio import normalize_words


def _join_text(left: str, right: str) -> str:
    if left and right and left[-1].isascii() and right[0].isascii():
        if left[-1].isalnum() and right[0].isalnum():
            return left + " " + right
    return left + right


def make_cues(words: list[dict]) -> list[dict]:
    """Split on pauses, length and duration without changing spoken words."""
    cues, current = [], None
    for word in words:
        text = strip_punct(word["text"])
        if not text:
            continue
        start, end = float(word["start"]), float(word["end"])
        proposed = _join_text(current["text"], text) if current else text
        if current and (start - current["end"] > 0.65 or
                        len(proposed) > 14 or end - current["start"] > 4.0):
            if start <= current["start"]:
                raise ValueError("转写词的重叠时码无法安全拆分字幕")
            current["end"] = min(current["end"], start)
            cues.append(current)
            current = None
        if current is None:
            current = {"start": start, "end": end, "text": text}
        else:
            current["text"] = proposed
            current["end"] = max(current["end"], end)
    if current:
        cues.append(current)
    return cues


def write_transcript(transcript: dict, output: Path, force: bool = False) -> dict:
    """Turn an ASR transcript into subtitles, keeping manual captions unless forced."""
    words = normalize_words(transcript["words"], float(transcript["duration"]))
    cues = make_cues(words)
    if not cues:
        return {"status": "no_speech", "cues": 0, "output": None}
    return write_cues(cues, output, force=force)


def write_cues(cues: list[dict], output: Path, force: bool = False) -> dict:
    """Write already-formed cues verbatim.

    Narration lines are semantic units already: running them back through
    `make_cues` would re-join adjacent lines into one cue and destroy the
    per-line timing that the delivery gate checks.
    """
    output = Path(output)
    if output.exists() and not force:
        raise FileExistsError(f"已有字幕 {output}；只在确认要替换时加 --force")
    lines = [f"{i}\n{ts_srt(cue['start'])} --> {ts_srt(cue['end'])}\n{cue['text']}\n"
             for i, cue in enumerate(cues, 1)]
    output.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=".captions-", suffix=".srt", dir=output.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write("\n".join(lines))
        os.replace(name, output)
    finally:
        Path(name).unlink(missing_ok=True)
    return {"status": "ok", "cues": len(cues), "output": str(output)}


def write_srt(transcript: dict, output: Path, force: bool = False) -> dict:
    """Backwards-compatible name for the ASR transcript path."""
    return write_transcript(transcript, output, force=force)


def main() -> None:
    ap = argparse.ArgumentParser(description="逐词转写结果生成字幕")
    ap.add_argument("transcript")
    ap.add_argument("output")
    ap.add_argument("--force", action="store_true", help="显式覆盖已有字幕")
    args = ap.parse_args()
    data = json.loads(Path(args.transcript).read_text(encoding="utf-8"))
    result = write_srt(data, Path(args.output), force=args.force)
    print(f"{result['status']}：{result['cues']} 条字幕")


if __name__ == "__main__":
    main()
