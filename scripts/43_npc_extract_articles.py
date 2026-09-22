#!/usr/bin/env python3
"""
Extract OCR text of newspaper articles matching search terms on
newspapers.com pages collected by 42_newspapers_search_download.py.

Pipeline per page (image id):
  1. Fetch /image/<id>/ in the authenticated browser -> embedded JWT
  2. GET /api/search/hits?images=<id>&terms=<terms>   (Bearer JWT)
     -> match bounding boxes in source-pixel space
  3. GET /api/article/page/<id>/articles             (Bearer JWT)
     -> article polygons (normalized 0-1)
  4. Download native-res page JPEG from img.newspapers.com
     (crop params are source pixels; native dims come back from the server)
  5. Crop each article region containing a term hit, OCR with tesseract
  6. Write data/reference/newspapers-com/articles/<id>__a<n>.txt + index

Usage:
    python scripts/43_npc_extract_articles.py --hits-file data/reference/newspapers-com/priority_hits.json
    python scripts/43_npc_extract_articles.py --terms "Ikeda" --limit 10
"""

import argparse
import asyncio
import io
import json
import re
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

from PIL import Image
from playwright.async_api import async_playwright

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PROFILE_DIR = PROJECT_ROOT / "data" / "cache" / "npc_chrome_profile"
OUT_DIR = PROJECT_ROOT / "data" / "reference" / "newspapers-com"
IMG_DIR = OUT_DIR / "page_images"
ART_DIR = OUT_DIR / "articles"

TERMS = "Ikeda aikido japan friendship seminar"


async def get_page_data(context, img_id: str, terms: str) -> dict | None:
    """In-browser: fetch image page HTML -> JWT; then call hits+articles APIs."""
    page = context.pages[0] if context.pages else await context.new_page()
    r = await page.evaluate(
        """async ([imgId, terms]) => {
            const tf = (u, o) => Promise.race([
                fetch(u, o),
                new Promise((_, rej) => setTimeout(() => rej(new Error('timeout')), 30000))]);
            const html = await (await tf('/image/' + imgId + '/')).text();
            const m = html.match(/eyJ[A-Za-z0-9_-]+\\.[A-Za-z0-9_-]+\\.[A-Za-z0-9_-]+/);
            if (!m) return {err: 'no jwt'};
            const jwt = m[0];
            const H = {Authorization: 'Bearer: ' + jwt};
            const hits = await (await tf(
                '/api/search/hits?images=' + imgId + '&terms=' + encodeURIComponent(terms),
                {headers: H})).json().catch(e => null);
            const arts = await (await tf(
                '/api/article/page/' + imgId + '/articles', {headers: H})).json().catch(e => null);
            // masthead + source image dims (embedded in viewer svg <image> tag)
            const tm = html.match(/<title>([^<]+)</);
            let dims = null;
            let dm = html.match(/\\\\"height\\\\":(\d+),\\\\"imageId\\\\":/)
                  || html.match(/"height":(\d+),"imageId":/);
            if (dm) {
                const seg = html.slice(dm.index, dm.index + 4000);
                const wm = seg.match(/\\\\"width\\\\":(\d+)/) || seg.match(/"width":(\d+)/);
                if (wm) dims = [parseInt(wm[1]), parseInt(dm[1])];
            }
            return {jwt, hits, arts, title: tm ? tm[1] : '', dims};
        }""",
        [img_id, terms],
    )
    return r


def cookie_header(cookies) -> str:
    return "; ".join(f"{c['name']}={c['value']}" for c in cookies)


IMG_HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/120 Safari/537.36",
    "Referer": "https://www.newspapers.com/",
}
STRIP_PX_BUDGET = 4_800_000  # img server 429s crops above ~5.4M px


def _fetch_strip(img_id: str, jwt: str, user: str, cookies: str,
                 y: int, h: int, w: int) -> Image.Image | None:
    url = (f"https://img.newspapers.com/img/img?id={img_id}"
           f"&crop=0,{y},{w},{h}&width={w}&height={h}"
           f"&brightness=0&contrast=0&invert=0&ts=1&cacheable=1&iat={jwt}&user={user}")
    req = urllib.request.Request(url, headers={**IMG_HEADERS, "Cookie": cookies})
    for attempt in range(4):
        try:
            data = urllib.request.urlopen(req, timeout=120).read()
            return Image.open(io.BytesIO(data))
        except urllib.error.HTTPError as e:
            if e.code == 429:
                time.sleep(25 * (attempt + 1))
                continue
            print(f"  img {img_id} y={y}: HTTP {e.code}", flush=True)
            return None
        except Exception as e:
            print(f"  img {img_id} y={y}: {e}", flush=True)
            return None
    print(f"  img {img_id} y={y}: gave up (429)", flush=True)
    return None


