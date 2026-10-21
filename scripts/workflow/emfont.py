"""emfont 字体库客户端：复用 emfont-mcp 背后的公开 HTTP API。

`emfont-mcp` 的六个工具（list-fonts / get-font-info / generate-font / get-css-link /
list-docs / get-doc）本质上是 `https://font.emtech.cc` 上几个 HTTP 接口的封装。
这里直接用 Python 调同一套接口，不引入 Node / MCP 运行时：

    GET  /list            字体目录
    GET  /info/{fontId}   字体详情（授权、描述、字重）
    POST /g/{fontId}      按文字生成子集字体（ttf/woff/woff2）

接口不可用时**不伪造结果**：抛 `EmfontError`，由上层写进「未检查」并回退到本地字体。
目录与详情会缓存到 `~/.cache/koubo/`，断网时还能用上次的目录做选择。

emfont-mcp: https://github.com/emfont/emfont-mcp （Apache-2.0）
"""
from __future__ import annotations

import json
import os
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

DEFAULT_BASE = "https://font.emtech.cc"
USER_AGENT = "koubo-font-picker/1.0 (emfont-mcp compatible)"
CATALOG_TTL = 7 * 24 * 3600
INFO_TTL = 30 * 24 * 3600
CACHE_DIR = Path(os.environ.get("KOUBO_CACHE", Path.home() / ".cache" / "koubo"))
CATALOG_FILE = CACHE_DIR / "emfont-catalog.json"
INFO_FILE = CACHE_DIR / "emfont-info.json"
MAX_FONT_BYTES = 40 * 1024 * 1024


class EmfontError(RuntimeError):
    """emfont 不可用或返回了无法使用的数据。"""


def api_base() -> str:
    return (os.environ.get("EMFONT_API_BASE") or DEFAULT_BASE).rstrip("/")


