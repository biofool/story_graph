#!/usr/bin/env python3
"""
Ingest Dan Millman sources into the story_graph.

Dan Millman (b. 1946) is an American author, lecturer, former gymnast, and
martial artist (Aikido black belt / shodan). He was director of gymnastics at
Stanford University (1968), coached U.S. Olympian Steve Hug, and trained in
Aikido during his Stanford tenure. He is best known for "Way of the Peaceful
Warrior" and the film "Peaceful Warrior."

This script fetches multiple URLs about Dan Millman, extracts text/metadata,
runs each through the standard entity/claim extraction pipeline (process_page),
and exports the result to the tracked graph_snapshot/ JSONL.

Usage:
    python scripts/20_ingest_dan_millman.py
    python scripts/20_ingest_dan_millman.py --dry-run
    python scripts/20_ingest_dan_millman.py --db data/graph.db --no-export
    python scripts/20_ingest_dan_millman.py --browser-ua
"""

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import requests
from bs4 import BeautifulSoup

from config.settings import settings
from scripts._pipeline_helpers import process_page
from src.crawler.web_crawler import CrawledPage, ImageCandidate
from src.extractor.claim_extractor import ClaimExtractor
from src.extractor.entity_extractor import EntityExtractor
from src.storage.graph_db import GraphDB
from src.storage.json_export import export_to_json, import_from_json
from src.utils.text_utils import clean_text

# Primary sources about Dan Millman
DEFAULT_URLS = [
    "https://en.wikipedia.org/wiki/Dan_Millman",
    "https://www.whistlekickmartialartsradio.com/blog/episode-672-mr-dan-millman/",
    "https://usagym.org/halloffame/inductee/millman-dan",
    "https://usghof.org/d_millman",
    "https://alchetron.com/Dan-Millman",
]

USER_AGENT = settings.crawl_user_agent
BROWSER_USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)
TIMEOUT = settings.crawl_timeout


def fetch_page(url: str, use_browser_ua: bool = False) -> CrawledPage:
    """Fetch and parse a single URL into a CrawledPage."""
    ua = BROWSER_USER_AGENT if use_browser_ua else USER_AGENT
    headers = {
        "User-Agent": ua,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.5",
    }
    resp = requests.get(url, headers=headers, timeout=TIMEOUT)
    resp.raise_for_status()

    soup = BeautifulSoup(resp.text, "lxml")

    title_tag = soup.find("title")
    title = title_tag.get_text(strip=True) if title_tag else ""

    author = None
    for selector in [
        ("meta", {"name": "author"}),
        ("meta", {"property": "article:author"}),
        ("meta", {"name": "twitter:creator"}),
    ]:
        tag = soup.find(*selector)
        if tag and tag.get("content"):
            author = tag["content"]
            break

    publish_date = None
    for selector in [
        ("meta", {"property": "article:published_time"}),
        ("meta", {"name": "date"}),
        ("meta", {"name": "DC.date"}),
        ("time", {}),
    ]:
        tag = soup.find(*selector)
        if tag:
            val = tag.get("content") or tag.get("datetime") or ""
            if val:
                publish_date = val
                break

    content_area = soup.find("article") or soup.find("main") or soup.find("body") or soup
    text = clean_text(str(content_area))

    images: list[ImageCandidate] = []
    seen: set[str] = set()
    og_image = soup.find("meta", {"property": "og:image"})
    if og_image and og_image.get("content"):
        img_url = og_image["content"].strip()
        if img_url and not img_url.startswith("data:"):
            seen.add(img_url)
            images.append(ImageCandidate(url=img_url, alt=title))

    for img_tag in content_area.find_all("img"):
        src = (img_tag.get("src") or img_tag.get("data-src") or "").strip()
        if not src or src.startswith("data:"):
            continue
        if src.lower().split("?")[0].endswith((".svg", ".ico")):
            continue
        if src in seen:
            continue
        seen.add(src)
        images.append(ImageCandidate(url=src, alt=img_tag.get("alt", "").strip()))

    return CrawledPage(
        url=url,
        title=title,
        text=text,
        links=[],
        images=images,
        author=author,
        publish_date=publish_date,
        status_code=resp.status_code,
    )


def main():
    parser = argparse.ArgumentParser(
        description="Ingest Dan Millman sources into the story graph"
    )
    parser.add_argument("--urls", nargs="*", default=None, help="URLs to ingest (default: built-in list)")
    parser.add_argument("--db", default=None, help="Database path (default: data/graph.db)")
    parser.add_argument("--snapshot", default=None, help="Snapshot dir (default: graph_snapshot)")
    parser.add_argument("--dry-run", action="store_true", help="Fetch and show what would be ingested, no DB writes")
    parser.add_argument("--no-export", action="store_true", help="Skip snapshot export after ingestion")
    parser.add_argument("--no-rebuild", action="store_true", help="Don't rebuild DB from snapshot first")
    parser.add_argument("--browser-ua", action="store_true", help="Use a browser-like User-Agent")
    args = parser.parse_args()

    urls = args.urls if args.urls else DEFAULT_URLS
    db_path = args.db or str(settings.graph_db_abs_path)
    snapshot_dir = args.snapshot or str(settings.graph_snapshot_abs_dir)

    print()
    print("╔════════════════════════════════════════════════════════════════════╗")
    print("║  INGEST DAN MILLMAN — story_graph                                   ║")
    print("╚════════════════════════════════════════════════════════════════════╝")
    print()

    print(f"  URLs:     {len(urls)}")
    for u in urls:
        print(f"    - {u}")
    print(f"  DB:       {db_path}")
    print(f"  Snapshot: {snapshot_dir}")
    print()

    # Phase 1: Fetch all pages
    print("[1/3] Fetching pages...")
    pages = []
    for url in urls:
        try:
            page = fetch_page(url, use_browser_ua=args.browser_ua)
            pages.append(page)
            print(f"  OK  {url}")
            print(f"       Title: {page.title[:80]}")
            print(f"       Text:  {len(page.text)} chars, Images: {len(page.images)}")
        except requests.RequestException as e:
            print(f"  FAIL {url}: {e}")

    if not pages:
        print("  ERROR: No pages fetched successfully")
        sys.exit(1)

    if args.dry_run:
        print(f"\n[dry-run mode — no DB writes]")
        for p in pages:
            print(f"\n--- {p.url} ---")
            print(f"First 500 chars:\n{p.text[:500]}...")
        return

    # Phase 2: Rebuild DB from snapshot, then process each page
    print("\n[2/3] Processing through extraction pipeline...")
    if args.no_rebuild:
        db = GraphDB(db_path)
    else:
        db = import_from_json(snapshot_dir, db_path)

    extractor = EntityExtractor(settings.spacy_model)
    claim_extractor = ClaimExtractor(extractor)

    for page in pages:
        print(f"\n  Processing: {page.url}")
        process_page(page, extractor, claim_extractor, db)

    node_count = db.get_node_count()
    source_count = len(db.get_all_sources())
    print(f"\n  Graph now has {node_count} nodes, {source_count} sources")

    # Phase 3: Export to snapshot
    if not args.no_export:
        print("\n[3/3] Exporting to snapshot...")
        counts = export_to_json(db, snapshot_dir)
        print(f"  Exported: {counts}")
    else:
        print("\n[3/3] Skipping export (--no-export)")

    print("\nDone.")


if __name__ == "__main__":
    main()