def fetch_full_image(img_id: str, jwt: str, user: str, cookies: str,
                     dest: Path, dims: tuple[int, int] | None = None) -> tuple[int, int] | None:
    """Download the page at native resolution in strips; stitch. Returns (w, h)."""
    W, H = dims or (0, 0)
    if not W or not H:
        print(f"  img {img_id}: no dims in page html", flush=True)
        return None
    strips = []
    strip_h = max(600, STRIP_PX_BUDGET // W)
    y = 0
    while y < H:
        h = min(strip_h, H - y)
        im = _fetch_strip(img_id, jwt, user, cookies, y, h, W)
        if im is None:
            return None
        strips.append(im)
        y += h
        time.sleep(1.0)
    full = Image.new("RGB", (W, H))
    y = 0
    for im in strips:
        full.paste(im.convert("RGB"), (0, y))
        y += im.height
    full.save(dest, quality=90)
    return W, H


def point_in_poly(x: float, y: float, poly: list[dict]) -> bool:
    """Ray casting on [{x,y}...] normalized polygon."""
    inside = False
    n = len(poly)
    for i in range(n):
        x1, y1 = poly[i]["x"], poly[i]["y"]
        x2, y2 = poly[(i + 1) % n]["x"], poly[(i + 1) % n]["y"]
        if (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / (y2 - y1) + x1:
            inside = not inside
    return inside


def ocr_image(im: Image.Image) -> str:
    tmp = Path("/tmp/npc_ocr_crop.png")
    im.save(tmp)
    r = subprocess.run(["tesseract", str(tmp), "-", "--psm", "3"],
                       capture_output=True, text=True, timeout=120)
    return r.stdout


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--hits-file", default=str(OUT_DIR / "priority_hits.json"))
    ap.add_argument("--terms", default=TERMS)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--reprocess", action="store_true")
    args = ap.parse_args()

    hits_meta = {h["id"]: h for h in json.loads(Path(args.hits_file).read_text())}
    ids = list(hits_meta)[: args.limit or None]
    IMG_DIR.mkdir(parents=True, exist_ok=True)
    ART_DIR.mkdir(parents=True, exist_ok=True)

    async with async_playwright() as p:
        context = await p.chromium.launch_persistent_context(
            user_data_dir=str(PROFILE_DIR), headless=False, channel="chrome",
            no_viewport=True,
            ignore_default_args=["--enable-automation"],
            args=["--disable-blink-features=AutomationControlled"])
        page = context.pages[0] if context.pages else await context.new_page()
        await page.goto("https://www.newspapers.com/", wait_until="domcontentloaded",
                        timeout=60000)
        await page.wait_for_timeout(2000)
        cookies = cookie_header(await context.cookies("https://www.newspapers.com"))

        index = []
        for n, img_id in enumerate(ids):
            marker = ART_DIR / f"{img_id}__index.json"
            if marker.exists() and not args.reprocess:
                continue
            print(f"[{n + 1}/{len(ids)}] page {img_id}", flush=True)
            try:
                d = await asyncio.wait_for(
                    get_page_data(context, img_id, args.terms), timeout=90)
            except Exception as e:
                print(f"  api err: {e}", flush=True)
                continue
            if not d or d.get("err"):
                print("  no jwt; skipping")
                continue
            jwt = d["jwt"]
            user = json.loads(__import__("base64").urlsafe_b64decode(
                jwt.split(".")[1] + "=="))["u"]
            arts = d.get("arts") or {}
            hit_groups = d.get("hits") or []
            flat_hits = [h for g in hit_groups for h in g]

            img_path = IMG_DIR / f"{img_id}.jpg"
            src_dims = tuple(d["dims"]) if d.get("dims") else None
            got = fetch_full_image(img_id, jwt, str(user), cookies, img_path, src_dims)
            if not got:
                continue
            W, H = got

            # find articles containing hits
            stories = arts.get("everydayStories", []) + arts.get("obituaries", []) \
                + arts.get("marriages", [])
            used = {}
            for h in flat_hits:
                nx, ny = h["x"] / W, h["y"] / H
                for i, st in enumerate(stories):
                    if st.get("polygon") and point_in_poly(nx, ny, st["polygon"]):
                        used.setdefault(i, st)
                        break
            with Image.open(img_path) as im:
                for i, st in used.items():
                    xs = [pt["x"] for pt in st["polygon"]]
                    ys = [pt["y"] for pt in st["polygon"]]
                    box = (max(0, int(min(xs) * W) - 10), max(0, int(min(ys) * H) - 10),
                           min(W, int(max(xs) * W) + 10), min(H, int(max(ys) * H) + 10))
                    crop = im.crop(box)
                    if crop.width > 2200:
                        crop = crop.resize((2200, int(crop.height * 2200 / crop.width)))
                    text = ocr_image(crop)
                    out = ART_DIR / f"{img_id}__a{i}.txt"
                    out.write_text(
                        f"# {d.get('title','')}  page_img={img_id} article={st['id']} "
                        f"topics={st.get('topics')}\n# source: https://www.newspapers.com/image/{img_id}/\n\n"
                        + text)
            index.append({"id": img_id, "title": d.get("title", ""),
                          "articles_ocr": len(used), "hits": len(flat_hits)})
            marker.write_text(json.dumps(index[-1]))
            (OUT_DIR / "articles_index.json").write_text(json.dumps(index, indent=2))
            time.sleep(1.5)  # rate limit

        (OUT_DIR / "articles_index.json").write_text(json.dumps(index, indent=2))
        await context.close()
    print(f"\nDone. {len(index)} pages processed -> {ART_DIR}")


if __name__ == "__main__":
    asyncio.run(main())
