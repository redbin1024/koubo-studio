#!/usr/bin/env python3
"""Mixkit 免费素材模块：搜索/下载 stock video、music、SFX，并记录来源与许可。

Mixkit 是 Envato 的免费素材站：脚本只抓公开页面/下载地址，不绕过登录或付费墙。
素材授权以 Mixkit License 为准（可商用，但不能单独转售/再分发素材本身）。
"""
from __future__ import annotations

import argparse
import html as html_mod
import json
import re
import subprocess
import sys
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _common import (find_ffmpeg, load_config, project_paths,  # noqa: E402
                     resolve_duration, write_json)

BASE = "https://mixkit.co"
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) KouboStudio/1.0"
LICENSE = {
    "video": "https://mixkit.co/license/#videoFree",
    "music": "https://mixkit.co/license/#musicFree",
    "sfx": "https://mixkit.co/license/#sfxFree",
}
KIND_PATHS = {
    "video": "free-stock-video",
    "music": "free-stock-music",
    "sfx": "free-sound-effects",
}
MAX_BYTES = 200 * 1024 * 1024


class MixkitError(RuntimeError):
    pass


def _get(url: str, *, timeout: int = 30) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            raw = response.read(MAX_BYTES + 1)
            ctype = (response.headers.get("Content-Type") or "").lower()
    except Exception as exc:  # noqa: BLE001
        raise MixkitError(f"Mixkit 请求失败 {url}: {type(exc).__name__}: {exc}") from exc
    if len(raw) > MAX_BYTES:
        raise MixkitError("页面超过 200MB，拒绝")
    if "text/html" not in ctype and "json" not in ctype:
        raise MixkitError(f"Mixkit 返回非 HTML/JSON：{ctype}")
    return raw.decode("utf-8", "ignore")


def _jsonld(page: str) -> list:
    out = []
    for match in re.finditer(
            r'<script[^>]+application/ld\+json[^>]*>(.*?)</script>', page, re.S):
        try:
            out.append(json.loads(html_mod.unescape(match.group(1))))
        except ValueError:
            continue
    return out


def _walk(value):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk(child)


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html_mod.unescape(text or ""))).strip()


