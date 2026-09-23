#!/usr/bin/env python3
"""
Add dojos that Hiroshi Ikeda Shihan visited frequently as Dojo nodes in the
story graph, with DOJO_AFFILIATION edges to person:hiroshi-ikeda.

The school list was provided by the user (working on Ikeda's Wikipedia
article) and matched against WorldStudioFinder's pipeline.db. The normalized
records live in data/ikeda_visited_dojos.json, including match_type and
confidence so exact matches stay distinguishable from city/country leads.
The association is user-provided research context pending confirmation —
the edges carry evidence_status=unverified and an outreach note.

Usage:
    python scripts/27_add_ikeda_dojos.py --dry-run
    python scripts/27_add_ikeda_dojos.py
"""

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.storage.graph_db import GraphDB
from src.storage.json_export import export_to_json, import_from_json
from src.storage.models import GraphEdge, GraphNode, NodeType, RelationType

DATA_FILE = PROJECT_ROOT / "data" / "ikeda_visited_dojos.json"
SOURCE_URL = "worldstudiofinder:pipeline.db#studios_flat"


def add_ikeda_dojos(db: GraphDB, dry_run: bool = False) -> dict:
    """Add Dojo nodes and DOJO_AFFILIATION edges to person:hiroshi-ikeda."""
    stats = {"nodes": 0, "edges": 0, "skipped": 0}

    records = json.loads(DATA_FILE.read_text(encoding="utf-8"))
    person_id = records["person_id"]

    for rec in records["dojos"]:
        node = GraphNode(
            id=rec["id"],
            type=NodeType.DOJO,
            label=rec["label"],
            canonical_name=rec["label"],
            metadata={
                "city": rec["city"],
                "state": rec["state"],
                "country": rec["country"],
                "email": rec["email"],
                "website": rec["website"],
                "wsf_ids": rec["wsf_ids"],
                "requested_as": rec["requested_as"],
                "match_type": rec["match_type"],
                "confidence": rec["confidence"],
                "notes": rec.get("notes", ""),
                "art": "aikido",
            },
            source_urls=[SOURCE_URL],
        )
        if not dry_run:
            db.add_node(node)
        stats["nodes"] += 1

        edge = GraphEdge(
            src_id=person_id,
            dst_id=rec["id"],
            rel_type=RelationType.DOJO_AFFILIATION,
            metadata={
                "association": "frequent_visited_teacher",
                "evidence_status": "user-provided, unverified",
                "context": "User is building Hiroshi Ikeda's Wikipedia page; Ikeda listed this school as one he visited frequently. Outreach requesting visit records/posters pending.",
                "match_type": rec["match_type"],
                "confidence": rec["confidence"],
            },
        )
        if not dry_run:
            db.add_edge(edge)
        stats["edges"] += 1

    stats["skipped"] = len(records.get("unmatched_requests", []))
    return stats


def main():
    parser = argparse.ArgumentParser(
        description="Add Ikeda frequently-visited dojos with DOJO_AFFILIATION edges"
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
    print("║  ADD IKEDA VISITED DOJOS — story_graph                              ║")
    print("╚════════════════════════════════════════════════════════════════════╝")
    print()

    if args.dry_run:
        print("[dry-run mode]")
        stats = add_ikeda_dojos(None, dry_run=True)
        print(f"  Would add: {stats['nodes']} dojo nodes, {stats['edges']} edges")
        print(f"  Unmatched requests (no node): {stats['skipped']}")
        return

    print("[1/2] Rebuilding DB from snapshot and adding nodes/edges...")
    if args.no_rebuild:
        db = GraphDB(db_path)
    else:
        db = import_from_json(snapshot_dir, db_path)

    stats = add_ikeda_dojos(db)
    print(f"  Added: {stats['nodes']} dojo nodes, {stats['edges']} edges")
    print(f"  Unmatched requests (no node): {stats['skipped']}")

    print(f"  Graph now has {db.get_node_count()} nodes")

    if not args.no_export:
        print("\n[2/2] Exporting to snapshot...")
        counts = export_to_json(db, snapshot_dir)
        print(f"  Exported: {counts}")
    else:
        print("\n[2/2] Skipping export (--no-export)")

    print("\nDone.")


if __name__ == "__main__":
    main()
