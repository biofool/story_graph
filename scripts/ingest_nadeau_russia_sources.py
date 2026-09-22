#!/usr/bin/env python3
"""Ingest the specific Russian sources documenting Nadeau's Russia seminars.

These URLs were identified in docs/nadeau-russia-seminar-search.md as
independent secondary sources confirming Robert Nadeau taught aikido
seminars in Russia (Moscow, Leningrad/St Petersburg) in the early 1990s.

Gemini grounded search does not find Russian-language pages, so we
ingest them directly via the same WebCrawler + GeminiExtractor + process_page
pipeline used by ingest_a_person.py.
"""

import logging
import sys
from pathlib import Path

# Ensure project root is on sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.crawler.web_crawler import WebCrawler
from src.llm.entity_claim_extractor import GeminiClaimExtractor, GeminiExtractor
from src.llm.gemini_client import TieredGeminiClient
from src.search.search_cache import SearchCache
from src.search.quota import QuotaTracker
from src.storage.graph_db import GraphDB
from src.storage.json_export import export_to_json, import_from_json
from scripts._pipeline_helpers import process_page

logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger(__name__)

# URLs from docs/nadeau-russia-seminar-search.md
# These are the independent Russian sources that confirm Nadeau's Russia seminars
RUSSIA_SOURCE_URLS = [
    # Moscow Aiki Club — St. Petersburg/Leningrad aikido history
    # Contains: "27 октября 1990 года ... провел тренировку Роберт НАДО (6-й Дан, США)"
    "http://www.aikiclub.ru/spb.html",
    # Federal Alliance of Bujutsu Russia (Kazan) — aikido history
    # Contains: "посчастливилось тренироваться у таких известных мастеров Айкидо, как
    #            Джек Вада ... Роберт Надо (6 Дан Aikido Aikikai, Канада) ..."
    "https://bujutsu.ru/aikido/",
    # Children's aikido school (Kazan, same org as bujutsu.ru)
    # Slightly different rank figure (7 dan vs 6 dan)
    "https://rebenok-na-aikido.ru/",
]

# Nadeau-affiliated sources that mention Russia (for completeness)
# These are NOT independent but confirm the claim from Nadeau's side
AFFILIATED_RUSSIA_URLS = [
    "https://www.cityaikido.com/nadeau-shihan",
    "http://dev.aikidoofpetaluma.com/energy.html",
    "https://aikido.org.nz/nadeauworkshop/",
]

SNAPSHOT_DIR = PROJECT_ROOT / "graph_snapshot"
DB_PATH = PROJECT_ROOT / "data" / "graph.db"


def main() -> int:
    print("=" * 70)
    print("  Nadeau Russia Seminar Sources — Direct Ingestion")
    print("=" * 70)

    # Initialize graph
    print(f"\nImporting snapshot from {SNAPSHOT_DIR} ...")
    db_file = PROJECT_ROOT / "data" / "graph.db"
    db = import_from_json(str(SNAPSHOT_DIR), str(db_file))
    print(f"  Imported {db.get_node_count()} nodes")

    # Initialize clients
    from config.settings import settings
    from urllib.parse import urlparse

    def get_domain(url: str) -> str:
        return urlparse(url).netloc

    def _fetch_single_page(url: str):
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

    gemini_client = TieredGeminiClient(vertexai_enabled=True)
    if not gemini_client.is_available():
        print("ERROR: Gemini client not available")
        return 1

    extractor = GeminiExtractor(gemini_client, allow_paid=True)
    claim_extractor = GeminiClaimExtractor(extractor)

    all_urls = RUSSIA_SOURCE_URLS + AFFILIATED_RUSSIA_URLS
    pages_processed = 0
    persons_extracted = 0

    print(f"\nFetching and extracting {len(all_urls)} URLs...")
    for url in all_urls:
        is_independent = url in RUSSIA_SOURCE_URLS
        label = "independent" if is_independent else "affiliated"
        print(f"\n  [{label}] {url}")

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
            if result and result.get("persons"):
                persons_extracted += len(result["persons"])
                print(f"    → {len(result['persons'])} persons, "
                      f"{len(result.get('claims', []))} claims")
            else:
                print(f"    → extracted (no persons)")

        except Exception as e:
            print(f"    ✗ {e}")

    # Export
    print(f"\n{'=' * 70}")
    print(f"  Exporting snapshot ...")
    counts = export_to_json(db, str(SNAPSHOT_DIR))
    print(f"  Snapshot exported: {counts}")
    print(f"  Pages processed: {pages_processed}")
    print(f"  Persons extracted: {persons_extracted}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
