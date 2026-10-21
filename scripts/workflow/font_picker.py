"""按参考片分析选字体：本地字体库优先，emfont 在线库可扩展，AI 只做可校验的推荐。

流程：

    reference-profile.json / config / 字幕
        → 风格信号（科技/温暖/叙事/促销…）
        → 候选字体（本机 CJK 字体 + emfont 目录）
        → 本地打分预筛
        → DeepSeek 从闭集里选 1 款（可选）
        → 校验；失败回退本地打分
        → 可选应用：写 captions.font；emfont 字体按字幕文字生成子集并下载

三条硬规矩：

1. **不编造字体**：AI 只能返回候选里的 id，字重/授权也要在候选范围内。
2. **没有 Key 也能用**：本地信号打分给一个可解释的选择，不假装 AI 选过。
3. **换字体是风格参数变更**：项目有 `work/style-lock.json` 时默认不应用，
   需要新配方版本重新绑定，或显式 `--force` 并接受 `koubo style check` 红项。
"""
from __future__ import annotations

import datetime as _dt
import json
import math
import os
import re
import urllib.error
import urllib.request
from pathlib import Path

from _common import (
    FONT_SEARCH_DIRS, _index_dir, _weight_rank, find_font, font_display_name,
    has_cjk_glyphs, load_config, parse_srt, project_paths, write_json,
)
from . import emfont
from .visual_analysis import ENDPOINT, api_key_from_env

SCHEMA = "koubo-font-selection/1"
DEFAULT_MODEL = "deepseek-flash"
MAX_CANDIDATES = 36
MAX_LLM_TOKENS = 1400

CATEGORY_TAGS = {
    "sans": "黑体/无衬线", "serif": "宋体/衬线", "rounded": "圆体",
    "handwriting": "手写/楷体", "pixel": "像素/点阵",
    "monospace": "等宽", "decorative": "装饰", "unknown": "未分类",
}

# 参考片里出现这些词，就认为需要某类气质。
SIGNAL_WORDS = {
    "tech": ("科技", "数码", "人工智能", "赛博", "未来", "程序", "代码", "软件",
             "效率", "游戏", "电竞", "硬件", "评测", "ai", "code"),
    "warm": ("温暖", "治愈", "情感", "生活", "家庭", "陪伴", "亲子", "美食",
             "手作", "日常", "慢", "温柔"),
    "editorial": ("叙事", "纪实", "文化", "人文", "访谈", "故事", "品牌", "质感",
                  "高级", "极简", "电影", "审美", "记录"),
    "energy": ("搞笑", "综艺", "娱乐", "夸张", "快节奏", "挑战", "反差", "热点",
               "节奏", "炸", "整活"),
    "traditional": ("国风", "传统", "古典", "历史", "书法", "东方", "中式", "非遗"),
    "promo": ("电商", "促销", "带货", "折扣", "产品", "转化", "口播", "种草",
              "测评", "卖点"),
    "kids": ("儿童", "亲子", "可爱", "萌", "动画", "宝宝", "童话"),
    "luxury": ("高端", "奢侈", "时尚", "美妆", "精致", "品牌"),
    "news": ("新闻", "资讯", "科普", "知识", "干货", "教程", "方法", "步骤", "盘点"),
    "vlog": ("vlog", "旅行", "探店", "记录", "日常"),
}

CATEGORY_PREF = {
    "tech": {"sans", "monospace", "pixel"},
    "warm": {"rounded", "handwriting", "sans", "serif"},
    "editorial": {"serif", "sans"},
    "energy": {"sans", "rounded", "decorative"},
    "traditional": {"serif", "handwriting"},
    "promo": {"sans", "rounded"},
    "kids": {"rounded", "handwriting"},
    "luxury": {"serif", "sans"},
    "news": {"sans", "serif"},
    "vlog": {"rounded", "sans", "handwriting"},
}

CATEGORY_AVOID = {
    "tech": {"handwriting"},
    "news": {"pixel", "handwriting", "decorative"},
    "promo": {"handwriting", "pixel"},
    "luxury": {"pixel", "decorative"},
    "kids": {"pixel"},
    "editorial": {"pixel", "decorative"},
}

EMFONT_CATEGORY = {"sans-serif": "sans", "serif": "serif", "cursive": "handwriting",
                   "fantasy": "decorative", "monospace": "monospace"}

WEIGHT_NUMBERS = (
    ("extralight", 200), ("ultralight", 200), ("demilight", 350), ("semibold", 600),
    ("demibold", 600), ("extrabold", 800), ("extrablack", 900), ("thin", 100),
    ("light", 300), ("regular", 400), ("normal", 400), ("book", 400), ("medium", 500),
    ("bold", 700), ("heavy", 900), ("black", 900),
)

COMMON_CHARS = ("0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
                "，。！？、；：“”‘’（）《》〈〉…—·%+-/：￥$ ")

LICENSE_PERMISSIVE = ("ofl", "apache", "mit", "cc0", "公有领域", "免费商用", "sil",
                      "public domain", "cc-by")
LICENSE_RESTRICTED = ("nc", "非商业", "非商業", "个人使用", "個人使用", "不可商用",
                      "禁用商业", "仅限学习")


class FontPickerError(RuntimeError):
    """选字体失败；消息要能直接告诉用户下一步做什么。"""


# ------------------------------------------------------------------ 小工具

