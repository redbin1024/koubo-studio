"""Check whether SRT cues can appear on the same output frame.

正本也是这里：**多条字幕轨合起来**的重叠判定（画面字幕 + 旁白字幕）走
`merged_overlap_status`，不要另写一个比较器 —— 两套字幕占的是同一条底部安全带，
各查各的都会通过，合起来才会撞车。
"""
from __future__ import annotations

import math
from pathlib import Path

from _common import parse_srt


def _load(path: Path, skipped: set[int] | None) -> tuple[list[dict] | None, str]:
    path = Path(path)
    if not path.is_file():
        return None, f"缺 {path.name}，无法检查字幕重叠"
    try:
        cues = [cue for cue in parse_srt(path)
                if cue["index"] not in (skipped or set()) and cue["raw"].strip()]
    except (OSError, UnicodeError, ValueError, IndexError) as exc:
        return None, f"{path.name} 无法解析：{exc}"
    if not cues:
        return None, f"{path.name} 没有任何有效字幕，无法交付字幕轨"
    for cue in cues:
        if not (math.isfinite(cue["start"]) and math.isfinite(cue["end"]) and
                0 <= cue["start"] < cue["end"]):
            return None, f"{path.name} 第 {cue['index']} 条字幕的时间范围无效"
        cue["file"] = path.name
    return cues, ""


def _scan(cues: list[dict], fps: int, label: str) -> tuple[bool | None, str]:
    """Return a three-state QC result for one or more subtitle tracks.

    Time ranges can overlap between frames without two cues ever being visible
    together. Check the output frame grid, matching the Pillow and MP4 renderers.
    """
    if fps <= 0:
        return None, "画布帧率无效，无法判断同帧重叠"
    ordered = sorted(cues, key=lambda cue: (cue["start"], cue["end"]))
    active = ordered[0]
    for cue in ordered[1:]:
        both_start = max(active["start"], cue["start"])
        both_end = min(active["end"], cue["end"])
        first_frame = math.ceil(both_start * fps - 1e-9)
        if first_frame / fps < both_end - 1e-9:
            where = (f"{active['file']} 第 {active['index']} 条与 {cue['file']} "
                     f"第 {cue['index']} 条" if active.get("file") != cue.get("file")
                     else f"第 {active['index']} 与第 {cue['index']} 条")
            return False, f"{where}在 {first_frame / fps:.3f}s 时间窗同帧重叠"
        if cue["end"] > active["end"]:
            active = cue
    return True, f"{label}的 {len(cues)} 条字幕没有同帧重叠"


def overlap_status(path: Path, fps: int, skipped: set[int] | None = None
                   ) -> tuple[bool | None, str]:
    cues, problem = _load(Path(path), skipped)
    if cues is None:
        return None, problem
    return _scan(cues, fps, f"{Path(path).name}")


def merged_overlap_status(tracks: list[tuple[Path, set[int]]], fps: int
                          ) -> tuple[bool | None, str]:
    """把几条字幕轨合起来判：各查各的过不了这一关，它们占的是同一条安全带。"""
    cues: list[dict] = []
    labels = []
    for path, skipped in tracks:
        loaded, problem = _load(Path(path), skipped)
        if loaded is None:
            return None, problem
        cues.extend(loaded)
        labels.append(Path(path).name)
    return _scan(cues, fps, "＋".join(labels))
