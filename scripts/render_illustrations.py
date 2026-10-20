#!/usr/bin/env python3
"""Render repo SVG illustrations into a project's assets/illustrations/*.png.

Only runs when the project config actually references `illustrations/...`.
The SVG is the editable source; the PNG is what make_assets composites.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _common import ensure_dirs, load_config, project_paths, write_json  # noqa: E402
from render_svg import render  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "assets" / "illustrations"


def _sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def referenced(cfg: dict) -> set[str]:
    out = set()
    for item in (cfg.get("inserts") or {}).get("items") or []:
        value = str(item.get("illustration") or "")
        if value.endswith(".png"):
            out.add(Path(value).stem)
    return out


async def render_all_async(project: Path, source: Path = SOURCE) -> dict:
    cfg = load_config(project_paths(project)["config"])
    names = referenced(cfg)
    if not names:
        return {"rendered": 0, "items": []}
    p = project_paths(project)
    dest = p["assets"] / "illustrations"
    dest.mkdir(parents=True, exist_ok=True)
    manifest = p["work"] / "illustrations.json"
    old = {}
    try:
        old = {x["name"]: x for x in json.loads(manifest.read_text())["items"]}
    except (OSError, ValueError, KeyError):
        old = {}
    items = []
    for name in sorted(names):
        svg = source / f"{name}.svg"
        if not svg.is_file():
            raise FileNotFoundError(f"插图源文件不存在：{svg}")
        out = dest / f"{name}.png"
        sha = _sha(svg)
        if out.is_file() and old.get(name, {}).get("svg_sha256") == sha:
            items.append({**old[name], "cached": True})
            continue
        await render(svg, out, 800, 1000)
        items.append({"name": name, "svg": str(svg), "png": str(out),
                      "svg_sha256": sha, "png_sha256": _sha(out), "cached": False})
    write_json(manifest, {"version": 1, "items": items})
    return {"rendered": sum(1 for x in items if not x.get("cached")), "items": items}


def render_all(project: Path, source: Path = SOURCE) -> dict:
    return asyncio.run(render_all_async(project, source))


def main() -> None:
    ap = argparse.ArgumentParser(description="SVG 插图 → 项目 PNG")
    ap.add_argument("project")
    ap.add_argument("--source", default=str(SOURCE))
    a = ap.parse_args()
    print(json.dumps(render_all(Path(a.project).resolve(), Path(a.source)), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
