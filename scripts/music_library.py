#!/usr/bin/env python3
"""剪映云端音乐库：扫描历史草稿里的 music_id，搜索、选择、下载为本地 BGM。

参考 jianying-editor-skill 的 build_cloud_music_library 思路，但只保留我们需要的：
- 扫描 draft_content.json（含 .capcut-cli-history/.backup 快照）里的 type=music；
- 可导入外部 CSV（music_id,title,duration_s,categories,url）；
- 选择后下载到 work/cloud-music，再转成 work/bgm.wav 进入现有渲染/草稿链；
- 没有 CDN 地址就明确报错，不伪造“云端音乐已加载”。

缓存默认 ~/.cache/koubo/music-library.json；可用 KOUBO_MUSIC_LIBRARY 覆盖。
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _common import (find_ffmpeg, load_config, project_paths,  # noqa: E402
                     resolve_duration, write_json)

DEFAULT_CACHE = Path(os.environ.get(
    "KOUBO_MUSIC_LIBRARY", Path.home() / ".cache" / "koubo" / "music-library.json"))
MAX_BYTES = 80 * 1024 * 1024
SYNONYMS = {
    "温暖": ["warm", "治愈", "舒缓", "温柔", "vlog"],
    "治愈": ["warm", "calm", "舒缓", "vlog"],
    "高级": ["corporate", "luxury", "cinematic", "premium"],
    "轻快": ["upbeat", "happy", "funk", "vlog"],
    "节奏": ["upbeat", "funk", "driving", "cut"],
    "安静": ["calm", "lofi", "ambient", "soft"],
    "品牌": ["corporate", "brand", "motivational"],
    "电子": ["electronic", "synth", "future"],
}


class MusicLibraryError(RuntimeError):
    pass


def default_roots() -> list[Path]:
    home = Path.home()
    return [
        home / "Movies/JianyingPro/User Data/Projects/com.lveditor.draft",
        home / "Movies/JianyingPro Drafts",
        home / "Library/Containers/com.lemon.lvpro/Data/Library/Application Support/"
        "JianyingPro/User Data/Projects/com.lveditor.draft",
    ]


def _read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def load_cache(path: Path = DEFAULT_CACHE) -> dict:
    try:
        data = _read(path)
        if isinstance(data.get("items"), list):
            return data
    except (OSError, ValueError, TypeError):
        pass
    return {"version": 1, "updated_at": "", "items": []}


def save_cache(data: dict, path: Path = DEFAULT_CACHE) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    items = []
    for row in data.get("items") or []:
        row = dict(row)
        row["categories"] = sorted(row.get("categories") or [])
        row["sources"] = sorted(row.get("sources") or [])
        items.append(row)
    data = {**data, "items": items, "updated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z")}
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def _merge(items: dict[str, dict], row: dict, source: str) -> None:
    mid = str(row.get("music_id") or "").strip()
    if not mid.isdigit():
        return
    current = items.get(mid)
    if current is None:
        current = items[mid] = {
            "music_id": mid, "title": str(row.get("title") or row.get("name") or "").strip(),
            "duration_s": float(row.get("duration_s") or 0.0),
            "categories": set(), "url": str(row.get("url") or "").strip(),
            "sources": set(),
        }
    if row.get("title") or row.get("name"):
        current["title"] = current["title"] or str(row.get("title") or row.get("name")).strip()
    try:
        duration = float(row.get("duration_s") or 0.0)
        if duration > 0:
            current["duration_s"] = duration
    except (TypeError, ValueError):
        pass
    cats = str(row.get("categories") or "").replace("|", ",").split(",")
    for cat in cats:
        if cat.strip():
            current["categories"].add(cat.strip())
    if row.get("url"):
        current["url"] = str(row["url"]).strip()
    current["sources"].add(source)


def _iter_json(path: Path):
    try:
        if path.stat().st_size > 80 * 1024 * 1024:
            return
    except OSError:
        return
    try:
        yield _read(path)
    except (OSError, ValueError):
        return


def scan_drafts(roots: list[Path] | None = None, *,
                cache_path: Path = DEFAULT_CACHE,
                include_history: bool = True) -> dict:
    items = {row["music_id"]: row for row in load_cache(cache_path)["items"]}
    for row in items.values():
        row["categories"] = set(row.get("categories") or [])
        row["sources"] = set(row.get("sources") or [])
    files = 0
    for root in roots or default_roots():
        root = Path(root).expanduser()
        if not root.is_dir():
            continue
        patterns = ["*/draft_content.json", "*/draft_info.json"]
        if include_history:
            patterns += ["*/.capcut-cli-history/*.snap", "*/.backup/**/*.bak"]
        seen = set()
        for pattern in patterns:
            for path in root.glob(pattern):
                if path in seen:
                    continue
                seen.add(path)
                for data in _iter_json(path):
                    files += 1
                    for audio in (data.get("materials") or {}).get("audios") or []:
                        if str(audio.get("type") or "") not in ("music", "cloud_music"):
                            continue
                        mid = str(audio.get("music_id") or "").strip()
                        if not mid.isdigit():
                            continue
                        url = ""
                        for key in ("url", "path", "material_url", "media_path"):
                            value = str(audio.get(key) or "")
                            if value.startswith("http"):
                                url = value
                                break
                        _merge(items, {
                            "music_id": mid, "name": audio.get("name") or "",
                            "duration_s": float(audio.get("duration") or 0) / 1_000_000,
                            "categories": audio.get("category_name") or "",
                            "url": url,
                        }, f"draft:{path.parent.name}")
    data = {"version": 1, "items": sorted(items.values(), key=lambda x: x["title"])}
    save_cache(data, cache_path)
    return {"files": files, "count": len(items), "cache": str(cache_path)}


def import_csv(path: Path, cache_path: Path = DEFAULT_CACHE) -> dict:
    items = {row["music_id"]: row for row in load_cache(cache_path)["items"]}
    for row in items.values():
        row["categories"] = set(row.get("categories") or [])
        row["sources"] = set(row.get("sources") or [])
    count = 0
    with Path(path).open(encoding="utf-8", newline="") as stream:
        lines = [line for line in stream if not line.startswith("#")]
    for row in csv.DictReader(lines):
        _merge(items, row, f"import:{Path(path).name}")
        count += 1
    save_cache({"version": 1, "items": sorted(items.values(), key=lambda x: x["title"])},
               cache_path)
    return {"imported": count, "count": len(items), "cache": str(cache_path)}


def _terms(query: str) -> set[str]:
    words = {w for w in query.lower().replace("/", " ").replace("|", " ").split() if w}
    for w in list(words):
        words.update(SYNONYMS.get(w, []))
    return words


def search(query: str, cache_path: Path = DEFAULT_CACHE, limit: int = 20) -> list[dict]:
    data = load_cache(cache_path)
    if not query.strip():
        rows = sorted(data["items"], key=lambda x: x.get("title", ""))
        return [{**row, "score": 0} for row in rows[:max(1, limit)]]
    words = _terms(query)
    scored = []
    for row in data["items"]:
        text = " ".join([row.get("music_id", ""), row.get("title", ""),
                         " ".join(row.get("categories") or []),
                         " ".join(row.get("sources") or [])]).lower()
        score = 0
        if query.lower() in text:
            score += 100
        for word in words:
            if word and word in text:
                score += 10
        if score:
            scored.append((score, row))
    scored.sort(key=lambda pair: (-pair[0], pair[1].get("title", "")))
    return [{**row, "score": score} for score, row in scored[:max(1, limit)]]


def find(query: str, cache_path: Path = DEFAULT_CACHE) -> dict:
    hits = search(query, cache_path, 5)
    if not hits:
        raise MusicLibraryError(f"音乐库里没有 {query!r}；先 scan/import 或换关键词")
    exact = [h for h in hits if h["music_id"] == query or h["title"] == query]
    return (exact or hits)[0]


def _download(item: dict, project: Path, total: float) -> Path:
    url = str(item.get("url") or "")
    if not url.startswith(("http://", "https://")):
        raise MusicLibraryError(
            f"音乐 {item['music_id']} 没有 CDN URL；先在剪映里播放/缓存这首，"
            "或从有 url 的 CSV import 后再选")
    work = project_paths(project)["work"]
    raw_dir = work / "cloud-music"
    raw_dir.mkdir(parents=True, exist_ok=True)
    suffix = ".m4a"
    parsed = urllib.parse.urlparse(url)
    query = urllib.parse.parse_qs(parsed.query)
    hint = (query.get("mime_type") or [""])[0].lower()
    if "mpeg" in hint:
        suffix = ".mp3"
    raw = raw_dir / f"{item['music_id']}{suffix}"
    if not raw.is_file() or raw.stat().st_size == 0:
        req = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0 KouboStudio/1.0",
            "Referer": "https://www.jianying.com/",
        })
        try:
            with urllib.request.urlopen(req, timeout=45) as response:
                ctype = (response.headers.get("Content-Type") or "").lower()
                if ctype.startswith(("text/html", "application/json")):
                    raise MusicLibraryError(f"音乐 URL 返回 {ctype}，不是音频")
                length = int(response.headers.get("Content-Length") or 0)
                if length > MAX_BYTES:
                    raise MusicLibraryError("音乐文件超过 80MB，拒绝下载")
                data = response.read(MAX_BYTES + 1)
        except Exception as exc:
            raise MusicLibraryError(f"音乐下载失败：{type(exc).__name__}: {exc}") from exc
        if len(data) > MAX_BYTES:
            raise MusicLibraryError("音乐文件超过 80MB，拒绝下载")
        raw.write_bytes(data)
    bgm = work / "bgm.wav"
    subprocess.run([
        find_ffmpeg(), "-v", "error", "-y", "-stream_loop", "-1", "-i", str(raw),
        "-t", f"{total:.3f}", "-ar", "48000", "-ac", "2", "-c:a", "pcm_s16le", str(bgm),
    ], check=True)
    write_json(work / "music-selection.json", {
        "version": 1, "music_id": item["music_id"], "title": item.get("title", ""),
        "duration_s": item.get("duration_s"), "url": url, "raw": str(raw),
        "bgm": str(bgm), "source": "jianying-cloud",
    })
    return bgm


def prepare(cfg: dict, project: Path, total: float,
            cache_path: Path = DEFAULT_CACHE) -> dict:
    bgm = (cfg.get("audio") or {}).get("bgm") or {}
    mid = str(bgm.get("music_id") or "")
    if not mid:
        return {"status": "not-cloud"}
    cache_path = Path(str(bgm.get("cache") or cache_path))
    item = find(mid, cache_path)
    bgm_path = project_paths(project)["work"] / "bgm.wav"
    if bgm_path.is_file():
        try:
            selection = _read(project_paths(project)["work"] / "music-selection.json")
        except (OSError, ValueError):
            selection = {}
        if selection.get("music_id") == mid:
            return {"status": "cached", "music_id": mid, "title": item.get("title", "")}
    _download(item, project, total)
    return {"status": "downloaded", "music_id": mid, "title": item.get("title", "")}


def pick(project: Path, query: str, *, volume: float = 0.25,
         cache_path: Path = DEFAULT_CACHE) -> dict:
    cfg = load_config(project_paths(project)["config"])
    total = resolve_duration(cfg, project)
    item = find(query, cache_path)
    _download(item, project, total)
    bgm = cfg.setdefault("audio", {}).setdefault("bgm", {})
    bgm.update({"enabled": True, "source": "jianying-cloud",
                "music_id": item["music_id"], "title": item.get("title", ""),
                "cache": str(cache_path)})
    cfg["audio"]["bgm_volume"] = float(volume)
    write_json(project_paths(project)["config"], cfg)
    return {"music_id": item["music_id"], "title": item.get("title", ""),
            "volume": volume, "project": str(project)}


def _cli() -> None:
    ap = argparse.ArgumentParser(description="剪映云端音乐库：scan/import/search/pick")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("scan"); s.add_argument("--cache", default=str(DEFAULT_CACHE))
    s.add_argument("--no-history", action="store_true")
    i = sub.add_parser("import"); i.add_argument("csv"); i.add_argument("--cache", default=str(DEFAULT_CACHE))
    q = sub.add_parser("search"); q.add_argument("query"); q.add_argument("--limit", type=int, default=20)
    q.add_argument("--cache", default=str(DEFAULT_CACHE))
    l = sub.add_parser("list"); l.add_argument("--limit", type=int, default=20)
    l.add_argument("--cache", default=str(DEFAULT_CACHE))
    p = sub.add_parser("pick"); p.add_argument("project"); p.add_argument("--id", required=True)
    p.add_argument("--volume", type=float, default=0.25); p.add_argument("--cache", default=str(DEFAULT_CACHE))
    a = ap.parse_args()
    cache = Path(a.cache)
    try:
        if a.cmd == "scan":
            print(json.dumps(scan_drafts(cache_path=cache, include_history=not a.no_history),
                             ensure_ascii=False, indent=2))
        elif a.cmd == "import":
            print(json.dumps(import_csv(Path(a.csv), cache), ensure_ascii=False, indent=2))
        elif a.cmd == "search":
            for row in search(a.query, cache, a.limit):
                print(f"{row['music_id']}  {row.get('duration_s')}s  {row.get('title')}  "
                      f"[{','.join(row.get('categories') or [])}]")
        elif a.cmd == "list":
            for row in search("", cache, a.limit):
                print(f"{row['music_id']}  {row.get('duration_s')}s  {row.get('title')}")
        else:
            print(json.dumps(pick(Path(a.project).resolve(), a.id, volume=a.volume,
                                  cache_path=cache), ensure_ascii=False, indent=2))
    except MusicLibraryError as exc:
        raise SystemExit(str(exc)) from exc


if __name__ == "__main__":
    _cli()
