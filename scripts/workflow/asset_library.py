"""素材库：登记、召回、稳定调用、授权台账。

为什么不是「把文件扔进文件夹」：

- **可被程序检索**：每个素材一条 JSONL 记录，带 kind / tags / mood / scene /
  use_for / duration / bpm / sync，`koubo assets search` 与工作流里的
  `resolve_ref("asset:...")` 都读这一份；
- **可被稳定调用**：ID 不随文件名改；配置里可以写 `asset:sfx/whoosh-short`，
  而不是记一个路径；文件旁边有 `.asset.json` sidecar；
- **授权边界清晰**：`license` 指向 `workflow/asset_licenses.py` 的许可目录，
  `verify` 判 `pass / unchecked / fail`，导出成片时附 `asset-licenses.csv` 与
  `CREDITS.md`。

目录（`assets/library/`）：

```text
audio/bgm/            BGM
audio/sfx/            音效（whoosh / click / pop / impact / riser …）
video/broll/          B-roll 空镜
video/overlays/       转场、光效、纹理
graphics/stickers/    贴纸
graphics/fonts/       字体（二进制不进仓库；许可记录见 fonts/licenses/）
graphics/illustrations/  插图
graphics/stills/      静帧
templates/jianying/   剪映草稿模板
templates/captions/   花字/字幕条模板
registry.jsonl        正本索引
licenses.csv          人可读授权台账（由 registry 生成）
```

边界：这里不是「素材下载站」。远程源只通过公开 API 单条检索/下载，不批量抓取、
不登录、不绕过付费墙；授权仍以官方条款为准，工具只负责把已知信息记下来并判三态。
"""
from __future__ import annotations

import csv
import hashlib
import json
import os
import re
import shutil
import unicodedata
from datetime import date, datetime, timezone
from pathlib import Path

from _common import input_path, load_config, probe_media, project_paths, write_json
from workflow import asset_licenses as lic

# ------------------------------------------------------------------ 常量

KINDS = ("bgm", "sfx", "broll", "overlay", "sticker", "font",
         "illustration", "still", "template", "caption")

KIND_LABELS = {
    "bgm": "背景音乐", "sfx": "音效", "broll": "B-roll", "overlay": "动效/转场",
    "sticker": "贴纸", "font": "字体", "illustration": "插图", "still": "静帧",
    "template": "模板", "caption": "花字/字幕条", "source": "原始素材",
}

KIND_ALIASES = {
    "music": "bgm", "bgm": "bgm", "audio": "bgm",
    "sfx": "sfx", "sound": "sfx", "sound-effect": "sfx",
    "video": "broll", "b-roll": "broll", "broll": "broll", "stock": "broll",
    "overlay": "overlay", "transition": "overlay", "motion": "overlay",
    "sticker": "sticker", "graphic": "sticker",
    "font": "font", "typeface": "font",
    "illustration": "illustration", "illust": "illustration",
    "still": "still", "photo": "still", "image": "still",
    "template": "template", "draft": "template",
    "caption": "caption", "captions": "caption",
}

# 目录是「程序可读」的固定约定；新类型加在这里，scan 才能按路径判 kind。
DIR_BY_KIND = {
    "bgm": "audio/bgm",
    "sfx": "audio/sfx",
    "broll": "video/broll",
    "overlay": "video/overlays",
    "sticker": "graphics/stickers",
    "font": "graphics/fonts",
    "illustration": "graphics/illustrations",
    "still": "graphics/stills",
    "template": "templates",
    "caption": "templates/captions",
}

MEDIA_SUFFIXES = {
    ".mp3", ".wav", ".m4a", ".aac", ".flac", ".aiff",
    ".mp4", ".mov", ".mkv", ".webm", ".m4v",
}
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".tif", ".tiff"}
SIDECAR_SUFFIX = ".asset.json"
REGISTRY_NAME = "registry.jsonl"
LEDGER_NAME = "licenses.csv"

# 外部库素材：没有来源 URL 时 audit 会记 unchecked（bundled 的随包采样除外）
_EXTERNAL_PROVIDERS = {"pexels", "pixabay", "mixkit", "sfx-kit", "web", "fma",
                       "coverr", "videvo", "giphy", "jianying-cloud"}

_STOPWORDS = {
    "的", "了", "吗", "呢", "吧", "啊", "就", "都", "也", "很", "在", "是", "有",
    "和", "与", "而", "及", "你", "我", "他", "她", "它", "我们", "你们", "他们",
    "这", "那", "这个", "那个", "一个", "一种", "什么", "怎么", "为什么", "可以",
}

# 中文口播词 → 素材标签。不是语义向量，只是把「可解释的召回」做扎实；
# 命中原因会写进 suggest 的 reasons，方便人工复核。
SCENE_SYNONYMS = {
    "城市": ["city", "street", "urban", "通勤", "commute"],
    "街道": ["street", "city", "road", "urban"],
    "办公室": ["office", "desk", "laptop", "work", "职场"],
    "工作": ["work", "office", "desk", "career"],
    "家": ["home", "room", "interior", "house"],
    "房间": ["room", "interior", "home"],
    "宝宝": ["baby", "child", "newborn", "care"],
    "孩子": ["child", "kid", "family"],
    "月子": ["postpartum", "baby", "care", "newborn"],
    "护理": ["care", "hands", "nurse", "照护"],
    "照顾": ["care", "hands", "help"],
    "食物": ["food", "meal", "tray", "nutrition"],
    "餐": ["food", "meal", "tray"],
    "营养": ["nutrition", "food", "meal"],
    "自然": ["nature", "tree", "leaf", "outdoor", "阳光"],
    "阳光": ["sunlight", "sun", "warm", "nature"],
    "户外": ["outdoor", "nature", "park"],
    "科技": ["tech", "technology", "data", "screen", "abstract"],
    "数据": ["data", "chart", "screen", "tech"],
    "屏幕": ["screen", "ui", "interface", "tech"],
    "时间": ["time", "clock", "waiting"],
    "等待": ["waiting", "clock", "time", "patience"],
    "焦虑": ["anxious", "stress", "worry", "dark"],
    "安静": ["quiet", "calm", "peaceful", "soft"],
    "休息": ["rest", "relax", "calm", "quiet"],
    "茶": ["tea", "cup", "calm", "quiet"],
    "车": ["car", "drive", "seat", "commute"],
    "接送": ["car", "drive", "commute", "seat"],
    "门": ["door", "doorway", "home", "arrival"],
    "半夜": ["night", "dark", "late", "quiet"],
    "夜": ["night", "dark", "city"],
    "放心": ["trust", "care", "safe", "warm"],
    "安心": ["safe", "trust", "calm", "warm"],
    "温暖": ["warm", "soft", "care", "healing"],
    "专业": ["professional", "clean", "corporate", "medical"],
    "快乐": ["happy", "joy", "bright", "playful"],
    "成长": ["growth", "child", "future", "progress"],
}


class AssetError(RuntimeError):
    """素材库操作失败；消息要能直接告诉用户下一步做什么。"""


# ------------------------------------------------------------------ 路径与序列化

def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def default_library_root() -> Path:
    env = os.environ.get("KOUBO_ASSET_LIBRARY")
    if env:
        return Path(env).expanduser().resolve()
    return repo_root() / "assets" / "library"


def resolve_library_root(root: str | Path | None = None) -> Path:
    return Path(root).expanduser().resolve() if root else default_library_root()


def today() -> str:
    return date.today().isoformat()


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _safe_rel(value: str | Path) -> str:
    raw = str(value).replace("\\", "/")
    if raw.startswith("/") or re.match(r"^[A-Za-z]:", raw):
        raise AssetError(f"素材库里的路径必须是相对路径：{raw}")
    parts = [p for p in raw.split("/") if p not in ("", ".")]
    if any(p == ".." for p in parts):
        raise AssetError(f"路径不能跳出素材库：{raw}")
    if not parts:
        raise AssetError("路径为空")
    return "/".join(parts)


def _write_text_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def _write_json_atomic(path: Path, data) -> None:
    _write_text_atomic(path, json.dumps(data, ensure_ascii=False, indent=2) + "\n")


def normalize_kind(kind: str) -> str:
    key = str(kind or "").strip().casefold()
    got = KIND_ALIASES.get(key, key)
    if got not in KINDS:
        raise AssetError(f"未知素材类型 {kind!r}；可用：{', '.join(KINDS)}")
    return got


def slugify(text: str, *, fallback: str = "asset", limit: int = 60) -> str:
    value = unicodedata.normalize("NFKC", str(text or "")).strip().casefold()
    value = re.sub(r"[^\w\u4e00-\u9fff-]+", "-", value, flags=re.UNICODE)
    value = re.sub(r"-{2,}", "-", value).strip("-_")
    return (value[:limit].strip("-_") or fallback)


def asset_id(kind: str, slug: str) -> str:
    return f"{normalize_kind(kind)}/{slugify(slug)}"


def sha256_file(path: str | Path) -> str:
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def entry_abs(entry: dict, library_root: str | Path | None = None,
              project: str | Path | None = None) -> Path:
    base = str(entry.get("base") or "library")
    rel = _safe_rel(entry.get("path") or "")
    if base == "repo":
        root = repo_root()
    elif base == "library":
        root = resolve_library_root(library_root)
    elif base == "project":
        if not project:
            raise AssetError(f"{entry.get('id')} 是工程内素材，需要 project 路径才能解析")
        root = Path(project).expanduser().resolve()
    else:
        raise AssetError(f"{entry.get('id')} 的 base 不认识：{base}")
    return (root / rel).resolve()


# ------------------------------------------------------------------ 探测