def _now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).astimezone().isoformat(timespec="seconds")


def _read_json(path: Path) -> dict | None:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _slug(value: str) -> str:
    text = re.sub(r"[^a-z0-9\u3400-\u9fff]+", "-", str(value).casefold()).strip("-")
    return text[:60] or "font"


def weight_number(style: str) -> int:
    text = str(style or "").casefold()
    match = re.search(r"\bw([0-9])\b", text)
    if match:
        return min(900, 100 + int(match.group(1)) * 100)
    for key, number in WEIGHT_NUMBERS:
        if key in text:
            return number
    return 400


def infer_category(name: str, tags=()) -> str:
    blob = (str(name) + " " + " ".join(str(t) for t in tags or [])).casefold()
    if any(k in blob for k in ("像素", "pixel", "bitmap", "点阵")):
        return "pixel"
    if any(k in blob for k in ("圆", "maru", "rounded")):
        return "rounded"
    if any(k in blob for k in ("楷", "手写", "hand", "script", "行书", "草书", "cursive")):
        return "handwriting"
    if any(k in blob for k in ("宋", "明", "serif", "song", "mincho")):
        return "serif"
    if any(k in blob for k in ("等宽", "mono", "code")):
        return "monospace"
    if any(k in blob for k in ("黑", "gothic", "sans", "hei", "雅黑")):
        return "sans"
    return "decorative" if tags else "unknown"


def license_tier(text: str) -> str:
    value = str(text or "").casefold()
    if re.search(r"\bnc\b|non[- ]?commercial|非商業|非商业", value):
        return "restricted"
    if any(k in value for k in LICENSE_RESTRICTED):
        return "restricted"
    if any(k in value for k in LICENSE_PERMISSIVE):
        return "permissive"
    if "系统字体" in value:
        return "system"
    return "unknown"


def license_for_local(family: str, dir_source: str) -> str:
    name = family.casefold()
    if any(k in name for k in ("noto", "source han", "思源", "smiley", "得意黑")):
        return "OFL-1.1"
    if "阿里妈妈" in family:
        return "免费商用（阿里妈妈条款，需核对）"
    if "阿里巴巴普惠体" in family:
        return "免费商用（阿里巴巴普惠体条款，需核对）"
    if dir_source == "system":
        return "系统字体（仅本机渲染，不可再分发）"
    return "unknown（商用前核对授权）"


def _dedupe_keep(text: str) -> str:
    seen, out = set(), []
    for char in str(text):
        if char in seen:
            continue
        if char == "\n":
            char = " "
        seen.add(char)
        out.append(char)
    return "".join(out)


# ------------------------------------------------------------------ 参考片/项目简报

def load_reference(reference) -> dict | None:
    """reference 可以是 profile 字典、profile 文件、或 koubo reference 目录。"""
    if isinstance(reference, dict):
        return reference
    if not reference:
        return None
    path = Path(reference).expanduser()
    if path.is_dir():
        for name in ("reference-profile.json", "work/reference-profile.json"):
            candidate = path / name
            if candidate.is_file():
                return _read_json(candidate)
        return None
    return _read_json(path) if path.is_file() else None


def _caption_text(project: Path | None) -> str:
    if project is None:
        return ""
    p = project_paths(project)
    srt = p["input"] / "captions.srt"
    if srt.is_file():
        try:
            return " ".join(str(cue.get("raw") or "").replace("\n", " ")
                            for cue in parse_srt(srt))
        except (OSError, ValueError):
            return ""
    return ""


def _transcript_text(project: Path | None, profile: dict | None) -> str:
    if profile:
        text = ((profile.get("transcript") or {}).get("text") or "").strip()
        if text:
            return text
    if project:
        data = _read_json(project_paths(project)["work"] / "reference" / "transcript.json")
        if not data:
            data = _read_json(project_paths(project)["work"] / "transcript.json")
        if data and data.get("text"):
            return str(data["text"])
    return ""


def _style_lock_font(project: Path | None) -> str | None:
    if project is None:
        return None
    lock = _read_json(project_paths(project)["work"] / "style-lock.json")
    if not lock:
        return None
    try:
        return str(lock["recipe"]["style"]["captions"]["font"])
    except (KeyError, TypeError):
        return None


def build_brief(project: Path | None, config: dict | None,
                profile: dict | None) -> dict:
    overview = {}
    style = {}
    pacing = {}
    source_meta = {}
    if profile:
        overview = (profile.get("breakdown") or {}).get("overview") or {}
        style = profile.get("style") or {}
        pacing = profile.get("pacing") or {}
        source_meta = (profile.get("source") or {}).get("meta") or {}
    cfg = config or {}
    captions = _caption_text(project)
    transcript = _transcript_text(project, profile)
    description = " ".join(str(overview.get(k) or "") for k in
                           ("hook", "structure", "visual_style", "rhythm", "audio",
                            "target_audience"))
    description += " " + " ".join(str(x) for x in overview.get("why_it_works") or [])
    blob = " ".join((str(source_meta.get("title") or ""), transcript, captions,
                     description, str((style.get("caption_band") or {}).get("note") or "")))
    signals = sorted({key for key, words in SIGNAL_WORDS.items()
                      if any(word in blob.casefold() for word in words)})
    existing = str((cfg.get("captions") or {}).get("font") or "")
    locked = _style_lock_font(project)
    return {
        "title": str(source_meta.get("title") or (project.name if project else ""))[:300],
        "signals": signals,
        "signal_words": sorted({word for key in signals
                                for word in SIGNAL_WORDS[key]
                                if word in blob.casefold()})[:24],
        "overview": {key: str(overview.get(key) or "")[:600] for key in
                     ("hook", "structure", "visual_style", "rhythm", "audio",
                      "target_audience")},
        "why_it_works": [str(x)[:200] for x in (overview.get("why_it_works") or [])][:4],
        "caption_sample": captions[:400],
        "caption_chars": len(captions),
        "transcript_sample": transcript[:800],
        "transcript_hook": str((profile or {}).get("recommendations", {}).get("copy", {})
                               .get("hook") or "")[:200],
        "existing_font": existing,
        "locked_font": locked,
        "aspect": style.get("aspect") or "",
        "cuts_per_minute": pacing.get("used_cuts_per_minute"),
        "commercial": False,
    }


