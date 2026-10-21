"""远程素材源：Pexels / Pixabay 的公开 API 适配器（单条检索，不批量抓取）。

只做三件事：

- `search()` 搜索视频/图片，归一化成素材库记录需要的字段；
- `add()` 下载**一条**并登记进素材库（写 sidecar / registry）；
- `import_sfx_kit()` 把本地 [sfx-kit](https://github.com/wyzowl/sfx-kit) 的
  CC0 音效按 `sounds.json` 导入（可选分类，不自动全量下载）。

边界：

- 必须自己申请 API Key，放环境变量 `PEXELS_API_KEY` / `PIXABAY_API_KEY`；
  没有 Key 明确报错，不假装搜到；
- 不抓 HTML、不绕登录、不批量下载；查询结果有 12 小时缓存；
- 许可只记录平台公开条款与来源 URL；人物/品牌/肖像风险仍需人工确认。
"""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from workflow import asset_licenses as lic
from workflow import asset_library as library

PROVIDERS = ("pexels", "pixabay")
MEDIA = ("video", "photo")
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) KouboStudio/1.0"
MAX_BYTES = 300 * 1024 * 1024
CACHE_DIR = Path(os.environ.get("KOUBO_REMOTE_CACHE",
                                Path.home() / ".cache" / "koubo" / "remote"))
CACHE_TTL = 12 * 3600
_LAST_CALL: dict[str, float] = {}

LICENSE_BY_PROVIDER = {
    "pexels": "Pexels-License",
    "pixabay": "Pixabay-Content-License",
    "sfx-kit": "CC0-1.0",
}

PROVIDER_HOME = {
    "pexels": "https://www.pexels.com",
    "pixabay": "https://pixabay.com",
    "sfx-kit": "https://github.com/wyzowl/sfx-kit",
}


class RemoteError(RuntimeError):
    """远程素材失败；消息要能直接告诉用户缺什么。"""


def _key(provider: str) -> str:
    env = {"pexels": "PEXELS_API_KEY", "pixabay": "PIXABAY_API_KEY"}.get(provider)
    value = os.environ.get(env or "") if env else ""
    if not value:
        raise RemoteError(
            f"{provider} 需要 API Key：先申请，再 export {env}=...；"
            f"没有 Key 不会伪造搜索结果")
    return value


def _throttle(provider: str) -> None:
    # 保守节流：Pexels 200 次/小时、Pixabay 100 次/分钟，单条交互远够用。
    last = _LAST_CALL.get(provider, 0.0)
    wait = 0.7 - (time.monotonic() - last)
    if wait > 0:
        time.sleep(wait)
    _LAST_CALL[provider] = time.monotonic()


def _cache_path(url: str) -> Path:
    import hashlib
    return CACHE_DIR / (hashlib.sha256(url.encode()).hexdigest()[:24] + ".json")


def _fetch_json(url: str, headers: dict[str, str], *, timeout: int = 30) -> dict:
    cached = _cache_path(url)
    if cached.is_file() and time.time() - cached.stat().st_mtime < CACHE_TTL:
        try:
            return json.loads(cached.read_text(encoding="utf-8"))
        except ValueError:
            pass
    req = urllib.request.Request(url, headers={"User-Agent": UA, **headers})
    last: Exception | None = None
    for attempt in range(2):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as response:
                ctype = (response.headers.get("Content-Type") or "").lower()
                raw = response.read(8 * 1024 * 1024 + 1)
            if "json" not in ctype:
                raise RemoteError(f"接口返回非 JSON：{ctype}")
            data = json.loads(raw.decode("utf-8", "ignore"))
            CACHE_DIR.mkdir(parents=True, exist_ok=True)
            cached.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
            return data
        except urllib.error.HTTPError as exc:
            body = ""
            try:
                body = exc.read().decode("utf-8", "ignore")[:200]
            except Exception:  # noqa: BLE001
                pass
            if exc.code in (401, 403):
                raise RemoteError(f"{url} 被拒绝（HTTP {exc.code}）：检查 API Key/配额；{body}") from exc
            if exc.code == 429:
                raise RemoteError(f"{url} 触发限流（HTTP 429）；等一会儿再试") from exc
            last = exc
        except Exception as exc:  # noqa: BLE001
            last = exc
        if attempt == 0:
            time.sleep(0.8)
    raise RemoteError(f"请求失败 {url}：{type(last).__name__}: {last}") from last


def _call(provider: str, url: str, *, fetch=None) -> dict:
    if fetch is not None:
        return fetch(url, {"Authorization": _key(provider)} if provider == "pexels"
                     else {})
    _throttle(provider)
    if provider == "pexels":
        return _fetch_json(url, {"Authorization": _key(provider)})
    return _fetch_json(url, {})


