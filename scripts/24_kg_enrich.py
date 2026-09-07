#!/usr/bin/env python3
"""
Enrich Story Graph persons using Google Knowledge Graph Search API.

Resolves person names to canonical URLs, Wikipedia links, and descriptions
via the Knowledge Graph API. Adds missing source URLs and metadata to
existing Person nodes, and creates new Person nodes for entities discovered
during relationship search that don't yet have KG metadata.

Usage:
    python scripts/24_kg_enrich.py
    python scripts/24_kg_enrich.py --dry-run
    python scripts/24_kg_enrich.py --entities person:dan-millman person:robert-nadeau
"""

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.search.kg_client import KnowledgeGraphClient, KGEntity
from src.storage.graph_db import GraphDB
from src.storage.json_export import export_to_json, import_from_json
from src.storage.models import GraphNode, NodeType, SourceRecord, SourceClass


# Persons to enrich (from the Bay Area Aikido lineage cluster + related)
TARGET_PERSONS = [
    ("person:dan-millman", "Dan Millman", "author martial arts"),
    ("person:robert-nadeau", "Robert Nadeau", "aikido"),
    ("person:richard-moon-aikido", "Richard Moon", "aikido peace building"),
    ("person:bob-noha", "Bob Noha", "aikido"),
    ("person:sig-kufferath", "Sig Kufferath", "jujitsu danzan"),
    ("person:richard-bunch", "Richard Bunch", "aikido jujitsu"),
    ("person:richard-strozzi-heckler", "Richard Strozzi-Heckler", "aikido somatics"),
    ("person:george-leonard", "George Leonard", "aikido author"),
    ("person:peter-ralston", "Peter Ralston", "martial arts"),
    ("person:michael-murphy", "Michael Murphy", "Esalen author"),
]


def enrich_persons(db: GraphDB, kg: KnowledgeGraphClient, dry_run: bool = False) -> dict:
    """Enrich Person nodes with Knowledge Graph metadata."""
    stats = {"persons_checked": 0, "persons_found": 0, "urls_added": 0, "sources_added": 0, "metadata_updated": 0}

    for node_id, name, context in TARGET_PERSONS:
        stats["persons_checked"] += 1
        print(f"\n  [{node_id}] Searching KG for: {name} (context: {context})")

        entity = kg.resolve_person(name, context)
        if not entity:
            print(f"    → no KG entity found")
            continue

        stats["persons_found"] += 1
        print(f"    → {entity.name} ({entity.description})")
        if entity.wikipedia_url:
            print(f"    wiki: {entity.wikipedia_url}")
        if entity.url:
            print(f"    url: {entity.url}")
        if entity.article_body:
            print(f"    article: {entity.article_body[:120]}...")

        # Collect new source URLs
        new_urls = []
        if entity.wikipedia_url and entity.wikipedia_url not in new_urls:
            new_urls.append(entity.wikipedia_url)
        if entity.url and entity.url not in new_urls and entity.url.startswith("http"):
            new_urls.append(entity.url)

        if dry_run:
            if new_urls:
                print(f"    would add URLs: {new_urls}")
            continue

        # Add source records for new URLs
        for url in new_urls:
            src_id = f"src:kg:{url.split('/')[-1].replace('_', '-').lower()[:50]}"
            src = SourceRecord(
                id=src_id,
                url=url,
                title=f"Knowledge Graph: {entity.name}",
                platform="Google Knowledge Graph" if "kgsearch" in url else ("Wikipedia" if "wikipedia" in url else "official"),
                source_class=SourceClass.JOURNALISTIC,
            )
            try:
                db.add_source(src)
                stats["sources_added"] += 1
            except Exception:
                pass  # May already exist

        # Update the node's source_urls and metadata
        existing = db.get_node(node_id)
        if existing:
            existing_urls = set(existing.source_urls or [])
            added = [u for u in new_urls if u not in existing_urls]
            if added:
                existing.source_urls = list(existing_urls | set(added))
                stats["urls_added"] += len(added)

            # Add KG metadata
            existing.metadata["kg_id"] = entity.kg_id
            existing.metadata["kg_description"] = entity.description
            if entity.article_body:
                existing.metadata["kg_article_body"] = entity.article_body[:500]
            existing.metadata["kg_enriched"] = True
            stats["metadata_updated"] += 1

            db.add_node(existing)  # upsert
        else:
            print(f"    [WARNING] node {node_id} not found in graph")

    return stats


