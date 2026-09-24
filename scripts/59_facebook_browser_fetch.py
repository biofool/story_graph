#!/usr/bin/env python3
"""
Direct Facebook browsing — fetch public Pages/posts via a persistent Chrome
profile (no Graph API token needed).

Technique ported from WorldStudioFinder scripts/acquire_fb_browser.py:
anonymous HTTP fetches of facebook.com (desktop and m.*) all redirect to
login, so browsing runs in a real headed Chrome with a dedicated persistent
profile at data/cache/fb_chrome_profile. On a login wall the script leaves
the visible browser open and polls until you log in manually — the session
then persists across runs.

Saves rendered HTML + extracted text under data/reference/facebook/<slug>/
for review; evidence is ingested via data/ingest/*.json specs, not directly.

Usage:
    python scripts/59_facebook_browser_fetch.py --url https://www.facebook.com/dojokashin
    python scripts/59_facebook_browser_fetch.py --url-file data/reference/fb_urls.txt
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import re
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from playwright.async_api import async_playwright

from src.crawler.facebook_collector import facebook_slug

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
_log = logging.getLogger("fb_browser_fetch")

PROFILE_DIR = _PROJECT_ROOT / "data" / "cache" / "fb_chrome_profile"
OUT_DIR = _PROJECT_ROOT / "data" / "reference" / "facebook"

PAGE_TIMEOUT_MS = 45_000
LOGIN_WAIT_S = 600
LOGIN_POLL_S = 3

_LOGIN_URL_RE = re.compile(r"/login|/checkpoint|/two_factor", re.I)
_LOGIN_TITLE_RE = re.compile(r"log\s*in|sign\s*up", re.I)
_LOGGED_IN_MARKERS = [
    "div[role='navigation']",
    "a[href*='/notifications']",
    "div[aria-label='Account']",
    "div[aria-label='Your profile']",
]


def _out_name(url: str) -> str:
    """Stable output filename for a FB URL (slug + post kind/id)."""
    parts = [p for p in url.split("?")[0].strip("/").split("/") if p]
    slug = parts[0] if parts else "page"
    tail = parts[-1] if len(parts) > 1 else "index"
    return re.sub(r"[^\w.-]", "_", f"{slug}__{tail}")[:120]


async def _has_any(page, selectors: list[str]) -> bool:
    for sel in selectors:
        try:
            if await page.locator(sel).count():
                return True
        except Exception:
            continue
    return False


async def _login_wall(page) -> bool:
    url = page.url or ""
    if _LOGIN_URL_RE.search(url):
        return True
    try:
        title = await page.title()
    except Exception:
        title = ""
    if _LOGIN_TITLE_RE.search(title or ""):
        return True
    try:
        has_form = await page.locator("input[name='email'],input[name='pass']").count() > 0
        has_content = await page.locator("div[role='main']").count() > 0
    except Exception:
        return False
    return has_form and not has_content


async def wait_for_login(page) -> bool:
    """Leave the visible browser on the login page and poll until the user
    completes login (or LOGIN_WAIT_S elapses)."""
    print("\n" + "=" * 70)
    print("FACEBOOK LOGIN REQUIRED")
    print("A browser window is open. Log in to Facebook there.")
    print(f"Waiting up to {LOGIN_WAIT_S}s — detected automatically once done.")
    print("=" * 70 + "\n", flush=True)
    try:
        await page.goto("https://www.facebook.com/login", timeout=PAGE_TIMEOUT_MS)
    except Exception as e:
        _log.warning("Could not navigate to login page: %s", e)
    deadline = asyncio.get_event_loop().time() + LOGIN_WAIT_S
    while asyncio.get_event_loop().time() < deadline:
        try:
            if not _LOGIN_URL_RE.search(page.url or "") and await _has_any(page, _LOGGED_IN_MARKERS):
                print("Login detected — continuing.\n", flush=True)
                return True
        except Exception:
            pass
        await asyncio.sleep(LOGIN_POLL_S)
    print("Login wait timed out.\n", flush=True)
    return False


async def fetch_url(page, url: str, delay: float, scrolls: int = 0) -> None:
    slug = facebook_slug(url) or "page"
    out_dir = OUT_DIR / slug
    out_dir.mkdir(parents=True, exist_ok=True)
    name = _out_name(url)
    html_path = out_dir / f"{name}.html"
    if html_path.exists():
        _log.info("SKIP %s (already fetched)", url)
        return
    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=PAGE_TIMEOUT_MS)
        await page.wait_for_timeout(3000)
    except Exception as e:
        _log.warning("NAV FAIL %s — %s", url, e)
        return
    if await _login_wall(page):
        _log.info("LOGIN WALL %s", url)
        if not await wait_for_login(page):
            return
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=PAGE_TIMEOUT_MS)
            await page.wait_for_timeout(3000)
        except Exception as e:
            _log.warning("NAV FAIL %s after login — %s", url, e)
            return
    for _ in range(scrolls):
        await page.mouse.wheel(0, 2500)
        await page.wait_for_timeout(2000)
    html = await page.content()
    html_path.write_text(html, encoding="utf-8")
    try:
        text = await page.locator("body").inner_text(timeout=5000)
    except Exception:
        text = ""
    (out_dir / f"{name}.txt").write_text(text, encoding="utf-8")
    try:
        title = await page.title()
    except Exception:
        title = ""
    _log.info("OK   %s → %s (%d chars text) [%s]", url, html_path, len(text), title[:60])
    await asyncio.sleep(delay)


async def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--url", action="append", default=[], help="Facebook URL (repeatable)")
    ap.add_argument("--url-file", type=Path, help="File with one Facebook URL per line")
    ap.add_argument("--delay", type=float, default=5.0, help="Seconds between pages")
    ap.add_argument("--scroll", type=int, default=0, help="Scroll N times to load the feed before extracting")
    ap.add_argument("--headless", action="store_true", help="Headless (only if a saved session exists)")
    ap.add_argument("--storage-state", type=Path,
                    help="Playwright storage_state JSON to seed cookies from "
                         "(e.g. an exported logged-in session)")
    args = ap.parse_args()

    urls = list(args.url)
    if args.url_file:
        urls += [l.strip() for l in args.url_file.read_text().splitlines()
                 if l.strip() and not l.startswith("#")]
    if not urls:
        ap.error("provide --url or --url-file")

    async with async_playwright() as p:
        context = await p.chromium.launch_persistent_context(
            user_data_dir=str(PROFILE_DIR),
            headless=args.headless,
            channel="chrome",
            no_viewport=True,
            ignore_default_args=["--enable-automation"],
            args=["--disable-blink-features=AutomationControlled"],
        )
        if args.storage_state:
            import json
            state = json.loads(args.storage_state.read_text())
            await context.add_cookies(state.get("cookies", []))
            _log.info("Seeded %d cookies from %s",
                      len(state.get("cookies", [])), args.storage_state)
        page = context.pages[0] if context.pages else await context.new_page()
        for url in urls:
            await fetch_url(page, url, args.delay, args.scroll)
        await context.close()


if __name__ == "__main__":
    asyncio.run(main())