def _query(provider: str, media: str, query: str, limit: int,
           orientation: str | None, *, fetch=None) -> dict:
    if provider not in PROVIDERS:
        raise RemoteError(f"未知远程源 {provider!r}；可用：{', '.join(PROVIDERS)}")
    if media not in MEDIA:
        raise RemoteError(f"media 必须是 {'/'.join(MEDIA)}")
    limit = max(1, min(int(limit), 50))
    params = {"query": query, "per_page": limit}
    if provider == "pexels":
        if media == "video":
            url = "https://api.pexels.com/videos/search?" + urllib.parse.urlencode(params)
        else:
            url = "https://api.pexels.com/v1/search?" + urllib.parse.urlencode(params)
        if orientation:
            url += "&orientation=" + urllib.parse.quote(orientation)
        return _call(provider, url, fetch=fetch)
    params = {"key": _key("pixabay"), "q": query, "per_page": limit, "safesearch": "true"}
    if media == "video":
        url = "https://pixabay.com/api/videos/?" + urllib.parse.urlencode(params)
    else:
        params["image_type"] = "photo"
        url = "https://pixabay.com/api/?" + urllib.parse.urlencode(params)
    return _call(provider, url, fetch=fetch)


def _pexels_video(item: dict, query: str, quality: int) -> dict:
    files = [f for f in item.get("video_files") or []
             if str(f.get("file_type") or "").startswith("video/mp4") and f.get("link")]
    files.sort(key=lambda f: int(f.get("height") or 0))
    pick = next((f for f in reversed(files) if int(f.get("height") or 0) <= quality), None)
    pick = pick or (files[0] if files else {})
    return {
        "provider": "pexels", "media": "video", "provider_id": str(item.get("id")),
        "title": f"Pexels video {item.get('id')}",
        "description": "", "page_url": item.get("url") or "",
        "download_url": pick.get("link") or "",
        "preview_url": item.get("image") or "",
        "width": pick.get("width") or item.get("width"),
        "height": pick.get("height") or item.get("height"),
        "duration": float(item.get("duration") or 0) or None,
        "creator": (item.get("user") or {}).get("name") or "",
        "creator_url": (item.get("user") or {}).get("url") or "",
        "license": "Pexels-License", "query": query, "tags": [query] if query else [],
    }


def _pixabay_video(item: dict, query: str, quality: int) -> dict:
    videos = item.get("videos") or {}
    order = ("large", "medium", "small", "tiny")
    if quality <= 720:
        order = ("medium", "small", "large", "tiny")
    pick = next((videos[k] for k in order if (videos.get(k) or {}).get("url")), {})
    return {
        "provider": "pixabay", "media": "video", "provider_id": str(item.get("id")),
        "title": f"Pixabay video {item.get('id')}",
        "description": str(item.get("tags") or ""), "page_url": item.get("pageURL") or "",
        "download_url": pick.get("url") or "",
        "preview_url": item.get("picture_id") and
        f"https://i.vimeocdn.com/video/{item.get('picture_id')}_640x360.jpg" or "",
        "width": pick.get("width"), "height": pick.get("height"),
        "duration": float(item.get("duration") or 0) or None,
        "creator": item.get("user") or "", "creator_url": item.get("user_id") and
        f"https://pixabay.com/users/{item.get('user')}-{item.get('user_id')}/" or "",
        "license": "Pixabay-Content-License", "query": query,
        "tags": [x.strip() for x in str(item.get("tags") or "").split(",") if x.strip()],
    }


def _pexels_photo(item: dict, query: str) -> dict:
    src = item.get("src") or {}
    return {
        "provider": "pexels", "media": "photo", "provider_id": str(item.get("id")),
        "title": str(item.get("alt") or f"Pexels photo {item.get('id')}"),
        "description": str(item.get("alt") or ""), "page_url": item.get("url") or "",
        "download_url": src.get("original") or src.get("large2x") or src.get("large") or "",
        "preview_url": src.get("medium") or src.get("small") or "",
        "width": item.get("width"), "height": item.get("height"), "duration": None,
        "creator": item.get("photographer") or "",
        "creator_url": item.get("photographer_url") or "",
        "license": "Pexels-License", "query": query, "tags": [query] if query else [],
    }


def _pixabay_photo(item: dict, query: str) -> dict:
    return {
        "provider": "pixabay", "media": "photo", "provider_id": str(item.get("id")),
        "title": str(item.get("tags") or f"Pixabay photo {item.get('id')}"),
        "description": str(item.get("tags") or ""), "page_url": item.get("pageURL") or "",
        "download_url": item.get("largeImageURL") or item.get("webformatURL") or "",
        "preview_url": item.get("previewURL") or "",
        "width": item.get("imageWidth"), "height": item.get("imageHeight"),
        "duration": None, "creator": item.get("user") or "",
        "creator_url": item.get("user_id") and
        f"https://pixabay.com/users/{item.get('user')}-{item.get('user_id')}/" or "",
        "license": "Pixabay-Content-License", "query": query,
        "tags": [x.strip() for x in str(item.get("tags") or "").split(",") if x.strip()],
    }


