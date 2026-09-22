#!/usr/bin/env python3
"""Crawl AikiWeb's seminars database (aikiweb.com/seminars) and save any
listing page mentioning Ikeda or "bridge".

AikiWeb seminar listings are static per-state/per-country pages
(show_us_seminars.html?state=XX&past=1 / show_seminars.html?country=X&past=1).
The site 403s non-browser fetches, so this uses a persistent headed-Chrome
profile (data/cache/aikiweb_chrome_profile).

Resumable: completed listing URLs are recorded in
data/reference/aikiweb_crawl_done.txt; hit pages (full body text) go to
data/reference/aikiweb_seminar_pages_ikeda_bridge.json.
"""
import argparse
import asyncio
import json
import os
import re

from playwright.async_api import async_playwright

PROFILE = "data/cache/aikiweb_chrome_profile"


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pattern", default=r"ikeda|bridge",
                    help="regex matched against each listing page body")
    ap.add_argument("--tag", default="ikeda_bridge",
                    help="suffix for output/done files")
    ap.add_argument("--pages-dir", default="data/reference/aikiweb/seminar_pages",
                    help="directory to archive every fetched listing page")
    args = ap.parse_args()
    out = f"data/reference/aikiweb_seminar_pages_{args.tag}.json"
    done_f = f"data/reference/aikiweb_crawl_done_{args.tag}.txt"
    pat = re.compile(args.pattern, re.I)
    os.makedirs(args.pages_dir, exist_ok=True)

    def page_path(u):
        q = re.search(r"(?:country|state)=([^&]+)", u)
        slug = re.sub(r"[^A-Za-z0-9_.-]+", "_", q.group(1)) if q else "index"
        return os.path.join(args.pages_dir, slug + ".txt")

    done = set()
    if os.path.exists(done_f):
        done = set(open(done_f).read().split())
    hits = json.load(open(out)) if os.path.exists(out) else []
    async with async_playwright() as pw:
        ctx = await pw.chromium.launch_persistent_context(
            PROFILE, headless=False,
            args=["--disable-blink-features=AutomationControlled"],
            ignore_default_args=["--enable-automation"],
            viewport={"width": 1280, "height": 900})
        page = await ctx.new_page()
        await page.goto("https://www.aikiweb.com/seminars/past.html", timeout=60000)
        await page.wait_for_selector("a[href*='show_seminars'], a[href*='show_us_seminars']", state="attached", timeout=60000)
        links = await page.eval_on_selector_all(
            "a",
            "els => els.map(e => e.href).filter(h => h.includes('show_seminars.html') || h.includes('show_us_seminars.html'))")
        urls = [u for u in sorted(set(links)) if u not in done]
        print(f"{len(urls)} listing pages to process", flush=True)
        fh = open(done_f, "a")
        for i, u in enumerate(urls):
            try:
                pp = page_path(u)
                if os.path.exists(pp) and os.path.getsize(pp) > 1000:
                    body = open(pp, errors="replace").read()
                else:
                    await page.goto(u, timeout=60000)
                    body = await page.inner_text("body")
                    with open(pp, "w") as pf:
                        pf.write(u + "\n" + body)
                if pat.search(body):
                    hits.append({"url": u, "body": body})
                    print(f"  HIT {u}", flush=True)
                fh.write(u + "\n")
                fh.flush()
            except Exception as e:
                print("ERR", u, str(e)[:70], flush=True)
            if i % 10 == 0:
                json.dump(hits, open(out, "w"), indent=1)
                print(f"  {i}/{len(urls)}", flush=True)
        json.dump(hits, open(out, "w"), indent=1)
        fh.close()
        print(f"done. {len(hits)} hit pages", flush=True)
        await ctx.close()


if __name__ == "__main__":
    asyncio.run(main())
