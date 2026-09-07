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

from config.settings import settings
from scripts._pipeline_helpers import process_page
from src.crawler.fetch_page import fetch_page
from src.extractor.claim_extractor import ClaimExtractor
from src.extractor.entity_extractor import EntityExtractor
from src.storage.graph_db import GraphDB
from src.storage.json_export import export_to_json, import_from_json

# Primary sources about Dan Millman
DEFAULT_URLS = [
    "https://en.wikipedia.org/wiki/Dan_Millman",
    "https://www.whistlekickmartialartsradio.com/blog/672-dan-millman",
    "https://usagym.org/halloffame/inductee/millman-dan",
    "https://usghof.org/d_millman",
    "https://alchetron.com/Dan-Millman",
]

TIMEOUT = settings.crawl_timeout


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
    parser.add_argument("--browser-ua", action="store_true", default=True, help="Use a browser-like User-Agent (default: on)")
    parser.add_argument("--no-browser-ua", action="store_true", help="Use the bare bot User-Agent instead of the browser one")
    parser.add_argument("--retry-archive", action="store_true", help="Skip the direct fetch and go straight to the Wayback Machine archive")
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
    use_browser_ua = not args.no_browser_ua
    for url in urls:
        try:
            page = fetch_page(
                url,
                timeout=TIMEOUT,
                use_browser_ua=use_browser_ua,
                retry_archive=args.retry_archive,
            )
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
