#!/usr/bin/env python3
"""
Facebook Public Page Research Pipeline for Story Graph (Father Yod / Source Family).

Queries the Meta Graph API (Page Public Content Access), extracts entities & claims,
and updates the SQLite property graph.

Usage:
    python scripts/03_facebook_research.py --page-id <PAGE_ID> --token <USER_OR_PAGE_ACCESS_TOKEN>
    # Or set FB_ACCESS_TOKEN in .env
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path
from dotenv import load_dotenv

# Ensure project root is in sys.path
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

load_dotenv()

from src.crawler.facebook_collector import FacebookGraphCollector
from src.extractor.entity_extractor import EntityExtractor
from src.extractor.claim_extractor import ClaimExtractor
from src.extractor.contradiction_detector import ContradictionDetector
from src.storage.graph_db import GraphDB
from scripts._pipeline_helpers import process_page

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
_log = logging.getLogger("facebook_research")


def main():
    parser = argparse.ArgumentParser(description="Ingest public Facebook Page posts and comments into Story Graph")
    parser.add_argument("--page-id", required=True, help="Facebook Page ID or handle (e.g., test page or public page)")
    parser.add_argument("--token", default=os.getenv("FB_ACCESS_TOKEN"), help="Meta Graph API Access Token (or set FB_ACCESS_TOKEN)")
    parser.add_argument("--db-path", default=os.getenv("GRAPH_DB_PATH", "data/graph.db"), help="SQLite database path")
    parser.add_argument("--max-posts", type=int, default=25, help="Max posts to collect")
    parser.add_argument("--no-comments", action="store_true", help="Skip fetching post comments")
    args = parser.parse_args()

    if not args.token:
        _log.error("Missing Meta Access Token. Provide --token or set FB_ACCESS_TOKEN in .env.")
        _log.info("Generate a User/Page token at: https://developers.facebook.com/tools/explorer/")
        sys.exit(1)

    collector = FacebookGraphCollector(access_token=args.token)
    extractor = EntityExtractor()
    claim_extractor = ClaimExtractor()
    db = GraphDB(db_path=args.db_path)

    _log.info(f"Starting Facebook Public Page Research on Page ID: {args.page_id}")
    pages = collector.collect_page_research(
        page_id=args.page_id,
        include_comments=not args.no_comments,
        max_posts=args.max_posts,
    )

    _log.info(f"Collected {len(pages)} posts/threads. Extracting entities and claims...")
    for page in pages:
        process_page(page, extractor, claim_extractor, db)

    _log.info("Running contradiction detection...")
    detector = ContradictionDetector()
    all_claims = [node.metadata for node in db.get_nodes_by_type("Claim")]
    contradictions = detector.find_contradictions(all_claims)
    _log.info(f"Found {len(contradictions)} potential contradictions.")

    _log.info("Research ingestion complete!")
    _log.info(f"Database saved to: {args.db_path}")
    _log.info("Explore with: datasette " + args.db_path)


if __name__ == "__main__":
    main()
