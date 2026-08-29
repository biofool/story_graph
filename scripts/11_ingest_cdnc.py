#!/usr/bin/env python3
"""
Ingest articles from the California Digital Newspaper Collection (CDNC)
at cdnc.ucr.edu into the story_graph.

CDNC is behind Cloudflare Turnstile, so this script uses the proven
WorldStudioFinder technique: system Chrome with a persistent profile,
no UA spoofing, no programmatic Turnstile clicks — just wait for the
challenge to auto-resolve.

The script:
1. Searches CDNC for the given query (default: "Richard Moon")
2. For each search hit, fetches the article page
3. Downloads block images (the article is rendered as images, not OCR text)
4. Runs Tesseract OCR on the images to extract text
5. Creates SourceRecord + Work node + Image nodes + DEPICTS edges
6. Links the Work node to any person nodes it MENTIONS

Usage:
    python scripts/11_ingest_cdnc.py                          # default: search "Richard Moon"
    python scripts/11_ingest_cdnc.py --query "Father Yod"     # custom query
    python scripts/11_ingest_cdnc.py --limit 5                # max articles
    python scripts/11_ingest_cdnc.py --dry-run                # search only, no DB writes
    python scripts/11_ingest_cdnc.py --research               # search + OCR, no DB writes
"""

import argparse
import asyncio
import base64
import hashlib
import logging
import re
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.storage.graph_db import GraphDB
from src.storage.json_export import export_to_json
from src.storage.models import (
    BiasHint,
    GraphEdge,
    GraphNode,
    NodeType,
    RelationType,
    SourceClass,
    SourceRecord,
)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PROFILE_DIR = PROJECT_ROOT / "data" / "cache" / "cdnc_chrome_profile"
STATE_PATH = PROJECT_ROOT / "data" / "cache" / "cdnc_cf_state.json"
OCR_TMP_DIR = Path("/tmp/cdnc_ocr")

CDNC_BASE = "https://cdnc.ucr.edu"

# Cloudflare challenge markers
CF_TITLE_MARKERS = (
    "just a moment",
    "attention required!",
    "verify you are human",
    "checking if the site connection is secure",
    "incompatible browser extension",
)
TURNSTILE_IFRAME = (
    'iframe[src*="challenges.cloudflare.com"], '
    'iframe[src*="turnstile"], '
    'iframe[title*="Cloudflare"]'
)


async def _is_blocking(page) -> list[str]:
    """Check if Cloudflare interstitial is still blocking."""
    try:
        title = (await page.title() or "").lower()
    except Exception:
        return ["inspect-failed"]
    markers = []
    for m in CF_TITLE_MARKERS:
        if m in title:
            markers.append(f"title:{m}")
    try:
        if await page.locator(TURNSTILE_IFRAME).count() > 0:
            markers.append("iframe:turnstile")
    except Exception as exc:
        logging.debug("turnstile iframe check failed: %s", exc)
    return markers


async def _wait_for_cf_clear(page, timeout_s: int = 120) -> bool:
    """Wait for Cloudflare challenge to auto-resolve. Returns True if cleared."""
    deadline = time.monotonic() + timeout_s
    last_log = 0.0
    while time.monotonic() < deadline:
        if page.is_closed():
            return False
        markers = await _is_blocking(page)
        if not markers:
            return True
        now = time.monotonic()
        if now - last_log >= 10.0:
            try:
                title = await page.title()
            except Exception:
                title = "?"
            print(f"  [{int(now - deadline + timeout_s)}s] Waiting for CF... title={title}")
            last_log = now
        await page.wait_for_timeout(1000)
    return False


async def _launch_browser():
    """Launch system Chrome with persistent profile (WorldStudioFinder technique)."""
    from playwright.async_api import async_playwright

    PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    p = await async_playwright().start()
    kwargs = {
        "user_data_dir": str(PROFILE_DIR),
        "headless": False,
        "channel": "chrome",
        "no_viewport": True,
        "ignore_default_args": ["--enable-automation"],
        "args": ["--disable-blink-features=AutomationControlled"],
    }
    try:
        context = await p.chromium.launch_persistent_context(**kwargs)
        print("Launched system Chrome with persistent profile")
    except Exception as exc:
        print(f"System Chrome unavailable ({exc}); using bundled Chromium")
        kwargs.pop("channel", None)
        context = await p.chromium.launch_persistent_context(**kwargs)
    return p, context


