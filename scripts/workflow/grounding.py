"""Strict on-screen claim grounding: visible brand/claim words must be spoken.

ASR errors are possible; this is why a missing transcript is `unchecked`, not `pass`.
"""
from __future__ import annotations
import json, re
from pathlib import Path
from _common import load_config, project_paths

# 会伤害信任的词：品牌/承诺/到店转化。命中却没在口播里出现，就不能上屏。
CLAIM_TOKENS = ("多萌", "哆萌", "十月", "预约", "参观", "品牌", "保证", "唯一",
                "百分百", "第一品牌", "最专业", "国家级")


def _transcript(project: Path) -> str:
    for rel in ("work/transcript.json", "input/transcript.json"):
        try:
            data = json.loads((project / rel).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if data.get("text"):
            return str(data["text"])
        if data.get("words"):
            return "".join(str(w.get("text") or "") for w in data["words"])
    return ""


def _visible(cfg: dict, project: Path) -> str:
    parts: list[str] = []
    srt = project_paths(project)["input"] / "captions.srt"
    try:
        parts.append(re.sub(r"\[\[|\]\]|\{@[^}]+\}", "", srt.read_text(encoding="utf-8")))
    except OSError:
        pass
    card = cfg.get("card") or {}
    parts.extend([card.get("title"), (card.get("theme") or {}).get("footnote")])
    for row in card.get("rows") or []:
        parts.extend([row.get("main"), row.get("sub")])
    for item in (cfg.get("inserts") or {}).get("items") or []:
        parts.extend([item.get("title"), item.get("text")])
    parts.append((cfg.get("gold") or {}).get("text"))
    return " ".join(str(x) for x in parts if x)


def check(cfg: dict, project: Path) -> tuple[bool | None, str]:
    transcript = _transcript(project).replace(" ", "")
    if not transcript:
        return None, "没有 work/transcript.json，无法核对品牌/承诺是否被口播"
    visible = _visible(cfg, project)
    missing = [tok for tok in CLAIM_TOKENS if tok in visible and tok not in transcript]
    if missing:
        return False, f"上屏出现未口播的品牌/承诺词：{'、'.join(missing)}"
    return True, "上屏品牌/承诺词均能在口播转写中找到"