def _cache_read(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _cache_write(path: Path, data: dict) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, name = tempfile.mkstemp(prefix=f".{path.stem}-", suffix=".json",
                                    dir=path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(data, handle, ensure_ascii=False, indent=2)
                handle.write("\n")
            os.replace(name, path)
        finally:
            Path(name).unlink(missing_ok=True)
    except OSError:
        pass


def _request(url: str, *, method: str = "GET", body: dict | None = None,
             timeout: float = 20.0) -> tuple[int, str, bytes]:
    """发一个请求并返回 (status, content_type, raw)。测试可替换这一层。"""
    headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
    data = None
    if body is not None:
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return (response.status, response.headers.get("Content-Type") or "",
                    response.read(MAX_FONT_BYTES))
    except urllib.error.HTTPError as exc:
        raw = b""
        try:
            raw = exc.read(4096)
        except OSError:
            pass
        return exc.code, exc.headers.get("Content-Type") or "", raw
    except (urllib.error.URLError, TimeoutError) as exc:
        raise EmfontError(f"连不上 emfont：{exc}") from exc


def _json(url: str, *, method: str = "GET", body: dict | None = None,
          timeout: float = 20.0):
    status, content_type, raw = _request(url, method=method, body=body, timeout=timeout)
    if "json" not in content_type.lower():
        raise EmfontError(
            f"emfont 返回了 {content_type or '非 JSON'}（HTTP {status}），"
            "服务可能暂时不可用；可稍后重试或设置 EMFONT_API_BASE")
    if status >= 400:
        raise EmfontError(f"emfont HTTP {status}：{raw[:200].decode('utf-8', 'replace')}")
    try:
        return json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise EmfontError(f"emfont 返回的 JSON 解析失败：{exc}") from exc


def _as_list(value) -> list:
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def _name_of(font: dict) -> dict:
    name = font.get("name")
    if isinstance(name, str):
        return {"original": name, "zh": name, "en": name}
    if not isinstance(name, dict):
        return {"original": "", "zh": "", "en": ""}
    return {
        "original": str(name.get("original") or ""),
        "zh": str(name.get("zh") or ""),
        "en": str(name.get("en") or ""),
    }


def normalize_font(raw: dict) -> dict:
    """把 /list 与 /info 的字段归一成同一套。"""
    if not isinstance(raw, dict):
        raise EmfontError("字体条目不是对象")
    ident = str(raw.get("id") or raw.get("fontId") or "").strip()
    names = _name_of(raw)
    explicit_zh = str(raw.get("name_zh") or "").strip()
    explicit_en = str(raw.get("name_en") or "").strip()
    name = (explicit_zh or names["zh"] or names["original"] or names["en"]
            or explicit_en or raw.get("name") or ident)
    weights = []
    for value in _as_list(raw.get("weight") or raw.get("weights")):
        try:
            weights.append(int(value))
        except (TypeError, ValueError):
            continue
    tags = []
    for value in _as_list(raw.get("tag") or raw.get("tags")):
        text = str(value or "").strip()
        if text and text not in tags:
            tags.append(text)
    return {
        "id": ident,
        "name": str(name).strip(),
        "name_zh": explicit_zh or names["zh"],
        "name_en": explicit_en or names["en"],
        "name_original": names["original"],
        "category": str(raw.get("category") or "").strip(),
        "tags": tags,
        "weights": sorted(set(weights)),
        "family": str(raw.get("family") or "").strip(),
        "version": str(raw.get("version") or "").strip(),
        "license": str(raw.get("license") or "").strip(),
        "author": str(raw.get("author") or "").strip(),
        "source": str(raw.get("source") or "").strip(),
        "description": str(raw.get("description") or "").strip(),
    }


def page_url(font_id: str) -> str:
    return f"{api_base()}/fonts/{urllib.parse.quote(font_id, safe='')}"


def list_fonts(timeout: float = 20.0) -> list[dict]:
    """GET /list，返回归一化字体列表。"""
    data = _json(f"{api_base()}/list", timeout=timeout)
    if isinstance(data, dict):
        data = data.get("fonts") or data.get("data") or data.get("items") or []
    if not isinstance(data, list):
        raise EmfontError("emfont /list 没有返回字体数组")
    fonts = []
    for raw in data:
        try:
            font = normalize_font(raw)
        except EmfontError:
            continue
        if font["id"] and font["name"]:
            fonts.append(font)
    if not fonts:
        raise EmfontError("emfont /list 返回了空目录")
    return fonts


def font_info(font_id: str, timeout: float = 15.0) -> dict:
    data = _json(f"{api_base()}/info/{urllib.parse.quote(font_id, safe='')}",
                 timeout=timeout)
    if not isinstance(data, dict):
        raise EmfontError(f"emfont /info/{font_id} 返回格式异常")
    font = normalize_font({**data, "id": font_id})
    # /info 可能把 name 放在对象里，normalize_font 已处理。
    return font


def generate_font(font_id: str, words: str, *, weight: int = 700,
                  minify: bool = False, fmt: str = "ttf",
                  timeout: float = 60.0) -> dict:
    """POST /g/{fontId} 生成只含 `words` 的子集字体，返回下载地址。"""
    if not words.strip():
        raise EmfontError("生成子集字体需要非空文字")
    if fmt not in ("ttf", "woff", "woff2"):
        raise EmfontError("字体格式只能是 ttf / woff / woff2")
    body = {"words": words, "weight": int(weight), "min": bool(minify), "format": fmt}
    data = _json(f"{api_base()}/g/{urllib.parse.quote(font_id, safe='')}",
                 method="POST", body=body, timeout=timeout)
    if not isinstance(data, dict):
        raise EmfontError(f"emfont /g/{font_id} 返回格式异常")
    status = str(data.get("status") or "").lower()
    if status and status != "success":
        raise EmfontError(f"emfont 生成字体失败：{data.get('message') or status}")
    locations = data.get("location") or data.get("locations") or []
    if isinstance(locations, str):
        locations = [locations]
    urls = [urllib.parse.urljoin(api_base() + "/", str(url))
            for url in locations if str(url).strip()]
    if not urls:
        raise EmfontError(f"emfont /g/{font_id} 没有返回字体地址")
    return {"name": str(data.get("name") or font_id), "locations": urls,
            "weight": int(weight), "format": fmt, "words": len(words)}


def download(url: str, dest: Path, *, timeout: float = 90.0) -> Path:
    """下载字体文件；校验大小与文件头，失败不留半截文件。"""
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    headers = {"User-Agent": USER_AGENT, "Accept": "font/ttf,font/otf,*/*"}
    request = urllib.request.Request(url, headers=headers)
    tmp = dest.with_suffix(dest.suffix + ".part")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            content_type = (response.headers.get("Content-Type") or "").lower()
            if "text/html" in content_type:
                raise EmfontError("字体地址返回了 HTML，可能已失效")
            with open(tmp, "wb") as handle:
                total = 0
                while True:
                    chunk = response.read(256 * 1024)
                    if not chunk:
                        break
                    total += len(chunk)
                    if total > MAX_FONT_BYTES:
                        raise EmfontError("字体文件超过 40MB，已停止下载")
                    handle.write(chunk)
        raw = tmp.read_bytes()[:4]
        if tmp.stat().st_size < 1024 or raw[:4] not in (b"\x00\x01\x00\x00", b"OTTO",
                                                        b"true", b"ttcf", b"wOFF"):
            raise EmfontError("下载到的文件不像 TTF/OTF 字体")
        os.replace(tmp, dest)
        return dest
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as exc:
        raise EmfontError(f"字体下载失败：{exc}") from exc
    finally:
        tmp.unlink(missing_ok=True)


def download_first(urls: list[str], dest: Path, *, timeout: float = 90.0) -> tuple[Path, str]:
    errors = []
    for url in urls:
        try:
            return download(url, dest, timeout=timeout), url
        except EmfontError as exc:
            errors.append(str(exc))
            continue
    raise EmfontError("所有字体地址都下载失败：\n  " + "\n  ".join(errors[-3:]))


def catalog(*, fresh: bool = False, allow_cache: bool = True,
            timeout: float = 20.0) -> dict:
    """读字体目录，优先线上，失败回退缓存（缓存过期也保留，并说明是旧数据）。"""
    cached = _cache_read(CATALOG_FILE)
    now = time.time()
    fetched = float(cached.get("fetched_at") or 0)
    if cached.get("fonts") and not fresh and now - fetched < CATALOG_TTL:
        return {"fonts": cached["fonts"], "from_cache": True, "stale": False,
                "fetched_at": cached.get("fetched_at")}
    try:
        fonts = list_fonts(timeout=timeout)
        _cache_write(CATALOG_FILE, {"fetched_at": now, "fonts": fonts})
        return {"fonts": fonts, "from_cache": False, "stale": False,
                "fetched_at": now}
    except EmfontError as exc:
        if allow_cache and cached.get("fonts"):
            return {"fonts": cached["fonts"], "from_cache": True, "stale": True,
                    "fetched_at": cached.get("fetched_at"), "warning": str(exc)}
        raise


def _info_cache() -> dict:
    return _cache_read(INFO_FILE)


def font_info_cached(font_id: str, *, timeout: float = 12.0) -> dict:
    """详情缓存 30 天；失败时返回目录里已有的最小信息，不阻断选择。"""
    data = _info_cache()
    row = data.get(font_id) or {}
    now = time.time()
    if row.get("info") and now - float(row.get("fetched_at") or 0) < INFO_TTL:
        return row["info"]
    try:
        info = font_info(font_id, timeout=timeout)
    except EmfontError:
        return {"id": font_id, "license": "", "description": "", "tags": [],
                "weights": [], "name": font_id, "name_zh": "", "name_en": "",
                "category": "", "family": "", "author": "", "source": ""}
    data[font_id] = {"fetched_at": now, "info": info}
    _cache_write(INFO_FILE, data)
    return info