def search(provider: str, media: str, query: str, *, limit: int = 12,
           orientation: str | None = None, min_duration: float | None = None,
           max_duration: float | None = None, quality: int = 1080,
           fetch=None) -> list[dict]:
    data = _query(provider, media, query, limit, orientation, fetch=fetch)
    if provider == "pexels":
        raw = data.get("videos" if media == "video" else "photos") or []
        items = [_pexels_video(x, query, quality) if media == "video"
                 else _pexels_photo(x, query) for x in raw]
    else:
        raw = data.get("hits") or []
        items = [_pixabay_video(x, query, quality) if media == "video"
                 else _pixabay_photo(x, query) for x in raw]
    out = []
    for item in items:
        if not item.get("download_url"):
            continue
        duration = item.get("duration")
        if min_duration is not None and (duration is None or duration < min_duration):
            continue
        if max_duration is not None and (duration is None or duration > max_duration):
            continue
        item["license_url"] = lic.license_info(item["license"]).get("url") or ""
        out.append(item)
    return out


def find(provider: str, media: str, provider_id: str, *, query: str,
         quality: int = 1080, fetch=None) -> dict:
    """按 ID 找回一条结果。Pexels/Pixabay 没有公开的单条 ID 查询，
    所以必须带搜索词，在结果里精确匹配。"""
    for item in search(provider, media, query, limit=50, quality=quality, fetch=fetch):
        if str(item.get("provider_id")) == str(provider_id):
            return item
    raise RemoteError(
        f"{provider} 搜索结果里没有 {provider_id}；换一个 --query 或先 search 看 ID")


def _safe_name(item: dict) -> str:
    base = f"{item['provider']}-{item['media']}-{item['provider_id']}"
    return library.slugify(base, fallback="remote")


def download(item: dict, dest: str | Path) -> Path:
    url = str(item.get("download_url") or "")
    if not url.startswith(("http://", "https://")):
        raise RemoteError("结果没有可下载地址")
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    provider = str(item.get("provider") or "")
    headers = {"User-Agent": UA,
               "Referer": PROVIDER_HOME.get(provider, "https://www.pexels.com/") + "/"}
    last: Exception | None = None
    for attempt in range(2):
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=90) as response:
                ctype = (response.headers.get("Content-Type") or "").lower()
                if ctype.startswith(("text/html", "application/json")):
                    raise RemoteError(f"下载地址返回 {ctype}")
                data = response.read(MAX_BYTES + 1)
            if len(data) > MAX_BYTES:
                raise RemoteError("远程素材超过 300MB，拒绝")
            dest.write_bytes(data)
            return dest
        except Exception as exc:  # noqa: BLE001
            last = exc
            if attempt == 0:
                time.sleep(0.8)
    raise RemoteError(f"下载失败：{type(last).__name__}: {last}") from last


def add(item: dict, *, library_root: str | Path | None = None,
        project: str | Path | None = None, tags: str | list[str] | None = None,
        title: str | None = None) -> dict:
    """下载一条远程素材并登记；project 给了就进工程，否则进共享库。"""
    provider = str(item.get("provider") or "")
    media = str(item.get("media") or "")
    if provider not in PROVIDERS or media not in MEDIA:
        raise RemoteError("item 缺少 provider/media")
    kind = "broll" if media == "video" else "still"
    suffix = ".mp4" if media == "video" else ".jpg"
    tmp_dir = Path(os.environ.get("TMPDIR", "/tmp")) / "koubo-remote"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    tmp = tmp_dir / (_safe_name(item) + suffix)
    download(item, tmp)
    meta_tags = list(item.get("tags") or [])
    if tags:
        meta_tags += [t for t in library._as_list(tags) if t not in meta_tags]
    info = lic.license_info(item.get("license"))
    entry = library.ingest_file(
        tmp, kind=kind, license_key=item.get("license") or "unknown",
        library_root=library_root, project=project,
        scope="project" if project else "library",
        ident=(f"{kind}/{_safe_name(item)}" if project else None),
        title=title or item.get("title") or _safe_name(item),
        provider=provider, provider_id=item.get("provider_id"),
        creator=item.get("creator"), creator_url=item.get("creator_url"),
        source_url=item.get("page_url") or item.get("download_url"),
        download_url=item.get("download_url"), page_url=item.get("page_url"),
        query=item.get("query"), tags=meta_tags,
        mood=item.get("mood"), scene=item.get("scene"),
        use_for=item.get("use_for"), avoid_for=item.get("avoid_for"),
        duration=item.get("duration"), width=item.get("width"),
        height=item.get("height"),
        downloaded_at=library.today(),
        notes=f"{provider} 单条下载；许可 {info['name']}；"
              "可识别人物/品牌/地点需自行确认肖像与商标风险。",
    )
    try:
        tmp.unlink()
    except OSError:
        pass
    return entry