def main():
    parser = argparse.ArgumentParser(
        description="Enrich Story Graph persons via Google Knowledge Graph API"
    )
    parser.add_argument("--db", default=None, help="Database path")
    parser.add_argument("--snapshot", default=None, help="Snapshot dir")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be added, no DB writes")
    parser.add_argument("--no-export", action="store_true", help="Skip snapshot export")
    parser.add_argument("--no-rebuild", action="store_true", help="Don't rebuild DB from snapshot first")
    args = parser.parse_args()

    from config.settings import settings

    db_path = args.db or str(settings.graph_db_abs_path)
    snapshot_dir = args.snapshot or str(settings.graph_snapshot_abs_dir)

    print()
    print("╔════════════════════════════════════════════════════════════════════╗")
    print("║  KNOWLEDGE GRAPH ENRICHMENT — story_graph                          ║")
    print("╚════════════════════════════════════════════════════════════════════╝")
    print()

    # Load the Google API key. The Knowledge Graph API needs a Cloud project
    # key (Maps/Cloud), NOT a Gemini AI Studio key. Try WorldStudioFinder's
    # .env first since Story Graph's GOOGLE_API_KEY is a Gemini key.
    import os, re
    key = os.environ.get("GOOGLE_KNOWLEDGE_GRAPH_API_KEY", "")

    if not key:
        # Try WorldStudioFinder .env (has a Maps/Cloud key with KG enabled)
        wsf_env = Path("/home/kkron/projects/github/WorldStudioFinder/.env")
        if wsf_env.exists():
            with open(wsf_env) as f:
                for line in f:
                    m = re.match(r'^GOOGLE_API_KEY=(.+)$', line.strip())
                    if m:
                        key = m.group(1).strip().strip('"').strip("'")
                        break

    if not key:
        # Fall back to Story Graph's env (may be a Gemini key that doesn't work)
        key = os.environ.get("GOOGLE_API_KEY", "")

    if not key:
        print("[ERROR] No GOOGLE_API_KEY found. Set it in .env or environment.")
        return 1

    print(f"[INFO] Using GOOGLE_API_KEY (length {len(key)})")

    kg = KnowledgeGraphClient(api_key=key)
    if not kg.is_available():
        print("[ERROR] Knowledge Graph client unavailable")
        return 1

    if args.dry_run:
        print("[dry-run mode]")
        stats = enrich_persons(None, kg, dry_run=True)
        print(f"\nWould enrich: {stats['persons_found']}/{stats['persons_checked']} persons")
        return

    print("[1/2] Rebuilding DB from snapshot and enriching persons...")
    if args.no_rebuild:
        db = GraphDB(db_path)
    else:
        db = import_from_json(snapshot_dir, db_path)

    stats = enrich_persons(db, kg)
    print(f"\n  Checked: {stats['persons_checked']}")
    print(f"  Found in KG: {stats['persons_found']}")
    print(f"  URLs added: {stats['urls_added']}")
    print(f"  Sources added: {stats['sources_added']}")
    print(f"  Metadata updated: {stats['metadata_updated']}")

    if not args.no_export:
        print("\n[2/2] Exporting to snapshot...")
        counts = export_to_json(db, snapshot_dir)
        print(f"  Exported: {counts}")
    else:
        print("\n[2/2] Skipping export (--no-export)")

    print("\nDone.")


if __name__ == "__main__":
    main()