def probe_file(path: str | Path) -> dict:
    p = Path(path)
    suffix = p.suffix.lower()
    out: dict = {"format": suffix.lstrip(".") or None}
    if suffix in MEDIA_SUFFIXES:
        try:
            info = probe_media(p)
            out.update({
                "duration": round(float(info.get("duration") or 0.0), 3) or None,
                "width": info.get("width"), "height": info.get("height"),
                "has_audio": bool(info.get("has_audio")),
                "video_codec": info.get("video_codec"),
                "audio_codec": info.get("audio_codec"),
            })
        except (Exception, SystemExit) as exc:  # ffprobe 缺失/坏文件都不该阻断入库
            lines = [x.strip() for x in str(exc).splitlines() if x.strip()]
            detail = lines[-1][:160] if lines else str(exc)[:160]
            out["probe_error"] = f"{type(exc).__name__}: {detail}"
    elif suffix in IMAGE_SUFFIXES:
        try:
            from PIL import Image
            with Image.open(p) as im:
                out["width"], out["height"] = im.size
        except Exception as exc:  # noqa: BLE001
            out["probe_error"] = f"{type(exc).__name__}: {str(exc)[:160]}"
    out["bytes"] = p.stat().st_size if p.is_file() else None
    return out


# ------------------------------------------------------------------ 记录

def _as_list(value) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [x.strip() for x in re.split(r"[,，;；/|]+", value) if x.strip()]
    if isinstance(value, (list, tuple, set)):
        return [str(x).strip() for x in value if str(x).strip()]
    return [str(value).strip()] if str(value).strip() else []


def _as_float(value) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _as_int(value) -> int | None:
    number = _as_float(value)
    return int(round(number)) if number is not None else None




def build_entry(*, ident: str, kind: str, base: str, path: str,
                library_root: str | Path | None = None,
                project: str | Path | None = None,
                title: str | None = None,
                license_key: str = "unknown",
                provider: str = "local",
                probe: bool = True,
                **meta) -> dict:
    """构造一条完整记录；文件必须存在。元数据里没有的字段不会凭空生成。"""
    kind = normalize_kind(kind)
    rel = _safe_rel(path)
    if base not in ("repo", "library", "project"):
        raise AssetError(f"base 必须是 repo/library/project：{base}")
    file = entry_abs({"id": ident, "base": base, "path": rel}, library_root, project)
    if not file.is_file():
        raise AssetError(f"素材文件不存在：{file}")

    probe_info = probe_file(file) if probe else {
        "format": file.suffix.lower().lstrip(".") or None,
        "bytes": file.stat().st_size,
    }
    explicit_duration = meta.pop("duration", None)
    explicit_width = meta.pop("width", None)
    explicit_height = meta.pop("height", None)
    info = lic.license_info(license_key)
    checked_at = str(meta.pop("license_checked_at", "") or today())
    snapshot = {
        "id": info["id"], "name": info["name"], "url": info["url"],
        "commercial": info.get("commercial"), "attribution": info.get("attribution"),
        "redistribute": info.get("redistribute"), "checked_at": checked_at,
    }
    entry = {
        "id": ident,
        "kind": kind,
        "title": str(title or meta.pop("title", "") or file.stem),
        "base": base,
        "path": rel,
        "sha256": sha256_file(file),
        "bytes": probe_info.get("bytes"),
        "format": probe_info.get("format"),
        "duration": probe_info.get("duration") if probe_info.get("duration") is not None
        else _as_float(explicit_duration),
        "width": probe_info.get("width") if probe_info.get("width") is not None
        else _as_int(explicit_width),
        "height": probe_info.get("height") if probe_info.get("height") is not None
        else _as_int(explicit_height),
        "has_audio": probe_info.get("has_audio"),
        "video_codec": probe_info.get("video_codec"),
        "audio_codec": probe_info.get("audio_codec"),
        "tags": _as_list(meta.pop("tags", None)),
        "mood": _as_list(meta.pop("mood", None)),
        "scene": _as_list(meta.pop("scene", None)),
        "use_for": _as_list(meta.pop("use_for", None)),
        "avoid_for": _as_list(meta.pop("avoid_for", None)),
        "sync": meta.pop("sync", None),
        "bpm": _as_float(meta.pop("bpm", None)),
        "energy": _as_int(meta.pop("energy", None)),
        "under_voiceover_db": _as_float(meta.pop("under_voiceover_db", None)),
        "fits_seconds": meta.pop("fits_seconds", None),
        "pairs_with": meta.pop("pairs_with", None),
        "variant": meta.pop("variant", None),
        "character": meta.pop("character", None),
        "provider": str(meta.pop("provider", "") or provider),
        "provider_id": meta.pop("provider_id", None),
        "creator": meta.pop("creator", None),
        "creator_url": meta.pop("creator_url", None),
        "source_url": meta.pop("source_url", None),
        "download_url": meta.pop("download_url", None),
        "page_url": meta.pop("page_url", None),
        "query": meta.pop("query", None),
        "downloaded_at": meta.pop("downloaded_at", None),
        "license": info["id"],
        "license_name": info["name"],
        "license_url": info["url"],
        "commercial": info.get("commercial"),
        "attribution": info.get("attribution"),
        "redistribute": info.get("redistribute"),
        "review_required": info.get("review_required"),
        "notice_required": info.get("notice_required"),
        "license_checked_at": checked_at,
        "license_snapshot": snapshot,
        "bundled": bool(meta.pop("bundled", False)),
        "tier": meta.pop("tier", None),
        "alt": meta.pop("alt", None),
        "focus": meta.pop("focus", None),
        "notes": str(meta.pop("notes", "") or ""),
        "added_at": meta.pop("added_at", None) or now_iso(),
        "updated_at": now_iso(),
    }
    if probe_info.get("probe_error"):
        entry["probe_error"] = probe_info["probe_error"]
    extra = {k: v for k, v in meta.items() if v not in (None, "", [], {})}
    if extra:
        entry["extra"] = extra
    return entry


def merge_entry(old: dict, new: dict) -> dict:
    """刷新时保留人工填的字段（授权、来源、标签），只更新文件派生字段。"""
    merged = dict(old)
    for key in ("sha256", "bytes", "format", "duration", "width", "height",
                "has_audio", "video_codec", "audio_codec", "probe_error",
                "updated_at"):
        if key in new:
            merged[key] = new[key]
        elif key == "probe_error":
            merged.pop("probe_error", None)
    for key in ("license", "license_name", "license_url", "commercial", "attribution",
                "redistribute", "review_required", "notice_required",
                "license_checked_at", "license_snapshot", "provider", "provider_id",
                "creator", "creator_url", "source_url", "download_url", "page_url",
                "tags", "mood", "scene", "use_for", "avoid_for", "title", "notes",
                "bundled", "tier", "alt", "focus"):
        if key not in old and key in new:
            merged[key] = new[key]
    return merged


# ------------------------------------------------------------------ registry

def registry_path(root: str | Path | None = None) -> Path:
    return resolve_library_root(root) / REGISTRY_NAME


def load_registry(root: str | Path | None = None, *,
                  path: str | Path | None = None,
                  required: bool = False) -> list[dict]:
    target = Path(path) if path else registry_path(root)
    if not target.is_file():
        if required:
            raise AssetError(f"找不到素材索引 {target}；先跑 `koubo assets init`")
        return []
    entries: list[dict] = []
    seen: dict[str, int] = {}
    for lineno, line in enumerate(target.read_text(encoding="utf-8").splitlines(), 1):
        text = line.strip()
        if not text or text.startswith(("#", "//")):
            continue
        try:
            entry = json.loads(text)
        except ValueError as exc:
            raise AssetError(f"{target}:{lineno} 不是合法 JSON：{exc}") from exc
        if not isinstance(entry, dict):
            raise AssetError(f"{target}:{lineno} 不是对象")
        ident = str(entry.get("id") or "").strip()
        if not ident:
            raise AssetError(f"{target}:{lineno} 缺 id")
        if ident in seen:
            raise AssetError(f"{target}:{lineno} id 重复：{ident}（首次在第 {seen[ident]} 行）")
        seen[ident] = lineno
        entry.setdefault("kind", ident.split("/", 1)[0])
        entry.setdefault("base", "library")
        entry.setdefault("path", "")
        entries.append(entry)
    return entries


def save_registry(entries: list[dict], root: str | Path | None = None, *,
                  path: str | Path | None = None) -> Path:
    target = Path(path) if path else registry_path(root)
    bad = [e.get("id") for e in entries if str(e.get("base") or "library") == "project"]
    if bad:
        raise AssetError("工程内素材用 sidecar，不进共享 registry：" + "、".join(bad[:3]))
    ordered = sorted(entries, key=lambda e: str(e.get("id") or ""))
    lines = [json.dumps(e, ensure_ascii=False, sort_keys=True) for e in ordered]
    _write_text_atomic(target, "\n".join(lines) + ("\n" if lines else ""))
    return target


def upsert_entry(entries: list[dict], entry: dict) -> list[dict]:
    ident = str(entry["id"])
    out = [e for e in entries if str(e.get("id")) != ident]
    out.append(entry)
    return out


def resolve_id(entries: list[dict], value: str) -> dict:
    ident = str(value or "").strip()
    if ident.startswith("asset:"):
        ident = ident[6:]
    if not ident:
        raise AssetError("缺少素材 ID")
    exact = [e for e in entries if str(e.get("id")) == ident]
    if len(exact) == 1:
        return exact[0]
    low = ident.casefold()
    ci = [e for e in entries if str(e.get("id")).casefold() == low]
    if len(ci) == 1:
        return ci[0]
    suffix = [e for e in entries if str(e.get("id")).casefold().endswith("/" + low)]
    if len(suffix) == 1:
        return suffix[0]
    if len(suffix) > 1:
        raise AssetError(f"ID {ident!r} 不唯一：" + "、".join(str(e["id"]) for e in suffix[:6]))
    raise AssetError(f"素材库里没有 {ident!r}；用 `koubo assets search` 找 ID")