# ------------------------------------------------------------------ sfx-kit 导入

def import_sfx_kit(kit_dir: str | Path, *, library_root: str | Path | None = None,
                   categories: list[str] | None = None, limit: int | None = None,
                   copy: bool = True) -> dict:
    """导入本地 sfx-kit：读 `sounds.json`，按分类复制/链接 WAV 并登记。

    需要先把 https://github.com/wyzowl/sfx-kit 克隆到本地（67MB），
    本项目不代下载全量音效库。只导入选中的分类，避免把仓库撑大。
    """
    kit = Path(kit_dir).expanduser().resolve()
    manifest = kit / "sounds.json"
    if not manifest.is_file():
        raise RemoteError(f"找不到 {manifest}；先把 sfx-kit 克隆到本地")
    try:
        data = json.loads(manifest.read_text(encoding="utf-8"))
    except ValueError as exc:
        raise RemoteError(f"sounds.json 读不出来：{exc}") from exc
    if lic.normalize_license(data.get("license")) != "CC0-1.0":
        raise RemoteError(f"sfx-kit 许可不是 CC0：{data.get('license')!r}；不导入")
    wanted = {str(x) for x in categories} if categories else None
    sounds = data.get("sounds") or []
    if wanted:
        sounds = [s for s in sounds if str(s.get("category")) in wanted]
    if limit:
        sounds = sounds[:int(limit)]
    root = library.resolve_library_root(library_root)
    added, skipped, errors = [], [], []
    for sound in sounds:
        if not isinstance(sound, dict) or not sound.get("file") or not sound.get("id"):
            continue
        source = kit / str(sound["file"])
        if not source.is_file():
            errors.append(f"缺文件：{source}")
            continue
        dest_rel = f"audio/sfx/sfx-kit/{library.slugify(sound['id'])}.wav"
        dest = root / dest_rel
        ident = f"sfx/sfx-kit-{library.slugify(sound['id'])}"
        try:
            if copy:
                entry = library.ingest_file(
                    source, kind="sfx", license_key="CC0-1.0", library_root=root,
                    dest_rel=dest_rel, ident=ident,
                    title=str(sound.get("name") or sound.get("id")),
                    provider="sfx-kit", provider_id=sound.get("id"),
                    creator="Wyzowl", source_url=str(data.get("homepage") or
                                                      "https://github.com/wyzowl/sfx-kit"),
                    download_url=(str(data.get("homepage") or "https://github.com/wyzowl/sfx-kit")
                                  + "/blob/main/" + str(sound["file"])),
                    tags=list(sound.get("tags") or []) + [str(sound.get("category") or "")],
                    use_for=sound.get("use_for"), avoid_for=sound.get("avoid_for"),
                    duration=sound.get("duration"), sync=sound.get("sync"),
                    under_voiceover_db=sound.get("under_voiceover_db"),
                    fits_seconds=sound.get("fits_seconds"),
                    pairs_with=sound.get("pairs_with"),
                    variant=sound.get("variant"), character=sound.get("character"),
                    downloaded_at=library.today(),
                    notes="sfx-kit CC0；元数据来自 sounds.json（sync.at 可直接用于对齐）",
                )
            else:
                dest.parent.mkdir(parents=True, exist_ok=True)
                if not dest.exists():
                    os.symlink(source, dest)
                entry = library.ingest_file(
                    dest, kind="sfx", license_key="CC0-1.0", library_root=root,
                    copy=False, ident=ident, title=str(sound.get("name") or sound.get("id")),
                    provider="sfx-kit", provider_id=sound.get("id"),
                    creator="Wyzowl", source_url=str(data.get("homepage") or ""),
                    tags=list(sound.get("tags") or []) + [str(sound.get("category") or "")],
                    use_for=sound.get("use_for"), avoid_for=sound.get("avoid_for"),
                    duration=sound.get("duration"), sync=sound.get("sync"),
                    under_voiceover_db=sound.get("under_voiceover_db"),
                    fits_seconds=sound.get("fits_seconds"),
                    pairs_with=sound.get("pairs_with"),
                    variant=sound.get("variant"), character=sound.get("character"),
                    downloaded_at=library.today(),
                    notes="sfx-kit CC0（符号链接）；元数据来自 sounds.json",
                )
            added.append(entry["id"])
        except (library.AssetError, OSError) as exc:
            if "已登记" in str(exc) or "目标已存在且内容不同" in str(exc):
                skipped.append(ident)
            else:
                errors.append(f"{ident}: {exc}")
    return {"kit": str(kit), "added": added, "skipped": skipped,
            "errors": errors, "count": len(added)}
