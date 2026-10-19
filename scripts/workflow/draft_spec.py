"""草稿决策规格（Draft Spec）。

这一层是「剪辑决策」和「剪映执行」之间的稳定接口：镜头、包装、字幕、贴纸、
原生特效/滤镜/转场、音频和验收要求先写成 JSON，再由 make_jianying_draft 执行，
由 draft_audit 复核。原则与 Edit-Skill 的 EDL 相同：

- 时间是秒（float），执行层负责换成剪映的微秒；
- 每个镜头带 role / rule_id / reason，便于复盘；
- 原生资源只记名字与参数，不记剪映内部 id；
- 规格先落盘，执行后**不许改规格来迁就产物**。
"""
from __future__ import annotations

from pathlib import Path

from _common import project_paths, resolve_video


def _packaging(cfg: dict, total: float) -> list[dict]:
    """包装层时间窗，和 make_jianying_draft.overlay_windows 保持同一口径。"""
    wins: list[dict] = []
    card = cfg["card"]
    if card["enabled"] and card["end"] - card["start"] > 0.05:
        wins.append({"label": "卡段", "start": float(card["start"]),
                     "end": float(card["end"])})
    gold = cfg["gold"]
    if gold["enabled"] and gold.get("text") and gold["out"] - gold["in"] > 0.05:
        wins.append({"label": "发光字", "start": float(gold["in"]),
                     "end": float(gold["out"])})
    fade = float(cfg["segments"]["fade_out"])
    if fade > 0.05:
        wins.append({"label": "收尾淡黑", "start": round(total - fade, 3),
                     "end": round(total, 3)})
    return wins


def _edit_plan_shots(project: Path) -> list[dict]:
    import json
    path = project_paths(project)["work"] / "edit-plan.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return [s for s in data.get("shots") or [] if isinstance(s, dict)]
    except (OSError, ValueError):
        return []


def build(cfg: dict, project: Path, *,
          name: str, total: float, main_durations: list[float],
          captions: list[dict], fx_plans: list[dict],
          voice: tuple[Path, float] | None,
          sfx: tuple[Path, float] | None,
          bgm: tuple[Path, float] | None,
          narration: tuple[Path, float] | None) -> dict:
    """生成一份可直接审计的草稿规格。

    main_durations 已经是对齐到帧的时长；main 轨引用 work/graded.mp4，
    每个 segment 的 source_in 就是时间线起点（压平视频的切段）。
    """
    p = project_paths(project)
    fps = int(cfg["canvas"]["fps"])
    main_source = p["work"] / "graded.mp4"
    overlay_source = p["work"] / "body-anim-silent.mp4"
    plan_shots = _edit_plan_shots(project)

    tracks = [
        {"name": "main", "type": "video", "label": "video"},
        {"name": "packaging", "type": "video", "label": "包装层"},
        {"name": "stickers", "type": "video", "label": "贴纸"},
        {"name": "voice", "type": "audio", "label": "人声"},
        {"name": "sfx", "type": "audio", "label": "音效"},
        {"name": "bgm", "type": "audio", "label": "BGM"},
        {"name": "effect", "type": "effect", "label": "effect"},
        {"name": "filter", "type": "filter", "label": "filter"},
        {"name": "captions", "type": "text", "label": "字幕"},
    ]

    clips: list[dict] = []
    cursor = 0.0
    for i, dur in enumerate(main_durations, 1):
        shot = plan_shots[i - 1] if i <= len(plan_shots) else {}
        clips.append({
            "id": f"main-{i}", "track": "main", "type": "video",
            "source": str(main_source), "source_in": round(cursor, 3),
            "start": round(cursor, 3), "duration": round(float(dur), 3),
            "role": "shot",
            "rule_id": str(shot.get("id") or f"shot_{i}"),
            "reason": str(shot.get("reason") or "按镜头表切段"),
        })
        cursor += float(dur)

    for i, win in enumerate(_packaging(cfg, total), 1):
        clips.append({
            "id": f"packaging-{i}", "track": "packaging", "type": "video",
            "source": str(overlay_source), "source_in": float(win["start"]),
            "start": float(win["start"]),
            "duration": round(float(win["end"]) - float(win["start"]), 3),
            "role": "packaging", "rule_id": f"PKG-{i:02d}",
            "reason": str(win["label"]),
        })

    sticker_cfg = cfg.get("stickers") or {}
    stickers = []
    if sticker_cfg.get("enabled"):
        for i, item in enumerate(sticker_cfg.get("items") or [], 1):
            asset = p["assets"] / f"sticker-{i}.png"
            if not asset.is_file():
                continue
            at = float(item.get("at", 0) or 0)
            dur = float(item.get("dur", 0) or 0)
            if at < 0 or dur <= 0 or at + dur > total + 0.05:
                continue
            row = {"id": f"sticker-{i}", "track": "stickers", "type": "video",
                   "source": str(asset), "source_in": 0.0, "start": round(at, 3),
                   "duration": round(dur, 3), "role": "sticker",
                   "rule_id": f"STK-{i:02d}",
                   "reason": f"{item.get('icon', 'sticker')} 贴纸"}
            clips.append(row)
            stickers.append(row)

    if narration is not None:
        tracks.insert(5, {"name": "narration", "type": "audio", "label": "旁白"})

    audio = []
    for track, item, required in (("voice", voice, True), ("sfx", sfx, False),
                                  ("bgm", bgm, False), ("narration", narration, False)):
        if item is None:
            continue
        path, span = item
        if span <= 0:
            continue
        row = {"id": track, "track": track, "type": "audio",
               "source": str(path), "source_in": 0.0, "start": 0.0,
               "duration": round(float(span), 3), "role": track,
               "rule_id": f"AUD-{track.upper()}", "required": required,
               "reason": "草稿独立音轨"}
        clips.append(row)
        audio.append(row)

    texts = []
    spacing = float((cfg.get("jianying") or {}).get("line_spacing", 0.22))
    for i, cue in enumerate(captions, 1):
        texts.append({
            "id": f"text-{i}", "track": "captions", "type": "text",
            "content": str(cue["text"]), "start": round(float(cue["start"]), 3),
            "duration": round(float(cue["end"]) - float(cue["start"]), 3),
            "role": "caption", "rule_id": f"CAP-{i:02d}",
            "reason": "字幕计划", "line_spacing": spacing,
            "ranges": cue.get("ranges") or [],
        })

    native = [{"kind": x["kind"], "name": x["name"],
               "at": round(float(x["at"]), 3), "dur": round(float(x["dur"]), 3)}
              for x in fx_plans]

    return {
        "version": 1,
        "project": name,
        "canvas": {"width": int(cfg["canvas"]["width"]),
                   "height": int(cfg["canvas"]["height"]), "fps": fps},
        "duration": round(float(total), 3),
        "tracks": tracks,
        "clips": clips,
        "texts": texts,
        "native": native,
        "stickers": stickers,
        "audio": audio,
        "qa": {
            "min_main_segments": len(main_durations),
            "require_voice": voice is not None,
            "min_line_spacing": 0.12,
            "max_text_overlaps": 0,
            "require_stickers": len(stickers),
            "require_native": len(native),
            "planned_main_segments": len(plan_shots),
        },
    }
