"""参考片拆解：把三联图交给视觉模型，产出「有证据」的镜头记录与全片结构。

原则和本项目的导演层一致：

- **本地先能跑**：没有 Key 时这里不产出任何「看起来像分析」的空壳，镜头保持
  `unchecked` 并写清原因，交给 `reference_intake` 汇总；
- **模型只当证据解释器**：每条结论必须引用左/中/右格看到的具体差异；枚举值、
  镜头 id、置信度全部由代码校验，不合格就重试一次，再不合格就标 unchecked；
- **不编造**：不知道景别/运镜/品牌/人物身份就写 unknown，不补全未完成的动作。
"""
from __future__ import annotations

import base64
import json
import math
import urllib.error
import urllib.request
from pathlib import Path

from .visual_analysis import ENDPOINT, api_key_from_env


SHOT_SIZES = ("大特写", "特写", "近景", "中景", "中全景", "全景", "远景", "unknown")
CAMERAS = ("固定", "推", "拉", "摇", "移", "跟", "升降", "手持", "环绕", "unknown")
END_STATES = ("settled", "ongoing", "cutoff", "unknown")
TRANSITIONS = ("硬切", "叠化", "闪白", "划像", "遮挡", "unknown")
HOOK_ROLES = ("钩子", "展开", "证明", "转折", "CTA", "无")
BATCH = 3
MAX_LLM_SHOTS = 30
MAX_OVERVIEW_IMAGES = 6

SYSTEM = """你是口播 / 短视频参考片的拆解导演。你只解释给出的证据，不负责夸片，也不负责复刻。

EVIDENCE
- 每个镜头给一张三联图：左 = 切入后不久，中 = 中点，右 = 切出前。先读左 → 右的变化，再下结论。
- 只写图里看得到的：景别、运镜、主体、动作的起止状态、场景、光线、画面文字。
- 看不出就写 unknown。不要猜品牌、价格、人物身份、地点、镜头焦距或画外空间。
- 动作没在右格完成就写 ongoing / cutoff，不要替它补完。被遮住的东西不等于消失。
- on_screen_text 只抄清晰可读的字；模糊或没有就写「无」或 unknown。
- evidence 必须引用左 / 中 / 右格里看到的具体差异，一句话，不写空话。
- 如果没有提供音频转写，声音一律写「不确定」；有转写时只依据转写，不编造语气和音乐。
- 三个格子不像同一个连续机位时，hidden_cut 设为 true，并在 evidence 里说明差异。
输出严格 JSON 对象，不要 markdown 代码块。"""


def _shot_contract(ids: list[str]) -> str:
    return f"""只返回这些镜头，顺序一致，不多不少：{', '.join(ids)}。
{{
  "shots": [
    {{
      "id": "{ids[0]}",
      "shot_size": "大特写|特写|近景|中景|中全景|全景|远景|unknown",
      "camera": "固定|推|拉|摇|移|跟|升降|手持|环绕|unknown",
      "subject": "中文：画面主体",
      "action": "中文：从左格到右格实际发生的动作",
      "action_phases": ["中文：看得见的阶段，1-4 条"],
      "end_state": "settled|ongoing|cutoff|unknown",
      "scene": "中文：场景",
      "lighting": "中文：光线",
      "on_screen_text": "画面文字；没有写 无；看不清写 unknown",
      "transition": "硬切|叠化|闪白|划像|遮挡|unknown",
      "hook_role": "钩子|展开|证明|转折|CTA|无",
      "hidden_cut": false,
      "evidence": "中文：引用左/中/右格的具体差异",
      "confidence": 0.0
    }}
  ]
}}"""


def _overview_contract() -> str:
    return """{
  "overview": {
    "hook": "中文：前 3 秒靠什么抓住人（画面 + 台词）",
    "structure": "中文：叙事结构，如 痛点→展示→对比→促单",
    "visual_style": "中文：画面风格、色调、质感、版式",
    "rhythm": "中文：剪辑节奏、镜头长度分配、转场习惯",
    "audio": "中文：口播/对白说了什么、谁在说、在叙事里的作用；没有转写写 不确定",
    "why_it_works": ["中文爆点 1", "中文爆点 2", "中文爆点 3"],
    "adaptation": ["中文：如果要借鉴，保留什么、改什么、哪几段是重点"],
    "target_audience": "中文：从内容能看出的受众；看不出写 不确定"
  }
}"""


