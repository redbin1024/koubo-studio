"""参考片来源：本机文件、抖音分享链接，以及可选的 yt-dlp 回退。

设计边界（先写在前面，免得把能力说大）：

- **只取公开可见的单条作品**。不登录、不批量、不抓评论；不做签名绕过。
- 抖音首选「分享页 SSR 数据」：一次请求拿到 ttwid，第二次请求才会带 `videoInfoRes`。
  分享页解析失败时，若本机装了 `yt-dlp` 才回退；两者都没有就明确报错，让用户
  先把视频下载到本地再分析，而不是假装成功。
- 不引入 MediaCrawler：它的许可证是 NON-COMMERCIAL LEARNING LICENSE，且需要
  扫码登录和 Chromium。这里只吸收「拿到原片」这一层，分析仍在本项目内完成。

方法参考 `Joho6666/video-replicate-studio` 的「抓取 → 切镜 → 导演拆解」思路，
但没有复制其代码或素材。
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from http.cookiejar import CookieJar
from pathlib import Path


MOBILE_UA = ("Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) "
             "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.6 "
             "Mobile/15E148 Safari/604.1")
BASE_HEADERS = {
    "User-Agent": MOBILE_UA,
    "Accept-Language": "zh-CN,zh;q=0.9",
    "Accept-Encoding": "identity",
}
SHARE_HOSTS = ("douyin.com", "iesdouyin.com")
VIDEO_EXT = (".mp4", ".mov", ".m4v", ".webm", ".mkv", ".flv")
MAX_PAGE_BYTES = 8 * 1024 * 1024


class ReferenceSourceError(RuntimeError):
    """拿不到参考片；消息要能直接告诉用户下一步做什么。"""


# ------------------------------------------------------------------ 链接解析

def extract_url(text: str) -> str | None:
    """从抖音分享文案里抠出第一个 http(s) 链接。

    分享文本通常是「7.9 复制打开抖音… https://v.douyin.com/xxxx/ …」。
    """
    match = re.search(r"https?://[^\s<>\"'，。！？、）】]+", str(text or ""), re.I)
    if not match:
        return None
    return match.group(0).rstrip(".,;:!?)]}>\u3002\uff0c")


def detect_platform(url: str) -> str:
    try:
        host = (urllib.parse.urlsplit(url).hostname or "").lower()
    except ValueError:
        return "unknown"
    if any(host == d or host.endswith("." + d) for d in SHARE_HOSTS):
        return "douyin"
    return "url"


def parse_aweme_id(url: str) -> str | None:
    """从 /video/<id>、/note/<id>、modal_id=<id>、aweme_id=<id> 或纯数字里取作品 id。"""
    text = str(url or "")
    patterns = (
        r"/(?:video|note|slides)/(\d{8,})",
        r"[?&](?:modal_id|aweme_id|item_id)=(\d{8,})",
        r"(?<!\d)(\d{19})(?!\d)",
    )
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            return match.group(1)
    return None


def _looks_like_url(value: str) -> bool:
    return bool(re.match(r"^https?://", str(value or ""), re.I))


def _clean_url(url: str) -> str:
    """去掉分享链接里的 did/iid/share_sign 等追踪参数，落盘时不留设备标识。"""
    try:
        parts = urllib.parse.urlsplit(str(url))
    except ValueError:
        return str(url)
    return urllib.parse.urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))


# ------------------------------------------------------------------ cookie

def load_cookie(value: str | None) -> str | None:
    """`--cookie` 既可以是 Netscape cookies.txt，也可以是 `a=b; c=d` 原文。"""
    if not value:
        return None
    path = Path(value).expanduser()
    if path.is_file():
        pairs = []
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            if not line or line.startswith("#"):
                continue
            fields = line.split("\t")
            if len(fields) >= 7 and any(h in fields[0] for h in SHARE_HOSTS):
                pairs.append(f"{fields[5]}={fields[6]}")
        return "; ".join(pairs) or None
    return value.strip() or None


def _opener() -> urllib.request.OpenerDirector:
    return urllib.request.build_opener(
        urllib.request.HTTPCookieProcessor(CookieJar()),
        urllib.request.HTTPRedirectHandler(),
    )


def _get(opener, url: str, *, cookie: str | None, timeout: float,
         referer: str = "https://www.douyin.com/") -> tuple[str, str]:
    """GET 一个页面并返回 (最终 URL, 文本)。失败时抛出可读错误。"""
    headers = dict(BASE_HEADERS)
    headers["Referer"] = referer
    if cookie:
        headers["Cookie"] = cookie
    request = urllib.request.Request(url, headers=headers)
    try:
        with opener.open(request, timeout=timeout) as response:
            final = response.geturl()
            raw = response.read(MAX_PAGE_BYTES)
            charset = response.headers.get_content_charset() or "utf-8"
    except urllib.error.HTTPError as exc:
        raise ReferenceSourceError(
            f"请求抖音失败：HTTP {exc.code}。链接可能失效，或当前网络被风控。"
        ) from exc
    except (urllib.error.URLError, TimeoutError) as exc:
        raise ReferenceSourceError(f"请求抖音失败：{exc}。检查网络后重试。") from exc
    return final, raw.decode(charset, "replace")


# ------------------------------------------------------------------ 分享页解析

def _decode_router_data(html: str) -> dict | None:
    marker = "window._ROUTER_DATA"
    at = html.find(marker)
    if at < 0:
        return None
    brace = html.find("{", at)
    if brace < 0:
        return None
    try:
        data, _ = json.JSONDecoder().raw_decode(html[brace:])
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def _find_item(data: dict) -> dict | None:
    """在 SSR 数据里找第一段作品；抖音的 key 是字面量 `video_(id)/page`。"""
    loader = data.get("loaderData")
    if not isinstance(loader, dict):
        return None
    for value in loader.values():
        if not isinstance(value, dict):
            continue
        info = value.get("videoInfoRes")
        if not isinstance(info, dict):
            continue
        items = info.get("item_list")
        if isinstance(items, list) and items:
            return items[0]
    return None


def _share_reason(data: dict) -> str:
    loader = data.get("loaderData") or {}
    for value in loader.values():
        if not isinstance(value, dict):
            continue
        info = value.get("videoInfoRes") or {}
        listed = info.get("filter_list")
        if isinstance(listed, list) and listed:
            reasons = [str((x or {}).get("detail_msg") or (x or {}).get("reason")
                           or (x or {}).get("filter_reason") or "").strip()
                       for x in listed if isinstance(x, dict)]
            reasons = [r for r in reasons if r]
            if reasons:
                return "；".join(reasons[:2])
    return "作品不存在、已删除，或分享页没有返回视频数据"


def parse_share_html(html: str) -> dict:
    """解析抖音分享页 HTML，返回规范化的作品信息。

    只做「读到什么就返回什么」；读不到就抛错，不猜。
    """
    if not html or not html.strip():
        raise ReferenceSourceError("抖音返回了空页面")
    data = _decode_router_data(html)
    if data is None:
        if "_$jsvmprt" in html or "verify" in html.lower():
            raise ReferenceSourceError(
                "抖音分享页返回了验证/风控页，没有视频数据。"
                "可加 `--cookie` 复用浏览器 Cookie，或先把视频下载到本地再分析。"
            )
        raise ReferenceSourceError("分享页里没有 `_ROUTER_DATA`，无法解析作品信息")
    item = _find_item(data)
    if item is None:
        raise ReferenceSourceError(_share_reason(data))
    return normalize_item(item)


def normalize_item(item: dict) -> dict:
    """把抖音 item 归一成 {aweme_id, meta, play_urls, cover_url, is_image_post}。"""
    if not isinstance(item, dict):
        raise ReferenceSourceError("作品数据格式异常")
    aweme_id = str(item.get("aweme_id") or "")
    video = item.get("video") or {}
    images = item.get("images") or []
    play_urls = _play_urls(video)
    is_image_post = bool(images) and not play_urls
    author = item.get("author") or {}
    music = item.get("music") or {}
    stats = item.get("statistics") or {}
    duration_ms = video.get("duration") or item.get("duration") or 0
    try:
        duration = round(float(duration_ms) / 1000.0, 3) if duration_ms else None
    except (TypeError, ValueError):
        duration = None
    created = item.get("create_time")
    meta = {
        "id": aweme_id,
        "title": str(item.get("desc") or "").strip(),
        "author": str(author.get("nickname") or "").strip(),
        "author_id": str(author.get("unique_id") or author.get("short_id") or "").strip(),
        "music": str(music.get("title") or "").strip(),
        "music_author": str(music.get("author") or "").strip(),
        "duration": duration,
        "created_at": _epoch_iso(created),
        "stats": {
            "likes": _int(stats.get("digg_count")),
            "comments": _int(stats.get("comment_count")),
            "shares": _int(stats.get("share_count")),
            "favorites": _int(stats.get("collect_count")),
            "plays": _int(stats.get("play_count")),
        },
        "hashtags": re.findall(r"#([^\s#]+)", str(item.get("desc") or "")),
    }
    return {
        "aweme_id": aweme_id,
        "meta": meta,
        "play_urls": play_urls,
        "cover_url": _first_url(video.get("cover")) or _first_url(video.get("origin_cover")),
        "is_image_post": is_image_post,
    }


def _play_urls(video: dict) -> list[str]:
    """优先无水印 play，再回退 playwm / download_addr。保持候选顺序。"""
    candidates: list[str] = []
    for key in ("play_addr", "play_addr_h264", "download_addr"):
        candidates.extend(_url_list((video or {}).get(key)))
    for rate in (video or {}).get("bit_rate") or []:
        if isinstance(rate, dict):
            candidates.extend(_url_list(rate.get("play_addr")))
    urls: list[str] = []
    for raw in candidates:
        clean = str(raw or "").strip()
        if not clean or not clean.lower().startswith("http"):
            continue
        clean = clean.replace("/playwm/", "/play/")
        if clean not in urls:
            urls.append(clean)
    # 去水印地址放在前面；同时保留原始 playwm，下载 403 时还有一次机会。
    cleaned = [u for u in urls if "/play/" in u]
    watermarked = [u for u in urls if "/playwm/" in u]
    others = [u for u in urls if u not in cleaned and u not in watermarked]
    for raw in candidates:
        raw = str(raw or "").strip()
        if "/playwm/" in raw and raw not in watermarked:
            watermarked.append(raw)
    return cleaned + others + watermarked


def _url_list(value) -> list[str]:
    if isinstance(value, dict):
        urls = value.get("url_list") or []
        return [str(u) for u in urls if u]
    if isinstance(value, list):
        return [str(u) for u in value if u]
    if isinstance(value, str) and value.startswith("http"):
        return [value]
    return []


def _first_url(value) -> str | None:
    urls = _url_list(value)
    return urls[0] if urls else None


def _int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _epoch_iso(value) -> str | None:
    try:
        stamp = int(value)
    except (TypeError, ValueError):
        return None
    if stamp <= 0:
        return None
    import datetime
    return datetime.datetime.fromtimestamp(stamp, tz=datetime.timezone.utc).isoformat()


# ------------------------------------------------------------------ 下载

def _download(opener, urls: list[str], dest: Path, *, cookie: str | None,
              timeout: float, referer: str, log) -> str:
    """依次尝试候选地址，成功返回实际使用的 URL。"""
    dest.parent.mkdir(parents=True, exist_ok=True)
    errors: list[str] = []
    for url in urls:
        headers = dict(BASE_HEADERS)
        headers["Referer"] = referer
        headers["Accept"] = "video/mp4,video/*;q=0.9,*/*;q=0.8"
        if cookie:
            headers["Cookie"] = cookie
        request = urllib.request.Request(url, headers=headers)
        tmp = dest.with_suffix(dest.suffix + ".part")
        try:
            with opener.open(request, timeout=timeout) as response, open(tmp, "wb") as handle:
                content_type = (response.headers.get("Content-Type") or "").lower()
                if "text/html" in content_type or "application/json" in content_type:
                    raise ReferenceSourceError(
                        f"地址返回的是 {content_type or '非视频内容'}，不是视频")
                total = 0
                while True:
                    chunk = response.read(1024 * 256)
                    if not chunk:
                        break
                    handle.write(chunk)
                    total += len(chunk)
                    if total and total % (10 * 1024 * 1024) < 1024 * 256:
                        log(f"    已下载 {total / 1024 / 1024:.1f} MB")
            if not tmp.is_file() or tmp.stat().st_size < 16 * 1024:
                raise ReferenceSourceError("下载到的文件为空或过小")
            os.replace(tmp, dest)
            return url
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError,
                ReferenceSourceError) as exc:
            tmp.unlink(missing_ok=True)
            errors.append(f"{_short_url(url)} → {exc}")
            log(f"    该地址失败，换下一个：{_short_url(url)}")
            continue
    raise ReferenceSourceError(
        "下载地址全部失败（链接可能过期或被限流）：\n  " + "\n  ".join(errors[-4:]))


def _short_url(url: str) -> str:
    host = urllib.parse.urlsplit(url).hostname or ""
    return f"{host}/…" if len(url) > 80 else url


def _verify_media(path: Path) -> dict:
    from _common import probe_media
    try:
        info = probe_media(path)
    except (SystemExit, ValueError) as exc:
        raise ReferenceSourceError(f"下载的文件无法用 ffprobe 识别：{path}（{exc}）") from exc
    if not info.get("width") or not info.get("height") or not info.get("duration"):
        raise ReferenceSourceError(f"下载的文件没有可用的视频轨：{path}")
    return info


# ------------------------------------------------------------------ 抖音入口

def fetch_douyin(url: str, out_dir: Path, *, cookie: str | None, timeout: float,
                 log) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    opener = _opener()
    warnings: list[str] = []
    resolved, html = _get(opener, url, cookie=cookie, timeout=timeout)
    aweme_id = parse_aweme_id(resolved) or parse_aweme_id(url)
    # 第一次请求通常只下发 ttwid；同一个 opener 再请求一次才带 videoInfoRes。
    # 桌面版 /video/ 页面可能是空壳，所以再给一个 iesdouyin 分享页兜底。
    targets = [resolved]
    if aweme_id:
        canonical = _share_url(aweme_id)
        if canonical.rstrip("/") not in resolved.rstrip("/"):
            targets.append(canonical)
    data = None
    last_error: ReferenceSourceError | None = None
    first = True
    for target in targets:
        if not first:
            resolved, html = _get(opener, target, cookie=cookie, timeout=timeout)
        first = False
        for attempt in range(2):
            try:
                data = parse_share_html(html)
                break
            except ReferenceSourceError as exc:
                last_error = exc
                if attempt == 1:
                    break
                log("  分享页首次未带作品数据；带 Cookie 重试")
                time.sleep(0.6)
                resolved, html = _get(opener, resolved, cookie=cookie, timeout=timeout)
        if data is not None:
            break
    if data is None:
        _save_debug(out_dir, html)
        raise ReferenceSourceError(
            f"抖音分享页没有返回作品数据：{last_error or '未知原因'}")
    if data.get("is_image_post"):
        raise ReferenceSourceError("这条抖音作品是图文，没有视频轨；请换一条视频链接")
    if not data.get("play_urls"):
        raise ReferenceSourceError("这条作品没有可下载的视频地址（可能仅登录可见或被限制）")
    log(f"  作品 {data['aweme_id']} · {data['meta'].get('author') or '未知作者'}"
        f" · {data['meta'].get('duration') or '?'}s")
    video_path = out_dir / "douyin.mp4"
    used = _download(opener, data["play_urls"], video_path, cookie=cookie,
                     timeout=timeout, referer="https://www.douyin.com/", log=log)
    if "/play/" not in used:
        warnings.append("没有拿到去水印地址，下载的是带水印版本；只用于拆解，不进成片。")
    cover_path = None
    if data.get("cover_url"):
        cover_path = out_dir / "cover.jpg"
        try:
            _download(opener, [data["cover_url"]], cover_path, cookie=cookie,
                      timeout=timeout, referer="https://www.douyin.com/", log=lambda *_: None)
        except ReferenceSourceError as exc:
            cover_path.unlink(missing_ok=True)
            cover_path = None
            warnings.append(f"封面下载失败：{exc}")
    _verify_media(video_path)
    return {
        "platform": "douyin",
        "engine": "share_page",
        "input": url,
        "resolved_url": _clean_url(resolved),
        "aweme_id": data["aweme_id"],
        "video": str(video_path.resolve()),
        "cover": str(cover_path.resolve()) if cover_path else None,
        "meta": data["meta"],
        "warnings": warnings,
    }


def _share_url(aweme_id: str) -> str:
    return f"https://www.iesdouyin.com/share/video/{aweme_id}/"


def _save_debug(out_dir: Path, html: str) -> None:
    try:
        (out_dir / "share-page.html").write_text(html[:2_000_000], encoding="utf-8")
    except OSError:
        pass


# ------------------------------------------------------------------ yt-dlp 回退

def find_ytdlp() -> list[str] | None:
    exe = shutil.which("yt-dlp")
    if exe:
        return [exe]
    try:
        proc = subprocess.run([sys.executable, "-m", "yt_dlp", "--version"],
                              capture_output=True, text=True, timeout=15)
        if proc.returncode == 0:
            return [sys.executable, "-m", "yt_dlp"]
    except (OSError, subprocess.SubprocessError):
        pass
    return None


def fetch_ytdlp(url: str, out_dir: Path, *, timeout: float, log) -> dict:
    cmd = find_ytdlp()
    if not cmd:
        raise ReferenceSourceError(
            "需要 `yt-dlp` 才能下载这个链接：`pip install -U yt-dlp`，"
            "或先把视频下载到本地再把文件路径传给本命令。")
    out_dir.mkdir(parents=True, exist_ok=True)
    template = str(out_dir / "source.%(ext)s")
    argv = [*cmd, "--no-playlist", "--no-warnings", "--write-info-json",
            "--merge-output-format", "mp4", "-f", "bv*+ba/b",
            "-o", template, url]
    log("  用 yt-dlp 下载…")
    try:
        proc = subprocess.run(argv, capture_output=True, text=True,
                              timeout=max(timeout, 600))
    except subprocess.TimeoutExpired as exc:
        raise ReferenceSourceError("yt-dlp 下载超时（10 分钟）") from exc
    if proc.returncode != 0:
        tail = "\n".join((proc.stderr or proc.stdout or "").strip().splitlines()[-4:])
        raise ReferenceSourceError(f"yt-dlp 下载失败：\n  {tail}")
    videos = [p for p in out_dir.glob("source.*") if p.suffix.lower() in VIDEO_EXT]
    if not videos:
        raise ReferenceSourceError("yt-dlp 没有产出视频文件")
    video = max(videos, key=lambda p: p.stat().st_size)
    info = {}
    for candidate in out_dir.glob("source*.info.json"):
        try:
            info = json.loads(candidate.read_text(encoding="utf-8"))
            break
        except (OSError, ValueError):
            continue
    meta = {
        "id": str(info.get("id") or parse_aweme_id(url) or ""),
        "title": str(info.get("title") or info.get("description") or "").strip(),
        "author": str(info.get("uploader") or info.get("creator") or "").strip(),
        "author_id": str(info.get("uploader_id") or "").strip(),
        "music": "",
        "duration": info.get("duration"),
        "created_at": info.get("timestamp"),
        "stats": {
            "likes": info.get("like_count"),
            "comments": info.get("comment_count"),
            "shares": info.get("repost_count"),
            "favorites": None,
            "plays": info.get("view_count"),
        },
        "hashtags": info.get("tags") or [],
    }
    _verify_media(video)
    return {
        "platform": "douyin" if detect_platform(url) == "douyin" else "url",
        "engine": "yt-dlp",
        "input": url,
        "resolved_url": _clean_url(str(info.get("webpage_url") or url)),
        "aweme_id": meta["id"] or None,
        "video": str(video.resolve()),
        "cover": None,
        "meta": meta,
        "warnings": [],
    }


# ------------------------------------------------------------------ 统一入口

def fetch_reference(source: str, out_dir: str | Path, *, cookie: str | None = None,
                    engine: str = "auto", timeout: float = 60.0,
                    log=print) -> dict:
    """把「本地路径 / 抖音链接 / 其他链接」统一成 {video, meta, engine, …}。

    已存在的本地文件不复制、不改名，直接作为分析对象。
    """
    raw = str(source or "").strip()
    if not raw:
        raise ReferenceSourceError("没有给参考片：需要本地文件路径或抖音分享链接")
    out = Path(out_dir).resolve()
    path = Path(raw).expanduser()
    if path.is_file():
        info = _verify_media(path.resolve())
        return {
            "platform": "local",
            "engine": "local",
            "input": raw,
            "resolved_url": None,
            "aweme_id": None,
            "video": str(path.resolve()),
            "cover": None,
            "meta": {"title": path.stem, "duration": info.get("duration"),
                     "author": "", "id": "", "stats": {}},
            "warnings": [],
        }
    if not _looks_like_url(raw):
        raise ReferenceSourceError(f"找不到参考片文件：{path}")
    url = extract_url(raw) or raw
    cookie = cookie or os.environ.get("DOUYIN_COOKIE") or None
    cookie = load_cookie(cookie)
    if engine not in ("auto", "share", "yt-dlp"):
        raise ReferenceSourceError("engine 只能是 auto / share / yt-dlp")
    platform = detect_platform(url)

    errors: list[str] = []
    if engine in ("auto", "share") and platform == "douyin":
        try:
            return fetch_douyin(url, out / "douyin", cookie=cookie,
                               timeout=timeout, log=log)
        except ReferenceSourceError as exc:
            errors.append(f"分享页：{exc}")
            if engine == "share":
                raise
            log(f"  分享页解析失败：{exc}")
    if engine in ("auto", "yt-dlp"):
        try:
            return fetch_ytdlp(url, out / "yt-dlp", timeout=timeout, log=log)
        except ReferenceSourceError as exc:
            errors.append(f"yt-dlp：{exc}")
    detail = "\n  ".join(errors) if errors else "没有可用的下载引擎"
    raise ReferenceSourceError(
        f"拿不到参考片：\n  {detail}\n"
        "下一步：在本机浏览器把视频下载成 mp4，再把文件路径传给本命令；"
        "或用 `--cookie` 复用抖音 Cookie。")


def _read_json_file(path: Path) -> dict | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def prepare_reference(value, work_dir: str | Path, *, cookie: str | None = None,
                      engine: str = "auto", log=print) -> dict:
    """给 `auto` / `new` 用的入口：本地文件 / 抖音链接 / reference 档案目录。

    返回 `{video, teardown, source, profile}`：
    - 目录是 `koubo reference` 的产物时，直接复用其中的 `teardown.json`，不重量；
    - 链接只下载原片，拆解仍由调用方决定（auto 只需要几何数值）；
    - 本地文件不复制。
    """
    text = str(value or "").strip()
    path = Path(text).expanduser()
    if path.is_dir():
        source = _read_json_file(path / "source.json")
        teardown = _read_json_file(path / "teardown.json")
        profile = path / "reference-profile.json"
        candidates = [path / "douyin" / "douyin.mp4"]
        candidates.extend(sorted(path.glob("source.*")))
        video = next((p for p in candidates if p.is_file()), None)
        if video is None and source and source.get("video"):
            candidate = Path(str(source["video"]))
            video = candidate if candidate.is_file() else None
        if teardown is None and video is None:
            raise ReferenceSourceError(f"目录里没有可用的参考片：{path}")
        return {"video": video, "teardown": teardown, "source": source,
                "profile": profile if profile.is_file() else None,
                "reused": bool(teardown)}
    if _looks_like_url(text):
        out = Path(work_dir) / "reference-source"
        result = fetch_reference(text, out, cookie=cookie, engine=engine, log=log)
        return {"video": Path(result["video"]), "teardown": None,
                "source": result, "profile": None, "reused": False}
    if not path.is_file():
        raise ReferenceSourceError(f"找不到参考片：{text}")
    return {"video": path.resolve(), "teardown": None, "source": None,
            "profile": None, "reused": False}
