"""渲染前预检：把草稿/包装/音频里能提前发现的结构错误，在 frames 前报掉。"""
from __future__ import annotations
import json
from pathlib import Path

from _common import load_config, project_paths, probe_media, resolve_duration
from workflow import broll, caption_plan


def check(project: Path) -> dict:
    p = project_paths(project)
    cfg = load_config(p["config"])
    total = resolve_duration(cfg, project)
    errors: list[str] = []
    warnings: list[str] = []

    try:
        plan = caption_plan.load(cfg, project)
    except (OSError, ValueError) as exc:
        return {"ok": False, "errors": [f"字幕/样式计划读不出来：{exc}"], "warnings": []}

    # 卡片与插图时窗
    card = cfg.get("card") or {}
    if card.get("enabled"):
        start, end = float(card.get("start") or 0), float(card.get("end") or 0)
        if end <= start or start < 0 or end > total + 0.05:
            errors.append(f"卡片区间 {start:.2f}–{end:.2f}s 越界（片长 {total:.2f}s）")
        for row in card.get("rows") or []:
            at = float(row.get("at") or 0)
            if at < start or at > end + 0.05:
                errors.append(f"卡片行“{row.get('main')}”at={at:.2f}s 不在卡段内")
    for item in ((plan.get("inserts") or {}).get("items") or []):
        if float(item.get("start", 0)) < 0 or float(item.get("end", 0)) > total + 0.05:
            errors.append(f"插图“{item.get('title')}”越界")

    # B-roll：复用正式解析器，错误一次报全
    broll_plans, broll_errors = broll.resolve(cfg, project, plan.get("cues") or [])
    errors.extend(broll_errors)

    # 草稿转场/特效：只算，不写盘
    fx_plans = []
    try:
        import make_jianying_draft as jy
        durations = jy.main_video_segments(cfg, project, total)
        segments, pos = [], 0.0
        for i, duration in enumerate(durations, 1):
            segments.append((f"preflight-{i}", pos, pos + duration))
            pos += duration
        fx_plans, fx_errors = jy.resolve_fx(cfg, segments, total)
        errors.extend(fx_errors)
    except Exception as exc:  # 预检不能因为单个导入失败而中断整轮
        warnings.append(f"草稿资源预检跳过：{type(exc).__name__}: {exc}")

    # 素材库引用 / B-roll / 字体：frames 前能解析的引用先解析，别等 audit 才发现
    try:
        from workflow import asset_library
        asset_errors, asset_warnings = asset_library.preflight_issues(cfg, project)
        errors.extend(asset_errors)
        warnings.extend(asset_warnings)
    except Exception as exc:  # 预检不能因为素材库损坏而整轮中断
        warnings.append(f"素材库预检跳过：{type(exc).__name__}: {exc}")

    # 音频长度：只在文件已存在时检查；云端/本地合成会在 music 步生成
    bgm = p["work"] / "bgm.wav"
    if bgm.is_file():
        try:
            duration = float(probe_media(bgm)["duration"])
            if abs(duration - total) > 0.25:
                errors.append(f"work/bgm.wav {duration:.2f}s 与片长 {total:.2f}s 不匹配")
        except Exception as exc:
            warnings.append(f"BGM 时长读不出来：{exc}")

    return {"ok": not errors, "errors": errors, "warnings": warnings,
            "broll": len(broll_plans), "fx": len(fx_plans)}
