#!/usr/bin/env python3
"""
Search newspapers.com and download matching pages as PDFs.

Uses the proven WorldStudioFinder/CDNC technique: system Chrome with a
persistent profile, no UA spoofing, automation flags stripped. Login uses
the Quantum-Aikido Proton Pass vault entry for newspapers.com (fetched via
pass-cli); a fresh profile dir = fresh identity for Cloudflare Turnstile.

Downloads use CDP Page.printToPDF, which works in headed mode (unlike
Playwright's page.pdf() which is headless-only).

Usage:
    python scripts/42_newspapers_search_download.py                      # login + search + download
    python scripts/42_newspapers_search_download.py --query '"Ikeda" aikido'
    python scripts/42_newspapers_search_download.py --search-only        # list hits, no downloads
    python scripts/42_newspapers_search_download.py --limit 20
    python scripts/42_newspapers_search_download.py --fresh-profile      # wipe profile, re-login
"""

import argparse
import asyncio
import base64
import json
import re
import subprocess
import sys
from pathlib import Path

from playwright.async_api import async_playwright

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PROFILE_DIR = PROJECT_ROOT / "data" / "cache" / "npc_chrome_profile"
OUT_DIR = PROJECT_ROOT / "data" / "reference" / "newspapers-com"
RESULTS_JSON = OUT_DIR / "search_results.json"

NPC = "https://www.newspapers.com"
VAULT = "Quantum-Aikido"


def get_credentials() -> tuple[str, str]:
    """Fetch newspapers.com creds from Proton Pass CLI."""
    out = subprocess.run(
        ["pass-cli", "item", "list", "--vault-name", VAULT],
        capture_output=True, text=True, check=True,
    ).stdout
    item_id = None
    for line in out.splitlines():
        m = re.match(r"- \[(.+?)\]: newspapers\.com \(state=(\w+)\)", line.strip())
        if m and m.group(2) == "Active":
            item_id = m.group(1)
            break
    if not item_id:
        raise RuntimeError("No active newspapers.com item in vault")
    out = subprocess.run(
        ["pass-cli", "item", "view", "--vault-name", VAULT,
         "--item-id", item_id, "--output", "json"],
        capture_output=True, text=True, check=True,
    ).stdout
    login = json.loads(out)["item"]["content"]["content"]["Login"]
    return login["email"], login["password"]


async def launch(p, profile: Path):
    profile.mkdir(parents=True, exist_ok=True)
    kwargs = {
        "user_data_dir": str(profile),
        "headless": False,
        "channel": "chrome",
        "no_viewport": True,
        "ignore_default_args": ["--enable-automation"],
        "args": ["--disable-blink-features=AutomationControlled"],
    }
    try:
        return await p.chromium.launch_persistent_context(**kwargs)
    except Exception as exc:
        print(f"System Chrome unavailable ({exc}); bundled Chromium")
        kwargs.pop("channel")
        return await p.chromium.launch_persistent_context(**kwargs)


async def wait_turnstile(page, timeout_s=90) -> bool:
    """Wait for Turnstile token to appear; click widget checkbox if it stalls."""
    import time
    deadline = time.time() + timeout_s
    clicked = False
    while time.time() < deadline:
        tok = await page.evaluate(
            "(() => { const t = document.querySelector('[name=\"cf-turnstile-response\"]');"
            " return t ? t.value.length : -1; })()"
        )
        if tok and tok > 0:
            return True
        if not clicked and time.time() > deadline - timeout_s + 15:
            # single cautious click on the widget iframe after 15s
            frame = page.frame(url=re.compile("challenges.cloudflare.com"))
            if frame:
                try:
                    cb = await frame.query_selector("input[type=checkbox], .cb-lb")
                    if cb:
                        await cb.click()
                        clicked = True
                except Exception:
                    pass
        await page.wait_for_timeout(1000)
    return False


async def login(context, email: str, password: str) -> bool:
    page = context.pages[0] if context.pages else await context.new_page()
    await page.goto(NPC + "/signin/", wait_until="domcontentloaded", timeout=60000)
    await page.wait_for_timeout(4000)

    await page.fill('input[type="email"], input[name*="email" i]', email)
    await page.fill('input[type="password"]', password)

    if not await wait_turnstile(page):
        print("WARN: Turnstile token not observed; trying submit anyway")

    btn = page.locator("button", has_text=re.compile("sign in with newspapers", re.I))
    try:
        await btn.first.wait_for(state="visible", timeout=10000)
        for _ in range(30):
            if await btn.first.is_enabled():
                break
            await page.wait_for_timeout(1000)
        await btn.first.click()
    except Exception as exc:
        print(f"Sign-in button issue: {exc}; submitting form via Enter")
        await page.keyboard.press("Enter")

    await page.wait_for_timeout(8000)
    ok = "/signin" not in page.url
    print(f"Login {'succeeded' if ok else 'FAILED'} — url={page.url}")
    return ok


