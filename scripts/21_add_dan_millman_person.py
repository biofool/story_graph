#!/usr/bin/env python3
"""
Add Dan Millman as a first-class Person node in the story graph, with key
biographical edges connecting him to Stanford, Aikido, and the places/groups
already in the graph.

The ingestion script (20_ingest_dan_millman.py) fetched and processed 4 web
sources about Dan Millman, but the rule-based extractor (spaCy not installed)
did not create a Person node for him. This script adds the Person node and
key relationship edges manually, sourced from the ingested web pages.

Usage:
    python scripts/21_add_dan_millman_person.py
    python scripts/21_add_dan_millman_person.py --dry-run
"""

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.storage.graph_db import GraphDB
from src.storage.json_export import export_to_json, import_from_json
from src.storage.models import (
    BiasHint,
    GraphEdge,
    GraphNode,
    NodeType,
    RelationType,
)

# Source URLs that were ingested via 20_ingest_dan_millman.py
WIKIPEDIA_URL = "https://en.wikipedia.org/wiki/Dan_Millman"
USAGYM_URL = "https://usagym.org/halloffame/inductee/millman-dan"
USGHOF_URL = "https://usghof.org/d_millman"
ALCHETRON_URL = "https://alchetron.com/Dan-Millman"

ALL_SOURCES = [WIKIPEDIA_URL, USAGYM_URL, USGHOF_URL, ALCHETRON_URL]


def add_dan_millman(db: GraphDB, dry_run: bool = False) -> dict:
    """Add Dan Millman Person node and key edges."""
    stats = {"nodes": 0, "edges": 0}

    # --- Person node: Dan Millman ---
    dan_node = GraphNode(
        id="person:dan-millman",
        type=NodeType.PERSON,
        label="Dan Millman",
        canonical_name="Daniel Jay Millman",
        metadata={
            "birth_date": "1946-02-22",
            "birth_place": "Los Angeles, California",
            "occupation": "author, lecturer, former gymnast, martial artist",
            "martial_arts": "Aikido (shodan/black belt), Judo, Karate",
            "notable_work": "Way of the Peaceful Warrior",
            "spouse": "Joy Millman",
            "residence": "Brooklyn, New York (formerly San Rafael, California)",
        },
        source_urls=ALL_SOURCES,
    )
    if not dry_run:
        db.add_node(dan_node)
    stats["nodes"] += 1

    # --- Place node: Stanford University ---
    stanford_node = GraphNode(
        id="place:stanford-university",
        type=NodeType.PLACE,
        label="Stanford University",
        canonical_name="Stanford University",
        metadata={
            "location": "Stanford, California",
            "role": "Director of Gymnastics (1968+)",
        },
        source_urls=[WIKIPEDIA_URL, USAGYM_URL, ALCHETRON_URL],
    )
    if not dry_run:
        db.add_node(stanford_node)
    stats["nodes"] += 1

    # --- Place node: Oberlin College ---
    oberlin_node = GraphNode(
        id="place:oberlin-college",
        type=NodeType.PLACE,
        label="Oberlin College",
        canonical_name="Oberlin College",
        metadata={
            "location": "Oberlin, Ohio",
            "role": "Assistant Professor of Physical Education (1972)",
        },
        source_urls=[WIKIPEDIA_URL],
    )
    if not dry_run:
        db.add_node(oberlin_node)
    stats["nodes"] += 1

    # --- Group node: Aikido ---
    aikido_node = GraphNode(
        id="group:aikido",
        type=NodeType.GROUP,
        label="Aikido",
        canonical_name="Aikido",
        metadata={"martial_art": True},
        source_urls=[WIKIPEDIA_URL, USAGYM_URL, USGHOF_URL, ALCHETRON_URL],
    )
    if not dry_run:
        db.add_node(aikido_node)
    stats["nodes"] += 1

    # --- Person node: Steve Hug (Olympian coached by Millman) ---
    hug_node = GraphNode(
        id="person:steve-hug",
        type=NodeType.PERSON,
        label="Steve Hug",
        canonical_name="Steve Hug",
        metadata={"role": "U.S. Olympian, gymnast coached by Dan Millman"},
        source_urls=[WIKIPEDIA_URL, USAGYM_URL],
    )
    if not dry_run:
        db.add_node(hug_node)
    stats["nodes"] += 1

    # --- Key edges ---

    edges = [
        # Dan Millman WORKED_AT Stanford University (Director of Gymnastics)
        GraphEdge(
            src_id="person:dan-millman",
            dst_id="place:stanford-university",
            rel_type=RelationType.WORKED_AT,
            metadata={
                "role": "Director of Gymnastics",
                "start_year": 1968,
                "evidence": WIKIPEDIA_URL,
            },
        ),
        # Dan Millman WORKED_AT Oberlin College
        GraphEdge(
            src_id="person:dan-millman",
            dst_id="place:oberlin-college",
            rel_type=RelationType.WORKED_AT,
            metadata={
                "role": "Assistant Professor of Physical Education",
                "start_year": 1972,
                "evidence": WIKIPEDIA_URL,
            },
        ),
        # Dan Millman MEMBER_OF Aikido (earned shodan/black belt)
        GraphEdge(
            src_id="person:dan-millman",
            dst_id="group:aikido",
            rel_type=RelationType.MEMBER_OF,
            metadata={
                "rank": "shodan (black belt)",
                "context": "Trained in Aikido during Stanford tenure",
                "evidence": WIKIPEDIA_URL,
            },
        ),
        # Steve Hug trained at Stanford under Millman
        GraphEdge(
            src_id="person:steve-hug",
            dst_id="place:stanford-university",
            rel_type=RelationType.WORKED_AT,
            metadata={
                "role": "U.S. Olympian gymnast",
                "coach": "Dan Millman",
                "evidence": WIKIPEDIA_URL,
            },
        ),
    ]

    for edge in edges:
        if not dry_run:
            db.add_edge(edge)
        stats["edges"] += 1

    return stats


def main():
    parser = argparse.ArgumentParser(
        description="Add Dan Millman as a Person node with key relationship edges"
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
    print("║  ADD DAN MILLMAN PERSON NODE — story_graph                          ║")
    print("╚════════════════════════════════════════════════════════════════════╝")
    print()

    if args.dry_run:
        print("[dry-run mode]")
        stats = add_dan_millman(None, dry_run=True)
        print(f"  Would add: {stats['nodes']} nodes, {stats['edges']} edges")
        return

    print("[1/2] Rebuilding DB from snapshot and adding nodes/edges...")
    if args.no_rebuild:
        db = GraphDB(db_path)
    else:
        db = import_from_json(snapshot_dir, db_path)

    stats = add_dan_millman(db)
    print(f"  Added: {stats['nodes']} nodes, {stats['edges']} edges")

    node_count = db.get_node_count()
    print(f"  Graph now has {node_count} nodes")

    if not args.no_export:
        print("\n[2/2] Exporting to snapshot...")
        counts = export_to_json(db, snapshot_dir)
        print(f"  Exported: {counts}")
    else:
        print("\n[2/2] Skipping export (--no-export)")

    print("\nDone.")


if __name__ == "__main__":
    main()
