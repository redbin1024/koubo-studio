"""字幕逐条样式计划：**一处算，两处读**。

成片 mp4 侧（`caption_layer.py`）和剪映草稿侧（`make_jianying_draft.py`）过去各自推导
「这条字幕长什么样」：草稿侧按序号循环 `ANIM_PLAN`，mp4 侧只认首句 hook，两边没有共同
真相。加了逐条样式之后，再各推一次必然漂移，所以这里算成一份 `work/style-plan.json`，
两个消费者只读它。

默认（没有指令、没有 styles、没选主题）时必须与加这套东西之前**逐条一致**：
第一条非跳过字幕照旧吃 hook，其余照旧 fade，字号/描边/投影/位置全部取 config 现值，
草稿侧的动画序号也照旧 `ANIM_PLAN[i % len]`。这条由 `tests/test_caption_plan.py` 锁住。

用法：
    from workflow.caption_plan import load, parse_cue_directives
    plan = load(cfg, project)          # 读，必要时重算并落盘
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from _common import CUE_DIRECTIVE_RE, parse_srt, write_json

PLAN_NAME = "style-plan.json"

# 指令里能写的键。写别的键就是畸形指令 —— 直接报错，不当字面文本渲染。
DIRECTIVE_KEYS = {"layout", "anim", "color"}

LAYOUTS = ("bottom", "center", "top", "side")
ANIMS = ("fade", "hook", "pop", "rise", "wipe", "karaoke")

# 剪映那侧只对齐它确实有的两种入场；其余动效在 mp4 里做，草稿照旧循环。
# 剪映命名空间里没有对应物时宁可退回默认，也不假装对齐（verify 会记 unchecked）。
JY_ANIM = {"hook": "弹入", "pop": "弹入", "rise": "弹入", "fade": "渐显",
           "wipe": "渐显", "karaoke": "渐显"}
ANIM_PLAN = ("弹入", "渐显", "渐显", "弹入", "弹入", "渐显", "渐显", "渐显", "渐显", "渐显", "弹入")


class CaptionPlanError(ValueError):
    """字幕指令或样式写错了 —— 这类错误必须炸出来，不能静默降级。"""


def parse_cue_directives(raw: str) -> tuple[dict, str]:
    """把 cue 第一行开头的 `{@style key=value ...}` 拆出来。

    返回 (指令, 去掉指令后的原文)。没有指令就返回 ({}, 原文)。
    畸形指令抛 CaptionPlanError —— 静默当字面文本会把「{@hero}」四个字符画到屏幕上。
    """
    text = raw.lstrip()
    if not text.startswith("{@"):
        return {}, raw
    match = CUE_DIRECTIVE_RE.match(text)
    if not match:
        raise CaptionPlanError(f"字幕指令没有闭合的 }}：{raw[:40]!r}")
    directive: dict = {}
    tokens = match.group(1).split()
    if not tokens:
        raise CaptionPlanError(f"字幕指令是空的：{raw[:40]!r}")
    for position, token in enumerate(tokens):
        # 第一个 token 不带 `=` 就是样式名（`{@hero …}`）；带 `=` 就是纯覆盖
        # （`{@layout=side …}`）。正则已经把 `{@` 吃掉，这里不再要求 token 带 `@`。
        if position == 0 and "=" not in token:
            if token.startswith("@"):
                raise CaptionPlanError(f"指令开头只写一次 @：{raw[:40]!r}")
            directive["style"] = token
            continue
        key, sep, value = token.partition("=")
        if key not in DIRECTIVE_KEYS:
            raise CaptionPlanError(
                f"不认得指令键 {key!r}；可用：{sorted(DIRECTIVE_KEYS)}")
        if not sep or not value:
            raise CaptionPlanError(f"指令键 {key!r} 需要写成 {key}=值")
        if key == "layout" and value not in LAYOUTS:
            raise CaptionPlanError(f"layout 只能是 {LAYOUTS}，收到 {value!r}")
        if key == "anim" and value not in ANIMS:
            raise CaptionPlanError(f"anim 只能是 {ANIMS}，收到 {value!r}")
        directive[key] = value
    return directive, text[match.end():].lstrip()


def _style_table(cap: dict) -> dict:
    """内置样式 + config 里自定义的样式，自定义可以覆盖内置。"""
    big = cap.get("big") or {}
    table = {
        "default": {},
        "big": {"layout": "center", "anim": "pop", "size": 132, "outline": 14,
                "shadow": 8, "tracking": 2.0, **big},
    }
    table.update({str(k): dict(v or {}) for k, v in (cap.get("styles") or {}).items()})
    return table


def srt_digest(path: Path) -> str:
    try:
        return hashlib.sha256(Path(path).read_bytes()).hexdigest()
    except OSError:
        return ""


def _reject_premiere_big(cue, style_name: str, big: bool) -> None:
    """大字卡不许压在片首 —— 那是「开头封面」的变体，房规禁的是这个。"""
    if (big or style_name == "big") and cue["start"] <= 0:
        raise CaptionPlanError(
            f"第 {cue['index']} 条大字卡的起始是 {cue['start']:.2f}s；"
            "房规不做开头封面，第一条大字卡必须晚于 0s")


def build_plan(cfg: dict, project: Path, srt: Path | None = None) -> dict:
    """算出逐条样式计划。纯计算，不落盘。"""
    from _common import project_paths
    cap = cfg["captions"]
    p = project_paths(project)
    srt = Path(srt) if srt else p["input"] / (cfg["input"]["subtitle"] or "captions.srt")
    skip = {int(i) for i in (cap.get("skip") or [])}
    styles = _style_table(cap)
    hook = cap["hook"]
    base = {
        "size": int(cap["size"]), "outline": int(cap["outline"]),
        "shadow": int(cap["shadow"]), "tracking": float(cap.get("spacing", 0) or 0),
        "max_width": int(cap["max_width"]), "margin_v": int(cap["margin_v"]),
        "layout": cap.get("layout") or "bottom",
    }
    cues, seen = [], 0
    for cue in parse_srt(srt):
        directive, cleaned = parse_cue_directives(cue["raw"])
        if cue["index"] in skip:
            continue
        name = directive.get("style", "default")
        if name not in styles:
            hint = (f"；{name} 是动效名，动效要写成 anim={name}"
                    if name in ANIMS else "")
            raise CaptionPlanError(
                f"第 {cue['index']} 条用了没定义的样式 {name!r}；"
                f"可用样式：{sorted(styles)}（动效写 anim=…）{hint}")
        look = dict(base)
        look.update(styles[name])
        for key in ("layout", "anim", "color"):
            if key in directive:
                look[key] = directive[key]
        big = name == "big" or bool(look.get("big"))
        _reject_premiere_big(cue, name, big)
        # 首句 hook 是既有行为：没写 anim 的第一条非跳过字幕照旧吃 hook。
        anim = look.get("anim") or ("hook" if (seen == 0 and hook.get("enabled")) else "fade")
        if anim == "hook":
            look["hook"] = hook
        if look["size"] > base["size"] and not big:
            look["max_width"] = int(cap["max_width"])
        # 淡入淡出沿用旧键；pop/rise/wipe 的位移时长用 anim_ms，两者别混。
        fade_in = int(look.get("anim_in_ms") or cap["fade_in_ms"])
        fade_out = int(look.get("anim_out_ms") or cap["fade_out_ms"])
        anim_ms = int(look.get("anim_in_ms") or
                       (cap["anim_ms"] if anim in ("pop", "rise", "wipe") else cap["fade_in_ms"]))
        cues.append({
            "index": cue["index"], "start": cue["start"], "end": cue["end"],
            "lines": [ln for ln in cleaned.split("|") if ln.strip()],
            "style": name, "big": big, "layout": look["layout"], "anim": anim,
            "fade_in_ms": fade_in, "fade_out_ms": fade_out, "anim_ms": anim_ms,
            "size": int(look["size"]), "outline": int(look["outline"]),
            "shadow": int(look["shadow"]), "tracking": float(look["tracking"]),
            "max_width": int(look["max_width"]), "margin_v": int(look["margin_v"]),
            "palette": dict(cap["palette"]),
            "jy_anim": JY_ANIM.get(anim, ANIM_PLAN[seen % len(ANIM_PLAN)]),
            "hook": look.get("hook"),
        })
        seen += 1
    return {"version": 1, "srt": srt.name, "srt_sha256": srt_digest(srt),
            "theme": cap.get("theme") or "",
            "inserts": resolve_inserts(cfg, cues, project), "cues": cues}


INSERT_KINDS = ("icon-label", "list", "stat", "quote")


def caption_band_top(cfg: dict) -> float:
    """字幕带的**保守**上沿（0–1 归一化高度）。

    按「允许的最多两行 + 当前字号」估，宁可估高：插图压到字幕上是最难在抽帧里
    发现的一类错，所以这条检查留余量，不留侥幸。
    """
    cap = cfg["captions"]
    size = int(cap["size"])
    pad = int(cap["outline"]) + int(cap["shadow"]) + max(4, size // 8)
    height = 2 * int(round(size * 1.30)) + 2 * pad
    return max(0.0, (cfg["canvas"]["height"] - int(cap["margin_v"]) - height)
               / cfg["canvas"]["height"])


def resolve_inserts(cfg: dict, cues: list[dict], project: Path | None = None) -> dict:
    """把插图配置解成「时间窗 + 框位 + 素材名」，并当场把违规的配置顶回去。

    三条硬规矩（不是建议）：
      1. 每条插图必须有据可依：要么由**真实存在的字幕关键词**触发，
         要么挂在**解说槽**上（那一句解说就是它的依据）；
      2. 框位不得越过字幕带的上沿；
      3. 时间窗不许越出它的触发范围。
    """
    from _common import caption_plain
    ins = cfg.get("inserts") or {}
    band_top = caption_band_top(cfg)
    if not ins.get("enabled"):
        return {"enabled": False, "items": [], "band_top": round(band_top, 4)}
    by_index = {cue["index"]: cue for cue in cues}
    slots = _narration_slot_spans(cfg, project) if project else []
    slots_with_lines = _slots_with_narration(project) if project else set()
    items = []
    for number, spec in enumerate(ins.get("items") or [], 1):
        kind = str(spec.get("kind") or "icon-label")
        if kind not in INSERT_KINDS:
            raise CaptionPlanError(f"第 {number} 条插图的 kind={kind!r} 不认得；可用 {list(INSERT_KINDS)}")
        trigger = spec.get("trigger") or {}
        keyword = ""
        if trigger.get("slot") is not None:
            # 挂在解说槽上：图形段与旁白同时出现，这句话就是它的依据。
            want = int(trigger["slot"])
            match = [span for span in slots if span[2] == want]
            if not match:
                raise CaptionPlanError(
                    f"第 {number} 条插图挂在解说槽 {want} 上，但镜头表里只有 {len(slots)} 个槽")
            if want not in slots_with_lines:
                raise CaptionPlanError(
                    f"第 {number} 条插图挂在解说槽 {want} 上，但 work/narration-lines.json 里"
                    "没有对应这一槽的解说；图形段要有旁白可配，不能凭空出现")
            span_start, span_end, _ = match[0]
            cue_start, cue_end, ref = span_start, span_end, f"槽 {want}"
        else:
            cue = by_index.get(int(trigger.get("cue", -1)))
            if cue is None:
                raise CaptionPlanError(
                    f"第 {number} 条插图的触发字幕 #{trigger.get('cue')} 不在当前字幕里")
            keyword = str(trigger.get("keyword") or "")
            plain = "".join(caption_plain(ln) for ln in cue["lines"])
            if not keyword or keyword not in plain:
                raise CaptionPlanError(
                    f"第 {number} 条插图的触发词 {keyword!r} 没有出现在第 {cue['index']} 条字幕"
                    f"（该条是「{plain}」）；插图必须由字幕触发，不做无据装饰")
            cue_start, cue_end, ref = cue["start"], cue["end"], f"字幕 #{cue['index']}"
        box = [float(v) for v in (spec.get("box") or ins["box"])]
        if len(box) != 4 or not (0 <= box[0] < box[2] <= 1 and 0 <= box[1] < box[3] <= 1):
            raise CaptionPlanError(f"第 {number} 条插图的 box 不是有效的归一化框：{box}")
        if box[3] > band_top + 1e-9:
            raise CaptionPlanError(
                f"第 {number} 条插图的下沿 {box[3]:.3f} 压进字幕带（上沿 {band_top:.3f}）；"
                "把 box 上移或调小 captions.size")
        start = float(spec.get("at", cue_start + 0.12))
        hold = float(spec.get("hold") or ins["hold"])
        end = start + hold
        if start < cue_start - 1e-9 or end > cue_end + 1e-9:
            raise CaptionPlanError(
                f"第 {number} 条插图 {start:.2f}–{end:.2f}s 超出它的触发范围"
                f"（{ref} {cue_start:.2f}–{cue_end:.2f}s）；改 hold 或换更长的一条")
        items.append({
            "index": number, "kind": kind, "asset": f"insert-{number}.png",
            "trigger_cue": by_index and (int(trigger["cue"]) if "cue" in trigger else None),
            "trigger_slot": int(trigger["slot"]) if "slot" in trigger else None,
            "keyword": keyword,
            "title": str(spec.get("title") or ""), "text": str(spec.get("text") or ""),
            "rows": [str(r) for r in (spec.get("rows") or [])],
            "icon": str(spec.get("icon") or "check"),
            "start": round(start, 3), "end": round(end, 3),
            "box": box, "layout": str(spec.get("layout") or ins["layout"]),
        })
    return {"enabled": True, "items": items, "band_top": round(band_top, 4)}


def _narration_slot_spans(cfg: dict, project: Path) -> list[tuple[float, float, int]]:
    from workflow.narration import narration_spans
    try:
        shots = json.loads((Path(project) / "work" / "edit-plan.json")
                           .read_text(encoding="utf-8"))["shots"]
    except (OSError, ValueError, KeyError, TypeError):
        return []
    return narration_spans(shots, int(cfg.get("canvas", {}).get("fps", 30)))


def _slots_with_narration(project: Path) -> set[int]:
    try:
        lines = json.loads((Path(project) / "work" / "narration-lines.json")
                           .read_text(encoding="utf-8"))["lines"]
    except (OSError, ValueError, KeyError, TypeError):
        return set()
    return {int(line["slot"]) for line in lines if isinstance(line, dict) and "slot" in line}


def load(cfg: dict, project: Path, srt: Path | None = None) -> dict:
    """读样式计划；缺失或与当前字幕对不上就重算并落盘（确定性，重算不会漂）。"""
    from _common import project_paths
    p = project_paths(project)
    target = p["work"] / PLAN_NAME
    fresh = build_plan(cfg, project, srt)
    try:
        cached = json.loads(target.read_text(encoding="utf-8"))
        if cached == fresh:
            return cached
    except (OSError, ValueError):
        pass
    write_json(target, fresh)
    return fresh


def main() -> None:
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from _common import load_config  # noqa: E402
    project = Path(sys.argv[1]).resolve()
    cfg = load_config(project / "config.json")
    plan = load(cfg, project)
    print(f"  {PLAN_NAME}：{len(plan['cues'])} 条"
          f"（样式 {sorted({c['style'] for c in plan['cues']})}）")


if __name__ == "__main__":
    main()
