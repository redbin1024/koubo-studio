#!/usr/bin/env python3
"""按视频内容匹配 talking-head-motion 的固定风格，输出“可参考的改编方案”。

只读取外部 catalog/recipes，不复制配方/素材；不把推荐当成已实现。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _common import load_config, project_paths  # noqa: E402

NATIVE = {"d06_frosted_chapter", "d08_glass_stack", "d11_punch_caption",
          "d14_collage_cards", "d19_corner_keywords", "d28_marker_sweep",
          "d22_chart_overlay"}
OVERLAY = {"d13_cutout_outline", "d15_behind_type", "d18_radial_orbit",
           "d24_concept_presenter", "d25_behind_type", "d27_wavy_frame",
           "d29_cutout_outline"}
COMPLEX = {"d20_mosaic_relay", "d21_shatter_type", "d26_film_frame", "d30_gallery_focus"}
ACTIONS = {
    "d01_three_band": "三段式人物/信息带；需要人物分层或遮罩",
    "d02_word_tiles": "逐字方块落位；字幕/标题逐字入场",
    "d03_evidence_over_speaker": "上方证据、下方人物；需要真实截图/素材",
    "d04_orbit_title": "弧字/圆窗；CapCut 需路径关键帧",
    "d05_focus_pip": "虚焦背景 + 人物小窗；需要抠像或双层",
    "d06_frosted_chapter": "毛玻璃章节卡：标题 + Part 标签，回到人物",
    "d07_iris_mask": "缩圈/圆形遮罩转场",
    "d08_glass_stack": "暗玻璃三卡递进：卡行逐项揭示 + 轻扫光",
    "d09_editorial_type": "衬线层级大字 + 聚光开场",
    "d10_sticker_label": "错位双色贴纸标签",
    "d11_punch_caption": "关键词重击：字幕缩放/弹入 + 音效",
    "d12_type_depth": "文字墙/步骤卡；需要分层排版",
    "d13_cutout_outline": "人物抠像描边；必须 HTML overlay",
    "d14_collage_cards": "三联卡/拼贴；需要 3 张真实图",
    "d15_behind_type": "人物前景 + 背后大字；必须动态 alpha",
    "d16_floating_frame": "黑网格人物窗 + 群体图标",
    "d17_mask_reveal": "矩形遮罩/素材开合；CapCut 蒙版可做",
    "d18_radial_orbit": "放射轨道入场；必须 overlay",
    "d19_corner_keywords": "四角重点词；需要 4 个短词",
    "d20_mosaic_relay": "六格接力/多人物副本；复杂",
    "d21_shatter_type": "字幕碎片爆开；复杂 overlay",
    "d22_chart_overlay": "趋势图卡；需要真实数据",
    "d23_split_crack": "裂屏转折；需要分屏/遮罩",
    "d24_concept_presenter": "人物描边 + 概念剪影；overlay",
    "d25_behind_type": "橙金大字置人物背后；overlay",
    "d26_film_frame": "胶片框/关键帧；复杂",
    "d27_wavy_frame": "波浪相框 + 前景人物；overlay",
    "d28_marker_sweep": "重点词色带划过：单个关键词强调",
    "d29_cutout_outline": "描边人物入场；overlay",
    "d30_gallery_focus": "缩略图聚光追踪；复杂",
}


def _read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_styles(catalog_path: Path) -> list[dict]:
    catalog = _read(catalog_path)
    out = []
    for row in catalog.get("styles") or []:
        recipe_path = (catalog_path.parent / row["recipe"]).resolve()
        if not recipe_path.is_file():
            continue
        if row.get("recipe_sha256") and _sha(recipe_path) != row["recipe_sha256"]:
            continue
        recipe = _read(recipe_path)
        out.append({**row, "recipe": recipe, "recipe_path": str(recipe_path)})
    return out


def _content_text(project: Path) -> str:
    p = project_paths(project)
    srt = p["input"] / (load_config(p["config"])["input"].get("subtitle") or "captions.srt")
    try:
        return srt.read_text(encoding="utf-8")
    except OSError:
        return ""


def _features(text: str, cfg: dict, project: Path) -> dict:
    plain = re.sub(r"\[\[|\]\]|\{@[^}]+\}", "", text)
    cues = max(1, len(re.findall(r"^\d+\s*$", text, re.M)))
    plain = re.sub(r"^\d+\s*$", "", plain, flags=re.M)
    plain = re.sub(r"^\d\d:\d\d:\d\d[,.]\d+ --> .*$", "", plain, flags=re.M)
    shots = 0
    try:
        plan = json.loads((project / "work" / "edit-plan.json").read_text(encoding="utf-8"))
        shots = len(plan.get("shots") or [])
    except (OSError, ValueError):
        pass
    return {
        "cues": cues,
        "shots": shots,
        "shots_per_min": round(shots / max(1.0, float(cfg.get("duration") or 1)) * 60, 1),
        "steps": bool(re.search(r"第一|第二|第三|首先|然后|最后|步骤|三点|三个|细节|清单", plain)),
        "details": bool(re.search(r"细节|一份份|这些|几件|三件", plain)),
        "numbers": bool(re.search(r"\d|百分之|倍|小时|天|年", plain)),
        "compare": bool(re.search(r"不是|而是|之前|之后|对比|区别|改变", plain)),
        "emotion": bool(re.search(r"安心|安稳|温柔|相信|陪伴|放心|感动|妈妈|宝宝|家|照护|接应|扶", plain)),
        "hook": bool(re.search(r"很多人问|为什么|你知道吗|其实|答案|这一趟|不用你|有人", plain)),
        "brand": bool(re.search(r"多萌|月子中心|预约|品牌", plain)),
        "keywords": len(re.findall(r"\[\[[^\]]+\]\]", text)),
        "card_skin": str(((cfg.get("card") or {}).get("theme") or {}).get("skin") or ""),
        "illustrations": len(list((project / "assets" / "illustrations").glob("*.png")))
                         if (project / "assets" / "illustrations").is_dir() else 0,
        "text": plain[:4000],
    }


def _score(style: dict, f: dict) -> tuple[float, list[str], list[str]]:
    recipe = style["recipe"]
    grammar = str((recipe.get("basic_implementation") or {}).get("grammar") or "")
    semantic = " ".join(recipe.get("semantic_use") or []) + " " + str(recipe.get("name") or "")
    observed = str(recipe.get("observed_motion") or "")
    text = f["text"]
    score, fit, risk = 0.0, [], []
    # content signals
    if f["steps"] and grammar in {"d06_frosted_chapter", "d08_glass_stack",
                                  "d12_type_depth", "d14_collage_cards"}:
        score += 5; fit.append("内容含步骤/清单，适合卡片递进")
    if f.get("details") and grammar in {"d08_glass_stack", "d06_frosted_chapter",
                                        "d14_collage_cards"}:
        score += 4; fit.append("内容以细节清单为主，适合三卡/章节")
    if f.get("card_skin") == "glass" and grammar == "d08_glass_stack":
        score += 6; fit.append("项目已有玻璃卡版式，d08 可直接复用")
    if grammar == "d14_collage_cards" and f.get("illustrations", 0) < 3:
        score -= 3; risk.append("d14 需要至少 3 张真实图/插画")
    if f["numbers"] and grammar in {"d22_chart_overlay", "d03_evidence_over_speaker"}:
        score += 3; fit.append("内容含数字/证据，适合图表/证据画面")
    if f["compare"] and grammar in {"d23_split_crack", "d14_collage_cards"}:
        score += 3; fit.append("内容含前后/对比，适合分屏或拼贴")
    if f["emotion"] and grammar in {"d01_three_band", "d09_editorial_type",
                                    "d13_cutout_outline", "d19_corner_keywords"}:
        score += 2; fit.append("内容偏情绪/人物，适合人物主导版式")
    if f["hook"] and grammar in {"d02_word_tiles", "d11_punch_caption"}:
        score += 3; fit.append("开头有钩子，适合逐字/关键词重击")
    if f["brand"] and grammar in {"d19_corner_keywords", "d28_marker_sweep"}:
        score += 2; fit.append("品牌/关键词明确，适合重点词强调")
    # semantic keyword overlap (bigrams)
    for token in set(re.findall(r"[\u4e00-\u9fff]{2,4}", semantic + observed)):
        if token in text:
            score += 1
    # readiness / engine
    readiness = str((style.get("readiness") or {}).get("status") or "")
    if readiness.startswith("partial"):
        score += 3; fit.append("已有部分原生窗口验证")
    elif readiness.startswith("mechanism"):
        score -= 1; risk.append("目前只有机制演示，不是完整风格")
    if grammar in OVERLAY:
        score -= 2; risk.append("需要动态抠像/overlay，不能直接用 CapCut 原生")
    elif grammar in COMPLEX:
        score -= 1; risk.append("多人物/复杂运动，工程量大")
    elif grammar in NATIVE:
        score += 1; fit.append("CapCut 原生可近似实现")
    if f["shots_per_min"] > 25 and grammar in {"d20_mosaic_relay", "d11_punch_caption",
                                              "d02_word_tiles"}:
        score += 2; fit.append("快节奏蒙太奇，适合短切/逐字")
    return score, fit, risk


def match(project: Path, catalog: Path, limit: int = 5) -> dict:
    cfg = load_config(project_paths(project)["config"])
    text = _content_text(project)
    if not text.strip():
        raise SystemExit("没有 input/字幕，无法按内容匹配")
    f = _features(text, cfg, project)
    styles = load_styles(catalog)
    rows = []
    for style in styles:
        score, fit, risk = _score(style, f)
        recipe = style["recipe"]
        grammar = str((recipe.get("basic_implementation") or {}).get("grammar") or "")
        engine = "overlay" if grammar in OVERLAY else ("hard" if grammar in COMPLEX else "capcut")
        rows.append({
            "id": style["id"], "name": style.get("name"), "version": style.get("version"),
            "readiness": (style.get("readiness") or {}).get("status"),
            "grammar": grammar, "score": round(score, 2), "engine": engine,
            "fit": fit[:4], "risk": risk[:3],
            "action": ACTIONS.get(grammar, "需要人工改写该风格的版式/动作"),
            "source": (recipe.get("source") or {}).get("url"),
        })
    rows.sort(key=lambda x: (-x["score"], x["id"]))
    return {"version": 1, "project": str(project), "features": f,
            "catalog": str(catalog), "matches": rows[:limit]}


def main() -> None:
    ap = argparse.ArgumentParser(description="按内容匹配 talking-head-motion 风格（只读外部配方）")
    ap.add_argument("project")
    ap.add_argument("--catalog", required=True, help="talking-head-motion/assets/fixed-styles/catalog.json")
    ap.add_argument("--limit", type=int, default=5)
    ap.add_argument("--out", help="写入 JSON")
    a = ap.parse_args()
    result = match(Path(a.project).resolve(), Path(a.catalog).resolve(), a.limit)
    text = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if a.out:
        Path(a.out).write_text(text, encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