async def search_cdnc(context, query: str, newspaper: str | None = None, year: str | None = None) -> list[dict]:
    """Search CDNC and return list of article hits with metadata."""
    page = list(context.pages)[0] if context.pages else await context.new_page()

    # Build search URL
    params = {"a": "q", "rq": "0", "q": f'"{query}"', "st": "txIN", "la": "en"}
    if newspaper:
        params["fl"] = newspaper
    if year:
        params["da"] = year
    search_url = CDNC_BASE + "/?" + "&".join(f"{k}={v}" for k, v in params.items())

    print(f"\nSearching CDNC: {search_url}")
    await page.goto(search_url, wait_until="domcontentloaded", timeout=60000)

    if not await _wait_for_cf_clear(page):
        print("ERROR: Could not pass Cloudflare challenge for search page")
        return []

    await page.wait_for_timeout(5000)  # Let JS render results

    # Extract search results from the page
    hits = await page.evaluate("""() => {
        const results = [];
        // Veridian search results are in .akresult or .result containers
        const items = document.querySelectorAll('.akresult, .result, .searchresult, .aksearchresult');
        items.forEach(item => {
            const link = item.querySelector('a[href*="d="]');
            const title = item.querySelector('.title, .aktitle, h3, h4');
            const snippet = item.querySelector('.snippet, .aksnippet, .text, .preview');
            if (link) {
                results.push({
                    url: link.href,
                    title: title ? title.innerText.trim() : '',
                    snippet: snippet ? snippet.innerText.trim().substring(0, 300) : ''
                });
            }
        });
        return results;
    }""")

    if not hits:
        # Try alternative: look for any links to article pages
        hits = await page.evaluate("""() => {
            const results = [];
            const links = document.querySelectorAll('a[href*="a=d&d="]');
            links.forEach(link => {
                const title = link.innerText.trim();
                if (title && title.length > 5) {
                    results.push({
                        url: link.href,
                        title: title,
                        snippet: ''
                    });
                }
            });
            return results;
        }""")

    print(f"Found {len(hits)} search results")
    for i, h in enumerate(hits[:10], 1):
        print(f"  [{i}] {h['title'][:60]} — {h['url'][:80]}")
        if h["snippet"]:
            print(f"      snippet: {h['snippet'][:100]}...")
    return hits


async def fetch_article_page(context, url: str) -> dict[str, Any]:
    """Fetch a CDNC article page and extract block image URLs + metadata."""
    page = list(context.pages)[0] if context.pages else await context.new_page()

    print(f"  Fetching article: {url[:80]}...")
    await page.goto(url, wait_until="domcontentloaded", timeout=60000)

    if not await _wait_for_cf_clear(page):
        print("  ERROR: Cloudflare challenge did not clear")
        return {}

    await page.wait_for_timeout(3000)

    # Extract article metadata and block image URLs
    info = await page.evaluate("""() => {
        const result = {title: '', date: '', newspaper: '', blockImages: [], articleText: ''};
        
        // Title from h1
        const h1 = document.querySelector('#documentdisplayheader h1, h1');
        result.title = h1 ? h1.innerText.trim() : document.title;
        
        // Block images
        const imgs = document.querySelectorAll('img[alt="Page area"]');
        imgs.forEach(img => result.blockImages.push(img.src));
        
        // Try to get any visible article text
        result.articleText = document.body.innerText.substring(0, 5000);
        
        // Extract newspaper name and date from breadcrumb
        const breadcrumbs = document.querySelectorAll('.breadcrumb-item a, .breadcrumb-item span');
        const crumbs = Array.from(breadcrumbs).map(b => b.innerText.trim()).filter(Boolean);
        if (crumbs.length >= 2) {
            result.newspaper = crumbs[0];
            result.date = crumbs[1];
        }
        
        return result;
    }""")

    # Download block images using browser fetch (includes cookies)
    images = []
    for i, img_url in enumerate(info.get("blockImages", []), 1):
        print(f"  Downloading block image {i}/{len(info['blockImages'])}...")
        result = await page.evaluate("""async (url) => {
            try {
                const resp = await fetch(url, {credentials: 'include'});
                const blob = await resp.blob();
                const reader = new FileReader();
                return new Promise(resolve => {
                    reader.onload = () => resolve({
                        type: blob.type, size: blob.size,
                        data: reader.result.split(',')[1]
                    });
                    reader.readAsDataURL(blob);
                });
            } catch(e) { return {error: e.message}; }
        }""", img_url)

        if "error" in result:
            print(f"    Error: {result['error']}")
            continue
        if not result.get("type", "").startswith("image"):
            print(f"    Not an image: type={result.get('type')}")
            continue

        data = base64.b64decode(result["data"])
        img_path = OCR_TMP_DIR / f"block_{i}.jpg"
        img_path.write_bytes(data)
        images.append({"path": img_path, "url": img_url, "size": result["size"]})
        print(f"    Saved {img_path.name} ({result['size']} bytes)")

    info["downloaded_images"] = images
    return info