# ------------------------------------------------------------------ 本地字体库

def _dir_sources(project: Path | None) -> list[tuple[Path, str]]:
    out: list[tuple[Path, str]] = []
    if project is not None:
        out.append((project / "fonts", "project"))
    install = Path(__file__).resolve().parents[2] / "fonts"
    if install.is_dir():
        out.append((install, "install"))
    for value in (os.environ.get("KOUBO_FONT_DIRS") or "").split(os.pathsep):
        if value.strip():
            out.append((Path(value).expanduser(), "custom"))
    out.extend((Path(d), "system") for d in FONT_SEARCH_DIRS)
    seen, unique = set(), []
    for path, source in out:
        if not path.is_dir():
            continue
        key = str(path.resolve())
        if key in seen:
            continue
        seen.add(key)
        unique.append((path, source))
    return unique


_CJK_CACHE: dict[str, bool] = {}


def _is_cjk(path: Path) -> bool:
    key = str(path)
    if key not in _CJK_CACHE:
        _CJK_CACHE[key] = has_cjk_glyphs(path)
    return _CJK_CACHE[key]


def local_candidates(project: Path | None = None, *,
                     include_system: bool = True) -> list[dict]:
    """扫本机 CJK 字体，按族名分组，每组选最粗的一档。工程 fonts/ 优先。"""
    seen_family: set[str] = set()
    rows: list[dict] = []
    for directory, source in _dir_sources(project):
        if source == "system" and not include_system:
            continue
        groups: dict[str, list] = {}
        for entry in _index_dir(directory):
            if not entry.display or not _is_cjk(entry.path):
                continue
            groups.setdefault(entry.display.casefold(), []).append(entry)
        for entries in groups.values():
            entries.sort(key=lambda e: (-_weight_rank(e.styles), str(e.path)))
            best = entries[0]
            key = best.display.casefold()
            if key in seen_family:
                continue
            seen_family.add(key)
            weight = weight_number(best.style_display)
            category = infer_category(best.display, [best.style_display])
            tags = [CATEGORY_TAGS.get(category, category)]
            tags.append("粗" if weight >= 700 else "细" if weight <= 300 else "常规")
            tags.append(source)
            rows.append({
                "id": "local:" + _slug(best.display),
                "name": best.suggest,
                "display": best.display,
                "source": "local",
                "dir_source": source,
                "family": best.display,
                "suggest": best.suggest,
                "category": category,
                "tags": tags,
                "weights": [best.style_display] if best.style_display else [],
                "weight": weight,
                "license": license_for_local(best.display, source),
                "path": str(best.path),
                "description": f"{source} 字体",
            })
    rows.sort(key=lambda row: (-row["weight"], row["name"]))
    return rows


# ------------------------------------------------------------------ emfont

def _emfont_candidate(font: dict) -> dict:
    tags = list(font.get("tags") or [])
    category = EMFONT_CATEGORY.get(font.get("category") or "", "")
    if not category:
        category = infer_category(font.get("name") or "", tags)
    weights = font.get("weights") or []
    weight = 700 if 700 in weights else (max(weights) if weights else 400)
    return {
        "id": "emfont:" + str(font["id"]),
        "name": font.get("name") or font["id"],
        "display": font.get("name") or font["id"],
        "source": "emfont",
        "dir_source": "emfont",
        "family": font.get("family") or font.get("name") or font["id"],
        "suggest": font.get("name") or font["id"],
        "category": category,
        "tags": tags + [CATEGORY_TAGS.get(category, category)],
        "weights": weights,
        "weight": weight,
        "license": font.get("license") or "",
        "emfont_id": str(font["id"]),
        "description": str(font.get("description") or "")[:240],
        "upstream": font.get("source") or "",
    }


