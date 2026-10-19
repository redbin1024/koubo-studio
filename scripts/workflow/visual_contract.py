"""包装层视觉合同（Visual Contract）。

灵感来自 auto-edit-pro 的 visual-contract：不仅记录“有什么对象”，还要记录
“这个 beat 用什么语义结构、哪块可见、文字稳定读多久、动效机制是什么、依据是什么”。

它管的是**包装层**，不是粗剪：
  card        信息卡（detail-list）
  insert      插图（icon-label / list / stat / quote）
  gold        品牌字（brand-stamp）
  sticker     装饰贴纸（decorative）
  native      剪映原生特效/滤镜/转场（style-layer，只进草稿，需剪映导出的视觉证据）

本模块不判断审美；它只把可审计的声明先写下来，verify 检查声明是否合规、
visual-review 再用真实帧/片段做人工验收。
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from _common import project_paths, resolve_video
from workflow import caption_plan

STRUCTURES = {"detail-list", "icon-label", "list", "stat", "quote",
              "brand-stamp", "decorative", "style-layer"}
CLAIM_STATUS = {"speech", "brand", "owner-confirmed", "sourced", "estimate", "none"}


def _sha(path: Path) -> str:
    try:
        h = hashlib.sha256()
        with path.open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                h.update(block)
        return h.hexdigest()
    except OSError:
        return ""


def _region(box) -> list[float]:
    return [round(float(v), 4) for v in box]


def _asset(project: Path, rel: str, kind: str = "authored-graphic") -> dict:
    p = project_paths(project)["assets"] / rel
    return {"id": Path(rel).stem, "kind": kind, "path": str(p),
            "exists": p.is_file(), "sha256": _sha(p) if p.is_file() else ""}


def _read_window(start: float, end: float, enter: float = 0.30) -> dict:
    stable = min(end, start + max(0.0, enter))
    return {"start": round(stable, 3), "end": round(end, 3),
            "stable_text": stable < end,
            "description": "入场完成后保持文字稳定，直到元素退出"}


def build(cfg: dict, project: Path, total: float,
          native_plans: list[dict] | None = None,
          advanced_plans: list[dict] | None = None) -> dict:
    beats: list[dict] = []
    p = project_paths(project)

    card = cfg.get("card") or {}
    if card.get("enabled") and float(card.get("end", 0)) - float(card.get("start", 0)) > 0.05:
        rows = card.get("rows") or []
        last_at = max([float(r.get("at", card["start"])) for r in rows] or [float(card["start"])])
        assets = [_asset(project, "card-base.png")]
        if card.get("title"):
            assets.append(_asset(project, "card-title.png"))
        for i in range(1, len(rows) + 1):
            assets.append(_asset(project, f"card-row-{i}.png"))
            assets.append(_asset(project, f"card-icon-{i}.png"))
        beats.append({
            "id": "card-1", "kind": "card", "structure": "detail-list",
            "start": round(float(card["start"]), 3), "end": round(float(card["end"]), 3),
            "style_id": f"card-{(card.get('theme') or {}).get('skin', 'flat')}",
            "visible_feature": {"description": "信息卡底板 + 标题 + 行条目 + 图标",
                                "region": _region(card.get("box") or [0.1, 0.1, 0.9, 0.8])},
            "reading": _read_window(last_at, float(card["end"]), 0.30),
            "motion": {"mechanism": "wipe+row-enter", "phase": "semantic-completion",
                       "windows": [[round(float(card["start"]), 3), round(last_at + 0.30, 3)]],
                       "description": "卡框上浮/展开，行和图标依次入场，随后文字稳定"},
            "assets": assets,
            "claim_status": "speech",
            "evidence_refs": [],
            "source_texts": ([card.get("title")] if card.get("title") else [])
                            + [str(r.get("title") or "") for r in rows]
                            + [str(r.get("detail") or "") for r in rows]
                            + ([(card.get("theme") or {}).get("footnote")]
                               if (card.get("theme") or {}).get("footnote") else []),
            "native": False,
        })

    gold = cfg.get("gold") or {}
    if gold.get("enabled") and gold.get("text"):
        beats.append({
            "id": "gold-1", "kind": "gold", "structure": "brand-stamp",
            "start": round(float(gold["in"]), 3), "end": round(float(gold["out"]), 3),
            "style_id": "gold-brand",
            "visible_feature": {"description": "居中金色品牌字",
                                "region": [0.15, 0.30, 0.85, 0.65]},
            "reading": _read_window(float(gold["in"]), float(gold["out"]), 0.28),
            "motion": {"mechanism": "stamp", "phase": "semantic-completion",
                       "windows": [[round(float(gold["in"]), 3), round(min(float(gold["out"]), float(gold["in"]) + 0.5), 3)]],
                       "description": "品牌字放大落位后保持"},
            "assets": [_asset(project, "gold-flash.png")],
            "claim_status": "brand",
            "evidence_refs": [],
            "source_texts": [gold["text"]],
            "native": False,
        })

    ins = caption_plan.load(cfg, project).get("inserts") or {}
    if ins.get("enabled"):
        for item in ins.get("items") or []:
            text = f"{item.get('title', '')} {item.get('text', '')}".strip()
            beats.append({
                "id": f"insert-{item['index']}", "kind": "insert",
                "structure": "icon-label",
                "start": round(float(item["start"]), 3), "end": round(float(item["end"]), 3),
                "style_id": "editorial-insert",
                "visible_feature": {"description": "图标 + 标题 + 正文的横条插图",
                                    "region": _region(item["box"])},
                "reading": _read_window(float(item["start"]), float(item["end"]), 0.30),
                "motion": {"mechanism": "rise+fade", "phase": "semantic-completion",
                           "windows": [[round(float(item["start"]), 3), round(min(float(item["end"]), float(item["start"]) + 0.5), 3)]],
                           "description": "上浮淡入后保持文字稳定"},
                "assets": [_asset(project, str(item["asset"]))],
                "claim_status": "speech",
                "evidence_refs": [],
                "native": False,
                "source_text": text,
                "source_texts": [item.get("title") or "", item.get("text") or ""],
            })

    sticker_cfg = cfg.get("stickers") or {}
    if sticker_cfg.get("enabled"):
        for i, item in enumerate(sticker_cfg.get("items") or [], 1):
            asset = p["assets"] / f"sticker-{i}.png"
            if not asset.is_file():
                continue
            beats.append({
                "id": f"sticker-{i}", "kind": "sticker", "structure": "decorative",
                "start": round(float(item.get("at", 0)), 3),
                "end": round(float(item.get("at", 0)) + float(item.get("dur", 0)), 3),
                "style_id": "brand-sticker",
                "visible_feature": {"description": f"{item.get('icon', 'sticker')} 装饰图形",
                                    "region": [round(max(0.0, float(item.get("x", 0.5)) - 0.1), 3),
                                               round(max(0.0, float(item.get("y", 0.5)) - 0.1), 3),
                                               round(min(1.0, float(item.get("x", 0.5)) + 0.1), 3),
                                               round(min(1.0, float(item.get("y", 0.5)) + 0.1), 3)]},
                "reading": {"start": round(float(item.get("at", 0)), 3),
                            "end": round(float(item.get("at", 0)) + float(item.get("dur", 0)), 3),
                            "stable_text": False, "description": "装饰，不承载阅读信息"},
                "motion": {"mechanism": "fade", "phase": "sustained",
                           "windows": [[round(float(item.get("at", 0)), 3),
                                        round(float(item.get("at", 0)) + float(item.get("dur", 0)), 3)]],
                           "description": "贴纸在窗口内保持可见"},
                "assets": [_asset(project, f"sticker-{i}.png")],
                "claim_status": "none", "evidence_refs": [], "native": False,
                "draft_only": True,
            })

    for i, plan in enumerate(advanced_plans or [], 1):
        start, end = float(plan["start"]), float(plan["end"])
        mechanisms = []
        if plan.get("keyframes"):
            mechanisms.append("keyframe")
        if plan.get("mask_slug"):
            mechanisms.append("mask")
        if plan.get("mix_mode"):
            mechanisms.append("mix-mode")
        if plan.get("bg_blur"):
            mechanisms.append("bg-blur")
        if plan.get("filters"):
            mechanisms.append("filter")
        beats.append({
            "id": f"advanced-{i}", "kind": "advanced", "structure": "style-layer",
            "start": round(start, 3), "end": round(end, 3),
            "style_id": "advanced-shot-fx",
            "visible_feature": {"description": "镜头级关键帧/蒙版/混合模式/滤镜",
                                "region": [0.0, 0.0, 1.0, 1.0]},
            "reading": {"start": round(start, 3), "end": round(end, 3),
                        "stable_text": False, "description": "镜头运动/合成，不承载阅读"},
            "motion": {"mechanism": "+".join(mechanisms) or "advanced",
                       "phase": "sustained",
                       "windows": [[round(start, 3), round(end, 3)]],
                       "description": "由剪映渲染，mp4 预览不包含"},
            "assets": [], "claim_status": "none", "evidence_refs": [],
            "native": False, "draft_only": True,
            "visual_status": "requires-capcut-export",
        })

    for i, plan in enumerate(native_plans or [], 1):
        kind = str(plan.get("kind"))
        start = float(plan.get("at", 0))
        dur = float(plan.get("dur", 0))
        if kind not in ("effect", "filter", "transition"):
            continue
        beats.append({
            "id": f"native-{i}", "kind": "native", "structure": "style-layer",
            "start": round(start, 3), "end": round(start + dur, 3),
            "style_id": f"native-{kind}:{plan.get('name')}",
            "visible_feature": {"description": f"剪映原生{kind}：{plan.get('name')}",
                                "region": [0.0, 0.0, 1.0, 1.0]},
            "reading": {"start": round(start, 3), "end": round(start + dur, 3),
                        "stable_text": False, "description": "原生视觉效果；不改变文字阅读"},
            "motion": {"mechanism": "native", "phase": "sustained",
                       "windows": [[round(start, 3), round(start + dur, 3)]],
                       "description": "由剪映渲染，mp4 预览不包含"},
            "assets": [], "claim_status": "none", "evidence_refs": [],
            "native": True, "native_kind": kind, "native_name": plan.get("name"),
            "visual_status": "requires-capcut-export",
        })

    source = resolve_video(cfg, project)
    return {
        "version": 1,
        "project": {"name": cfg.get("name"), "duration": round(float(total), 3),
                    "source": str(source), "source_sha256": _sha(source)},
        "style_policy": {"name": "warm-brand", "mode": "curated",
                         "note": "不是 71 风格洗牌；品牌片用固定、克制的包装语言"},
        "beats": beats,
    }


def validate(contract: dict) -> list[str]:
    issues: list[str] = []
    if contract.get("version") != 1:
        issues.append("version 必须为 1")
    beats = contract.get("beats") or []
    if not beats:
        issues.append("没有任何包装 beat")
    seen = set()
    for beat in beats:
        bid = str(beat.get("id") or "?")
        if bid in seen:
            issues.append(f"{bid}: id 重复")
        seen.add(bid)
        if beat.get("structure") not in STRUCTURES:
            issues.append(f"{bid}: 未知 structure {beat.get('structure')!r}")
        if beat.get("claim_status") not in CLAIM_STATUS:
            issues.append(f"{bid}: 未知 claim_status {beat.get('claim_status')!r}")
        if beat.get("claim_status") == "sourced" and not beat.get("evidence_refs"):
            issues.append(f"{bid}: sourced 声明必须有 evidence_refs")
        start, end = float(beat.get("start", 0)), float(beat.get("end", 0))
        if end <= start:
            issues.append(f"{bid}: 时间窗口无效")
        region = (beat.get("visible_feature") or {}).get("region") or []
        if len(region) != 4 or not (0 <= region[0] < region[2] <= 1 and 0 <= region[1] < region[3] <= 1):
            issues.append(f"{bid}: visible region 无效")
        reading = beat.get("reading") or {}
        rs, re_ = float(reading.get("start", 0)), float(reading.get("end", 0))
        if re_ <= rs:
            issues.append(f"{bid}: reading 窗口无效")
        if beat.get("structure") not in ("decorative", "style-layer") and re_ - rs < 0.6:
            issues.append(f"{bid}: 稳定阅读窗口不足 0.6s")
        for asset in beat.get("assets") or []:
            if not asset.get("exists"):
                issues.append(f"{bid}: 缺素材 {asset.get('path')}")
        if beat.get("native") and beat.get("visual_status") != "requires-capcut-export":
            issues.append(f"{bid}: 原生资源必须标记 requires-capcut-export")
    return issues
