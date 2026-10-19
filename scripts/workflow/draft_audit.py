"""草稿审计：把剪映草稿和 draft-spec 对账。

执行层（make_jianying_draft）不能自己证明自己正确。这里只读两份东西：
  work/draft-spec.json     先写下的决策
  draft_content.json       剪映实际落盘的对象

检查的是最近真实踩过的坑：主轨退回一整段、人声轨丢失、字幕行距 0.02 叠字、
贴纸/特效/滤镜没写进去、转场数量对不上、素材路径失效。
"""
from __future__ import annotations

import json
from pathlib import Path


def _load(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _tracks(draft: dict) -> list[dict]:
    return [t for t in draft.get("tracks") or [] if isinstance(t, dict)]


def _segments(track: dict) -> list[dict]:
    return [s for s in track.get("segments") or [] if isinstance(s, dict)]


def _track_by(draft: dict, *, name: str | None = None,
              type_: str | None = None) -> dict | None:
    for track in _tracks(draft):
        if name is not None and track.get("name") != name:
            continue
        if type_ is not None and track.get("type") != type_:
            continue
        return track
    return None


def _us(seg: dict, key: str) -> float:
    return float(((seg.get("target_timerange") or {}).get(key) or 0)) / 1e6


def audit(spec: dict, draft_dir: Path, *, installed: str | None = None) -> dict:
    checks: list[dict] = []

    def add(name: str, ok: bool | None, detail: str) -> None:
        checks.append({"name": name,
                       "status": "pass" if ok is True else ("fail" if ok is False else "unchecked"),
                       "detail": detail})

    draft_path = Path(draft_dir) / "draft_content.json"
    draft = _load(draft_path)
    if not draft:
        add("draft-readable", False, f"读不到 {draft_path}")
        return _finish(checks, draft_dir)
    add("draft-readable", True, str(draft_path))

    canvas = spec.get("canvas") or {}
    got = draft.get("canvas_config") or {}
    add("canvas", (int(got.get("width", 0)), int(got.get("height", 0))) ==
        (int(canvas.get("width", 0)), int(canvas.get("height", 0))),
        f"{got.get('width')}x{got.get('height')}（期望 {canvas.get('width')}x{canvas.get('height')}）")

    main_spec = [c for c in spec.get("clips") or [] if c.get("track") == "main"]
    main = _track_by(draft, name="video")
    main_segs = _segments(main) if main else []
    add("main-segments", len(main_segs) == len(main_spec),
        f"草稿 {len(main_segs)} 段 / 规格 {len(main_spec)} 段")
    planned = int(((spec.get("qa") or {}).get("planned_main_segments")) or 0)
    if planned:
        add("main-planned", len(main_segs) >= planned,
            f"草稿 {len(main_segs)} 段 / 镜头表计划 {planned} 段")
    else:
        add("main-planned", None, "没有 edit-plan，无法对账计划镜头数")
    if main_segs and main_spec:
        durations = [_us(s, "duration") for s in main_segs]
        want = [float(c["duration"]) for c in main_spec]
        max_delta = max(abs(a - b) for a, b in zip(durations, want)) if len(durations) == len(want) else 999
        add("main-durations", max_delta <= 0.05,
            f"最大偏差 {max_delta:.3f}s（容差 0.05s）")
        end = _us(main_segs[-1], "start") + _us(main_segs[-1], "duration")
        add("timeline-end", abs(end - float(spec.get("duration", 0))) <= 0.05,
            f"主轨结尾 {end:.3f}s / 规格 {float(spec.get('duration', 0)):.3f}s")
        gaps = []
        for prev, cur in zip(main_segs, main_segs[1:]):
            gaps.append(_us(cur, "start") - (_us(prev, "start") + _us(prev, "duration")))
        add("main-gaps", all(abs(g) <= 0.002 for g in gaps),
            f"最大间隙 {max((abs(g) for g in gaps), default=0):.3f}s")

    audio_spec = {c["track"]: c for c in spec.get("clips") or [] if c.get("type") == "audio"}
    names = {"voice": "人声", "sfx": "音效", "bgm": "BGM", "narration": "旁白"}
    for key, expected in audio_spec.items():
        track = _track_by(draft, name=names.get(key, key))
        segs = _segments(track) if track else []
        duration = sum(_us(s, "duration") for s in segs)
        ok = bool(segs) and duration > 0.05
        if key == "voice" and expected.get("required", True):
            ok = ok and not any(bool(s.get("muted")) for s in segs)
        add(f"audio-{key}", ok,
            f"{names.get(key, key)} {len(segs)} 段 / {duration:.3f}s"
            + ("，期望存在" if expected.get("required") else ""))

    text_spec = spec.get("texts") or []
    text_track = _track_by(draft, name="字幕")
    text_segs = _segments(text_track) if text_track else []
    add("text-count", len(text_segs) == len(text_spec),
        f"草稿 {len(text_segs)} 条 / 规格 {len(text_spec)} 条")
    if text_segs:
        times = sorted((_us(s, "start"), _us(s, "start") + _us(s, "duration"))
                       for s in text_segs)
        overlaps = sum(1 for (_, a), (b, _) in zip(times, times[1:]) if a > b + 0.001)
        add("text-overlap", overlaps == 0, f"时间重叠 {overlaps} 处")

    texts = (draft.get("materials") or {}).get("texts") or []
    spacing = [float(t.get("line_spacing", 0)) for t in texts
               if isinstance(t, dict) and "line_spacing" in t]
    min_spacing = float(((spec.get("qa") or {}).get("min_line_spacing")) or 0)
    add("text-line-spacing", (not spacing) or min(spacing) >= min_spacing,
        f"最小 {min(spacing):.3f} / 要求 ≥ {min_spacing:.3f}" if spacing
        else "草稿没有 text material")

    sticker_spec = spec.get("stickers") or []
    sticker_track = _track_by(draft, name="贴纸")
    sticker_segs = _segments(sticker_track) if sticker_track else []
    if sticker_spec:
        add("stickers", len(sticker_segs) == len(sticker_spec),
            f"草稿 {len(sticker_segs)} 段 / 规格 {len(sticker_spec)} 段")
    else:
        add("stickers", None, "规格未启用贴纸")

    native = spec.get("native") or []
    effect_track = _track_by(draft, type_="effect")
    filter_track = _track_by(draft, type_="filter")
    want_effect = sum(1 for x in native if x.get("kind") == "effect")
    want_filter = sum(1 for x in native if x.get("kind") == "filter")
    effect_segs = _segments(effect_track) if effect_track else []
    filter_segs = _segments(filter_track) if filter_track else []
    add("native-effect", (not want_effect) or len(effect_segs) == want_effect,
        f"草稿 effect {len(effect_segs)} 段 / 规格 {want_effect} 项")
    add("native-filter", (not want_filter) or len(filter_segs) == want_filter,
        f"草稿 filter {len(filter_segs)} 段 / 规格 {want_filter} 项")

    want_tr = sum(1 for x in native if x.get("kind") == "transition")
    if want_tr:
        transition_ids = {m.get("id") for m in (draft.get("materials") or {}).get("transitions") or []}
        got_tr = 0
        for seg in main_segs:
            refs = seg.get("extra_material_refs") or []
            if any(ref in transition_ids for ref in refs):
                got_tr += 1
        add("native-transitions", got_tr == want_tr, f"草稿 {got_tr} 处 / 规格 {want_tr} 处")
    else:
        add("native-transitions", None, "规格未启用转场")

    paths = []
    for group in ("videos", "audios"):
        for material in (draft.get("materials") or {}).get(group) or []:
            if isinstance(material, dict) and material.get("path"):
                paths.append(Path(material["path"]))
    missing = [str(p) for p in paths if not p.exists()]
    add("media-paths", not missing, f"缺 {len(missing)} 个文件"
        + (f"：{missing[:3]}" if missing else ""))

    qa = spec.get("qa") or {}
    if qa.get("require_installed"):
        add("installed", bool(installed) and Path(installed).is_dir(),
            str(installed or "没有安装路径"))
    else:
        add("installed", None, "规格未要求安装")

    return _finish(checks, draft_dir)


def _finish(checks: list[dict], draft_dir: Path) -> dict:
    summary = {
        "pass": sum(1 for c in checks if c["status"] == "pass"),
        "fail": sum(1 for c in checks if c["status"] == "fail"),
        "unchecked": sum(1 for c in checks if c["status"] == "unchecked"),
    }
    return {"version": 1, "draft": str(draft_dir), "checks": checks,
            "summary": summary, "ok": summary["fail"] == 0}
