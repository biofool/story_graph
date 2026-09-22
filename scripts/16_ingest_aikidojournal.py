#!/usr/bin/env python3
"""
Ingest an Aikido Journal article into the story_graph.

This script fetches a URL from aikidojournal.com, extracts text/metadata,
runs it through the standard entity/claim extraction pipeline (process_page),
and exports the result to the tracked graph_snapshot/ JSONL.

Primary use case: ingesting articles about Aikido figures connected to the
Source Family / Father Yod story (e.g. Robert Nadeau, who studied with
O-Sensei and taught in California during the same era).

Usage:
    python scripts/16_ingest_aikidojournal.py
    python scripts/16_ingest_aikidojournal.py --url <URL>
    python scripts/16_ingest_aikidojournal.py --dry-run
    python scripts/16_ingest_aikidojournal.py --db data/graph.db --no-export
"""

import argparse
import sys
from pathlib import Path

# Add project root to path
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

DEFAULT_URL = (
    "https://aikidojournal.com/2025/05/12/"
    "a-journey-through-aikido-robert-nadeau-on-spirituality-"
    "o-sensei-and-the-golden-age-of-aikido-in-california/"
)

TIMEOUT = settings.crawl_timeout


def main():
    parser = argparse.ArgumentParser(
        description="Ingest an Aikido Journal article into the story graph"
    )
    parser.add_argument("--url", default=DEFAULT_URL, help="URL to ingest")
    parser.add_argument("--db", default=None, help="Database path (default: data/graph.db)")
    parser.add_argument("--snapshot", default=None, help="Snapshot dir (default: graph_snapshot)")
    parser.add_argument("--dry-run", action="store_true", help="Fetch and show what would be ingested, no DB writes")
    parser.add_argument("--no-export", action="store_true", help="Skip snapshot export after ingestion")
    parser.add_argument("--no-rebuild", action="store_true", help="Don't rebuild DB from snapshot first (use existing data/graph.db)")
    parser.add_argument("--browser-ua", action="store_true", default=True, help="Use a browser-like User-Agent (default: on)")
    parser.add_argument("--no-browser-ua", action="store_true", help="Use the bare bot User-Agent instead of the browser one")
    parser.add_argument("--retry-archive", action="store_true", help="Skip the direct fetch and go straight to the Wayback Machine archive")
    args = parser.parse_args()

    print()
    print("╔════════════════════════════════════════════════════════════════════╗")
    print("║  INGEST AIKIDO JOURNAL — story_graph                                ║")
    print("╚════════════════════════════════════════════════════════════════════╝")
    print()

    url = args.url
    db_path = args.db or str(settings.graph_db_abs_path)
    snapshot_dir = args.snapshot or str(settings.graph_snapshot_abs_dir)

    print(f"  URL:      {url}")
    print(f"  DB:       {db_path}")
    print(f"  Snapshot: {snapshot_dir}")
    print()

    # Phase 1: Fetch
    print("[1/3] Fetching page...")
    use_browser_ua = not args.no_browser_ua
    try:
        page = fetch_page(
            url,
            timeout=TIMEOUT,
            use_browser_ua=use_browser_ua,
            retry_archive=args.retry_archive,
        )
    except requests.RequestException as e:
        print(f"  ERROR: Failed to fetch {url}: {e}")
        sys.exit(1)

    print(f"  Title:    {page.title}")
    print(f"  Author:   {page.author}")
    print(f"  Date:     {page.publish_date}")
    print(f"  Text:     {len(page.text)} chars")
    print(f"  Images:   {len(page.images)} candidates")

    if not page.text:
        print("  ERROR: No text extracted from page")
        sys.exit(1)

    if args.dry_run:
        print("\n[dry-run mode — no DB writes]")
        print(f"\nFirst 500 chars of extracted text:\n{page.text[:500]}...")
        return

    # Phase 2: Rebuild DB from snapshot, then process page
    print("\n[2/3] Processing through extraction pipeline...")
    if args.no_rebuild:
        db = GraphDB(db_path)
    else:
        db = import_from_json(snapshot_dir, db_path)

    extractor = EntityExtractor(settings.spacy_model)
    claim_extractor = ClaimExtractor(extractor)

    process_page(page, extractor, claim_extractor, db)

    # Count what was added (approximate — upsert semantics)
    node_count = db.get_node_count()
    source_count = len(db.get_all_sources())
    print(f"  Graph now has {node_count} nodes, {source_count} sources")

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
