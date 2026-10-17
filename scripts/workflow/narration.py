"""「解说槽在哪」的**正本**：镜头表 → 时间轴上的空隙区间。

旁白装槽（`tts.py`）、图形段对齐（`caption_plan`）、质检（`speech_policy`）三处
都需要同一个答案，所以只在这里算一次。

**必须按帧对齐**：`render_plan` 的 `fps` 滤镜会把每一段向上取整到整帧，段数一多，
累加出来的偏差能有零点几秒。不按同一套规则算，槽在文件里是一个位置、在画面里是
另一个位置 —— 表现就是「解说比画面早/晚一点点」，而且看不出来是谁错了。
"""
from __future__ import annotations

import math


def shot_spans(shots: list[dict], fps: int = 30) -> list[tuple[float, float, dict]]:
    """逐段时间轴区间 [(start, end, shot)]，与 render_plan 的取整规则一致。"""
    if fps <= 0:
        raise ValueError("帧率必须大于 0")
    cursor, spans = 0.0, []
    for shot in shots:
        frames = math.ceil(round(float(shot["duration"]) * fps, 6)) / fps
        spans.append((round(cursor, 3), round(cursor + frames, 3), shot))
        cursor += frames
    return spans


def narration_spans(shots: list[dict], fps: int = 30) -> list[tuple[float, float, int]]:
    """返回 [(start, end, 槽序号)]，槽按时间顺序从 1 编号。"""
    spans = []
    for start, end, shot in shot_spans(shots, fps):
        if (shot.get("kind") or "speech") == "narration-slot":
            spans.append((start, end, len(spans) + 1))
    return spans


def slot_source_status(shots: list[dict], tolerance: float = 0.15
                       ) -> tuple[bool | None, str]:
    """槽必须真的落在**原素材的静音**里。

    拦的是「手改镜头表把一段说话声标成 narration-slot」——那样画面里的人在说话、
    解说又压上去，文件上却看不出任何异常。判不了（源文件没了）就返回 None。
    """
    from pathlib import Path
    from merge_cut import silences
    marked = [shot for shot in shots
              if (shot.get("kind") or "speech") == "narration-slot"]
    if not marked:
        return None, "镜头表里没有 narration-slot，本项没查"
    missing = [shot["source"] for shot in marked
               if not Path(shot["source"]).is_file()]
    if missing:
        return None, f"源素材不在本机（{Path(missing[0]).name}），查不了槽是不是真静音"
    cache: dict[str, list[tuple[float, float]]] = {}
    for shot in marked:
        source = str(shot["source"])
        if source not in cache:
            cache[source] = silences(Path(source), -34.0, 0.30)
        start, end = float(shot["in"]), float(shot["in"]) + float(shot["duration"])
        covered = any(a - tolerance <= start and end <= b + tolerance
                      for a, b in cache[source])
        if not covered:
            return False, (f"槽 {start:.2f}–{end:.2f}s 在 {Path(source).name} 里不是静音；"
                           "解说槽只能从真实静音里留出来，不许把说话声标成槽")
    return True, f"{len(marked)} 个解说槽都落在原素材的真实静音里"
