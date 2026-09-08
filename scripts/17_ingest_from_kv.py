#!/usr/bin/env python3
"""
Batch ingestion: pull pending URLs from the Cloudflare Email Worker KV
and process them through the story_graph pipeline.

The Email Worker (email-worker/) receives emails at story@magicsolutions.biz,
extracts URLs, and stores them in a Cloudflare KV namespace. This script:

1. Lists pending URLs from the Worker's HTTP endpoint (GET /pending)
2. For each URL, fetches the page and processes it through process_page
3. Exports the updated graph to graph_snapshot/
4. Deletes successfully processed URLs from KV (DELETE /pending/:key)

Usage:
    python scripts/17_ingest_from_kv.py
    python scripts/17_ingest_from_kv.py --dry-run
    python scripts/17_ingest_from_kv.py --limit 5
    python scripts/17_ingest_from_kv.py --worker-url https://story-graph-email.<account>.workers.dev
"""

import argparse
import json
import sys
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import requests

from config.settings import settings
from scripts._pipeline_helpers import process_page
from scripts.16_ingest_aikidojournal import fetch_page
from src.extractor.claim_extractor import ClaimExtractor
from src.extractor.entity_extractor import EntityExtractor
from src.storage.graph_db import GraphDB
from src.storage.json_export import export_to_json, import_from_json

# Default Worker URL — update with your actual Workers dev URL or custom domain
DEFAULT_WORKER_URL = "https://story-graph-email.workers.dev"


def list_pending(worker_url: str, auth_token: str) -> list[dict]:
    """List pending URLs from the Worker."""
    resp = requests.get(
        f"{worker_url}/pending",
        headers={"Authorization": f"Bearer {auth_token}"},
        timeout=15,
    )
    resp.raise_for_status()
    data = resp.json()
    return data.get("pending", [])


def get_pending_detail(worker_url: str, auth_token: str, key: str) -> dict:
    """Get full detail for a pending URL."""
    resp = requests.get(
        f"{worker_url}/pending/{key}",
        headers={"Authorization": f"Bearer {auth_token}"},
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json().get("data", {})


def delete_pending(worker_url: str, auth_token: str, key: str) -> bool:
    """Delete a processed URL from KV."""
    resp = requests.delete(
        f"{worker_url}/pending/{key}",
        headers={"Authorization": f"Bearer {auth_token}"},
        timeout=15,
    )
    return resp.status_code == 200


def main():
    parser = argparse.ArgumentParser(
        description="Batch ingest URLs from the Email Worker KV into the story graph"
    )
    parser.add_argument("--worker-url", default=DEFAULT_WORKER_URL,
                        help="URL of the story-graph-email Worker")
    parser.add_argument("--auth-token", default=None,
                        help="Bearer token for the Worker (or set STORY_GRAPH_AUTH_TOKEN env var)")
    parser.add_argument("--db", default=None, help="Database path")
    parser.add_argument("--snapshot", default=None, help="Snapshot directory")
    parser.add_argument("--limit", type=int, default=None, help="Max URLs to process")
    parser.add_argument("--dry-run", action="store_true", help="List URLs but don't process")
    parser.add_argument("--no-export", action="store_true", help="Skip snapshot export")
    parser.add_argument("--no-rebuild", action="store_true", help="Don't rebuild DB from snapshot first")
    args = parser.parse_args()

    import os
    auth_token = args.auth_token or os.getenv("STORY_GRAPH_AUTH_TOKEN", "")
    if not auth_token:
        print("ERROR: No auth token. Set STORY_GRAPH_AUTH_TOKEN env var or use --auth-token")
        sys.exit(1)

    print()
    print("╔════════════════════════════════════════════════════════════════════╗")
    print("║  INGEST FROM KV — story_graph                                       ║")
    print("╚════════════════════════════════════════════════════════════════════╝")
    print()

    # Phase 1: List pending URLs
    print(f"[1/3] Listing pending URLs from {args.worker_url}...")
    try:
        pending = list_pending(args.worker_url, auth_token)
    except requests.RequestException as e:
        print(f"  ERROR: Failed to list pending URLs: {e}")
        sys.exit(1)

    if not pending:
        print("  No pending URLs found.")
        return

    print(f"  Found {len(pending)} pending URL(s):")
    for item in pending[:10]:
        meta = item.get("metadata", {})
        print(f"    {meta.get('url', item['key'])} (from {meta.get('sender', '?')})")
    if len(pending) > 10:
        print(f"    ... and {len(pending) - 10} more")

    if args.limit:
        pending = pending[: args.limit]
        print(f"  [limited to {len(pending)}]")

    if args.dry_run:
        print("\n[dry-run mode — no processing]")
        return

    # Phase 2: Process each URL
    print(f"\n[2/3] Processing {len(pending)} URL(s)...")
    db_path = args.db or str(settings.graph_db_abs_path)
    snapshot_dir = args.snapshot or str(settings.graph_snapshot_abs_dir)

    if args.no_rebuild:
        db = GraphDB(db_path)
    else:
        db = import_from_json(snapshot_dir, db_path)

    extractor = EntityExtractor(settings.spacy_model)
    claim_extractor = ClaimExtractor(extractor)

    processed = 0
    failed = 0

    for item in pending:
        key = item["key"]
        meta = item.get("metadata", {})
        url = meta.get("url", "")

        if not url:
            # Fetch full detail if URL not in metadata
            try:
                detail = get_pending_detail(args.worker_url, auth_token, key)
                url = detail.get("url", "")
            except requests.RequestException:
                pass

        if not url:
            print(f"  SKIP: {key} (no URL found)")
            failed += 1
            continue

        print(f"  Processing: {url}")

        try:
            page = fetch_page(url)
            if page.error or not page.text:
                print(f"    ERROR: No text extracted from {url}")
                failed += 1
                continue

            process_page(page, extractor, claim_extractor, db)
            processed += 1
            print(f"    OK: {len(page.text)} chars, title: {page.title[:60]}")

            # Delete from KV on success
            if delete_pending(args.worker_url, auth_token, key):
                print(f"    Deleted from KV: {key}")
            else:
                print(f"    WARNING: Failed to delete from KV: {key}")

        except requests.RequestException as e:
            print(f"    ERROR: Failed to fetch {url}: {e}")
            failed += 1
        except Exception as e:
            print(f"    ERROR: Failed to process {url}: {e}")
            failed += 1

    print(f"\n  Processed: {processed}, Failed: {failed}")

    # Phase 3: Export to snapshot
    if processed > 0 and not args.no_export:
        print("\n[3/3] Exporting to snapshot...")
        counts = export_to_json(db, snapshot_dir)
        print(f"  Exported: {counts}")
    else:
        print("\n[3/3] Skipping export (no changes or --no-export)")

    print("\nDone.")


if __name__ == "__main__":
    main()
