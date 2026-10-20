#!/usr/bin/env python3
"""Render a deterministic HTML/Canvas scene to transparent ProRes 4444.

The page must expose `window.renderAt(t)`; each frame is captured at an exact
time, so the output is seek-safe and reproducible. This is for short overlay
motion (steam, line draw, particles), not for rendering a whole talking-head film.
"""
from __future__ import annotations

import argparse
import asyncio
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _common import find_ffmpeg  # noqa: E402


async def frames(src: Path, out_dir: Path, duration: float, fps: int,
                 width: int, height: int) -> int:
    from playwright.async_api import async_playwright
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page(viewport={"width": width, "height": height},
                                      device_scale_factor=1)
        await page.goto(src.resolve().as_uri())
        await page.wait_for_function("typeof window.renderAt === 'function'")
        count = int(round(duration * fps))
        for i in range(count):
            await page.evaluate("(t) => window.renderAt(t)", i / fps)
            await page.screenshot(path=str(out_dir / f"f-{i:05d}.png"),
                                  omit_background=True)
        await browser.close()
        return count


def encode(frames_dir: Path, out: Path, fps: int) -> None:
    subprocess.run([
        find_ffmpeg(), "-y", "-v", "error", "-framerate", str(fps),
        "-i", str(frames_dir / "f-%05d.png"),
        "-c:v", "prores_ks", "-profile:v", "4444", "-pix_fmt", "yuva444p10le",
        str(out)], check=True)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("scene")
    ap.add_argument("--out", required=True)
    ap.add_argument("--duration", type=float, default=2.0)
    ap.add_argument("--fps", type=int, default=30)
    ap.add_argument("--width", type=int, default=800)
    ap.add_argument("--height", type=int, default=1000)
    a = ap.parse_args()
    out = Path(a.out).resolve()
    with tempfile.TemporaryDirectory(prefix="koubo-motion-") as tmp:
        n = asyncio.run(frames(Path(a.scene), Path(tmp), a.duration, a.fps,
                               a.width, a.height))
        encode(Path(tmp), out, a.fps)
    print(f"{out}  {n} frames / {a.duration}s / {a.fps}fps / ProRes 4444")


if __name__ == "__main__":
    main()