class VisionError(RuntimeError):
    """拆解调用失败；调用方据此把镜头标成 unchecked，而不是假装分析过。"""


def _strip_text(value, limit: int) -> str:
    return str(value or "").strip()[:limit]


def validate_overview(payload: dict) -> dict:
    if not isinstance(payload, dict):
        raise ValueError("全片拆解不是 JSON 对象")
    data = payload.get("overview")
    if not isinstance(data, dict):
        raise ValueError("缺少 overview 对象")
    for key in ("hook", "structure", "visual_style", "rhythm"):
        if not _strip_text(data.get(key), 2000):
            raise ValueError(f"overview.{key} 不能为空")
    audio = _strip_text(data.get("audio"), 2000) or "不确定"
    works = data.get("why_it_works")
    if not isinstance(works, list) or not 1 <= len(works) <= 6:
        raise ValueError("overview.why_it_works 必须是 1-6 条数组")
    works = [_strip_text(x, 300) for x in works if _strip_text(x, 300)]
    if not works:
        raise ValueError("overview.why_it_works 不能全是空字符串")
    adaptation = data.get("adaptation")
    if adaptation is None:
        adaptation = []
    if not isinstance(adaptation, list):
        raise ValueError("overview.adaptation 必须是数组")
    adaptation = [_strip_text(x, 300) for x in adaptation if _strip_text(x, 300)]
    return {
        "hook": _strip_text(data.get("hook"), 2000),
        "structure": _strip_text(data.get("structure"), 2000),
        "visual_style": _strip_text(data.get("visual_style"), 2000),
        "rhythm": _strip_text(data.get("rhythm"), 2000),
        "audio": audio,
        "why_it_works": works[:6],
        "adaptation": adaptation[:8],
        "target_audience": _strip_text(data.get("target_audience"), 500) or "不确定",
    }


def validate_shot_payload(payload: dict, ids: list[str]) -> dict[str, dict]:
    if not isinstance(payload, dict):
        raise ValueError("镜头拆解不是 JSON 对象")
    entries = payload.get("shots")
    if not isinstance(entries, list):
        raise ValueError("缺少 shots 数组")
    wanted = set(ids)
    result: dict[str, dict] = {}
    for entry in entries:
        if not isinstance(entry, dict):
            raise ValueError("shots 里有非对象条目")
        ident = str(entry.get("id") or "")
        if ident not in wanted or ident in result:
            raise ValueError(f"未知或重复的镜头 id：{ident!r}")
        size = _strip_text(entry.get("shot_size"), 20)
        camera = _strip_text(entry.get("camera"), 20)
        end_state = _strip_text(entry.get("end_state"), 20)
        transition = _strip_text(entry.get("transition"), 20)
        role = _strip_text(entry.get("hook_role"), 20)
        if size not in SHOT_SIZES:
            raise ValueError(f"{ident}.shot_size 不在枚举里：{size}")
        if camera not in CAMERAS:
            raise ValueError(f"{ident}.camera 不在枚举里：{camera}")
        if end_state not in END_STATES:
            raise ValueError(f"{ident}.end_state 不在枚举里：{end_state}")
        if transition not in TRANSITIONS:
            raise ValueError(f"{ident}.transition 不在枚举里：{transition}")
        if role not in HOOK_ROLES:
            raise ValueError(f"{ident}.hook_role 不在枚举里：{role}")
        confidence = entry.get("confidence")
        if isinstance(confidence, bool) or not isinstance(confidence, (int, float)):
            raise ValueError(f"{ident}.confidence 必须是数值")
        if not math.isfinite(confidence) or not 0 <= confidence <= 1:
            raise ValueError(f"{ident}.confidence 超出 0-1")
        evidence = _strip_text(entry.get("evidence"), 500)
        if not evidence:
            raise ValueError(f"{ident}.evidence 不能为空；没有证据就不该下结论")
        phases = entry.get("action_phases")
        if not isinstance(phases, list) or not phases:
            raise ValueError(f"{ident}.action_phases 必须列出看得见的阶段")
        phases = [_strip_text(x, 160) for x in phases if _strip_text(x, 160)]
        if not phases:
            raise ValueError(f"{ident}.action_phases 不能全是空字符串")
        result[ident] = {
            "shot_size": size,
            "camera": camera,
            "subject": _strip_text(entry.get("subject"), 300) or "unknown",
            "action": _strip_text(entry.get("action"), 500) or "unknown",
            "action_phases": phases[:6],
            "end_state": end_state,
            "scene": _strip_text(entry.get("scene"), 300) or "unknown",
            "lighting": _strip_text(entry.get("lighting"), 300) or "unknown",
            "on_screen_text": _strip_text(entry.get("on_screen_text"), 300) or "无",
            "transition": transition,
            "hook_role": role,
            "hidden_cut": bool(entry.get("hidden_cut")),
            "evidence": evidence,
            "confidence": round(float(confidence), 3),
        }
    missing = [ident for ident in ids if ident not in result]
    if missing:
        raise ValueError("漏掉了镜头：" + "、".join(missing))
    return result


