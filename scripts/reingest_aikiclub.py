#!/usr/bin/env python3
"""Re-ingest aikiclub.ru with the fixed encoding (Windows-1251) crawler.

Deletes the old mojibake source record, re-fetches with the fixed
WebCrawler, re-extracts with Gemini, and exports the snapshot.
"""

import logging
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

URL = "http://www.aikiclub.ru/spb.html"
SNAPSHOT_DIR = PROJECT_ROOT / "graph_snapshot"
DB_PATH = PROJECT_ROOT / "data" / "graph.db"


def get_domain(url: str) -> str:
    return urlparse(url).netloc


def main() -> int:
    print("=" * 70)
    print("  Re-ingest aikiclub.ru with fixed encoding")
    print("=" * 70)

    # Import snapshot
    print(f"\nImporting snapshot from {SNAPSHOT_DIR} ...")
    db = import_from_json(str(SNAPSHOT_DIR), str(DB_PATH))
    print(f"  Imported {db.get_node_count()} nodes")

    # Delete old mojibake source for aikiclub.ru
    print(f"\nDeleting old aikiclub.ru records ...")
    conn = db._conn  # access underlying sqlite connection
    # Find work node ID for aikiclub.ru
    work_id = "work:9c12646dacf2facd"  # from previous run
    # Delete edges referencing this work node
    conn.execute("DELETE FROM edges WHERE src_id = ? OR dst_id = ?", (work_id, work_id))
    # Delete the work node
    conn.execute("DELETE FROM nodes WHERE id = ?", (work_id,))
    # Delete the source record
    conn.execute("DELETE FROM sources WHERE url = ?", (URL,))
    # Delete claim-source links for this source
    conn.execute("DELETE FROM claim_sources WHERE source_id = ?", (work_id,))
    conn.commit()
    print(f"  Deleted old records for {URL}")

    # Re-fetch with fixed crawler
    print(f"\nFetching {URL} with fixed encoding ...")
    crawler = WebCrawler(
        seed_urls=[URL],
        allowed_domains={get_domain(URL)},
        max_depth=0,
        max_pages=1,
        delay_seconds=settings.crawl_delay_seconds,
        user_agent=settings.crawl_user_agent,
        timeout=settings.crawl_timeout,
    )
    pages = crawler.crawl()
    if not pages:
        print("  ✗ no pages fetched")
        return 1

    page = pages[0]
    if not page.text:
        print("  ✗ no text extracted")
        return 1

    print(f"  ✓ fetched: {page.title[:60]} ({len(page.text)} chars)")

    # Verify encoding is fixed
    if "НАДО" in page.text or "Надо" in page.text:
        print("  ✓ Cyrillic text decoded correctly (found 'НАДО')")
    else:
        print("  ⚠ Cyrillic text may still be mojibake")

    # Extract with Gemini
    print(f"\nExtracting with Gemini ...")
    gemini_client = TieredGeminiClient(vertexai_enabled=True)
    if not gemini_client.is_available():
        print("ERROR: Gemini client not available")
        return 1

    extractor = GeminiExtractor(gemini_client, allow_paid=True)
    claim_extractor = GeminiClaimExtractor(extractor)

    result = process_page(
        page,
        extractor=extractor,
        claim_extractor=claim_extractor,
        db=db,
    )

    if result:
        persons = result.get("persons", [])
        claims = result.get("claims", [])
        print(f"  → {len(persons)} persons, {len(claims)} claims extracted")
        for p in persons[:10]:
            print(f"    person: {p.get('name', '?')}")
        for c in claims[:5]:
            print(f"    claim: {c.get('text', '?')[:80]}")
    else:
        print("  → extraction returned None")

    # Export
    print(f"\nExporting snapshot ...")
    counts = export_to_json(db, str(SNAPSHOT_DIR))
    print(f"  Snapshot exported: {counts}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