def resolve_ref(ref: str, *, library_root: str | Path | None = None,
                project: str | Path | None = None,
                entries: list[dict] | None = None) -> dict:
    """解析 `asset:<id>` 或普通路径。

    返回 `{id, kind, path, entry}`。`asset:` 引用是稳定调用：ID 不变，路径可以变。
    """
    text = str(ref or "").strip()
    if not text:
        raise AssetError("引用为空")
    if text.startswith(("asset:", "library:")):
        ident = text.split(":", 1)[1]
        pool = entries if entries is not None else load_registry(library_root)
        entry = resolve_id(pool, ident)
        file = entry_abs(entry, library_root, project)
        if not file.is_file():
            raise AssetError(f"{entry['id']} 指向的文件不存在：{file}")
        return {"id": entry["id"], "kind": entry.get("kind"), "path": str(file),
                "entry": entry}
    p = Path(text).expanduser()
    if not p.is_absolute():
        base = Path(project) if project else Path.cwd()
        p = base / p
    p = p.resolve()
    return {"id": None, "kind": None, "path": str(p), "entry": None}


# ------------------------------------------------------------------ sidecar

def sidecar_path(file: str | Path) -> Path:
    p = Path(file)
    return p.with_name(p.name + SIDECAR_SUFFIX)


def write_sidecar(file: str | Path, entry: dict) -> Path:
    """在素材旁边写 `.asset.json`；工程内素材靠它随工程走，不依赖共享索引。"""
    target = sidecar_path(file)
    data = {k: v for k, v in entry.items() if k not in ("probe_error",)}
    _write_json_atomic(target, data)
    return target


def read_sidecar(file: str | Path) -> dict | None:
    target = sidecar_path(file)
    if not target.is_file():
        return None
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise AssetError(f"sidecar 读不出来 {target}：{exc}") from exc
    if not isinstance(data, dict):
        raise AssetError(f"sidecar 不是对象：{target}")
    return data


def sidecar_entry(file: str | Path, *, base: str = "project",
                  library_root: str | Path | None = None,
                  project: str | Path | None = None) -> dict | None:
    data = read_sidecar(file)
    if not data:
        return None
    p = Path(file).resolve()
    root = repo_root() if base == "repo" else (
        Path(project).resolve() if base == "project" and project else
        resolve_library_root(library_root))
    try:
        rel = str(p.relative_to(root)).replace(os.sep, "/")
    except ValueError:
        rel = Path(file).name
    ident = str(data.get("id") or asset_id(str(data.get("kind") or "broll"), p.stem))
    skip = {"id", "kind", "base", "path", "title", "license", "provider",
            "sha256", "bytes", "format",
            "has_audio", "video_codec", "audio_codec", "probe_error", "updated_at",
            "commercial", "attribution", "redistribute", "review_required",
            "notice_required", "license_name", "license_url", "license_snapshot",
            "path_abs"}
    meta = {k: v for k, v in data.items() if k not in skip}
    return build_entry(ident=ident, kind=str(data.get("kind") or "broll"),
                       base=base, path=rel, library_root=library_root,
                       project=project,
                       title=data.get("title"),
                       license_key=data.get("license") or "unknown",
                       provider=str(data.get("provider") or "local"),
                       **meta)


# ------------------------------------------------------------------ 入库 / 扫描

def _dest_rel(kind: str, slug: str, suffix: str, *, scope: str) -> str:
    ext = suffix if suffix.startswith(".") else ("." + suffix if suffix else "")
    if scope == "project":
        project_dirs = {
            "broll": "input/broll", "still": "assets/stills",
            "illustration": "assets/illustrations", "sticker": "assets/stickers",
            "sfx": "assets/sfx", "bgm": "assets/audio/bgm",
            "overlay": "assets/overlays", "font": "assets/fonts",
            "template": "assets/templates", "caption": "assets/captions",
        }
        return f"{project_dirs.get(kind, 'assets/' + DIR_BY_KIND[kind])}/{slug}{ext}"
    return f"{DIR_BY_KIND[kind]}/{slug}{ext}"


def _unique_id(entries: list[dict], base_ident: str) -> str:
    taken = {str(e.get("id")) for e in entries}
    if base_ident not in taken:
        return base_ident
    for i in range(2, 1000):
        candidate = f"{base_ident}-{i}"
        if candidate not in taken:
            return candidate
    raise AssetError(f"ID {base_ident} 的变体太多")


def _entry_path_or_none(entry: dict, root: str | Path | None = None,
                        project: str | Path | None = None) -> Path | None:
    try:
        return entry_abs(entry, root, project)
    except AssetError:
        return None


def ingest_file(source: str | Path, *, kind: str, license_key: str,
                library_root: str | Path | None = None,
                project: str | Path | None = None,
                scope: str = "library",
                copy: bool = True,
                ident: str | None = None,
                dest_rel: str | None = None,
                allow_unknown: bool = False,
                write_registry_file: bool = True,
                **meta) -> dict:
    """把一个文件登记进素材库。

    - `scope="library"`：复制到 `assets/library/<kind目录>/`，写 sidecar + registry；
    - `scope="project"`：复制到工程内（B-roll → `input/broll/`），只写 sidecar；
    - `copy=False`：文件必须已经在目标根内，原地登记。

    授权必须显式给；`license=unknown` 需要 `allow_unknown=True`，用于「先入库、再补授权」
    的扫描场景，正常入库不该走这条。
    """
    kind = normalize_kind(kind)
    root = resolve_library_root(library_root)
    if scope not in ("library", "project"):
        raise AssetError("scope 必须是 library 或 project")
    if scope == "project" and not project:
        raise AssetError("scope=project 需要 project 路径")
    src = Path(source).expanduser().resolve()
    if not src.is_file():
        raise AssetError(f"找不到素材：{src}")
    key = lic.normalize_license(license_key)
    if key == "unknown" and not allow_unknown:
        raise AssetError("授权未知不能入库；给 --license（如 CC0-1.0 / OFL-1.1），"
                         "或明确加 --allow-unknown 先登记待核")
    target_root = Path(project).expanduser().resolve() if scope == "project" else root
    base = "project" if scope == "project" else "library"
    suffix = src.suffix.lower()
    slug = slugify(ident.split("/", 1)[-1] if ident else src.stem)
    rel = _safe_rel(dest_rel) if dest_rel else _dest_rel(kind, slug, suffix, scope=scope)
    dest = (target_root / rel).resolve()
    if target_root not in dest.parents and dest != target_root:
        raise AssetError(f"目标路径跳出工程/素材库：{dest}")

    entries = load_registry(root) if base == "library" else []

    if not copy:
        try:
            rel = str(src.relative_to(target_root)).replace(os.sep, "/")
        except ValueError as exc:
            raise AssetError(f"--no-copy 时文件必须在 {target_root} 内：{src}") from exc
        dest = src
    else:
        dest.parent.mkdir(parents=True, exist_ok=True)
        if dest.exists():
            if sha256_file(dest) != sha256_file(src):
                raise AssetError(f"目标已存在且内容不同：{dest}；换 --id 或 --dest")
            # 内容相同 = 同一条素材。先按路径/sidecar 找回原 ID，不能造出
            # 「两份索引指向同一个文件」这种脏数据。
            existing = next((e for e in entries if e.get("base") == base
                             and _entry_path_or_none(e, root, project) == dest), None)
            if existing:
                if ident and str(ident) != str(existing["id"]):
                    raise AssetError(f"文件已登记为 {existing['id']}，与 --id {ident} 冲突")
                return existing
            try:
                sc = sidecar_entry(dest, base=base, library_root=root, project=project)
            except AssetError:
                sc = None
            if sc:
                if ident and str(ident) != str(sc["id"]):
                    raise AssetError(f"文件已有 sidecar {sc['id']}，与 --id {ident} 冲突")
                if base == "library" and write_registry_file:
                    save_registry(upsert_entry(entries, sc), root)
                return sc
        elif dest.resolve() != src:
            shutil.copy2(src, dest)
        else:
            dest = src

    if ident:
        base_ident = str(ident) if "/" in str(ident) else asset_id(kind, str(ident))
    else:
        base_ident = asset_id(kind, slug)
    if base == "library":
        base_ident = _unique_id(entries, base_ident)

    entry = build_entry(ident=base_ident, kind=kind, base=base, path=rel,
                        library_root=root, project=project,
                        license_key=key, **meta)
    write_sidecar(dest, entry)
    if base == "library" and write_registry_file:
        save_registry(upsert_entry(entries, entry), root)
    return entry


