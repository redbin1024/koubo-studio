"""Evidence-linked story suggestions; never execute the model output directly."""
from __future__ import annotations

import json

from .visual_analysis import _http_transport, api_key_from_env


MOODS = {"calm", "upbeat", "warm", "tense", "none"}
STORY_RULES = (
    "你是视频剪辑策划。只能依据给定的视觉描述和真实口播文本，不能推断人物身份、"
    "未看到的动作或事件。仅返回 JSON 对象：order 为全部镜头 ID 恰好一次的排序；"
    "narration 为数组，元素 shot_id、text（不超过30字）、evidence（含当前镜头ID）；"
    "口播已有对应信息时旁白留空。music_mood 只能选 calm/upbeat/warm/tense/none。"
    "beats 为最多三个实际有视觉依据的节拍数组，每项含 shot_id 和 cue（wipe/reveal/cut），"
    "没有确切节拍时返回空数组。"
    "所有旁白是待审核建议，不要把推测当成事实。"
)


def validate_story(review: dict, payload: dict) -> dict:
    shots = review.get("shots", [])
    ids = [f"shot_{i}" for i in range(1, len(shots) + 1)]
    order = payload.get("order")
    if (not ids or not isinstance(order, list) or len(order) != len(ids) or
            any(not isinstance(item, str) for item in order) or set(order) != set(ids)):
        raise ValueError("故事方案的镜头顺序必须恰好覆盖每个镜头一次")
    mood = payload.get("music_mood")
    if mood not in MOODS:
        raise ValueError("未知的音乐情绪标签")
    beats = payload.get("beats", [])
    if not isinstance(beats, list) or len(beats) > 3:
        raise ValueError("音效节拍最多三个")
    beat_ids = set()
    for beat in beats:
        if not isinstance(beat, dict) or beat.get("shot_id") not in ids:
            raise ValueError("音效节拍引用未知镜头")
        if beat.get("shot_id") in beat_ids or beat.get("cue") not in ("wipe", "reveal", "cut"):
            raise ValueError("重复镜头或不支持的音效节拍")
        beat_ids.add(beat["shot_id"])
    lines = payload.get("narration")
    if not isinstance(lines, list):
        raise ValueError("旁白建议必须是数组")
    if review.get("mode") == "talking-head" and lines:
        # 口播不自动叠旁白是默认；唯一例外是**解说槽**镜头 —— 那里本来就没人在说话。
        # 判据是镜头的 kind，不是一个「允许旁白」的开关：开关是绕过，槽是事实。
        slots = {ids[i] for i, shot in enumerate(shots)
                 if (shot.get("kind") or "speech") == "narration-slot"}
        stray = [line for line in lines
                 if isinstance(line, dict) and line.get("shot_id") not in slots]
        if stray or not slots:
            raise ValueError("口播画面已有现场人声；旁白只能挂在解说槽（narration-slot）"
                             "镜头上，其余镜头不叠加旁白")
    starts = {}
    cursor = 0.0
    for ident in order:
        starts[ident] = round(cursor, 3)
        cursor += float(shots[ids.index(ident)]["duration"])
    narration, used = [], set()
    for line in lines:
        if not isinstance(line, dict):
            raise ValueError("旁白建议格式不正确")
        ident, text, evidence = line.get("shot_id"), line.get("text"), line.get("evidence")
        if ident not in starts or ident in used:
            raise ValueError("旁白引用未知或重复的镜头")
        if not isinstance(text, str) or not text.strip() or len(text.strip()) > 30:
            raise ValueError("旁白必须为 1-30 字的非空文本")
        if not isinstance(evidence, list) or ident not in evidence or not set(evidence) <= set(ids):
            raise ValueError("旁白缺少有效的对应画面证据")
        used.add(ident)
        narration.append({"shot_id": ident, "text": text.strip(), "evidence": evidence,
                          "start": starts[ident]})
    return {"status": "proposal", "review_required": True, "order": order,
            "narration": sorted(narration, key=lambda line: line["start"]),
            "music_mood": mood, "duration": round(cursor, 3),
            "beats": beats,
            "shot_refs": {ident: {"source": shot["source"], "in": shot["in"],
                                  "duration": shot["duration"]}
                          for ident, shot in zip(ids, shots)}}


def suggest_story(review: dict, transcript_text: str = "", *,
                  api_key: str | None = None, transport=None,
                  model: str = "deepseek-flash") -> dict:
    key = api_key if api_key is not None else api_key_from_env()
    if not key:
        raise ValueError("缺少 DEEPSEEK_API_KEY；未生成故事建议")
    if len(transcript_text) > 3000:
        raise ValueError("口播文本超过 3000 字，请拆分工程以免丢失内容")
    evidence = [{"id": f"shot_{i}", "duration": shot["duration"],
                 "description": shot["visual"]["description"],
                 "confidence": shot["visual"]["confidence"]}
                for i, shot in enumerate(review["shots"], 1)]
    body = {"model": model, "temperature": 0, "max_tokens": 2200,
            "response_format": {"type": "json_object"},
            "messages": [{"role": "system", "content": STORY_RULES},
                         {"role": "user", "content": json.dumps(
                             {"mode": review["mode"], "shots": evidence,
                              "spoken_text": transcript_text}, ensure_ascii=False)}]}
    response = (transport or _http_transport)(body, key)
    try:
        proposal = json.loads(response["choices"][0]["message"]["content"])
    except (KeyError, IndexError, TypeError, ValueError) as exc:
        raise ValueError("故事 API 未返回符合约定的 JSON") from exc
    return validate_story(review, proposal)
