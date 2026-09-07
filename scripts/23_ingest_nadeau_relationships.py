#!/usr/bin/env python3
"""
Ingest relationship evidence for the Bay Area Aikido lineage cluster.

Sources discovered via relationship search (scripts/22_relationship_search.py):
- Wikipedia: Robert Nadeau (aikidoka) — lists Dan Millman, Richard Moon, and
  Richard Bunch as notable students of Nadeau
- aikido-health.com: Robert Nadeau profile — mentions Dan Millman
- budovideos.com: "Aikido: The Art of Transformation" book — Dan Millman
  contributed personal stories about training with Nadeau
- cityaikido.com: City Aikido Nadeau page — mentions Dan Millman
- usadojo.com: USAdojo Nadeau profile — mentions Dan Millman

This script adds:
- SourceRecord entries for each fetched URL
- Claim nodes documenting the relationships
- STUDENT_OF edges from students to Nadeau
- MENTIONS edges from sources to persons

Usage:
    python scripts/23_ingest_nadeau_relationships.py
    python scripts/23_ingest_nadeau_relationships.py --dry-run
"""

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.storage.graph_db import GraphDB
from src.storage.json_export import export_to_json, import_from_json
from src.storage.models import (
    GraphEdge,
    GraphNode,
    NodeType,
    RelationType,
    SourceRecord,
    SourceClass,
)

# Source URLs discovered via relationship search
WIKIPEDIA_NADEAU = "https://en.wikipedia.org/wiki/Robert_Nadeau_(aikidoka)"
AIKIDO_HEALTH = "https://www.aikido-health.com/robert-nadeau.html"
BUDOVIDEOS = "https://budovideos.com/products/aikido-the-art-of-transformation-the-life-and-teachings-of-robert-nadeau"
CITYAIKIDO = "https://www.cityaikido.com/nadeau-shihan"
USADOJO = "https://www.usadojo.com/robert-nadeau/"

ALL_SOURCES = [WIKIPEDIA_NADEAU, AIKIDO_HEALTH, BUDOVIDEOS, CITYAIKIDO, USADOJO]