async def search(context, query: str, max_pages: int = 30) -> list[dict]:
    """Collect result links + metadata from newspapers.com search.

    Result cards are div.SearchResult_ArticleResult__*; pagination is via
    <button>Next</button> (not anchor links).
    """
    page = context.pages[0] if context.pages else await context.new_page()
    from urllib.parse import quote
    hits, seen = [], set()
    url = f"{NPC}/search/results/?keyword={quote(query)}&sort=score-desc"
    for pageno in range(1, max_pages + 1):
        if pageno == 1:
            await page.goto(url, wait_until="domcontentloaded", timeout=60000)
        await page.wait_for_timeout(5000)
        items = await page.evaluate("""() => {
            const out = [];
            document.querySelectorAll('[class*=SearchResult_ArticleResult]').forEach(card => {
                const a = card.querySelector('a[href*="/image/"], a[href*="/newspage/"], a[href*="/article/"]');
                if (a) {
                    const m = a.href.match(/\\/(\\d+)/);
                    out.push({url: a.href.split('?')[0], id: m ? m[1] : a.href,
                              text: card.innerText.slice(0, 600)});
                }
            });
            if (!out.length) {  // fallback: any image/newspage links
                document.querySelectorAll('a[href]').forEach(a => {
                    const m = a.href.match(/newspapers\\.com\\/(?:image|newspage|article)\\/(\\d+)/);
                    if (m) out.push({url: a.href.split('?')[0], id: m[1], text: ''});
                });
            }
            const h = document.querySelector('h1');
            return {heading: h ? h.innerText : '', items: out};
        }""")
        if items.get("heading") and pageno == 1:
            print("  " + items["heading"])
        new = 0
        for it in items["items"]:
            if it["id"] not in seen:
                seen.add(it["id"])
                hits.append(it)
                new += 1
        print(f"  page {pageno}: {new} new ({len(hits)} total)")
        if new == 0:
            break
        nxt_js = """() => {
            const b = [...document.querySelectorAll('button')]
                .find(b => /show more results/i.test(b.innerText || ''));
            if (b) { b.click(); return true; } return false;
        }"""
        try:
            if not await page.evaluate(nxt_js):
                break
        except Exception:
            break
    return hits


async def download_pdf(context, url: str, dest: Path):
    page = await context.new_page()
    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=60000)
        await page.wait_for_timeout(6000)
        session = await context.new_cdp_session(page)
        result = await session.send("Page.printToPDF", {
            "printBackground": True,
            "preferCSSPageSize": True,
        })
        dest.write_bytes(base64.b64decode(result["data"]))
        print(f"  saved {dest.name} ({dest.stat().st_size // 1024} KB)")
    finally:
        await page.close()


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--query", default='"Hiroshi Ikeda" aikido')
    ap.add_argument("--queries", help="pipe-separated list of queries, searched in one session")
    ap.add_argument("--limit", type=int, default=25)
    ap.add_argument("--search-only", action="store_true")
    ap.add_argument("--from-file", help="download PDFs from a saved search_results JSON")
    ap.add_argument("--fresh-profile", action="store_true")
    args = ap.parse_args()

    if args.fresh_profile and PROFILE_DIR.exists():
        import shutil
        shutil.rmtree(PROFILE_DIR)
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    email, password = get_credentials()
    print(f"Creds loaded for {email}")

    async with async_playwright() as p:
        context = await launch(p, PROFILE_DIR)
        page = context.pages[0] if context.pages else await context.new_page()
        await page.goto(NPC, wait_until="domcontentloaded", timeout=60000)
        await page.wait_for_timeout(3000)

        signed_in = await page.evaluate(
            "(() => !document.querySelector('a[href*=\"/signin\"]') && "
            "!/sign in/i.test(document.body.innerText.slice(0, 3000)))()"
        )
        if not signed_in:
            signed_in = await login(context, email, password)
        else:
            print("Already signed in (persistent profile)")
        if not signed_in:
            sys.exit("Login failed — cannot proceed")

        hits = []
        if args.from_file:
            hits = json.loads(Path(args.from_file).read_text())
        elif args.queries:
            seen_ids = set()
            for q in args.queries.split("|"):
                print(f"\n=== QUERY: {q} ===")
                qhits = await search(context, q)
                for h in qhits:
                    h["query"] = q
                slug = re.sub(r"[^a-z0-9]+", "_", q.lower()).strip("_")[:60]
                (OUT_DIR / f"search_results_{slug}.json").write_text(
                    json.dumps(qhits, indent=2))
                print(f"  -> {len(qhits)} hits -> search_results_{slug}.json")
                for h in qhits:
                    if h["id"] not in seen_ids:
                        seen_ids.add(h["id"])
                        hits.append(h)
        else:
            hits = await search(context, args.query)
            slug = re.sub(r"[^a-z0-9]+", "_", args.query.lower()).strip("_")[:60]
            results_path = OUT_DIR / f"search_results_{slug}.json"
            results_path.write_text(json.dumps(hits, indent=2))
            print(f"Wrote {results_path}")
        print(f"\n{len(hits)} result links collected")

        if args.search_only:
            for h in hits:
                print(" ", h["url"], "|", h["text"].split("\n")[0][:80])
            return

        for i, h in enumerate(hits[: args.limit]):
            dest = OUT_DIR / f"npc_{h['id']}.pdf"
            if dest.exists():
                continue
            print(f"[{i + 1}/{min(len(hits), args.limit)}] {h['url']}")
            try:
                await download_pdf(context, h["url"], dest)
            except Exception as exc:
                print(f"  ERROR: {exc}")

    print(f"\nDone. PDFs in {OUT_DIR}")


if __name__ == "__main__":
    asyncio.run(main())