def emfont_candidates(project: Path | None, brief: dict, *, shortlist: int = 10,
                      timeout: float = 20.0, log=print) -> tuple[list[dict], dict]:
    """线上目录 → 预筛 → 取前 N 个补详情。目录/详情都走缓存。"""
    data = emfont.catalog(timeout=timeout)
    fonts = data.get("fonts") or []
    prelim = []
    for font in fonts:
        tags = [str(t) for t in (font.get("tags") or [])]
        if any("icon" in tag.casefold() for tag in tags):
            continue
        prelim.append(_emfont_candidate(font))
    if not prelim:
        raise emfont.EmfontError("emfont 目录里没有可用的文字字体")
    ranked = rank_candidates(prelim, brief)
    top = ranked[:max(shortlist, 1)]
    for candidate in top:
        info = emfont.font_info_cached(candidate["emfont_id"])
        if info.get("name_zh") or info.get("name"):
            candidate["name"] = info.get("name_zh") or info.get("name")
            candidate["display"] = candidate["name"]
            candidate["suggest"] = candidate["name"]
        if info.get("family"):
            candidate["family"] = info["family"]
        if info.get("category"):
            candidate["category"] = EMFONT_CATEGORY.get(info["category"], candidate["category"])
        if info.get("tags"):
            candidate["tags"] = list(dict.fromkeys(candidate["tags"] + info["tags"]))
        if info.get("weights"):
            candidate["weights"] = info["weights"]
            candidate["weight"] = 700 if 700 in info["weights"] else max(info["weights"])
        if info.get("license"):
            candidate["license"] = info["license"]
        elif not candidate.get("license"):
            candidate["license"] = "unknown（emfont 未提供，商用前核对）"
        if info.get("description"):
            candidate["description"] = str(info["description"])[:240]
    status = {
        "status": "cached" if data.get("from_cache") else "online",
        "count": len(fonts),
        "stale": bool(data.get("stale")),
        "fetched_at": data.get("fetched_at"),
    }
    if data.get("warning"):
        status["warning"] = str(data["warning"])
    return top, status


# ------------------------------------------------------------------ 评分

def _signals_of(brief: dict) -> tuple[set[str], set[str]]:
    pref, avoid = set(), set()
    for signal in brief.get("signals") or []:
        pref.update(CATEGORY_PREF.get(signal, set()))
        avoid.update(CATEGORY_AVOID.get(signal, set()))
    return pref, avoid


def score_candidate(candidate: dict, brief: dict) -> float:
    pref, avoid = _signals_of(brief)
    category = candidate.get("category") or "unknown"
    score = 0.0
    if category in pref:
        score += 3.0
    if category in avoid:
        score -= 2.5
    text = (str(candidate.get("name") or "") + " "
            + " ".join(str(t) for t in candidate.get("tags") or [])).casefold()
    token_hits = sum(1 for token in brief.get("signal_words") or []
                     if token and token.casefold() in text)
    score += min(3.0, token_hits * 0.8)
    weight = int(candidate.get("weight") or 400)
    score += max(-1.5, min(1.5, (weight - 500) / 200))
    if candidate.get("source") == "local":
        score += 1.2
    tier = license_tier(str(candidate.get("license") or ""))
    if tier == "restricted":
        score -= 4.0 if brief.get("commercial") else 1.5
    elif tier == "permissive":
        score += 0.8
    elif tier == "system":
        score -= 0.15
    else:
        score -= 0.3
    chars = int(brief.get("caption_chars") or 0)
    if chars > 60 and category in ("pixel", "handwriting", "decorative"):
        score -= 2.5
    if chars <= 20 and category in ("pixel", "handwriting"):
        score += 0.6
    if weight < 400:
        score -= 0.8
    if (brief.get("locked_font") and not brief.get("replace_locked")
            and candidate.get("suggest") == brief["locked_font"]):
        score += 2.5
    elif brief.get("existing_font") and candidate.get("suggest") == brief["existing_font"]:
        score += 1.0
    return round(score, 3)


def rank_candidates(candidates: list[dict], brief: dict) -> list[dict]:
    ranked = []
    for candidate in candidates:
        row = dict(candidate)
        row["score"] = score_candidate(row, brief)
        ranked.append(row)
    ranked.sort(key=lambda row: (-row["score"], row.get("source") != "local",
                                 row.get("name") or ""))
    return ranked


def filter_license(candidates: list[dict], strict: bool) -> list[dict]:
    if not strict:
        return candidates
    return [c for c in candidates if license_tier(c.get("license") or "") == "permissive"]


# ------------------------------------------------------------------ AI 选择

SYSTEM = """你是中文短视频的字幕字体指导。你只根据给出的参考片分析、文案和候选字体做选择。

规则：
- 只能从 candidates 里选，selected_id 必须原样返回；不要编造候选里没有的字体、字重或授权。
- 字幕第一原则是可读：小字号、描边、深色背景、快速切换下不能糊。手写、像素、装饰体只在文案很短或风格极强时选。
- 参考片的 visual_style / structure / rhythm / audience 是主要依据；不要因为名字好听选。
- 如果 locked_font 存在，除非它与参考片风格明显冲突，否则优先保留它（换字体会让 style-lock 红项）。
- commercial=true 时优先 OFL/Apache/免费商用，避开 NC/非商业；授权不明可以选，但 risk 必须写清。
- 不确定就写进 unchecked，不要装懂。
- 输出严格 JSON 对象，不要 markdown。"""


def _contract(ids: list[str]) -> str:
    return f"""只返回一个 JSON 对象：
{{
  "selected_id": "必须是这些 id 之一：{', '.join(ids)}",
  "confidence": 0.0,
  "reason": "中文 1-3 句：为什么这款适合这条参考片（风格、节奏、可读性）",
  "usage": "caption|title|both",
  "weight": 700,
  "alternates": ["最多 2 个候选 id"],
  "risk": "中文：授权/缺字/可读性风险；没有写 无",
  "unchecked": ["中文：你没把握、需要人看的点"]
}}"""


