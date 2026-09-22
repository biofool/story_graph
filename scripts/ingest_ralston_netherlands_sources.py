#!/usr/bin/env python3
"""Ingest the Netherlands Taijivizier interview and German TQJ interview
as independent secondary sources for Peter Ralston.

These are martial-arts association/journal publications — exactly the kind
of independent, editorially-overseen secondary sources that Wikipedia
needs for notability.
"""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.crawler.web_crawler import WebCrawler
from src.storage.json_export import export_to_json, import_from_json
from scripts._pipeline_helpers import process_page
from src.llm.gemini_client import TieredGeminiClient
from src.llm.entity_claim_extractor import GeminiExtractor, GeminiClaimExtractor
from urllib.parse import urlparse

DB_PATH = PROJECT_ROOT / "data" / "graph.db"
SNAPSHOT_DIR = PROJECT_ROOT / "graph_snapshot"

SOURCES = [
    {
        "url": "https://www.chenghsin.nl/wp-content/uploads/2020/04/Tai-Chi-Interview-met-Peter-Ralston.pdf",
        "title": "Tai Chi Interview met Peter Ralston (Taijivizier magazine)",
        "platform": "chenghsin.nl",
        "publisher": "Stichting Taijiquan Nederland (STN) / Taijivizier magazine",
        "source_class": "archival",
        "bias_hint": "neutral_ish",
        "note": (
            "Interview by Epi van de Pol and Rob van Ham, published in "
            "Taijivizier, the magazine of the Dutch Tai Chi Association "
            "(Stichting Taijiquan Nederland / STN). Conducted at the "
            "Cheng Hsin Holland Camp in De Glind, Holland, 2005. "
            "Independent secondary source — martial arts association journal."
        ),
    },
    {
        "url": "https://chenghsin.com/peter-ralston-holland-interview/",
        "title": "Peter Ralston Holland Interview (2016, Connie Witte)",
        "platform": "chenghsin.com",
        "publisher": "Cheng Hsin",
        "source_class": "primary_first_person",
        "bias_hint": "defensive",
        "note": (
            "2016 interview by Connie Witte for a Dutch T'ai Chi magazine, "
            "republished on chenghsin.com in English. The original magazine "
            "publication is the independent source; this chenghsin.com "
            "republication is primary (ABOUTSELF)."
        ),
    },
    {
        "url": "https://tqj.de/wp-content/uploads/2024/09/tqj-online-Interview-Ralston-407.pdf",
        "title": "Interview with Peter Ralston (Tai Chi Chuan Journal / TQJ)",
        "platform": "tqj.de",
        "publisher": "Tai Chi Chuan Journal (TQJ)",
        "source_class": "archival",
        "bias_hint": "neutral_ish",
        "note": (
            "Interview by Almut Schmitz, published in Tai Chi Chuan Journal "
            "(TQJ), a German tai chi magazine. Independent secondary source — "
            "martial arts journal with editorial oversight."
        ),
    },
]


def get_domain(url: str) -> str:
    parsed = urlparse(url)
    host = parsed.hostname or ""
    if host.startswith("www."):
        host = host[4:]
    return host.lower()


def main() -> int:
    print("=" * 70)
    print("  Ingest Netherlands + German martial arts interview sources")
    print("=" * 70)

    # Import snapshot
    print(f"\nImporting snapshot from {SNAPSHOT_DIR} ...")
    db = import_from_json(str(SNAPSHOT_DIR), str(DB_PATH))
    print(f"  Imported {db.get_node_count()} nodes")

    # Initialize Gemini
    print("\nInitializing Gemini ...")
    gemini_client = TieredGeminiClient(vertexai_enabled=True)
    if not gemini_client.is_available():
        print("ERROR: Gemini client not available")
        return 1
    extractor = GeminiExtractor(gemini_client, allow_paid=True)
    claim_extractor = GeminiClaimExtractor(extractor)

    for src in SOURCES:
        url = src["url"]
        print(f"\n  Fetching: {url[:70]}")

        # Check if already ingested
        existing = db.get_source_by_url(url)
        if existing:
            print("    Already in graph, skipping")
            continue

        try:
            # Fetch the page
            domain = get_domain(url)
            crawler = WebCrawler(
                seed_urls=[url],
                allowed_domains={domain},
                max_depth=0,
                max_pages=1,
                delay_seconds=1.0,
                user_agent="story-graph-bot/0.1 (+research)",
                timeout=30,
            )
            pages = crawler.crawl()
            if not pages or not pages[0].text:
                print("    No text fetched")
                continue

            page = pages[0]
            print(f"    Fetched: {page.title[:60]} ({len(page.text)} chars)")

            # Override source classification — these are known publications
            # process_page will classify automatically, but we want to
            # ensure the correct source_class is set
            result = process_page(
                page,
                extractor=extractor,
                claim_extractor=claim_extractor,
                db=db,
            )
            print(f"    Processed: {result}")

            # Now update the source record with the correct classification
            source = db.get_source_by_url(url)
            if source:
                # Update source_class and metadata
                conn = db._conn
                conn.execute(
                    "UPDATE sources SET source_class = ?, bias_hint = ? WHERE url = ?",
                    (src["source_class"], src["bias_hint"], url),
                )
                # Add metadata note
                conn.execute(
                    "UPDATE sources SET metadata = json_set("
                    "COALESCE(metadata, '{}'), '$.publisher', ?, "
                    "'$.note', ?"
                    ") WHERE url = ?",
                    (src["publisher"], src["note"], url),
                )
                conn.commit()
                print(f"    Updated source_class: {src['source_class']}")
                print(f"    Publisher: {src['publisher']}")

        except Exception as e:
            print(f"    ERROR: {e}")

    # Export
    print("\nExporting snapshot ...")
    counts = export_to_json(db, str(SNAPSHOT_DIR))
    print(f"  Snapshot: {counts}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
