#!/usr/bin/env python3
"""Re-ingest all sources with mojibake (wrong encoding) using the fixed WebCrawler.

Identifies sources whose raw_text contains mojibake (non-Latin-1 text decoded
as Latin-1), deletes their old graph records, re-fetches with the fixed crawler
(which uses response.apparent_encoding), re-extracts with Gemini, and exports
the snapshot.
"""

import json
import logging
import re
import sqlite3
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from config.settings import settings
from src.crawler.web_crawler import WebCrawler
from src.llm.entity_claim_extractor import GeminiClaimExtractor, GeminiExtractor
from src.llm.gemini_client import TieredGeminiClient
from src.storage.graph_db import GraphDB
from src.storage.json_export import export_to_json, import_from_json
from scripts._pipeline_helpers import process_page
from urllib.parse import urlparse

logging.basicConfig(level=logging.INFO, format="%(message)s")

SNAPSHOT_DIR = PROJECT_ROOT / "graph_snapshot"
DB_PATH = PROJECT_ROOT / "data" / "graph.db"

# Mojibake detection: 4+ consecutive chars in U+0080-U+00FF range
# At least 5 such sequences in first 3000 chars
MOJIBAKE_REGEX = re.compile(r"[\u0080-\u00FF]{4,}")


def get_domain(url: str) -> str:
    return urlparse(url).netloc


def is_mojibake(text: str) -> bool:
    if not text or len(text) < 100:
        return False
    if text.startswith("%PDF") or text.startswith("OTTO"):
        return False
    sample = text[:3000]
    matches = [m for m in MOJIBAKE_REGEX.findall(sample) if len(m) >= 4]
    return len(matches) >= 5


def find_mojibake_sources(snapshot_dir: Path) -> list[dict]:
    """Find all sources with mojibake in their raw_text."""
    mojibake = []
    with open(snapshot_dir / "sources.jsonl") as f:
        for line in f:
            s = json.loads(line)
            text = s.get("raw_text", "") or ""
            if is_mojibake(text):
                mojibake.append(s)
    return mojibake


def delete_source_records(db: GraphDB, work_id: str, url: str):
    """Delete a source's Work node, edges, and claim-source links."""
    conn = db._conn
    conn.execute("DELETE FROM edges WHERE src_id = ? OR dst_id = ?", (work_id, work_id))
    conn.execute("DELETE FROM nodes WHERE id = ?", (work_id,))
    conn.execute("DELETE FROM sources WHERE url = ? OR id = ?", (url, work_id))
    conn.execute("DELETE FROM claim_sources WHERE source_id = ?", (work_id,))
    conn.commit()


def main() -> int:
    print("=" * 70)
    print("  Re-ingest mojibake sources with fixed encoding")
    print("=" * 70)

    # Find mojibake sources
    print("\nScanning for mojibake sources ...")
    mojibake_sources = find_mojibake_sources(SNAPSHOT_DIR)
    print(f"  Found {len(mojibake_sources)} mojibake sources")

    if not mojibake_sources:
        print("  No mojibake sources found. Nothing to do.")
        return 0

    for s in mojibake_sources:
        print(f"    {s['url'][:80]}")

    # Import snapshot
    print(f"\nImporting snapshot from {SNAPSHOT_DIR} ...")
    db = import_from_json(str(SNAPSHOT_DIR), str(DB_PATH))
    print(f"  Imported {db.get_node_count()} nodes")

    # Delete old mojibake records
    print(f"\nDeleting old mojibake records ...")
    for s in mojibake_sources:
        work_id = s["id"]
        url = s["url"]
        delete_source_records(db, work_id, url)
        print(f"  Deleted: {url[:70]}")

    # Initialize Gemini
    print(f"\nInitializing Gemini ...")
    gemini_client = TieredGeminiClient(vertexai_enabled=True)
    if not gemini_client.is_available():
        print("ERROR: Gemini client not available")
        return 1
    extractor = GeminiExtractor(gemini_client, allow_paid=True)
    claim_extractor = GeminiClaimExtractor(extractor)

    # Re-fetch and extract
    print(f"\nRe-fetching {len(mojibake_sources)} sources with fixed encoding ...")
    pages_processed = 0
    fetch_failures = []

    for s in mojibake_sources:
        url = s["url"]
        print(f"\n  [{pages_processed + 1}/{len(mojibake_sources)}] {url[:70]}")

        try:
            crawler = WebCrawler(
                seed_urls=[url],
                allowed_domains={get_domain(url)},
                max_depth=0,
                max_pages=1,
                delay_seconds=settings.crawl_delay_seconds,
                user_agent=settings.crawl_user_agent,
                timeout=settings.crawl_timeout,
            )
            pages = crawler.crawl()
            if not pages or not pages[0].text:
                print(f"    ✗ no text fetched")
                fetch_failures.append(url)
                continue

            page = pages[0]
            print(f"    ✓ fetched: {page.title[:60]} ({len(page.text)} chars)")

            # Verify mojibake is fixed
            if is_mojibake(page.text):
                print(f"    ⚠ still has mojibake after fix")
            else:
                print(f"    ✓ encoding fixed")

            result = process_page(
                page,
                extractor=extractor,
                claim_extractor=claim_extractor,
                db=db,
            )
            pages_processed += 1

        except Exception as e:
            print(f"    ✗ {e}")
            fetch_failures.append(url)

    # Export
    print(f"\n{'=' * 70}")
    print(f"  Exporting snapshot ...")
    counts = export_to_json(db, str(SNAPSHOT_DIR))
    print(f"  Snapshot exported: {counts}")
    print(f"  Pages processed: {pages_processed}")
    print(f"  Fetch failures: {len(fetch_failures)}")
    for url in fetch_failures:
        print(f"    {url[:70]}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