def ocr_image(img_path: Path) -> str:
    """Run Tesseract OCR on an image file and return the text."""
    try:
        result = subprocess.run(
            ["tesseract", str(img_path), "-"],
            capture_output=True, text=True, timeout=30
        )
        return result.stdout.strip()
    except Exception as e:
        print(f"    OCR failed for {img_path}: {e}")
        return ""


def ocr_article(images: list[dict]) -> str:
    """OCR all block images and concatenate the text."""
    OCR_TMP_DIR.mkdir(parents=True, exist_ok=True)
    parts = []
    for img in images:
        text = ocr_image(img["path"])
        if text:
            parts.append(text)
    return "\n\n---\n\n".join(parts)


def ingest_article(
    db: GraphDB,
    article: dict[str, Any],
    ocr_text: str,
    query: str,
) -> None:
    """Add a CDNC article to the graph DB."""
    url = article.get("url", "")
    title = article.get("title", "(untitled)")
    newspaper = article.get("newspaper", "Unknown")
    date_str = article.get("date", "")

    # Parse date (e.g., "7 May 1976")
    publish_date = None
    if date_str:
        for fmt in ("%d %B %Y", "%B %d, %Y", "%Y-%m-%d"):
            try:
                publish_date = datetime.strptime(date_str, fmt).date().isoformat()
                break
            except ValueError:
                continue

    # Create a stable source ID from the URL
    doc_id_match = re.search(r"d=([^&]+)", url)
    doc_id = doc_id_match.group(1) if doc_id_match else hashlib.sha256(url.encode()).hexdigest()[:12]
    source_id = f"cdnc-{doc_id}"
    work_id = f"work-cdnc-{doc_id}"

    # Check if already ingested
    existing = db.get_node(work_id)
    if existing:
        print(f"  Already in graph: {work_id} — skipping (use --force to re-ingest)")
        return

    # 1. SourceRecord
    source = SourceRecord(
        id=source_id,
        url=url,
        title=title,
        author=newspaper,
        publish_date=publish_date,
        platform="cdnc",
        source_class=SourceClass.ARCHIVAL,
        bias_hint=BiasHint.NEUTRAL_ISH,
        raw_text=ocr_text[:5000],
    )
    db.add_source(source)
    print(f"  Added source: {source_id}")

    # 2. Work node
    work_node = GraphNode(
        id=work_id,
        type=NodeType.WORK,
        label=title[:100],
        metadata={
            "work_type": "newspaper_article",
            "source_archive": "cdnc",
            "newspaper": newspaper,
            "publish_date": publish_date,
            "ocr_text": ocr_text[:2000],
            "search_query": query,
        },
        source_urls=[url],
    )
    db.add_node(work_node)
    print(f"  Added work node: {work_id}")

    # 3. Image nodes + DEPICTS edges
    for img in article.get("downloaded_images", []):
        img_path = img["path"]
        if not img_path.exists():
            continue

        data = img_path.read_bytes()
        content_hash = hashlib.sha256(data).hexdigest()

        # Save to data/images/ using the image_capture module's path convention
        from src.crawler.image_capture import image_path_for, thumb_path_for
        ext = ".jpg"
        dest = image_path_for(content_hash, ext)
        if not dest.exists():
            dest.write_bytes(data)
        thumb = thumb_path_for(content_hash)
        if not thumb.exists():
            from io import BytesIO

            from PIL import Image
            pil_img = Image.open(BytesIO(data))
            pil_img.convert("RGB").thumbnail((320, 320))
            pil_img.save(thumb, format="JPEG", quality=80)

        image_node = GraphNode(
            id=f"image:{content_hash}",
            type=NodeType.IMAGE,
            label=f"CDNC block image: {title[:60]}",
            metadata={
                "original_url": img["url"],
                "content_hash": content_hash,
                "mime": "image/jpeg",
                "source": "cdnc",
            },
            source_urls=[url],
        )
        db.add_node(image_node)
        db.add_edge(GraphEdge(
            src_id=work_id,
            rel_type=RelationType.DEPICTS,
            dst_id=image_node.id,
        ))
        print(f"  Added image: {image_node.id[:30]}...")

    # 4. Link to person nodes mentioned in the OCR text
    # Check for known person patterns
    person_patterns = {
        "person:richard-moon": ["Richard Moon", "Richard  Moon"],
        "person:jim-baker": ["Jim Baker", "James Baker"],
        "person:father-yod": ["Father Yod", "Yogi Bhajan"],
    }
    for person_id, patterns in person_patterns.items():
        for pattern in patterns:
            if pattern.lower() in ocr_text.lower():
                person_node = db.get_node(person_id)
                if person_node:
                    db.add_edge(GraphEdge(
                        src_id=work_id,
                        rel_type=RelationType.MENTIONS,
                        dst_id=person_id,
                        metadata={"evidence": pattern, "source": "ocr"},
                    ))
                    print(f"  Linked MENTIONS {person_id} (found '{pattern}')")
                break


