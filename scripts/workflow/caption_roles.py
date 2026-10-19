"""字幕角色检查：底部字幕只保留一处；卡片/插图/品牌字不得逐句复述。

不是禁止所有非字幕文字：结构标题、对照栏名、图表单位、来源、品牌名可以独立存在；
但把正在讲的句子换个说法再放一遍，就是第二套字幕。这里给出可复核的 warning。
"""
from __future__ import annotations

import difflib
import re

MARKUP = re.compile(r"\[\[|\]\]")
PUNCT = re.compile(r"[\s，。！？、；：,.!?;:\"'“”‘’（）()《》【】\-—…·]+")


def normalize(text: str) -> str:
    return PUNCT.sub("", MARKUP.sub("", str(text or ""))).casefold()


def compare(overlay: str, caption: str) -> tuple[str, float] | None:
    a, b = normalize(overlay), normalize(caption)
    if len(a) < 2 or len(b) < 2:
        return None
    if a in b or b in a:
        return "duplicate", 1.0
    ratio = difflib.SequenceMatcher(None, a, b).ratio()
    if ratio >= 0.55:
        return "paraphrase", round(ratio, 3)
    return None


def audit(contract: dict, cues: list[dict], policy: str = "warn") -> dict:
    findings = []
    for beat in contract.get("beats") or []:
        if beat.get("kind") not in ("card", "insert", "gold"):
            continue
        start, end = float(beat.get("start", 0)), float(beat.get("end", 0))
        active = []
        for cue in cues:
            text = "".join(cue.get("lines") or [])
            if float(cue.get("start", 0)) < end and float(cue.get("end", 0)) > start:
                active.append((str(cue.get("index") or "?"), text))
        for text in beat.get("source_texts") or []:
            for cue_index, cue_text in active:
                hit = compare(str(text), cue_text)
                if hit:
                    kind, ratio = hit
                    findings.append({
                        "beat": beat.get("id"), "kind": beat.get("kind"),
                        "overlay": str(text), "caption_index": cue_index,
                        "caption": cue_text, "match": kind, "ratio": ratio,
                    })
    return {"version": 1, "policy": policy, "findings": findings,
            "note": "duplicate/paraphrase 都属于第二套字幕；品牌/结构标签需人工判断独立信息任务。"}