def scan_library(root: str | Path | None = None, *, refresh: bool = False,
                 dry_run: bool = False, fast: bool = False,
                 kinds: list[str] | None = None) -> dict:
    """扫 `assets/library/`，把新文件登记为 `license=unknown` 的待核条目。

    扫描**不会**替用户编授权：新文件一律 `unknown`，`verify` 会记 unchecked。
    已经有 sidecar 的按 sidecar 走；已经登记的默认跳过，`--refresh` 只更新文件派生字段。
    """
    root = resolve_library_root(root)
    entries = load_registry(root)
    wanted = {normalize_kind(k) for k in kinds} if kinds else None
    added, updated, skipped, warnings = [], [], [], []
    for directory in sorted({DIR_BY_KIND[k].split("/")[0] for k in KINDS}):
        base_dir = root / directory
        if not base_dir.is_dir():
            continue
        for file in sorted(base_dir.rglob("*")):
            if not file.is_file() or file.name.startswith("."):
                continue
            if file.name in {REGISTRY_NAME, LEDGER_NAME, "README.md", "licenses.local.json"}:
                continue
            if file.name.endswith(SIDECAR_SUFFIX) or file.name == ".gitkeep":
                continue
            rel = str(file.relative_to(root)).replace(os.sep, "/")
            kind = _kind_from_rel(rel)
            if not kind or (wanted and kind not in wanted):
                warnings.append(f"跳过无法归类的文件：{rel}")
                continue
            existing = next((e for e in entries if e.get("base") == "library"
                             and str(e.get("path")) == rel), None)
            try:
                sc = sidecar_entry(file, base="library", library_root=root)
            except AssetError as exc:
                warnings.append(str(exc))
                continue
            if sc:
                if existing and not refresh:
                    skipped.append(sc["id"])
                    continue
                entries = upsert_entry(entries, sc)
                (updated if existing else added).append(sc["id"])
                continue
            if existing:
                if not refresh:
                    skipped.append(str(existing["id"]))
                    continue
                ident = str(existing["id"])
                try:
                    fresh = build_entry(ident=ident, kind=kind, base="library", path=rel,
                                        library_root=root, probe=not fast,
                                        license_key=existing.get("license") or "unknown",
                                        **_preserved_meta(existing))
                except AssetError as exc:
                    warnings.append(str(exc))
                    continue
                entries = upsert_entry(entries, merge_entry(existing, fresh))
                updated.append(ident)
                continue
            ident = _unique_id(entries, asset_id(kind, file.stem))
            try:
                entry = build_entry(ident=ident, kind=kind, base="library", path=rel,
                                    library_root=root, license_key="unknown",
                                    provider="local", probe=not fast,
                                    notes="扫描入库：授权未填，商用前必须补 --license",
                                    tags=_tags_from_rel(rel))
            except AssetError as exc:
                warnings.append(str(exc))
                continue
            entries = upsert_entry(entries, entry)
            if not dry_run:
                try:
                    write_sidecar(file, entry)
                except OSError as exc:
                    warnings.append(f"写 sidecar 失败 {file}：{exc}")
            added.append(ident)
    if not dry_run:
        save_registry(entries, root)
    return {"root": str(root), "added": added, "updated": updated,
            "skipped": len(skipped), "warnings": warnings,
            "total": len(entries), "dry_run": dry_run}


def _preserved_meta(entry: dict) -> dict:
    keys = ("title", "provider", "provider_id", "creator", "creator_url", "source_url",
            "download_url", "page_url", "query", "downloaded_at", "tags", "mood",
            "scene", "use_for", "avoid_for", "sync", "bpm", "energy",
            "under_voiceover_db", "fits_seconds", "pairs_with", "variant",
            "character", "bundled", "tier", "alt", "focus", "notes",
            "license_checked_at", "added_at")
    return {k: entry[k] for k in keys if k in entry}


def _kind_from_rel(rel: str) -> str | None:
    parts = rel.split("/")
    if len(parts) < 2:
        return None
    head = "/".join(parts[:2])
    mapping = {
        "audio/bgm": "bgm", "audio/sfx": "sfx",
        "video/broll": "broll", "video/overlays": "overlay",
        "graphics/stickers": "sticker", "graphics/fonts": "font",
        "graphics/illustrations": "illustration", "graphics/stills": "still",
        "templates/jianying": "template", "templates/captions": "caption",
    }
    if head in mapping:
        return mapping[head]
    if parts[0] == "templates":
        return "template"
    return None


def _tags_from_rel(rel: str) -> list[str]:
    parts = rel.split("/")[:-1]
    out = []
    for part in parts:
        if part in ("audio", "video", "graphics", "templates", "bgm", "sfx",
                    "broll", "overlays", "stickers", "fonts", "illustrations",
                    "stills", "jianying", "captions"):
            continue
        out.append(part)
    return out


# ------------------------------------------------------------------ 内置素材

def seed_bundled(root: str | Path | None = None, *, force: bool = False) -> dict:
    """把随包素材（音效/插图/动效）登记进索引；已存在的用户条目默认不覆盖。"""
    root = resolve_library_root(root)
    entries = load_registry(root)
    by_id = {str(e.get("id")): e for e in entries}
    added, updated, skipped, warnings = [], [], [], []

    # 音效：assets/sfx/manifest.json
    sfx_manifest = repo_root() / "assets" / "sfx" / "manifest.json"
    if sfx_manifest.is_file():
        try:
            data = json.loads(sfx_manifest.read_text(encoding="utf-8"))
        except ValueError as exc:
            warnings.append(f"音效 manifest 读不出来：{exc}")
            data = {}
        for key, item in (data or {}).items():
            if key.startswith("_") or not isinstance(item, dict):
                continue
            file = str(item.get("file") or f"{key}.mp3")
            meta = {k: item[k] for k in ("tags", "mood", "scene", "use_for", "avoid_for",
                                         "sync", "bpm", "energy", "under_voiceover_db",
                                         "fits_seconds", "pairs_with", "variant",
                                         "character", "notes") if k in item}
            try:
                entry = build_entry(
                    ident=f"sfx/{key}", kind="sfx", base="repo",
                    path=f"assets/sfx/{file}", library_root=root,
                    title=str(item.get("title") or key),
                    license_key=str(item.get("license") or "Pixabay-Content-License"),
                    provider="pixabay", bundled=True,
                    source_url=item.get("source_url") or None,
                    notes=meta.pop("notes", "") or "随包真实采样；原始来源 URL 未逐条留存",
                    **meta)
            except AssetError as exc:
                warnings.append(str(exc))
                continue
            ident = str(entry["id"])
            if ident in by_id and not force:
                skipped.append(ident)
            else:
                existed = ident in by_id
                if existed:
                    entry["added_at"] = by_id[ident].get("added_at") or entry.get("added_at")
                entries[:] = upsert_entry(entries, entry)
                by_id[ident] = entry
                (updated if existed else added).append(ident)

    # 插图：assets/illustrations/manifest.json
    ill_manifest = repo_root() / "assets" / "illustrations" / "manifest.json"
    if ill_manifest.is_file():
        try:
            data = json.loads(ill_manifest.read_text(encoding="utf-8"))
        except ValueError as exc:
            warnings.append(f"插图 manifest 读不出来：{exc}")
            data = {}
        for item in (data or {}).get("items") or []:
            if not isinstance(item, dict) or not item.get("file"):
                continue
            ident = f"illustration/{item.get('id') or Path(item['file']).stem}"
            try:
                entry = build_entry(
                    ident=ident, kind="illustration", base="repo",
                    path=f"assets/illustrations/{item['file']}", library_root=root,
                    title=str(item.get("alt") or item.get("id") or Path(item["file"]).stem),
                    license_key=str(item.get("license") or "project-owned"),
                    provider="project", bundled=True, tier=item.get("tier"),
                    focus=item.get("focus"), tags=item.get("tags"),
                    alt=item.get("alt"), notes="项目自绘 SVG/PNG")
            except AssetError as exc:
                warnings.append(str(exc))
                continue
            ident = str(entry["id"])
            if ident in by_id and not force:
                skipped.append(ident)
            else:
                existed = ident in by_id
                if existed:
                    entry["added_at"] = by_id[ident].get("added_at") or entry.get("added_at")
                entries[:] = upsert_entry(entries, entry)
                by_id[ident] = entry
                (updated if existed else added).append(ident)

    # 动效：assets/motion/manifest.json（没有就只登记已知文件）
    motion_manifest = repo_root() / "assets" / "motion" / "manifest.json"
    motion_items: list[dict] = []
    if motion_manifest.is_file():
        try:
            data = json.loads(motion_manifest.read_text(encoding="utf-8"))
            motion_items = (data.get("items") if isinstance(data, dict) else data) or []
        except ValueError as exc:
            warnings.append(f"动效 manifest 读不出来：{exc}")
    if not motion_items:
        motion_items = [{"id": p.stem, "file": p.name, "title": p.stem,
                         "tags": ["motion", "overlay"]}
                        for p in sorted((repo_root() / "assets" / "motion").glob("*.html"))]
    for item in motion_items:
        if not isinstance(item, dict) or not item.get("file"):
            continue
        ident = f"overlay/{item.get('id') or Path(item['file']).stem}"
        try:
            entry = build_entry(
                ident=ident, kind="overlay", base="repo",
                path=f"assets/motion/{item['file']}", library_root=root,
                title=str(item.get("title") or item.get("id") or Path(item["file"]).stem),
                license_key=str(item.get("license") or "project-owned"),
                provider="project", bundled=True, tags=item.get("tags"),
                notes="项目自绘 HTML/Canvas 动效")
        except AssetError as exc:
            warnings.append(str(exc))
            continue
        ident = str(entry["id"])
        if ident in by_id and not force:
            skipped.append(ident)
        else:
            existed = ident in by_id
            if existed:
                entry["added_at"] = by_id[ident].get("added_at") or entry.get("added_at")
            entries[:] = upsert_entry(entries, entry)
            by_id[ident] = entry
            (updated if existed else added).append(ident)

    if entries:
        save_registry(entries, root)
    return {"root": str(root), "added": added, "updated": updated,
            "skipped": skipped, "warnings": warnings, "total": len(entries)}


EXTRA_DIRS = ("templates/jianying",)


def init_library(root: str | Path | None = None, *, seed: bool = True) -> dict:
    root = resolve_library_root(root)
    for rel in sorted(set(DIR_BY_KIND.values()) | set(EXTRA_DIRS)):
        directory = root / rel
        directory.mkdir(parents=True, exist_ok=True)
        keep = directory / ".gitkeep"
        if not keep.exists():
            keep.write_text("", encoding="utf-8")
    if not registry_path(root).is_file():
        save_registry([], root)
    seeded = seed_bundled(root) if seed else {"added": [], "warnings": []}
    return {"root": str(root), "seeded": seeded,
            "registry": str(registry_path(root))}