def _parse_json(text: str) -> dict:
    raw = str(text or "").strip()
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[1] if "\n" in raw else raw
        raw = raw.rsplit("```", 1)[0].strip()
    if raw.lower().startswith("json"):
        raw = raw[4:].lstrip()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"模型没有返回合法 JSON：{exc}") from exc
    if not isinstance(data, dict):
        raise ValueError("模型返回的不是 JSON 对象")
    return data


def _http_transport(body: dict, key: str) -> dict:
    payload = json.dumps(body, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        ENDPOINT, data=payload, method="POST",
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=180) as response:
            return json.load(response)
    except urllib.error.HTTPError as exc:
        detail = ""
        try:
            detail = exc.read().decode("utf-8", "replace")[:300]
        except OSError:
            pass
        raise VisionError(f"拆解接口 HTTP {exc.code}：{detail}") from exc
    except (urllib.error.URLError, TimeoutError) as exc:
        raise VisionError(f"拆解接口连不上：{exc}") from exc


def _chat(messages: list[dict], *, key: str, model: str, transport,
          max_tokens: int) -> tuple[dict, dict]:
    body = {
        "model": model,
        "temperature": 0.2,
        "max_tokens": max_tokens,
        "response_format": {"type": "json_object"},
        "messages": messages,
    }
    response = transport(body, key)
    try:
        text = response["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise VisionError("拆解接口返回的结构不符合约定") from exc
    usage = response.get("usage") if isinstance(response, dict) else None
    return _parse_json(text), usage if isinstance(usage, dict) else {}


def _image_block(path: Path) -> dict:
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return {"type": "image_url",
            "image_url": {"url": "data:image/jpeg;base64," + encoded, "detail": "low"}}


def _shot_batch_messages(batch: list[dict], out_dir: Path, *, transcript: str,
                         meta: dict) -> list[dict]:
    content: list[dict] = [{
        "type": "text",
        "text": ("逐镜头拆解。三联图里左/中/右分别对应下面的三个时间点；"
                 "先读变化再写，证据不足写 unknown。\n"
                 + _shot_contract([shot["id"] for shot in batch])),
    }]
    if meta.get("title"):
        content.append({"type": "text",
                        "text": f"作品标题（只作背景，不可当画面证据）：{meta['title'][:300]}"})
    if transcript:
        content.append({"type": "text",
                        "text": "口播转写（唯一的声音证据）：\n" + transcript[:1200]})
    for shot in batch:
        times = shot.get("strip_times") or []
        stamp = "/".join(f"{float(t):.2f}s" for t in times) if times else "未知"
        content.append({"type": "text",
                        "text": f"{shot['id']} 全片 {shot['start']:.2f}-{shot['end']:.2f}s"
                                f"（时长 {shot['duration']:.2f}s），三联图时间点 {stamp}："})
        path = out_dir / str(shot.get("strip") or "")
        if not path.is_file():
            raise VisionError(f"{shot['id']} 的 strip 不存在：{path}")
        content.append(_image_block(path))
    return [{"role": "system", "content": SYSTEM},
            {"role": "user", "content": content}]


def _overview_messages(shots: list[dict], out_dir: Path, *, meta: dict,
                       pacing: dict | None, transcript: str) -> list[dict]:
    content: list[dict] = [{
        "type": "text",
        "text": ("读完整条参考片后做全片拆解。只看给出的抽帧和转写，"
                 "不要复述分镜表，要解释它为什么成立。\n" + _overview_contract()),
    }]
    facts = []
    if meta.get("title"):
        facts.append(f"标题：{meta['title'][:400]}")
    if meta.get("author"):
        facts.append(f"作者：{meta['author']}")
    if pacing:
        facts.append(f"镜头数：{pacing.get('shot_count')}，每分钟切点："
                     f"{pacing.get('cuts_per_minute')}，中位镜头长度："
                     f"{pacing.get('median_shot_duration')}s")
    if facts:
        content.append({"type": "text", "text": "\n".join(facts)})
    content.append({"type": "text", "text": "分镜表：\n" + "\n".join(
        f"{s['id']} {s['start']:.2f}-{s['end']:.2f}s" for s in shots)})
    if transcript:
        content.append({"type": "text", "text": "口播转写：\n" + transcript[:1500]})
    else:
        content.append({"type": "text", "text": "没有音频转写：声音相关结论写「不确定」。"})
    picks = shots if len(shots) <= MAX_OVERVIEW_IMAGES else [
        shots[round(i * (len(shots) - 1) / (MAX_OVERVIEW_IMAGES - 1))]
        for i in range(MAX_OVERVIEW_IMAGES)]
    for shot in picks:
        path = out_dir / str(shot.get("strip") or "")
        if path.is_file():
            content.append({"type": "text", "text": f"{shot['id']}："})
            content.append(_image_block(path))
    return [{"role": "system", "content": SYSTEM},
            {"role": "user", "content": content}]


def _merge_usage(total: dict, usage: dict) -> None:
    for key, value in (usage or {}).items():
        if isinstance(value, (int, float)):
            total[key] = total.get(key, 0) + value


def analyze(shots: list[dict], out_dir: str | Path, *, api_key: str | None = None,
            model: str = "deepseek-flash", transport=None, pacing: dict | None = None,
            transcript: str = "", meta: dict | None = None,
            max_shots: int = MAX_LLM_SHOTS, log=print) -> dict:
    """拆解可用的镜头；单批失败只影响那几镜，整体结论仍可交付。"""
    key = api_key if api_key is not None else api_key_from_env()
    if not key:
        raise VisionError("缺少 DEEPSEEK_API_KEY：未调用视觉拆解")
    ready = [s for s in shots if s.get("strip") and s.get("status") == "ok"]
    if len(ready) > max_shots:
        # 均匀取样覆盖全片，别只拆前 30 镜而漏掉结尾的 CTA。
        picks = [round(i * (len(ready) - 1) / (max_shots - 1))
                 for i in range(max_shots)] if max_shots > 1 else [0]
        usable = [ready[i] for i in picks]
    else:
        usable = ready
    if not usable:
        raise VisionError("没有可用的三联图，未调用视觉拆解")
    send = transport or _http_transport
    out = Path(out_dir)
    meta = meta or {}
    result: dict = {"status": "ok", "overview": None, "shots": {},
                    "warnings": [], "usage": {}}

    # 全片结构：先用一张总览，再用明确的镜头表约束它别乱编。
    try:
        payload, usage = _chat(_overview_messages(usable, out, meta=meta, pacing=pacing,
                                                  transcript=transcript),
                               key=key, model=model, transport=send, max_tokens=3200)
        result["overview"] = validate_overview(payload)
        _merge_usage(result["usage"], usage)
    except (VisionError, ValueError) as exc:
        result["warnings"].append(f"全片结构拆解失败：{exc}")
        result["status"] = "partial"

    for offset in range(0, len(usable), BATCH):
        batch = usable[offset:offset + BATCH]
        ids = [shot["id"] for shot in batch]
        messages = _shot_batch_messages(batch, out, transcript=transcript, meta=meta)
        error = None
        for attempt in range(2):
            try:
                payload, usage = _chat(messages, key=key, model=model,
                                       transport=send, max_tokens=4000)
                analyzed = validate_shot_payload(payload, ids)
                _merge_usage(result["usage"], usage)
                result["shots"].update(analyzed)
                error = None
                break
            except (VisionError, ValueError) as exc:
                error = exc
                if attempt == 0 and not isinstance(exc, VisionError):
                    messages = messages + [{
                        "role": "user",
                        "content": f"上一次输出不合格：{exc}。请严格按契约重写，只返回 JSON。",
                    }]
                    log(f"    {ids[0]}…{ids[-1]} 输出不合格，重试一次：{exc}")
        if error is not None:
            result["status"] = "partial"
            result["warnings"].append(f"{ids[0]}…{ids[-1]} 拆解失败：{error}")
            for ident in ids:
                result["shots"].setdefault(ident, {"unchecked": True,
                                                   "reason": str(error)})
    if result["overview"] is None and not result["shots"]:
        result["status"] = "unchecked"
    return result