def _slug(query: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", query.lower()).strip("-") or "nature"


def _parse_video(page: str) -> list[dict]:
    items, seen = [], set()
    for obj in _walk(_jsonld(page)):
        if str(obj.get("@type") or "") != "VideoObject":
            continue
        url = str(obj.get("contentUrl") or "")
        if not url.startswith("http") or url in seen:
            continue
        seen.add(url)
        m = re.search(r"/videos/(\d+)/", url)
        items.append({
            "id": m.group(1) if m else url, "kind": "video",
            "title": _clean(str(obj.get("name") or "")),
            "description": _clean(str(obj.get("description") or ""))[:300],
            "duration": str(obj.get("duration") or ""),
            "url": url, "thumb": str(obj.get("thumbnailUrl") or ""),
            "license": str(obj.get("license") or LICENSE["video"]),
            "page": str(obj.get("url") or obj.get("mainEntityOfPage") or ""),
        })
    return items


def _parse_music(page: str) -> list[dict]:
    items, seen = [], set()
    for obj in _walk(_jsonld(page)):
        if str(obj.get("@type") or "") != "MusicRecording":
            continue
        url = str(obj.get("url") or "")
        if not url.startswith("http") or url in seen:
            continue
        seen.add(url)
        m = re.search(r"/music/(\d+)/", url)
        items.append({
            "id": m.group(1) if m else url, "kind": "music",
            "title": _clean(str(obj.get("name") or "")),
            "artist": _clean(str(obj.get("byArtist") or "")),
            "genre": _clean(str(obj.get("genre") or "")),
            "duration": str(obj.get("duration") or ""),
            "url": url, "license": str(obj.get("license") or LICENSE["music"]),
            "page": str(obj.get("@id") or ""),
        })
    return items


def _parse_sfx(page: str) -> list[dict]:
    items = []
    pattern = re.compile(
        r'data-audio-player-preview-url-value="(?P<preview>https://[^"]+)"'
        r'.*?data-audio-player-item-id-value="(?P<id>\d+)"'
        r'.*?<h2[^>]*>(?P<title>.*?)</h2>', re.S)
    for m in pattern.finditer(page):
        items.append({
            "id": m.group("id"), "kind": "sfx",
            "title": _clean(m.group("title")),
            "preview": m.group("preview"),
            "url": "", "license": LICENSE["sfx"], "page": "",
        })
    # 兼容标题在 player 前面的布局
    if not items:
        pattern2 = re.compile(
            r'<h2[^>]*>(?P<title>.*?)</h2>.*?'
            r'data-audio-player-preview-url-value="(?P<preview>https://[^"]+)"'
            r'.*?data-audio-player-item-id-value="(?P<id>\d+)"', re.S)
        for m in pattern2.finditer(page):
            items.append({
                "id": m.group("id"), "kind": "sfx",
                "title": _clean(m.group("title")), "preview": m.group("preview"),
                "url": "", "license": LICENSE["sfx"], "page": "",
            })
    return items


def search(kind: str, query: str, limit: int = 12) -> list[dict]:
    if kind not in KIND_PATHS:
        raise MixkitError(f"未知类型 {kind}")
    url = f"{BASE}/{KIND_PATHS[kind]}/discover/{urllib.parse.quote(_slug(query))}/"
    page = _get(url)
    items = {"video": _parse_video, "music": _parse_music, "sfx": _parse_sfx}[kind](page)
    for item in items:
        item["search_url"] = url
    return items[:max(1, limit)]


def _resolve_sfx(url: str, item: dict) -> str:
    if item.get("url"):
        return str(item["url"])
    page = _get(f"{BASE}/free-sound-effects/download/{item['id']}/")
    match = re.search(r'data-download--modal-url-value="([^"]+)"', page)
    if not match:
        raise MixkitError(f"SFX {item['id']} 没有解析到下载地址")
    return html_mod.unescape(match.group(1))


def _choose(item: dict, kind: str, quality: str) -> str:
    if kind == "sfx":
        return _resolve_sfx("", item)
    url = str(item.get("url") or "")
    if not url:
        raise MixkitError("素材没有下载地址")
    if kind == "video" and quality == "720":
        return url.replace("-1080.mp4", "-720.mp4")
    return url


def _direct_url(kind: str, item_id: str, quality: str = "1080") -> str:
    if not str(item_id).isdigit():
        return ""
    if kind == "video":
        return f"https://assets.mixkit.co/videos/{item_id}/{item_id}-{quality}.mp4"
    if kind == "music":
        return f"https://assets.mixkit.co/music/{item_id}/{item_id}.mp3"
    return ""


def _safe_stem(item: dict, fallback: str) -> str:
    stem = _slug(str(item.get("title") or fallback))
    return stem[:60] or fallback


def _download_file(url: str, dest: Path) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Referer": BASE + "/"})
    try:
        with urllib.request.urlopen(req, timeout=60) as response:
            ctype = (response.headers.get("Content-Type") or "").lower()
            if ctype.startswith(("text/html", "application/json")):
                raise MixkitError(f"下载地址返回 {ctype}")
            data = response.read(MAX_BYTES + 1)
    except Exception as exc:  # noqa: BLE001
        if isinstance(exc, MixkitError):
            raise
        raise MixkitError(f"下载失败：{type(exc).__name__}: {exc}") from exc
    if len(data) > MAX_BYTES:
        raise MixkitError("素材超过 200MB，拒绝")
    dest.write_bytes(data)
    return dest


def _record(project: Path, item: dict, local: Path, url: str) -> None:
    p = project_paths(project)
    path = p["work"] / "mixkit.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {"version": 1, "items": []}
    data.setdefault("items", []).append({
        "kind": item.get("kind"), "id": item.get("id"), "title": item.get("title"),
        "url": url, "local": str(local), "license": item.get("license") or LICENSE.get(item.get("kind"), ""),
        "search_url": item.get("search_url") or item.get("page") or "",
    })
    write_json(path, data)


def download(project: Path, kind: str, item_id: str | None, url: str | None,
             *, out: str | None = None, quality: str = "1080") -> dict:
    if kind not in KIND_PATHS:
        raise MixkitError("kind 必须是 video/music/sfx")
    if not item_id and not url:
        raise MixkitError("需要 --id 或 --url（先用 search 找）")
    item = {"id": item_id or "custom", "kind": kind, "title": item_id or "mixkit", "url": url or ""}
    if item_id and not url:
        if kind == "sfx":
            item["url"] = _resolve_sfx("", item)
        else:
            direct = _direct_url(kind, str(item_id), quality)
            if not direct:
                raise MixkitError("这类素材需要 --url（先用 search 查看；active_storage ID 不能用固定文件名）")
            item["url"] = direct
    target = _choose(item, kind, quality)
    p = project_paths(project)
    if out:
        dest = (project / out).resolve()
    elif kind == "video":
        dest = p["assets"] / "mixkit" / "video" / f"{_safe_stem(item, str(item['id']))}.mp4"
    elif kind == "music":
        dest = p["assets"] / "mixkit" / "music" / f"{_safe_stem(item, str(item['id']))}.mp3"
    else:
        dest = p["assets"] / "mixkit" / "sfx" / f"{_safe_stem(item, str(item['id']))}.wav"
    _download_file(target, dest)
    _record(project, item, dest, target)
    return {"local": str(dest), "url": target, "item": item}


def use_as_bgm(project: Path, local: Path) -> dict:
    p = project_paths(project)
    cfg = load_config(p["config"])
    total = resolve_duration(cfg, project)
    raw = local
    out = p["work"] / "bgm.wav"
    ff = find_ffmpeg()
    subprocess.run([ff, "-v", "error", "-y", "-stream_loop", "-1", "-i", str(raw),
                    "-t", f"{total:.3f}", "-ar", "48000", "-ac", "2", "-c:a", "pcm_s16le",
                    str(out)], check=True)
    cfg.setdefault("audio", {}).setdefault("bgm", {})
    cfg["audio"]["bgm"].update({"enabled": True, "source": "mixkit", "title": raw.stem})
    write_json(p["config"], cfg)
    return {"bgm": str(out), "duration": total}


def use_as_broll(project: Path, local: Path, cue: int, keyword: str, dur: float = 2.0) -> dict:
    p = project_paths(project)
    cfg = load_config(p["config"])
    broll_dir = p["input"] / "broll"
    broll_dir.mkdir(parents=True, exist_ok=True)
    dest = broll_dir / local.name
    dest.write_bytes(local.read_bytes())
    block = cfg.setdefault("broll", {"enabled": True, "items": []})
    block["enabled"] = True
    block.setdefault("items", []).append({
        "cue": int(cue), "keyword": keyword, "source": f"broll/{dest.name}",
        "in": 0.0, "dur": float(dur), "volume": 0.0,
    })
    write_json(p["config"], cfg)
    return {"source": f"broll/{dest.name}", "cue": cue, "keyword": keyword}


def _cli() -> None:
    ap = argparse.ArgumentParser(description="Mixkit 免费素材：search/download/broll/bgm")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("search"); s.add_argument("kind", choices=sorted(KIND_PATHS))
    s.add_argument("query"); s.add_argument("--limit", type=int, default=12)
    d = sub.add_parser("download"); d.add_argument("project"); d.add_argument("kind", choices=sorted(KIND_PATHS))
    d.add_argument("--id"); d.add_argument("--url"); d.add_argument("--out")
    d.add_argument("--quality", choices=("1080", "720"), default="1080")
    b = sub.add_parser("broll"); b.add_argument("project"); b.add_argument("--id", required=True)
    b.add_argument("--cue", type=int, required=True); b.add_argument("--keyword", required=True)
    b.add_argument("--dur", type=float, default=2.0); b.add_argument("--quality", default="1080")
    m = sub.add_parser("bgm"); m.add_argument("project"); m.add_argument("--id", required=True)
    a = ap.parse_args()
    try:
        if a.cmd == "search":
            for i, item in enumerate(search(a.kind, a.query, a.limit), 1):
                print(f"{i:02d}. {item['id']}  {item.get('duration','')}  {item['title']}"
                      f"  {item.get('artist','')}  {item.get('url') or item.get('preview','')}")
        elif a.cmd == "download":
            print(json.dumps(download(Path(a.project).resolve(), a.kind, a.id, a.url,
                                      out=a.out, quality=a.quality), ensure_ascii=False, indent=2))
        elif a.cmd == "broll":
            got = download(Path(a.project).resolve(), "video", a.id, None, quality=a.quality)
            print(json.dumps(use_as_broll(Path(a.project).resolve(), Path(got["local"]),
                                          a.cue, a.keyword, a.dur), ensure_ascii=False, indent=2))
        else:
            got = download(Path(a.project).resolve(), "music", a.id, None)
            print(json.dumps(use_as_bgm(Path(a.project).resolve(), Path(got["local"])),
                             ensure_ascii=False, indent=2))
    except MixkitError as exc:
        raise SystemExit(str(exc)) from exc


if __name__ == "__main__":
    _cli()