# ------------------------------------------------------------------ 查询

def _cjk_ngrams(text: str) -> list[str]:
    out = []
    for run in re.findall(r"[\u4e00-\u9fff]+", text):
        for n in range(min(4, len(run)), 1, -1):
            for i in range(len(run) - n + 1):
                token = run[i:i + n]
                if token not in _STOPWORDS:
                    out.append(token)
    return out


def _tokens(query: str | list[str] | None) -> list[str]:
    if not query:
        return []
    if isinstance(query, list):
        raw = [str(x) for x in query]
    else:
        raw = [str(query)]
    out: list[str] = []
    for item in raw:
        out.extend(re.findall(r"[a-z0-9]+", item.casefold()))
        out.extend(_cjk_ngrams(item))
        out.extend(x for x in re.split(r"[,，;；\s]+", item) if x)
    seen, unique = set(), []
    for token in out:
        token = token.strip().casefold()
        if len(token) < 2 or token in seen or token in _STOPWORDS:
            continue
        seen.add(token)
        unique.append(token)
    return unique[:40]


def _entry_blob(entry: dict) -> str:
    parts = [
        entry.get("id"), entry.get("title"), entry.get("provider"),
        entry.get("creator"), entry.get("notes"), entry.get("alt"),
        entry.get("license_name"),
        " ".join(_as_list(entry.get("tags"))),
        " ".join(_as_list(entry.get("mood"))),
        " ".join(_as_list(entry.get("scene"))),
        " ".join(_as_list(entry.get("use_for"))),
        " ".join(_as_list(entry.get("avoid_for"))),
    ]
    extra = entry.get("extra")
    if isinstance(extra, dict):
        parts.append(" ".join(str(v) for v in extra.values() if isinstance(v, (str, int, float))))
    return " ".join(str(x) for x in parts if x).casefold()


def _score_entry(entry: dict, tokens: list[str]) -> tuple[float, list[str]]:
    score = 0.0
    reasons: list[str] = []
    tags = [str(x).casefold() for x in _as_list(entry.get("tags"))]
    title = str(entry.get("title") or "").casefold()
    use_for = " ".join(_as_list(entry.get("use_for"))).casefold()
    avoid_for = " ".join(_as_list(entry.get("avoid_for"))).casefold()
    blob = _entry_blob(entry)
    for token in tokens:
        if token in tags:
            score += 4 + min(len(token), 4)
            reasons.append(f"tag:{token}")
        elif token in title:
            score += 3
            reasons.append(f"标题:{token}")
        elif token in use_for:
            score += 2
            reasons.append(f"适用:{token}")
        elif token in blob:
            score += 1
            reasons.append(f"描述:{token}")
        if token in avoid_for:
            score -= 2
            reasons.append(f"避用:{token}")
    return score, reasons


def search(entries: list[dict], query: str | list[str] | None = None, *,
           kinds: list[str] | None = None,
           tags: list[str] | None = None,
           any_tags: bool = False,
           mood: str | None = None,
           scene: str | None = None,
           providers: list[str] | None = None,
           license_key: str | None = None,
           commercial_only: bool = False,
           min_duration: float | None = None,
           max_duration: float | None = None,
           has_sync: bool | None = None,
           limit: int | None = None,
           sort: str = "relevance",
           library_root: str | Path | None = None,
           project: str | Path | None = None) -> list[dict]:
    """按元数据召回；返回带 `score/reasons/path` 的命中，不替用户决定。"""
    wanted_kinds = {normalize_kind(k) for k in kinds} if kinds else None
    want_tags = [str(t).casefold() for t in _as_list(tags)]
    want_providers = {str(p).casefold() for p in _as_list(providers)}
    tokens = _tokens(query)
    hits = []
    for entry in entries:
        kind = str(entry.get("kind") or "")
        if wanted_kinds and kind not in wanted_kinds:
            continue
        etags = [str(t).casefold() for t in _as_list(entry.get("tags"))]
        if want_tags:
            matched = sum(1 for t in want_tags if t in etags)
            if any_tags and not matched:
                continue
            if not any_tags and matched != len(want_tags):
                continue
        if mood and str(mood).casefold() not in [m.casefold() for m in _as_list(entry.get("mood"))]:
            continue
        if scene and str(scene).casefold() not in [s.casefold() for s in _as_list(entry.get("scene"))]:
            continue
        if want_providers and str(entry.get("provider") or "").casefold() not in want_providers:
            continue
        if license_key and lic.normalize_license(entry.get("license")) != lic.normalize_license(license_key):
            continue
        if commercial_only and lic.license_info(entry.get("license")).get("commercial") is not True:
            continue
        duration = _as_float(entry.get("duration"))
        if min_duration is not None and (duration is None or duration < min_duration):
            continue
        if max_duration is not None and (duration is None or duration > max_duration):
            continue
        if has_sync is True and not entry.get("sync"):
            continue
        if has_sync is False and entry.get("sync"):
            continue
        score, reasons = _score_entry(entry, tokens) if tokens else (0.0, [])
        if tokens and score <= 0:
            continue
        hit = {"entry": entry, "score": round(score, 2), "reasons": reasons[:8]}
        try:
            hit["path"] = str(entry_abs(entry, library_root, project))
            hit["exists"] = Path(hit["path"]).is_file()
        except AssetError:
            hit["path"] = None
            hit["exists"] = False
        hits.append(hit)
    if sort == "duration":
        hits.sort(key=lambda h: (-h["score"], _as_float(h["entry"].get("duration")) or 0))
    elif sort == "title":
        hits.sort(key=lambda h: (-h["score"], str(h["entry"].get("title") or "")))
    else:
        hits.sort(key=lambda h: (-h["score"], str(h["entry"].get("id") or "")))
    return hits[:limit] if limit else hits


def apply_license(entry: dict, license_key: str, *, checked_at: str | None = None,
                 notes: str | None = None) -> dict:
    """给已有记录补/改授权，并刷新许可快照；不写盘，调用方决定写 registry/sidecar。"""
    key = lic.normalize_license(license_key)
    info = lic.license_info(key)
    checked = str(checked_at or today())
    out = dict(entry)
    out.update({
        "license": key, "license_name": info["name"], "license_url": info["url"],
        "commercial": info.get("commercial"), "attribution": info.get("attribution"),
        "redistribute": info.get("redistribute"),
        "review_required": info.get("review_required"),
        "notice_required": info.get("notice_required"),
        "license_checked_at": checked,
        "license_snapshot": {
            "id": key, "name": info["name"], "url": info["url"],
            "commercial": info.get("commercial"),
            "attribution": info.get("attribution"),
            "redistribute": info.get("redistribute"), "checked_at": checked,
        },
        "updated_at": now_iso(),
    })
    if notes is not None:
        out["notes"] = notes
    return out


# ------------------------------------------------------------------ 核验

def verify_entries(entries: list[dict], *, library_root: str | Path | None = None,
                   project: str | Path | None = None, commercial: bool = True,
                   strict: bool = False, check_hash: bool = True,
                   now: date | None = None) -> dict:
    root = resolve_library_root(library_root)
    issues: list[dict] = []
    counts = {"pass": 0, "unchecked": 0, "fail": 0}
    seen_paths: dict[str, str] = {}
    for entry in entries:
        ident = str(entry.get("id") or "?")
        try:
            file = entry_abs(entry, root, project)
        except AssetError as exc:
            issues.append({"id": ident, "kind": entry.get("kind"), "status": "fail",
                           "path": None, "reasons": [str(exc)]})
            counts["fail"] += 1
            continue
        reasons: list[str] = []
        status = "pass"
        if not file.is_file():
            status = "fail"
            reasons.append(f"文件不存在：{file}")
        else:
            key = str(file)
            if key in seen_paths and seen_paths[key] != ident:
                status = "fail"
                reasons.append(f"同一文件被两个 ID 登记：{seen_paths[key]} / {ident}")
            seen_paths[key] = ident
            if check_hash and entry.get("sha256"):
                got = sha256_file(file)
                if got != entry.get("sha256"):
                    status = "fail"
                    reasons.append("sha256 与登记不一致；文件被替换过或登记过期，"
                                   "用 `koubo assets scan --refresh` 重新登记")
        result = lic.check(entry.get("license"), commercial=commercial,
                           attribution_exported=False,
                           snapshot=entry.get("license_snapshot"),
                           strict=strict, checked_at=entry.get("license_checked_at"),
                           now=now)
        rank = {"pass": 0, "unchecked": 1, "fail": 2}
        if rank[result["status"]] > rank[status]:
            status = result["status"]
        reasons.extend(result["reasons"])
        provider = str(entry.get("provider") or "local").casefold()
        if provider in _EXTERNAL_PROVIDERS and not entry.get("source_url") \
                and not entry.get("bundled"):
            if rank[status] < rank["unchecked"]:
                status = "unchecked"
            reasons.append("外部素材缺来源 URL；无法复核许可与作者")
        if not entry.get("license_checked_at"):
            if rank[status] < rank["unchecked"]:
                status = "unchecked"
            reasons.append("没有授权核验日期")
        counts[status] += 1
        issues.append({"id": ident, "kind": entry.get("kind"), "status": status,
                       "path": str(file), "title": entry.get("title"),
                       "license": entry.get("license"),
                       "reasons": list(dict.fromkeys(reasons))})
    return {"ok": counts["fail"] == 0, "root": str(root), "counts": counts,
            "entries": len(entries), "issues": issues,
            "policy": {"commercial": commercial, "strict": strict, "check_hash": check_hash}}