def _candidate_payload(candidates: list[dict]) -> list[dict]:
    rows = []
    for candidate in candidates:
        rows.append({
            "id": candidate["id"],
            "name": candidate["name"],
            "source": candidate["source"],
            "category": candidate["category"],
            "tags": candidate.get("tags") or [],
            "weights": candidate.get("weights") or [],
            "license": candidate.get("license") or "unknown",
        })
    return rows


def _http_transport(body: dict, key: str) -> dict:
    payload = json.dumps(body, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        ENDPOINT, data=payload, method="POST",
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            return json.load(response)
    except urllib.error.HTTPError as exc:
        detail = ""
        try:
            detail = exc.read().decode("utf-8", "replace")[:300]
        except OSError:
            pass
        raise FontPickerError(f"字体选择接口 HTTP {exc.code}：{detail}") from exc
    except (urllib.error.URLError, TimeoutError) as exc:
        raise FontPickerError(f"字体选择接口连不上：{exc}") from exc


def _chat(messages: list[dict], *, key: str, model: str, transport) -> tuple[dict, dict]:
    body = {
        "model": model,
        "temperature": 0.3,
        "max_tokens": MAX_LLM_TOKENS,
        "response_format": {"type": "json_object"},
        "messages": messages,
    }
    response = transport(body, key)
    try:
        text = response["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise FontPickerError("字体选择接口返回结构不符合约定") from exc
    raw = str(text or "").strip()
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[1] if "\n" in raw else raw
        raw = raw.rsplit("```", 1)[0].strip()
    try:
        payload = json.loads(raw)
    except ValueError as exc:
        raise FontPickerError(f"字体选择没有返回合法 JSON：{exc}") from exc
    if not isinstance(payload, dict):
        raise FontPickerError("字体选择返回的不是 JSON 对象")
    usage = response.get("usage") if isinstance(response, dict) else {}
    return payload, usage if isinstance(usage, dict) else {}


def validate_selection(payload: dict, candidates: list[dict]) -> dict:
    ids = [c["id"] for c in candidates]
    selected = str(payload.get("selected_id") or "").strip()
    if selected not in ids:
        raise FontPickerError(f"AI 选了候选之外的字体：{selected!r}")
    confidence = payload.get("confidence")
    if isinstance(confidence, bool) or not isinstance(confidence, (int, float)):
        raise FontPickerError("confidence 必须是数值")
    if not math.isfinite(confidence) or not 0 <= confidence <= 1:
        raise FontPickerError("confidence 超出 0-1")
    reason = str(payload.get("reason") or "").strip()
    if not reason:
        raise FontPickerError("reason 不能为空")
    usage = str(payload.get("usage") or "caption").strip()
    if usage not in ("caption", "title", "both"):
        raise FontPickerError(f"usage 不合法：{usage!r}")
    weight = payload.get("weight", 700)
    if isinstance(weight, bool) or not isinstance(weight, (int, float)):
        raise FontPickerError("weight 必须是数值")
    weight = max(100, min(900, int(weight)))
    alternates = payload.get("alternates") or []
    if not isinstance(alternates, list):
        raise FontPickerError("alternates 必须是数组")
    alternates = [str(x) for x in alternates if str(x) in ids and str(x) != selected]
    alternates = list(dict.fromkeys(alternates))[:2]
    unchecked = payload.get("unchecked") or []
    if not isinstance(unchecked, list):
        unchecked = []
    return {
        "selected_id": selected,
        "confidence": round(float(confidence), 3),
        "reason": reason[:800],
        "usage": usage,
        "weight": weight,
        "alternates": alternates,
        "risk": str(payload.get("risk") or "无").strip()[:500],
        "unchecked": [str(x)[:300] for x in unchecked if str(x).strip()][:5],
    }


def ai_select(brief: dict, candidates: list[dict], *, api_key: str,
              model: str, transport=None) -> dict:
    if not candidates:
        raise FontPickerError("没有候选字体")
    payload = {
        "brief": {
            "title": brief.get("title"),
            "signals": brief.get("signals"),
            "overview": brief.get("overview"),
            "why_it_works": brief.get("why_it_works"),
            "caption_sample": brief.get("caption_sample"),
            "caption_chars": brief.get("caption_chars"),
            "transcript_hook": brief.get("transcript_hook"),
            "existing_font": brief.get("existing_font"),
            "locked_font": brief.get("locked_font"),
            "replace_locked": brief.get("replace_locked"),
            "commercial": brief.get("commercial"),
        },
        "candidates": _candidate_payload(candidates),
    }
    messages = [
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content": json.dumps(payload, ensure_ascii=False)
         + "\n\n" + _contract([c["id"] for c in candidates])},
    ]
    response, usage = _chat(messages, key=api_key, model=model,
                            transport=transport or _http_transport)
    selection = validate_selection(response, candidates)
    selection["usage_tokens"] = usage
    return selection


# ------------------------------------------------------------------ 兜底选择

def fallback_select(ranked: list[dict], *, reason: str) -> dict:
    selected = ranked[0]
    alternates = [row["id"] for row in ranked[1:3]]
    return {
        "selected_id": selected["id"],
        "confidence": 0.55,
        "reason": reason,
        "usage": "caption",
        "weight": int(selected.get("weight") or 700),
        "alternates": alternates,
        "risk": ("本地规则只按风格信号、字重和授权文本打分；"
                 "没有判断字形细节和实际渲染观感"),
        "unchecked": ["字体观感需要人眼在成片字幕上复核"],
        "usage_tokens": {},
    }


# ------------------------------------------------------------------ 主入口

def select(project: str | Path | None = None, reference=None, *,
           library: str = "auto", no_llm: bool = False,
           api_key: str | None = None, model: str = DEFAULT_MODEL,
           transport=None, commercial: bool = False,
           strict_license: bool = False, force: bool = False,
           max_candidates: int = MAX_CANDIDATES, log=print) -> dict:
    if library not in ("auto", "local", "emfont"):
        raise FontPickerError("library 只能是 auto / local / emfont")
    project_path = Path(project).resolve() if project else None
    config = None
    if project_path and project_paths(project_path)["config"].is_file():
        try:
            config = load_config(project_paths(project_path)["config"])
        except SystemExit as exc:
            raise FontPickerError(str(exc)) from exc
    profile = load_reference(reference)
    if profile is None and project_path:
        profile = load_reference(project_path / "work" / "reference")
    brief = build_brief(project_path, config, profile)
    brief["commercial"] = bool(commercial)
    brief["replace_locked"] = bool(force)
    warnings: list[str] = []
    unchecked: list[dict] = []

    local: list[dict] = []
    if library in ("auto", "local"):
        try:
            local = local_candidates(project_path)
        except Exception as exc:                    # 字体损坏/权限问题不阻断
            warnings.append(f"本地字体扫描不完整：{exc}")
        if not local:
            unchecked.append({"item": "本地字体库",
                              "reason": "没有扫到带汉字的本地字体；只能依赖 emfont"})

    online: list[dict] = []
    em_status: dict = {"status": "skipped"}
    if library in ("auto", "emfont"):
        try:
            online, em_status = emfont_candidates(
                project_path, brief, shortlist=10,
                timeout=12.0 if library == "auto" else 20.0, log=log)
            if em_status.get("stale"):
                unchecked.append({"item": "emfont 目录",
                                  "reason": "线上不可用，使用了过期缓存；新字体可能不在候选里"})
            if em_status.get("warning"):
                warnings.append(f"emfont：{em_status['warning']}")
        except emfont.EmfontError as exc:
            em_status = {"status": "unchecked", "reason": str(exc)}
            unchecked.append({"item": "emfont 字体库", "reason": str(exc)})
            if library == "emfont":
                raise FontPickerError(f"emfont 不可用：{exc}") from exc
            log(f"  emfont 不可用，继续用本地字体：{exc}")

    candidates = filter_license(local + online, strict_license)
    if strict_license:
        dropped = len(local) + len(online) - len(candidates)
        if dropped:
            unchecked.append({"item": "严格授权过滤",
                              "reason": f"过滤掉 {dropped} 个授权不明/受限的候选"})
    if not candidates:
        raise FontPickerError("没有可用字体候选：本地没有 CJK 字体，emfont 也不可用")
    ranked = rank_candidates(candidates, brief)
    prompt_pool = ranked[:max(1, int(max_candidates))]

    source_key = api_key if api_key is not None else api_key_from_env()
    selection: dict
    mode = "fallback"
    if no_llm or not source_key:
        selection = fallback_select(
            ranked, reason=("没有调用 AI：使用本地风格信号打分"
                            + ("（--no-llm）" if no_llm else "（没有 DEEPSEEK_API_KEY）")))
    else:
        try:
            selection = ai_select(brief, prompt_pool, api_key=source_key,
                                  model=model, transport=transport)
            mode = "ai"
        except FontPickerError as exc:
            warnings.append(f"AI 选择失败，回退本地打分：{exc}")
            selection = fallback_select(ranked, reason="AI 选择失败，回退本地风格信号打分")
    selection["mode"] = mode
    selected = next((row for row in ranked if row["id"] == selection["selected_id"]), None)
    if selected is None:
        raise FontPickerError(f"选中的字体不在候选里：{selection['selected_id']}")
    selection["selected"] = selected
    selection["alternates_detail"] = [
        row for row in ranked if row["id"] in selection.get("alternates", [])]
    if license_tier(selected.get("license") or "") in ("unknown", "system"):
        unchecked.append({"item": "字体授权",
                          "reason": f"{selected['name']} 的授权是「{selected.get('license')}」，"
                                    "商用发布前需自行核对"})
    unchecked.append({"item": "字体观感",
                      "reason": "选择依据是字体元数据与参考片文本分析；"
                                "成片字幕需看 work/font-samples.jpg 或播放复核"})

    shortlist = []
    for row in ranked[:12]:
        shortlist.append({key: row.get(key) for key in
                          ("id", "name", "source", "category", "tags", "weights",
                           "license", "score")})
    return {
        "schema": SCHEMA,
        "generated_at": _now(),
        "brief": brief,
        "library": {
            "requested": library,
            "local_count": len(local),
            "emfont_count": len(online),
            "emfont": em_status,
        },
        "shortlist": shortlist,
        "selected": {key: selected.get(key) for key in
                     ("id", "name", "display", "source", "category", "tags",
                      "weights", "weight", "license", "path", "family",
                      "suggest", "dir_source", "emfont_id", "description",
                      "score") if selected.get(key) is not None},
        "alternates": selection.get("alternates_detail") or [],
        "mode": mode,
        "confidence": selection["confidence"],
        "reason": selection["reason"],
        "usage": selection["usage"],
        "risk": selection["risk"],
        "warnings": warnings,
        "unchecked": unchecked + [{
            "item": "AI 自述" if mode == "ai" else "本地打分说明",
            "reason": x} for x in selection.get("unchecked") or []],
        "selection": selection,
        "applied": None,
        "apply_blocked": None,
    }


# ------------------------------------------------------------------ 应用

def _project_words(project: Path, config: dict, brief: dict) -> str:
    p = project_paths(project)
    parts = [_caption_text(project)]
    transcript = _read_json(p["work"] / "reference" / "transcript.json")
    if not transcript:
        transcript = _read_json(p["work"] / "transcript.json")
    if transcript and transcript.get("text"):
        parts.append(str(transcript["text"]))
    for row in (config.get("card") or {}).get("rows") or []:
        if isinstance(row, str):
            parts.append(row)
    parts.append(project.name)
    words = _dedupe_keep("".join(parts) + COMMON_CHARS)
    return words[:3000]


def missing_glyphs(path: Path, text: str, *, limit: int = 120) -> list[str]:
    try:
        from PIL import ImageFont
    except ImportError:
        return []
    chars = [ch for ch in dict.fromkeys(text or "") if ch.strip()]
    if not chars:
        return []
    chosen = chars[:limit]
    try:
        font = ImageFont.truetype(str(path), 48)
        notdef = bytes(font.getmask("\ue000"))
        return [ch for ch in chosen if bytes(font.getmask(ch)) == notdef]
    except Exception:
        return []


def _safe_find(family: str | None, project: Path) -> Path | None:
    if not family:
        return None
    try:
        return find_font(family, project=project)
    except SystemExit:
        return None
    except Exception:
        return None


def _materialize_local(candidate: dict, project: Path) -> dict:
    suggest = candidate.get("suggest") or candidate.get("family")
    path = _safe_find(suggest, project)
    if path is None:
        path = _safe_find(candidate.get("family"), project)
    if path is None:
        raise FontPickerError(f"本机找不到字体：{suggest}")
    if not has_cjk_glyphs(path):
        raise FontPickerError(f"{path.name} 没有汉字字形")
    resolved = _safe_find(suggest, project)
    font = suggest if (suggest and resolved) else font_display_name(path)
    return {"font": font, "path": str(path), "source": "local",
            "family": font_display_name(path)}


def _materialize_emfont(candidate: dict, project: Path, config: dict,
                        brief: dict) -> dict:
    font_id = candidate.get("emfont_id")
    if not font_id:
        raise FontPickerError("emfont 候选缺少字体 id")
    words = _project_words(project, config, brief)
    result = emfont.generate_font(font_id, words, weight=int(candidate.get("weight") or 700),
                                  minify=False, fmt="ttf")
    p = project_paths(project)
    dest = p["root"] / "fonts" / f"emfont-{_slug(font_id)}.ttf"
    path, used = emfont.download_first(result["locations"], dest)
    font = font_display_name(path)
    missing = missing_glyphs(path, _caption_text(project) or words)
    if missing:
        raise FontPickerError(f"生成的字体缺字：{''.join(missing[:20])}")
    return {"font": font, "path": str(path), "source": "emfont",
            "family": font, "emfont_id": font_id, "download_url": used,
            "subset_chars": len(set(words)), "license": candidate.get("license") or ""}


def render_samples(project: Path, result: dict, *, width: int = 960) -> str | None:
    """把候选里本机可用的字体渲成一张样张，供人眼复核。"""
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError:
        return None
    project = Path(project).resolve()
    p = project_paths(project)
    p["work"].mkdir(parents=True, exist_ok=True)
    text = str((result.get("brief") or {}).get("caption_sample") or "").strip()
    if not text:
        text = "口播工坊 字幕示例 ABC 123"
    text = text[:24]
    try:
        label_path = find_font(None, project=project)
    except SystemExit:
        label_path = None
    rows = []
    seen = set()
    for row in [result.get("selected")] + list(result.get("alternates") or []) + list(result.get("shortlist") or []):
        if not row or row.get("source") != "local":
            continue
        path = row.get("path")
        if not path or path in seen or not Path(path).is_file():
            continue
        seen.add(path)
        rows.append((row.get("name") or Path(path).stem, Path(path)))
        if len(rows) >= 6:
            break
    applied = result.get("applied") or {}
    if applied.get("source") == "emfont" and applied.get("path") and Path(applied["path"]).is_file():
        rows.insert(0, (applied.get("font") or "emfont", Path(applied["path"])))
    if not rows:
        return None
    row_height = 132
    margin = 24
    sheet = Image.new("RGB", (width, margin + len(rows) * row_height), (18, 18, 18))
    draw = ImageDraw.Draw(sheet)
    try:
        label_font = ImageFont.truetype(str(label_path), 22) if label_path else ImageFont.load_default()
    except Exception:
        label_font = ImageFont.load_default()
    for index, (name, path) in enumerate(rows):
        y = margin + index * row_height
        draw.text((margin, y), name[:60], fill=(160, 160, 160), font=label_font)
        size, sample = 48, None
        while size >= 20:
            try:
                sample = ImageFont.truetype(str(path), size)
            except Exception:
                sample = None
                break
            if draw.textlength(text, font=sample) <= width - 2 * margin:
                break
            size -= 2
        if sample is None:
            continue
        draw.text((margin, y + 34), text, fill=(255, 255, 255), font=sample)
        draw.line([(margin, y + row_height - 10), (width - margin, y + row_height - 10)],
                  fill=(40, 40, 40), width=1)
    target = p["work"] / "font-samples.jpg"
    sheet.save(target, quality=88)
    return str(target)


def _write_report(project: Path, result: dict) -> None:
    p = project_paths(project)
    p["work"].mkdir(parents=True, exist_ok=True)
    selected = result.get("selected") or {}
    lines = [
        "# 字体选择",
        "",
        f"- 生成时间：{result.get('generated_at')}",
        f"- 方式：{'AI 选择' if result.get('mode') == 'ai' else '本地规则回退'}",
        f"- 选中：**{selected.get('name')}**（{selected.get('source')} / "
        f"{selected.get('category')}）",
        f"- 分数：{selected.get('score')}",
        f"- 理由：{result.get('reason')}",
        f"- 授权：{selected.get('license') or 'unknown'}",
        f"- 风险：{result.get('risk')}",
        "",
    ]
    alternates = result.get("alternates") or []
    if alternates:
        lines.append("## 备选")
        lines.append("")
        for row in alternates:
            lines.append(f"- {row.get('name')}（{row.get('source')} / "
                         f"{row.get('license') or 'unknown'}）")
        lines.append("")
    if result.get("samples"):
        lines.append(f"![字体样张]({Path(result['samples']).name})")
        lines.append("")
    applied = result.get("applied")
    blocked = result.get("apply_blocked")
    lines.append("## 应用")
    lines.append("")
    if applied:
        lines.append(f"- 已写入 `config.json` 的 `captions.font`：`{applied.get('font')}`")
        if applied.get("source") == "emfont":
            lines.append(f"- 子集字体：`{applied.get('path')}`（{applied.get('subset_chars')} 字）")
    elif blocked:
        lines.append(f"- 未应用：{blocked.get('reason')}")
        lines.append(f"- 处理：{blocked.get('hint')}")
    else:
        lines.append("- 未应用（只生成建议；加 `--apply` 才会写 config）。")
    lines.append("")
    unchecked = result.get("unchecked") or []
    lines.append("## 未检查")
    lines.append("")
    if unchecked:
        for row in unchecked:
            lines.append(f"- {row.get('item')}：{row.get('reason')}")
    else:
        lines.append("无。字体观感仍需在成片字幕上人眼复核。")
    lines.append("")
    (p["work"] / "font-selection.md").write_text("\n".join(lines), encoding="utf-8")


def _same_font(left: str, right: str) -> bool:
    def key(value: str) -> str:
        return re.sub(r"[\s\-_·．.,，、（）()\[\]]+", "", str(value or "").casefold())
    a, b = key(left), key(right)
    return bool(a and b and a == b)


def apply_selection(project: str | Path, result: dict, *, force: bool = False,
                    log=print) -> dict:
    project_path = Path(project).resolve()
    p = project_paths(project_path)
    if not p["config"].is_file():
        raise FontPickerError(f"找不到 config.json：{p['config']}")
    config = load_config(p["config"])
    locked_font = _style_lock_font(project_path)
    selected = result.get("selected") or {}
    ordered = [selected] + list(result.get("alternates") or [])
    if locked_font and not _same_font(selected.get("suggest") or selected.get("family") or "",
                                      locked_font):
        if not force:
            result["apply_blocked"] = {
                "reason": f"项目绑定了 style-lock，字体锁定为「{locked_font}」",
                "hint": ("换字体会改风格参数；先发布新配方版本并重新绑定，"
                         "或加 --force 接受 `koubo style check` 红项"),
                "locked_font": locked_font,
            }
            save_result(project_path, result)
            log(f"  未应用：{result['apply_blocked']['reason']}")
            return result
        result["style_lock_conflict"] = True
        log("  ⚠ --force：字体与 style-lock 不一致，`koubo style check` 会红")

    errors = []
    applied = None
    for candidate in ordered:
        try:
            if candidate.get("source") == "emfont":
                applied = _materialize_emfont(candidate, project_path, config,
                                              result.get("brief") or {})
            else:
                applied = _materialize_local(candidate, project_path)
            break
        except (FontPickerError, emfont.EmfontError) as exc:
            errors.append(f"{candidate.get('name')}: {exc}")
            log(f"    {candidate.get('name')} 不可用，试下一个：{exc}")
    if applied is None:
        result["apply_error"] = "；".join(errors[-4:])
        result["unchecked"] = list(result.get("unchecked") or []) + [
            {"item": "应用字体", "reason": result["apply_error"]}]
    else:
        config.setdefault("captions", {})["font"] = applied["font"]
        write_json(p["config"], config)
        result["applied"] = applied
        log(f"  已应用字体：{applied['font']}（{applied['source']}）")
    save_result(project_path, result)
    return result


def save_result(project: str | Path, result: dict) -> Path:
    p = project_paths(project)
    sample = render_samples(Path(project).resolve(), result)
    if sample:
        result["samples"] = sample
    target = p["work"] / "font-selection.json"
    write_json(target, result)
    _write_report(Path(project).resolve(), result)
    return target


def report_path(project: str | Path) -> Path:
    return project_paths(project)["work"] / "font-selection.json"