def add_relationship_evidence(db: GraphDB, dry_run: bool = False) -> dict:
    """Add relationship evidence from discovered sources."""
    stats = {"nodes": 0, "edges": 0, "sources": 0, "claims": 0}

    # --- Source records ---
    sources = [
        SourceRecord(
            id="src:wikipedia:nadeau-aikidoka",
            url=WIKIPEDIA_NADEAU,
            title="Robert Nadeau (aikidoka) - Wikipedia",
            platform="Wikipedia",
            source_class=SourceClass.JOURNALISTIC,
        ),
        SourceRecord(
            id="src:aikido-health:nadeau",
            url=AIKIDO_HEALTH,
            title="Robert Nadeau - Aikido Master",
            platform="aikido-health.com",
            source_class=SourceClass.JOURNALISTIC,
        ),
        SourceRecord(
            id="src:budovideos:nadeau-book",
            url=BUDOVIDEOS,
            title="Aikido: The Art of Transformation: The Life and Teachings of Robert Nadeau",
            platform="budovideos.com",
            source_class=SourceClass.DOCUMENTARY_PROMOTIONAL,
        ),
        SourceRecord(
            id="src:cityaikido:nadeau-shihan",
            url=CITYAIKIDO,
            title="Robert Nadeau Shihan - City Aikido",
            platform="cityaikido.com",
            source_class=SourceClass.DOCUMENTARY_PROMOTIONAL,
        ),
        SourceRecord(
            id="src:usadojo:nadeau",
            url=USADOJO,
            title="Robert Nadeau Aikido - USAdojo.com",
            platform="usadojo.com",
            source_class=SourceClass.JOURNALISTIC,
        ),
    ]

    for src in sources:
        if not dry_run:
            db.add_source(src)
        stats["sources"] += 1

    # --- Claim: Dan Millman is a student of Robert Nadeau ---
    # Wikipedia explicitly lists Dan Millman as a "Notable student" of Nadeau.
    # budovideos.com confirms Millman contributed personal stories about
    # training with Nadeau. Multiple sources corroborate.
    millman_student_claim = GraphNode(
        id="claim:search:nadeau-millman-student",
        type=NodeType.CLAIM,
        label="Dan Millman is a notable student of Robert Nadeau (Wikipedia + multiple sources)",
        canonical_name="Dan Millman student of Robert Nadeau",
        metadata={
            "claim_type": "biographical",
            "stance": "supportive",
            "evidence_mode": "secondary_report",
            "discovered_via": "relationship_search",
            "search_query": '"Dan Millman" "Robert Nadeau" aikido',
            "sources": [WIKIPEDIA_NADEAU, BUDOVIDEOS, AIKIDO_HEALTH, CITYAIKIDO, USADOJO],
            "wikipedia_quote": "Notable students: George Leonard, Richard Strozzi-Heckler, Dan Millman, Richard Moon",
            "budovideos_quote": "Presents inspiring personal stories about Nadeau contributed by students, including Dan Millman, Richard Strozzi-Heckler, Peter Ralston, and Renee Gregorio",
        },
        source_urls=[WIKIPEDIA_NADEAU, BUDOVIDEOS],
    )
    if not dry_run:
        db.add_node(millman_student_claim)
    stats["claims"] += 1

    # --- Claim: Richard Moon is a student of Robert Nadeau ---
    moon_student_claim = GraphNode(
        id="claim:search:nadeau-moon-student",
        type=NodeType.CLAIM,
        label="Richard Moon is a notable student of Robert Nadeau (Wikipedia)",
        canonical_name="Richard Moon student of Robert Nadeau",
        metadata={
            "claim_type": "biographical",
            "stance": "supportive",
            "evidence_mode": "secondary_report",
            "discovered_via": "relationship_search",
            "search_query": '"Dan Millman" "Robert Nadeau" aikido',
            "sources": [WIKIPEDIA_NADEAU],
            "wikipedia_quote": "Notable students: George Leonard, Richard Strozzi-Heckler, Dan Millman, Richard Moon",
        },
        source_urls=[WIKIPEDIA_NADEAU],
    )
    if not dry_run:
        db.add_node(moon_student_claim)
    stats["claims"] += 1

    # --- Claim: Richard Bunch connected Nadeau with Kufferath ---
    bunch_kufferath_claim = GraphNode(
        id="claim:search:nadeau-bunch-kufferath",
        type=NodeType.CLAIM,
        label="Robert Nadeau shared dojo space with Sig Kufferath, later with Richard Bunch (Wikipedia)",
        canonical_name="Nadeau shared space with Kufferath and Bunch",
        metadata={
            "claim_type": "biographical",
            "stance": "supportive",
            "evidence_mode": "secondary_report",
            "discovered_via": "relationship_search",
            "sources": [WIKIPEDIA_NADEAU],
            "wikipedia_quote": "he opened a series of martial art schools sharing space with first Professor Sig Kufferath and later Richard Bunch through whom he has had on-going contact with several notable Ju-Jitsu schools",
        },
        source_urls=[WIKIPEDIA_NADEAU],
    )
    if not dry_run:
        db.add_node(bunch_kufferath_claim)
    stats["claims"] += 1

    # --- Person nodes for entities not yet in graph ---
    # Richard Strozzi-Heckler — mentioned as another notable student
    strozzi_node = GraphNode(
        id="person:richard-strozzi-heckler",
        type=NodeType.PERSON,
        label="Richard Strozzi-Heckler",
        canonical_name="Richard Strozzi-Heckler",
        metadata={
            "role": "Aikido teacher, author, somatics practitioner",
            "context": "Notable student of Robert Nadeau (Wikipedia)",
        },
        source_urls=[WIKIPEDIA_NADEAU, BUDOVIDEOS],
    )
    if not dry_run:
        db.add_node(strozzi_node)
    stats["nodes"] += 1

    # Peter Ralston — mentioned in budovideos book description
    ralston_node = GraphNode(
        id="person:peter-ralston",
        type=NodeType.PERSON,
        label="Peter Ralston",
        canonical_name="Peter Ralston",
        metadata={
            "role": "Martial arts teacher",
            "context": "Contributed personal stories about training with Nadeau (budovideos.com)",
        },
        source_urls=[BUDOVIDEOS],
    )
    if not dry_run:
        db.add_node(ralston_node)
    stats["nodes"] += 1

    # George Leonard — mentioned as notable student
    leonard_node = GraphNode(
        id="person:george-leonard",
        type=NodeType.PERSON,
        label="George Leonard",
        canonical_name="George Leonard",
        metadata={
            "role": "Author, aikido practitioner",
            "context": "Notable student of Robert Nadeau (Wikipedia); founder of Esalen-related work",
        },
        source_urls=[WIKIPEDIA_NADEAU, AIKIDO_HEALTH, CITYAIKIDO, USADOJO],
    )
    if not dry_run:
        db.add_node(leonard_node)
    stats["nodes"] += 1

    # Michael Murphy — mentioned as founder of Esalen
    murphy_node = GraphNode(
        id="person:michael-murphy",
        type=NodeType.PERSON,
        label="Michael Murphy",
        canonical_name="Michael Murphy",
        metadata={
            "role": "Founder of Esalen Institute",
            "context": "Featured Nadeau in his books; mentioned alongside Dan Millman",
        },
        source_urls=[AIKIDO_HEALTH, CITYAIKIDO, USADOJO],
    )
    if not dry_run:
        db.add_node(murphy_node)
    stats["nodes"] += 1

    # --- Edges: STUDENT_OF relationships ---
    # Dan Millman STUDENT_OF Robert Nadeau
    edges = [
        GraphEdge(
            src_id="person:dan-millman",
            dst_id="person:robert-nadeau",
            rel_type=RelationType.MEMBER_OF,
            metadata={
                "relationship": "student_of",
                "context": "Dan Millman is listed as a notable student of Robert Nadeau",
                "evidence": WIKIPEDIA_NADEAU,
                "corroborating_sources": [BUDOVIDEOS, AIKIDO_HEALTH, CITYAIKIDO, USADOJO],
                "discovered_via": "relationship_search",
            },
        ),
        # Richard Moon STUDENT_OF Robert Nadeau
        GraphEdge(
            src_id="person:richard-moon-aikido",
            dst_id="person:robert-nadeau",
            rel_type=RelationType.MEMBER_OF,
            metadata={
                "relationship": "student_of",
                "context": "Richard Moon is listed as a notable student of Robert Nadeau",
                "evidence": WIKIPEDIA_NADEAU,
                "discovered_via": "relationship_search",
            },
        ),
        # Richard Strozzi-Heckler STUDENT_OF Robert Nadeau
        GraphEdge(
            src_id="person:richard-strozzi-heckler",
            dst_id="person:robert-nadeau",
            rel_type=RelationType.MEMBER_OF,
            metadata={
                "relationship": "student_of",
                "context": "Richard Strozzi-Heckler is listed as a notable student of Robert Nadeau",
                "evidence": WIKIPEDIA_NADEAU,
                "corroborating_sources": [BUDOVIDEOS],
                "discovered_via": "relationship_search",
            },
        ),
        # George Leonard STUDENT_OF Robert Nadeau
        GraphEdge(
            src_id="person:george-leonard",
            dst_id="person:robert-nadeau",
            rel_type=RelationType.MEMBER_OF,
            metadata={
                "relationship": "student_of",
                "context": "George Leonard is listed as a notable student of Robert Nadeau",
                "evidence": WIKIPEDIA_NADEAU,
                "corroborating_sources": [AIKIDO_HEALTH, CITYAIKIDO, USADOJO],
                "discovered_via": "relationship_search",
            },
        ),
        # Peter Ralston STUDENT_OF Robert Nadeau
        GraphEdge(
            src_id="person:peter-ralston",
            dst_id="person:robert-nadeau",
            rel_type=RelationType.MEMBER_OF,
            metadata={
                "relationship": "student_of",
                "context": "Peter Ralston contributed personal stories about training with Nadeau",
                "evidence": BUDOVIDEOS,
                "discovered_via": "relationship_search",
            },
        ),
        # Claim ABOUT edges
        GraphEdge(
            src_id="claim:search:nadeau-millman-student",
            dst_id="person:dan-millman",
            rel_type=RelationType.ABOUT,
            metadata={"evidence": WIKIPEDIA_NADEAU},
        ),
        GraphEdge(
            src_id="claim:search:nadeau-millman-student",
            dst_id="person:robert-nadeau",
            rel_type=RelationType.ABOUT,
            metadata={"evidence": WIKIPEDIA_NADEAU},
        ),
        GraphEdge(
            src_id="claim:search:nadeau-moon-student",
            dst_id="person:richard-moon-aikido",
            rel_type=RelationType.ABOUT,
            metadata={"evidence": WIKIPEDIA_NADEAU},
        ),
        GraphEdge(
            src_id="claim:search:nadeau-moon-student",
            dst_id="person:robert-nadeau",
            rel_type=RelationType.ABOUT,
            metadata={"evidence": WIKIPEDIA_NADEAU},
        ),
        GraphEdge(
            src_id="claim:search:nadeau-bunch-kufferath",
            dst_id="person:robert-nadeau",
            rel_type=RelationType.ABOUT,
            metadata={"evidence": WIKIPEDIA_NADEAU},
        ),
        # Nadeau MENTIONS Kufferath (shared dojo space)
        GraphEdge(
            src_id="person:robert-nadeau",
            dst_id="person:sig-kufferath",
            rel_type=RelationType.MENTIONS,
            metadata={
                "context": "Nadeau shared martial art school space with Professor Sig Kufferath",
                "evidence": WIKIPEDIA_NADEAU,
                "discovered_via": "relationship_search",
            },
        ),
        # Nadeau MENTIONS Richard Bunch (shared dojo space, link to Ju-Jitsu)
        GraphEdge(
            src_id="person:robert-nadeau",
            dst_id="person:richard-bunch",
            rel_type=RelationType.MENTIONS,
            metadata={
                "context": "Nadeau later shared space with Richard Bunch, who connected him to Ju-Jitsu schools",
                "evidence": WIKIPEDIA_NADEAU,
                "discovered_via": "relationship_search",
            },
        ),
        # Michael Murphy MENTIONS Nadeau (featured in his books)
        GraphEdge(
            src_id="person:michael-murphy",
            dst_id="person:robert-nadeau",
            rel_type=RelationType.MENTIONS,
            metadata={
                "context": "Michael Murphy (founder of Esalen) featured Nadeau in his books, alongside Dan Millman",
                "evidence": AIKIDO_HEALTH,
                "corroborating_sources": [CITYAIKIDO, USADOJO],
                "discovered_via": "relationship_search",
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
        description="Ingest relationship evidence for Bay Area Aikido lineage cluster"
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
    print("║  INGEST NADEAU RELATIONSHIP EVIDENCE — story_graph                 ║")
    print("╚════════════════════════════════════════════════════════════════════╝")
    print()

    if args.dry_run:
        print("[dry-run mode]")
        stats = add_relationship_evidence(None, dry_run=True)
        print(f"  Would add: {stats['sources']} sources, {stats['claims']} claims, {stats['nodes']} nodes, {stats['edges']} edges")
        return

    print("[1/2] Rebuilding DB from snapshot and adding relationship evidence...")
    if args.no_rebuild:
        db = GraphDB(db_path)
    else:
        db = import_from_json(snapshot_dir, db_path)

    stats = add_relationship_evidence(db)
    print(f"  Added: {stats['sources']} sources, {stats['claims']} claims, {stats['nodes']} nodes, {stats['edges']} edges")

    node_count = db.get_node_count()
    print(f"  Graph now has {node_count} nodes")

    if not args.no_export:
        print("\n[2/2] Exporting to snapshot...")
        counts = export_to_json(db, snapshot_dir)
        print(f"  Exported: {counts}")
    else:
        print("\n[2/2] Skipping export (--no-export)")

    print("\nDone.")
    print()
    print("Key relationships added:")
    print("  • Dan Millman → student of → Robert Nadeau (5 sources)")
    print("  • Richard Moon → student of → Robert Nadeau (Wikipedia)")
    print("  • Richard Strozzi-Heckler → student of → Robert Nadeau (2 sources)")
    print("  • George Leonard → student of → Robert Nadeau (4 sources)")
    print("  • Peter Ralston → student of → Robert Nadeau (budovideos)")
    print("  • Robert Nadeau → shared dojo with → Sig Kufferath (Wikipedia)")
    print("  • Robert Nadeau → shared dojo with → Richard Bunch (Wikipedia)")
    print("  • Michael Murphy → mentions → Robert Nadeau (3 sources)")


if __name__ == "__main__":
    main()