def preflight_issues(cfg: dict, project: str | Path) -> tuple[list[str], list[str]]:
    """frames 前的轻量检查：`asset:` 引用能不能解析、B-roll/音效文件在不在。"""
    project = Path(project)
    root = resolve_library_root((cfg.get("assets") or {}).get("library"))
    errors: list[str] = []
    warnings: list[str] = []
    try:
        entries = load_registry(root)
    except AssetError as exc:
        return [f"素材索引读不出来：{exc}"], []

    def check_ref(ref: str, where: str) -> None:
        text = str(ref or "").strip()
        if not text:
            return
        if text.startswith(("asset:", "library:")):
            try:
                got = resolve_ref(text, library_root=root, project=project, entries=entries)
            except AssetError as exc:
                errors.append(f"{where} 的 {text} 解析失败：{exc}")
                return
            if not Path(got["path"]).is_file():
                errors.append(f"{where} 的 {text} 指向的文件不存在：{got['path']}")

    for i, item in enumerate((cfg.get("broll") or {}).get("items") or [], 1):
        check_ref((item or {}).get("source"), f"broll #{i}")
    for i, event in enumerate((cfg.get("sfx") or {}).get("events") or [], 1):
        check_ref((event or {}).get("clip"), f"sfx #{i}")
    for i, item in enumerate((cfg.get("inserts") or {}).get("items") or [], 1):
        rel = (item or {}).get("illustration")
        if rel and not (project / "assets" / str(rel)).is_file():
            errors.append(f"inserts #{i} 的插图不存在：assets/{rel}")
    font = str((cfg.get("captions") or {}).get("font") or "")
    if font:
        try:
            from _common import find_font
            if not find_font(font, project):
                warnings.append(f"字幕字体 {font!r} 在本机找不到；渲染器可能回退")
        except Exception as exc:  # noqa: BLE001
            warnings.append(f"字体检查跳过：{type(exc).__name__}: {exc}")
    return errors, warnings


# ------------------------------------------------------------------ 工程用量 / 台账

def _synthetic_entry(*, kind: str, path: str | None, license_key: str,
                     title: str = "", provider: str = "project",
                     notes: str = "", source_url: str = "",
                     project: str | Path | None = None,
                     library_root: str | Path | None = None) -> dict:
    info = lic.license_info(license_key)
    rel = ""
    if path and project:
        try:
            rel = str(Path(path).resolve().relative_to(Path(project).resolve())).replace(os.sep, "/")
        except ValueError:
            rel = ""
    elif path:
        rel = str(path)
    ident = f"{kind}/{slugify(title or Path(path or '').stem or kind)}"
    return {
        "id": ident, "kind": kind, "title": title or Path(path or "").stem or ident,
        "base": "project" if project else "library", "path": rel or (path or ""),
        "license": info["id"], "license_name": info["name"], "license_url": info["url"],
        "commercial": info.get("commercial"), "attribution": info.get("attribution"),
        "redistribute": info.get("redistribute"),
        "review_required": info.get("review_required"),
        "notice_required": info.get("notice_required"),
        "license_checked_at": today(),
        "license_snapshot": {"id": info["id"], "name": info["name"], "url": info["url"],
                             "commercial": info.get("commercial"),
                             "attribution": info.get("attribution"),
                             "checked_at": today()},
        "provider": provider, "source_url": source_url or None,
        "creator": None, "notes": notes,
        "path_abs": str(path) if path else None,
    }


def _abs_for(entry: dict, *, library_root=None, project=None) -> str | None:
    if entry.get("path_abs"):
        return str(entry["path_abs"])
    try:
        return str(entry_abs(entry, library_root, project))
    except AssetError:
        return None


def _license_status(entry: dict, *, commercial: bool, strict: bool,
                    attribution_exported: bool = True,
                    file_exists: bool | None = None) -> tuple[str, list[str]]:
    reasons: list[str] = []
    status = "pass"
    if file_exists is False:
        status = "fail"
        reasons.append("文件不存在")
    result = lic.check(entry.get("license"), commercial=commercial,
                       attribution_exported=attribution_exported,
                       snapshot=entry.get("license_snapshot"),
                       strict=strict, checked_at=entry.get("license_checked_at"))
    rank = {"pass": 0, "unchecked": 1, "fail": 2}
    if rank[result["status"]] > rank[status]:
        status = result["status"]
    reasons.extend(result["reasons"])
    provider = str(entry.get("provider") or "").casefold()
    if provider in _EXTERNAL_PROVIDERS and not entry.get("source_url") \
            and not entry.get("bundled"):
        if rank[status] < rank["unchecked"]:
            status = "unchecked"
        reasons.append("外部素材缺来源 URL；无法复核授权与作者")
    return status, list(dict.fromkeys(reasons))


def _entry_from_path(path: Path, kind: str, entries: list[dict],
                     *, library_root=None, project=None) -> dict | None:
    p = path.resolve()
    for entry in entries:
        try:
            if entry_abs(entry, library_root, project) == p:
                return entry
        except AssetError:
            continue
    try:
        sc = sidecar_entry(p, base="project", library_root=library_root, project=project)
    except AssetError:
        sc = None
    if sc:
        return sc
    try:
        rel = str(p.relative_to(Path(project).resolve())) if project else ""
    except (ValueError, TypeError):
        rel = ""
    if rel.startswith("input/"):
        return _synthetic_entry(kind=kind, path=p, license_key="project-input",
                                title=p.stem, provider="project-input",
                                notes="用户提供的原始素材；商用权利由用户确认",
                                project=project)
    if rel.startswith("work/"):
        return _synthetic_entry(kind=kind, path=p, license_key="project-generated",
                                title=p.stem, provider="project-generated",
                                notes="工作区生成文件", project=project)
    if rel.startswith("assets/"):
        name = p.name
        if name.startswith(("insert-", "card-", "frame-")):
            return _synthetic_entry(kind=kind, path=p, license_key="project-generated",
                                    title=p.stem, provider="project-generated",
                                    notes="脚本生成的包装素材", project=project)
        if rel.startswith("assets/stills/"):
            return _synthetic_entry(kind=kind, path=p, license_key="project-input",
                                    title=p.stem, provider="project-input",
                                    notes="从用户源片抽取的静帧；权利随源片",
                                    project=project)
    if project:
        for item in _mixkit_items(Path(project)):
            local = Path(str(item.get("local") or ""))
            if local.name and local.name == p.name:
                mapped = {"video": "broll", "music": "bgm", "sfx": "sfx"}.get(
                    str(item.get("kind") or ""), kind)
                return _synthetic_entry(
                    kind=mapped, path=p, license_key="Mixkit-Free-License",
                    title=str(item.get("title") or p.stem), provider="mixkit",
                    source_url=str(item.get("search_url") or item.get("page") or ""),
                    notes="Mixkit 免费素材；work/mixkit.json 有来源记录",
                    project=project)
    return None