async def main_async(args) -> int:
    print("""
╔════════════════════════════════════════════════════════════════════╗
║          CDNC ARTICLE INGESTION — Cloudflare-aware                 ║
║   California Digital Newspaper Collection (cdnc.ucr.edu)           ║
╚════════════════════════════════════════════════════════════════════╝
    """)

    OCR_TMP_DIR.mkdir(parents=True, exist_ok=True)

    p, context = await _launch_browser()

    try:
        # 1. Search CDNC
        hits = await search_cdnc(context, args.query, newspaper=args.newspaper, year=args.year)
        if not hits:
            print("\nNo results found. Try a different query or remove filters.")
            return 0

        hits = hits[:args.limit]

        if args.dry_run:
            print(f"\n[dry-run] Found {len(hits)} articles. Skipping OCR and DB writes.")
            return 0

        # 2. Fetch and OCR each article
        db_path = Path(args.db) if args.db else PROJECT_ROOT / "data" / "graph.db"
        db = GraphDB(db_path) if not args.research else None

        ingested = 0
        for i, hit in enumerate(hits, 1):
            print(f"\n[{i}/{len(hits)}] {hit['title'][:60]}")
            article = await fetch_article_page(context, hit["url"])
            if not article:
                continue

            images = article.get("downloaded_images", [])
            if not images:
                print("  No block images found — skipping")
                continue

            ocr_text = ocr_article(images)
            print(f"  OCR extracted {len(ocr_text)} chars")
            if ocr_text:
                print(f"  Preview: {ocr_text[:200]}...")

            if args.research:
                print("  [research mode] Skipping DB write")
                # Save OCR text for review
                ocr_path = Path(f"/tmp/cdnc_ocr_{i}.txt")
                ocr_path.write_text(ocr_text)
                print(f"  Saved OCR to {ocr_path}")
                continue

            if db:
                ingest_article(db, article, ocr_text, args.query)
                ingested += 1

            # Polite delay between articles
            await asyncio.sleep(2)

        if db:
            print(f"\n✓ Ingested {ingested} articles into graph DB")
            if not args.no_export:
                snapshot_dir = PROJECT_ROOT / "graph_snapshot"
                counts = export_to_json(db, snapshot_dir)
                print(f"✓ Exported snapshot: {counts}")
            db.close()

        # 3. Also check if the query mentions a person already in the graph
        if db and not args.research:
            print(f"\nChecking for person nodes matching '{args.query}'...")
            # This is handled in ingest_article via MENTIONS edges

    finally:
        # Save cookies for reuse
        try:
            await context.storage_state(path=str(STATE_PATH))
            print(f"\nSaved clearance cookies to {STATE_PATH}")
        except Exception as exc:
            logging.warning("could not save clearance cookies: %s", exc)
        await context.close()
        await p.stop()

    return 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Ingest CDNC articles into story_graph")
    p.add_argument("--query", default="Richard Moon", help="Search query (default: Richard Moon)")
    p.add_argument("--newspaper", default=None, help="Newspaper code filter (e.g., TPN for Tamalpais News)")
    p.add_argument("--year", default=None, help="Year filter (e.g., 1976)")
    p.add_argument("--limit", type=int, default=10, help="Max articles to ingest")
    p.add_argument("--db", default=None, help="Path to graph.db")
    p.add_argument("--dry-run", action="store_true", help="Search only, no fetch/OCR/DB")
    p.add_argument("--research", action="store_true", help="Search + OCR, but no DB writes")
    p.add_argument("--no-export", action="store_true", help="Skip graph_snapshot export")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    return asyncio.run(main_async(args))


if __name__ == "__main__":
    sys.exit(main())
