#!/usr/bin/env python3
"""Render a local SVG/HTML file to PNG with Playwright Chromium (transparent)."""
from __future__ import annotations
import argparse, asyncio, sys
from pathlib import Path


async def render(src: Path, out: Path, width: int, height: int) -> None:
    from playwright.async_api import async_playwright
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page(viewport={"width": width, "height": height},
                                      device_scale_factor=1)
        await page.goto(src.resolve().as_uri())
        await page.wait_for_timeout(150)
        await page.screenshot(path=str(out), omit_background=True)
        await browser.close()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("src")
    ap.add_argument("out")
    ap.add_argument("--width", type=int, default=800)
    ap.add_argument("--height", type=int, default=1000)
    a = ap.parse_args()
    asyncio.run(render(Path(a.src), Path(a.out), a.width, a.height))
    print(a.out)


if __name__ == "__main__":
    main()