def _mixkit_items(project: Path) -> list[dict]:
    try:
        data = json.loads((project / "work" / "mixkit.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return [x for x in (data.get("items") or []) if isinstance(x, dict)]


def _find_mixkit(items: list[dict], *, kind: str | None = None,
                 title: str | None = None, path: str | None = None) -> dict | None:
    for item in items:
        if kind and item.get("kind") != kind:
            continue
        if title and (str(item.get("title") or "").casefold() == str(title).casefold()
                      or Path(str(item.get("local") or "")).stem.casefold()
                      == Path(str(title)).stem.casefold()):
            return item
        if path and Path(str(item.get("local") or "")).name == Path(path).name:
            return item
    return None


def _usage_item(kind: str, ref: str, usage: str, path: str | None,
                entry: dict | None, *, note: str = "") -> dict:
    return {"kind": kind, "ref": ref, "usage": usage, "path": path,
            "entry": entry, "note": note}


def collect_usage(project: str | Path, *, cfg: dict | None = None,
                  library_root: str | Path | None = None,
                  entries: list[dict] | None = None) -> list[dict]:
    """把 config/work 里实际用到的素材扫成用量表；不写盘。"""
    project = Path(project).resolve()
    cfg = cfg or load_config(project_paths(project)["config"])
    root = resolve_library_root(library_root or (cfg.get("assets") or {}).get("library"))
    entries = entries if entries is not None else load_registry(root)
    usages: list[dict] = []

    def add(kind: str, ref: str, usage: str, path: str | Path | None,
            entry: dict | None = None, note: str = "") -> None:
        p = str(path) if path else None
        if entry is None and p:
            entry = _entry_from_path(Path(p), kind, entries,
                                     library_root=root, project=project)
        usages.append(_usage_item(kind, ref, usage, p, entry, note=note))

    # 1) 原始输入（用户素材）
    inp = cfg.get("input") or {}
    for key in ("video", "audio"):
        ref = inp.get(key)
        if ref:
            p = input_path(project, str(ref))
            add("source", str(ref), f"input.{key}", p)
    for clip in inp.get("clips") or []:
        add("source", str(clip), "input.clips", input_path(project, str(clip)))
    for clip, ext in (inp.get("audio_map") or {}).items():
        add("source", str(ext), f"input.audio_map[{clip}]",
            input_path(project, str(ext)))

    # 2) B-roll
    for i, item in enumerate((cfg.get("broll") or {}).get("items") or [], 1):
        ref = str((item or {}).get("source") or "")
        if not ref:
            continue
        try:
            got = resolve_ref(ref, library_root=root, project=project, entries=entries)
            add("broll", ref, f"broll.items[{i}].source", got["path"], got.get("entry"))
        except AssetError as exc:
            add("broll", ref, f"broll.items[{i}].source", None, None, note=str(exc))

    # 3) 插图/静帧
    for i, item in enumerate((cfg.get("inserts") or {}).get("items") or [], 1):
        rel = (item or {}).get("illustration")
        if not rel:
            continue
        p = project / "assets" / str(rel)
        kind = "still" if str(rel).startswith("stills/") else "illustration"
        add(kind, str(rel), f"inserts.items[{i}].illustration", p)

    # 3.5) 贴纸：外部 source 走素材库；内置 icon 是脚本现画，不计第三方素材
    for i, item in enumerate((cfg.get("stickers") or {}).get("items") or [], 1):
        ref = str((item or {}).get("source") or (item or {}).get("image") or "")
        if not ref:
            continue
        try:
            got = resolve_ref(ref, library_root=root, project=project, entries=entries)
            add("sticker", ref, f"stickers.items[{i}].source", got["path"], got.get("entry"))
        except AssetError as exc:
            add("sticker", ref, f"stickers.items[{i}].source", None, None, note=str(exc))

    # 4) 音效：按 make_sfx 的 cue 解析，避免把 cue 名当成文件
    sfx_events = (cfg.get("sfx") or {}).get("events") or []
    resolved_sfx: list[tuple[float, str, float]] = []
    if sfx_events:
        try:
            import make_sfx
            resolved_sfx = make_sfx.resolve(cfg)
        except Exception:  # noqa: BLE001
            resolved_sfx = [(float(e.get("t") or 0), str(e.get("clip") or ""),
                             float(e.get("peak_db") or -18))
                            for e in sfx_events if e.get("clip")]
    for index, (at, name, _peak) in enumerate(resolved_sfx, 1):
        ref = str(name)
        if ref.startswith(("asset:", "library:")):
            try:
                got = resolve_ref(ref, library_root=root, project=project, entries=entries)
                add("sfx", ref, f"sfx.events[{index}]", got["path"], got.get("entry"))
            except AssetError as exc:
                add("sfx", ref, f"sfx.events[{index}]", None, None, note=str(exc))
            continue
        p = Path(ref)
        if not p.is_absolute():
            candidate = repo_root() / "assets" / "sfx" / f"{ref}.mp3"
            if not candidate.is_file():
                candidate = project / "assets" / "sfx" / f"{ref}.mp3"
            p = candidate
        add("sfx", ref, f"sfx.events[{index}]", p)

    # 5) BGM
    bgm = (cfg.get("audio") or {}).get("bgm") or {}
    bgm_file = project / "work" / "bgm.wav"
    source = str(bgm.get("source") or "")
    if bgm.get("enabled") or bgm_file.is_file():
        mixkit = _mixkit_items(project)
        if source == "mixkit":
            title = str(bgm.get("title") or "")
            item = _find_mixkit(mixkit, kind="music", title=title) or \
                _find_mixkit(mixkit, kind="music", path=str(bgm_file))
            if item:
                p = Path(str(item.get("local") or ""))
                entry = _synthetic_entry(
                    kind="bgm", path=p, license_key="Mixkit-Free-License",
                    title=str(item.get("title") or title or p.stem),
                    provider="mixkit", source_url=str(item.get("search_url") or ""),
                    notes="Mixkit 免费音乐；已转码为 work/bgm.wav",
                    project=project)
                add("bgm", title or p.name, "audio.bgm", p, entry)
            else:
                add("bgm", title or "mixkit", "audio.bgm", bgm_file,
                    _synthetic_entry(kind="bgm", path=bgm_file,
                                     license_key="Mixkit-Free-License",
                                     title=title or "mixkit bgm", provider="mixkit",
                                     notes="source=mixkit，但 work/mixkit.json 里没有对应记录",
                                     project=project))
        elif bgm.get("music_id") or source == "jianying-cloud":
            try:
                sel = json.loads((project / "work" / "music-selection.json").read_text(encoding="utf-8"))
            except (OSError, ValueError):
                sel = {}
            raw = Path(str(sel.get("raw") or ""))
            p = raw if raw.is_file() else bgm_file
            entry = _synthetic_entry(
                kind="bgm", path=p, license_key="Jianying-Cloud",
                title=str(sel.get("title") or bgm.get("title") or "jianying cloud music"),
                provider="jianying-cloud",
                source_url=str(sel.get("url") or ""),
                notes="剪映云端音乐；授权随平台，发布前核对；不随项目分发",
                project=project)
            add("bgm", str(bgm.get("music_id") or ""), "audio.bgm", p, entry)
        elif bgm_file.is_file():
            add("bgm", "bgm.wav", "audio.bgm", bgm_file,
                _synthetic_entry(kind="bgm", path=bgm_file,
                                 license_key="project-generated",
                                 title="本地/合成 BGM", provider="project-generated",
                                 notes="本地生成或用户自行提供的 BGM",
                                 project=project))

    # 6) 字体
    family = str((cfg.get("captions") or {}).get("font") or "")
    if family:
        try:
            from _common import find_font
            font_path = find_font(family, project)
        except Exception:  # noqa: BLE001
            font_path = None
        if font_path and Path(font_path).is_file():
            info = lic.font_license_for(family, font_path, project)
            entry = {
                "id": f"font/{slugify(family)}", "kind": "font", "title": family,
                "base": "repo", "path": "", "path_abs": str(font_path),
                "license": info["id"], "license_name": info["name"],
                "license_url": info.get("url"), "commercial": info.get("commercial"),
                "attribution": info.get("attribution"),
                "redistribute": info.get("redistribute"),
                "review_required": info.get("review_required"),
                "notice_required": info.get("notice_required"),
                "license_checked_at": str((info.get("record") or {}).get("checked_at")
                                          or today()),
                "license_snapshot": {
                    "id": info["id"], "name": info["name"], "url": info.get("url"),
                    "commercial": info.get("commercial"),
                    "attribution": info.get("attribution"),
                    "checked_at": str((info.get("record") or {}).get("checked_at") or today()),
                },
                "provider": "system" if info["id"] == "system-font" else "font",
                "source_url": info.get("url"), "creator": (info.get("record") or {}).get("copyright"),
                "notes": info.get("notes") or "",
            }
            add("font", family, "captions.font", font_path, entry)
        else:
            entry = _synthetic_entry(
                kind="font", path=None, license_key="unknown", title=family,
                provider="font", notes="找不到字体文件，无法核验授权")
            usages.append(_usage_item("font", family, "captions.font", None, entry,
                                      note="找不到字体文件，无法核验授权"))

    # 去重：同一路径只留一条，合并 usage
    merged: dict[tuple, dict] = {}
    for usage in usages:
        key = (usage["kind"], usage.get("path") or usage.get("ref"))
        if key in merged:
            merged[key]["usage"] = merged[key]["usage"] + "、" + usage["usage"]
            if usage.get("note") and usage["note"] not in merged[key].get("note", ""):
                merged[key]["note"] = (merged[key].get("note") or "") + "；" + usage["note"]
        else:
            merged[key] = usage
    return list(merged.values())


def audit_project(project: str | Path, *, library_root: str | Path | None = None,
                  commercial: bool | None = None, strict: bool | None = None,
                  write_outputs: bool = True) -> dict:
    """把工程实际用到的素材写成 manifest + CSV + CREDITS。"""
    project = Path(project).resolve()
    p = project_paths(project)
    cfg = load_config(p["config"])
    policy = cfg.get("assets") or {}
    commercial = bool(policy.get("commercial", True)) if commercial is None else bool(commercial)
    strict = bool(policy.get("strict_license", False)) if strict is None else bool(strict)
    root = resolve_library_root(library_root or policy.get("library"))
    entries = load_registry(root)
    usages = collect_usage(project, cfg=cfg, library_root=root, entries=entries)

    items = []
    counts = {"pass": 0, "unchecked": 0, "fail": 0}
    for usage in usages:
        entry = usage.get("entry") or {}
        path = usage.get("path")
        exists = Path(path).is_file() if path else None
        status, reasons = _license_status(entry, commercial=commercial, strict=strict,
                                          attribution_exported=True,
                                          file_exists=exists)
        if usage.get("note") and status == "fail" and not path:
            reasons.append(usage["note"])
        counts[status] += 1
        info = lic.license_info(entry.get("license"))
        items.append({
            "id": entry.get("id") or f"{usage['kind']}/missing",
            "kind": usage["kind"], "title": entry.get("title") or usage.get("ref") or "",
            "usage": usage["usage"], "ref": usage.get("ref"),
            "path": path, "exists": exists, "status": status,
            "reasons": reasons,
            "provider": entry.get("provider"),
            "creator": entry.get("creator"),
            "source_url": entry.get("source_url"),
            "license": info["id"], "license_name": info["name"],
            "license_url": info.get("url"),
            "commercial": info.get("commercial"),
            "attribution": info.get("attribution"),
            "redistribute": info.get("redistribute"),
            "review_required": info.get("review_required"),
            "notice_required": info.get("notice_required"),
            "license_checked_at": entry.get("license_checked_at"),
            "sha256": entry.get("sha256"),
            "duration": entry.get("duration"),
            "width": entry.get("width"),
            "height": entry.get("height"),
            "downloaded_at": entry.get("downloaded_at"),
            "notes": entry.get("notes") or usage.get("note") or "",
        })
    items.sort(key=lambda x: (x["kind"], x["id"]))
    overall = "fail" if counts["fail"] else ("unchecked" if counts["unchecked"] else "pass")
    manifest = {
        "version": 1, "project": str(project), "generated_at": now_iso(),
        "library": str(root), "policy": {"commercial": commercial, "strict": strict},
        "overall": overall, "summary": {**counts, "used": len(items)},
        "items": items,
        "export": {},
        "note": "pass 只代表已知授权边界内没有障碍；肖像/商标/平台规则仍需人工签收。",
    }
    write_json(p["work"] / "asset-manifest.json", manifest)
    if write_outputs:
        out_dir = p["output"]
        out_dir.mkdir(parents=True, exist_ok=True)
        csv_path = out_dir / "asset-licenses.csv"
        credits_path = out_dir / "CREDITS.md"
        write_ledger(items, csv_path, credits_path, project=project,
                     commercial=commercial, strict=strict)
        manifest["export"] = {"csv": str(csv_path), "credits": str(credits_path)}
        write_json(p["work"] / "asset-manifest.json", manifest)
    return manifest


def _ledger_row(item: dict) -> dict:
    return {
        "asset_id": item.get("id") or "",
        "title": item.get("title") or "",
        "kind": item.get("kind") or "",
        "provider": item.get("provider") or "",
        "creator": item.get("creator") or "",
        "source_url": item.get("source_url") or "",
        "license": item.get("license") or "",
        "license_name": item.get("license_name") or "",
        "license_url": item.get("license_url") or "",
        "commercial": "" if item.get("commercial") is None else str(bool(item.get("commercial"))).lower(),
        "attribution": item.get("attribution") or "",
        "status": item.get("status") or "",
        "path": item.get("path") or "",
        "sha256": item.get("sha256") or "",
        "duration": item.get("duration") or "",
        "width": item.get("width") or "",
        "height": item.get("height") or "",
        "downloaded_at": item.get("downloaded_at") or "",
        "license_checked_at": item.get("license_checked_at") or "",
        "usage": item.get("usage") or "",
        "notes": item.get("notes") or "",
    }


def write_ledger(items: list[dict], csv_path: str | Path,
                 credits_path: str | Path | None = None, *,
                 project: str | Path | None = None,
                 commercial: bool = True, strict: bool = False) -> dict:
    rows = [_ledger_row(item) for item in items]
    csv_path = Path(csv_path)
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    fields = list(rows[0]) if rows else list(_ledger_row({}))
    with csv_path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    if credits_path:
        _write_credits(items, Path(credits_path), project=project,
                       commercial=commercial, strict=strict)
    return {"csv": str(csv_path), "rows": len(rows)}


def _write_credits(items: list[dict], path: Path, *, project=None,
                   commercial=True, strict=False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# 素材授权清单（CREDITS）",
        "",
        f"- 生成时间：{now_iso()}",
        f"- 工程：`{project or '-'}`",
        f"- 用途：{'商业' if commercial else '非商业'}",
        f"- 策略：{'严格' if strict else '标准'}",
        "",
        "> 本清单由 `koubo assets audit` 从素材库记录生成。许可结论只是当前记录的"
        "程序化判断，**不替代法律意见**；肖像权、商标权、平台规则仍需人工签收。",
        "",
    ]
    required = [x for x in items if x.get("attribution") == "required"]
    lines += ["## 必须署名", ""]
    if required:
        for item in required:
            info = lic.license_info(item.get("license"))
            lines.append("- " + lic.attribution_line(
                str(item.get("title") or item.get("id") or ""),
                str(item.get("creator") or ""), info,
                str(item.get("source_url") or "")))
    else:
        lines.append("（没有需要强制署名的素材）")
    lines += ["", "## 全部素材", "",
              "| 素材 | 用途 | 类型 | 许可 | 状态 | 来源 |",
              "| --- | --- | --- | --- | --- | --- |"]
    for item in items:
        lines.append("| {title} | {usage} | {kind} | {lic} | {status} | {source} |".format(
            title=str(item.get("title") or item.get("id") or "").replace("|", "\\|"),
            usage=str(item.get("usage") or "").replace("|", "\\|"),
            kind=str(item.get("kind") or ""),
            lic=str(item.get("license_name") or item.get("license") or ""),
            status=str(item.get("status") or ""),
            source=str(item.get("source_url") or "—").replace("|", "\\|"),
        ))
    lines += ["", "## 状态说明", "",
              "- `pass`：当前已知许可边界内没有障碍；",
              "- `unchecked`：需人工确认（授权不明、平台条款、需核对、找不到文件）；",
              "- `fail`：明确不可用或文件缺失。",
              "", "字体：OFL 字体嵌进成片不需要在片尾署名；再分发字体文件时必须附"
              " OFL 文本与版权声明。", ""]
    path.write_text("\n".join(lines), encoding="utf-8")


def export_library(root: str | Path | None = None, *, out: str | Path | None = None,
                   commercial: bool = True, strict: bool = False) -> dict:
    root = resolve_library_root(root)
    entries = load_registry(root)
    items = []
    for entry in entries:
        path = _abs_for(entry, library_root=root)
        status, reasons = _license_status(entry, commercial=commercial, strict=strict,
                                          attribution_exported=True,
                                          file_exists=Path(path).is_file() if path else False)
        info = lic.license_info(entry.get("license"))
        items.append({**entry, "status": status, "reasons": reasons,
                      "license_name": info["name"], "license_url": info.get("url"),
                      "commercial": info.get("commercial"),
                      "attribution": info.get("attribution"),
                      "path": entry.get("path"), "resolved_path": path,
                      "license_checked_at": entry.get("license_checked_at")})
    out = Path(out) if out else root
    out.mkdir(parents=True, exist_ok=True)
    got = write_ledger(items, out / LEDGER_NAME, out / "CREDITS.md",
                       commercial=commercial, strict=strict)
    counts = {s: sum(1 for i in items if i["status"] == s)
              for s in ("pass", "unchecked", "fail")}
    return {"root": str(root), "entries": len(items), "counts": counts,
            "csv": got["csv"], "credits": str(out / "CREDITS.md")}


# ------------------------------------------------------------------ 召回建议

def _cue_tokens(text: str) -> list[str]:
    tokens = _tokens(text)
    out = list(tokens)
    for needle, synonyms in SCENE_SYNONYMS.items():
        if needle in text:
            out.extend(synonyms)
            out.extend([needle])
    seen, unique = set(), []
    for token in out:
        token = token.casefold().strip()
        if len(token) < 2 or token in seen:
            continue
        seen.add(token)
        unique.append(token)
    return unique[:60]


def suggest(project: str | Path, cue_index: int, *, kind: str = "broll",
            limit: int = 8, library_root: str | Path | None = None,
            remote: list[str] | None = None) -> dict:
    """按某条字幕召回候选素材；只出建议，不改 config。

    这是**元数据召回**，不是语义向量/VLM：命中原因写在 `reasons` 里，
    人能看到「为什么推荐它」，也能一眼否掉。
    """
    project = Path(project).resolve()
    cfg = load_config(project_paths(project)["config"])
    root = resolve_library_root(library_root or (cfg.get("assets") or {}).get("library"))
    entries = load_registry(root)
    from workflow import caption_plan
    plan = caption_plan.load(cfg, project)
    cue = next((c for c in plan.get("cues") or [] if int(c.get("index", -1)) == int(cue_index)), None)
    if cue is None:
        raise AssetError(f"没有第 {cue_index} 条字幕")
    from _common import caption_plain
    text = "".join(caption_plain(line) for line in cue.get("lines") or [])
    tokens = _cue_tokens(text)
    kinds = [kind] if kind != "broll" else ["broll", "overlay"]
    hits = []
    for entry in entries:
        if str(entry.get("kind")) not in kinds:
            continue
        score, reasons = _score_entry(entry, tokens)
        duration = _as_float(entry.get("duration"))
        cue_dur = float(cue.get("end") or 0) - float(cue.get("start") or 0)
        if kind == "broll" and duration:
            if 1.0 <= duration <= max(1.5, cue_dur) + 0.5:
                score += 2
                reasons.append(f"时长合适:{duration:.2f}s")
            elif duration > cue_dur + 0.5:
                score -= 1
                reasons.append(f"时长偏长:{duration:.2f}s")
        status, why = _license_status(entry, commercial=True, strict=False,
                                      attribution_exported=False,
                                      file_exists=True)
        if status == "fail":
            continue
        if status == "pass":
            score += 1
        if score <= 0:
            continue
        hits.append({"entry": entry, "score": round(score, 2),
                     "reasons": reasons[:10], "remote": False,
                     "status": status, "reasons_license": why})
    hits.sort(key=lambda h: (-h["score"], str(h["entry"].get("id"))))
    hits = hits[:limit]
    remote_hits = []
    if remote:
        try:
            from workflow import asset_remote
            query = " ".join(tokens[:8]) or text[:40]
            for provider in remote:
                for media in ("video", "photo"):
                    try:
                        items = asset_remote.search(provider, media, query, limit=max(3, limit // 2))
                    except Exception as exc:  # noqa: BLE001
                        remote_hits.append({"provider": provider, "media": media,
                                            "error": f"{type(exc).__name__}: {exc}"})
                        continue
                    for item in items:
                        remote_hits.append({**item, "remote": True})
        except Exception as exc:  # noqa: BLE001
            remote_hits.append({"error": f"{type(exc).__name__}: {exc}"})
    return {"project": str(project), "cue": {"index": cue_index,
                                             "start": cue.get("start"), "end": cue.get("end"),
                                             "text": text},
            "tokens": tokens, "suggestions": hits, "remote": remote_hits,
            "note": "元数据召回；命中原因可复核；不自动改 config"}


# ------------------------------------------------------------------ 统计

def stats(entries: list[dict]) -> dict:
    by_kind: dict[str, int] = {}
    by_provider: dict[str, int] = {}
    by_license: dict[str, int] = {}
    for entry in entries:
        by_kind[str(entry.get("kind"))] = by_kind.get(str(entry.get("kind")), 0) + 1
        by_provider[str(entry.get("provider"))] = by_provider.get(str(entry.get("provider")), 0) + 1
        by_license[str(entry.get("license"))] = by_license.get(str(entry.get("license")), 0) + 1
    return {"total": len(entries), "by_kind": dict(sorted(by_kind.items())),
            "by_provider": dict(sorted(by_provider.items())),
            "by_license": dict(sorted(by_license.items()))}
