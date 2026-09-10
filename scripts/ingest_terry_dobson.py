#!/usr/bin/env python3
"""Ingest Terry Dobson into the Story Graph, starting with his Wikipedia page.

Terry Dobson (1937–1992) was an American aikido pioneer, one of the first
Western students of Morihei Ueshiba (O-Sensei) at the Aikikai Hombu Dojo in
Tokyo. He is notable for:
  - Being one of the first Americans to study aikido in Japan (from 1962)
  - Teaching aikido in New York City in the late 1960s and 1970s
  - The famous "Brooklyn subway incident" (also told as "The Train Driver")
  - His role in the New York aikido community alongside Yamada, Chiba, and Kanai

Sources to ingest (in order of authority):
  1. Wikipedia — https://en.wikipedia.org/wiki/Terry_Dobson_(aikidoka)
  2. Aikido Journal — encyclopedia entry and interviews
  3. Other martial-arts sources discovered via search

This script uses the same WebCrawler + GeminiExtractor + process_page
pipeline as ingest_a_person.py and ingest_nadeau_russia_sources.py.
"""

import logging
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.crawler.web_crawler import WebCrawler
from src.llm.entity_claim_extractor import GeminiClaimExtractor, GeminiExtractor
from src.llm.gemini_client import TieredGeminiClient
from src.storage.graph_db import GraphDB
from src.storage.json_export import export_to_json, import_from_json
from scripts._pipeline_helpers import process_page

logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger(__name__)

# Primary sources — start with Wikipedia, then add authoritative martial-arts sources
SOURCE_URLS = [
    # Wikipedia — the canonical biographical entry
    "https://en.wikipedia.org/wiki/Terry_Dobson_(aikidoka)",
    # Aikido Journal — encyclopedia entry (high-authority martial arts source)
    "https://aikidojournal.com/terry-dobson/",
    # Aikido Journal — 1998 interview by Stanley Pranin
    "https://aikidojournal.com/1998/09/01/interview-terry-dobson/",
]

SNAPSHOT_DIR = PROJECT_ROOT / "graph_snapshot"
DB_PATH = PROJECT_ROOT / "data" / "graph.db"


def _fetch_single_page(url: str):
    from urllib.parse import urlparse
    from config.settings import settings

    def get_domain(url: str) -> str:
        return urlparse(url).netloc

    crawler = WebCrawler(
        seed_urls=[url],
        allowed_domains={get_domain(url)},
        max_depth=0,
        max_pages=1,
        delay_seconds=settings.crawl_delay_seconds,
        user_agent=settings.crawl_user_agent,
        timeout=settings.crawl_timeout,
    )
    return crawler.crawl()


def main() -> int:
    print("=" * 70)
    print("  Terry Dobson — Direct Ingestion")
    print("  Starting with Wikipedia + Aikido Journal sources")
    print("=" * 70)

    # Initialize graph
    print(f"\nImporting snapshot from {SNAPSHOT_DIR} ...")
    db = import_from_json(str(SNAPSHOT_DIR), str(DB_PATH))
    print(f"  Imported {db.get_node_count()} nodes, {db.get_edge_count()} edges")

    # Check if Terry Dobson is already in the graph
    from src.storage.models import NodeType

    existing_persons = [
        n for n in db.get_all_nodes()
        if n.type == NodeType.PERSON and "dobson" in n.label.lower()
    ]
    if existing_persons:
        print(f"  Found existing person node(s): {[n.label for n in existing_persons]}")
    else:
        print("  No existing Terry Dobson node — will be created during ingestion")

    # Initialize Gemini
    gemini_client = TieredGeminiClient(vertexai_enabled=True)
    if not gemini_client.is_available():
        print("ERROR: Gemini client not available")
        return 1

    extractor = GeminiExtractor(gemini_client, allow_paid=True)
    claim_extractor = GeminiClaimExtractor(extractor)

    pages_processed = 0
    persons_extracted = 0
    claims_extracted = 0

    print(f"\nFetching and extracting {len(SOURCE_URLS)} URLs...")
    for url in SOURCE_URLS:
        print(f"\n  → {url}")
        try:
            pages = _fetch_single_page(url)
            if not pages:
                print(f"    ✗ no pages fetched")
                continue

            page = pages[0]
            if not page.text:
                print(f"    ✗ no text extracted")
                continue

            print(f"    ✓ fetched: {page.title[:60]} ({len(page.text)} chars)")

            result = process_page(
                page,
                extractor=extractor,
                claim_extractor=claim_extractor,
                db=db,
            )
            pages_processed += 1
            if result:
                persons = result.get("persons", [])
                claims = result.get("claims", [])
                persons_extracted += len(persons)
                claims_extracted += len(claims)
                print(f"    → {len(persons)} persons, {len(claims)} claims")
            else:
                print(f"    → extracted (no result returned)")

        except Exception as e:
            print(f"    ✗ {e}")

    # Export
    print(f"\n{'=' * 70}")
    print(f"  Exporting snapshot ...")
    counts = export_to_json(db, str(SNAPSHOT_DIR))
    print(f"  Snapshot exported: {counts}")
    print(f"  Pages processed: {pages_processed}")
    print(f"  Persons extracted: {persons_extracted}")
    print(f"  Claims extracted: {claims_extracted}")

    # Verify Terry Dobson is in the graph
    dobson_nodes = [
        n for n in db.get_all_nodes()
        if n.type == NodeType.PERSON and "dobson" in n.label.lower()
    ]
    if dobson_nodes:
        print(f"\n  ✓ Terry Dobson node(s) in graph:")
        for n in dobson_nodes:
            print(f"    {n.id}: {n.label}")
            if n.metadata:
                bio = n.metadata.get("bio_summary", "")
                if bio:
                    print(f"      bio: {bio[:100]}...")
    else:
        print(f"\n  ⚠ No 'Dobson' person node found — check extraction results")

    return 0


if __name__ == "__main__":
    sys.exit(main())
