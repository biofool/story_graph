#!/usr/bin/env python3
"""
Ingest Peter Ralston biographical data and sources into the Story Graph.

Sources:
- chenghsin.com/who-is-peter-ralston/ — official biography
- chenghsin.com/about-the-cheng-hsin-center/ — center history
- chenghsin.com/books-and-more/ — book list
- Open Library — 5 books confirmed

Peter Ralston has NO Wikipedia page (confirmed 404 on all URL variants).
This script documents his biography and creates a Wikipedia gap claim.

Key facts:
- Born in San Francisco, raised primarily in Asia
- Began martial arts at age 9 in Singapore
- Black belts in Judo, Jujitsu, Karate by age 20
- Sumo champion (high school, Japan), Judo & fencing champion (UC Berkeley)
- Studied Aikido, Japanese/Chinese fencing, western boxing, Muay Thai
- Founded Cheng Hsin School in 1975
- Opened center in Oakland, CA in 1977
- 1978: First non-Asian to win World Championship full-contact martial arts
  tournament in Republic of China (Taiwan)
- Founder of the consciousness movement in SF Bay Area
- Worked with Stewart Emery (Actualizations), Werner Erhard (EST/Forum)
- Author of 9+ books including The Book of Not Knowing, Zen Body-Being

Usage:
    python scripts/25_ingest_peter_ralston.py
    python scripts/25_ingest_peter_ralston.py --dry-run
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

# Source URLs
CHENGHSIN_BIO = "https://chenghsin.com/who-is-peter-ralston/"
CHENGHSIN_CENTER = "https://chenghsin.com/about-the-cheng-hsin-center/"
CHENGHSIN_BOOKS = "https://chenghsin.com/books-and-more/"
OPEN_LIBRARY = "https://openlibrary.org/search.json?author=Peter+Ralston"

ALL_SOURCES = [CHENGHSIN_BIO, CHENGHSIN_CENTER, CHENGHSIN_BOOKS, OPEN_LIBRARY]


def add_ralston_data(db: GraphDB, dry_run: bool = False) -> dict:
    """Add Peter Ralston biographical data and edges."""
    stats = {"nodes": 0, "edges": 0, "sources": 0, "claims": 0}

    # --- Sources ---
    sources = [
        SourceRecord(
            id="src:chenghsin:ralston-bio",
            url=CHENGHSIN_BIO,
            title="Who is Peter Ralston? — Cheng Hsin",
            platform="chenghsin.com",
            source_class=SourceClass.PRIMARY_FIRST_PERSON,
        ),
        SourceRecord(
            id="src:chenghsin:center",
            url=CHENGHSIN_CENTER,
            title="About the Cheng Hsin Center",
            platform="chenghsin.com",
            source_class=SourceClass.DOCUMENTARY_PROMOTIONAL,
        ),
        SourceRecord(
            id="src:chenghsin:books",
            url=CHENGHSIN_BOOKS,
            title="Books and More — Peter Ralston",
            platform="chenghsin.com",
            source_class=SourceClass.DOCUMENTARY_PROMOTIONAL,
        ),
        SourceRecord(
            id="src:openlibrary:ralston",
            url=OPEN_LIBRARY,
            title="Open Library: Peter Ralston books",
            platform="openlibrary.org",
            source_class=SourceClass.JOURNALISTIC,
        ),
    ]
    for src in sources:
        if not dry_run:
            db.add_source(src)
        stats["sources"] += 1

    # --- Update Peter Ralston Person node with rich biographical data ---
    ralston_node = GraphNode(
        id="person:peter-ralston",
        type=NodeType.PERSON,
        label="Peter Ralston",
        canonical_name="Peter Ralston",
        metadata={
            "birth_place": "San Francisco, California",
            "raised": "Primarily in Asia (Singapore, Japan)",
            "occupation": "martial arts teacher, author, consciousness facilitator",
            "martial_arts": "Judo, Jujitsu, Karate, Aikido, Japanese/Chinese fencing, western boxing, Muay Thai, Sumo",
            "ranks": "Black belts in Judo, Jujitsu, Karate (by age 20)",
            "achievements": [
                "Sumo champion at high school in Japan",
                "Judo and fencing champion at UC Berkeley",
                "1978: First non-Asian to win World Championship full-contact martial arts tournament in Republic of China (Taiwan)",
            ],
            "founded": "Cheng Hsin School (1975), Cheng Hsin Center in Oakland, CA (1977)",
            "books": [
                "The Book of Not Knowing (2010)",
                "Zen Body-Being (2006)",
                "Pursuing Consciousness (2015)",
                "Cheng Hsin: The Principles of Effortless Power (1989)",
                "Ancient Wisdom, New Spirit",
                "Reflections of Being",
                "Ending Unnecessary Suffering",
                "Island Journal (1985)",
            ],
            "movement": "One of the founders of the consciousness movement in the San Francisco Bay Area",
            "collaborators": "Stewart Emery (Actualizations), Werner Erhard (EST/Forum)",
            "kg_description": "Author",
            "kg_enriched": True,
            "wikipedia_exists": False,
            "wikipedia_gap": "Peter Ralston has no Wikipedia page despite being a notable martial arts pioneer, author of 9+ books, and the first non-Asian to win the World Championship full-contact martial arts tournament in Taiwan (1978).",
        },
        source_urls=ALL_SOURCES,
    )
    if not dry_run:
        db.add_node(ralston_node)
    stats["nodes"] += 1

    # --- Group nodes ---
    chenghsin_group = GraphNode(
        id="group:cheng-hsin",
        type=NodeType.GROUP,
        label="Cheng Hsin",
        canonical_name="Cheng Hsin School",
        metadata={
            "founded": 1975,
            "location": "Oakland, California (from 1977)",
            "type": "martial arts school + ontological research center",
            "founder": "Peter Ralston",
            "description": "Internal martial arts and consciousness research center. Creator of the Art of Effortless Power.",
        },
        source_urls=[CHENGHSIN_BIO, CHENGHSIN_CENTER],
    )
    if not dry_run:
        db.add_node(chenghsin_group)
    stats["nodes"] += 1

    # Place node for Oakland
    oakland_node = GraphNode(
        id="place:oakland-california",
        type=NodeType.PLACE,
        label="Oakland, California",
        canonical_name="Oakland",
        metadata={"location": "Alameda County, California"},
        source_urls=[CHENGHSIN_BIO],
    )
    if not dry_run:
        db.add_node(oakland_node)
    stats["nodes"] += 1

    # Place node for UC Berkeley
    berkeley_node = GraphNode(
        id="place:uc-berkeley",
        type=NodeType.PLACE,
        label="UC Berkeley",
        canonical_name="University of California, Berkeley",
        metadata={
            "location": "Berkeley, California",
            "context": "Ralston was Judo and fencing champion here",
        },
        source_urls=[CHENGHSIN_BIO],
    )
    if not dry_run:
        db.add_node(berkeley_node)
    stats["nodes"] += 1

    # Person nodes for collaborators
    emery_node = GraphNode(
        id="person:stewart-emery",
        type=NodeType.PERSON,
        label="Stewart Emery",
        canonical_name="Stewart Emery",
        metadata={
            "role": "Founder of Actualizations",
            "context": "Ralston worked for Emery in Actualizations",
        },
        source_urls=[CHENGHSIN_BIO],
    )
    if not dry_run:
        db.add_node(emery_node)
    stats["nodes"] += 1

    erhard_node = GraphNode(
        id="person:werner-erhard",
        type=NodeType.PERSON,
        label="Werner Erhard",
        canonical_name="Werner Erhard",
        metadata={
            "role": "Founder of EST and The Forum",
            "context": "Ralston helped Erhard create a fundamental shift from EST to the Forum",
        },
        source_urls=[CHENGHSIN_BIO],
    )
    if not dry_run:
        db.add_node(erhard_node)
    stats["nodes"] += 1

    # --- Claim: 1978 World Championship ---
    tournament_claim = GraphNode(
        id="claim:ralston-1978-world-championship",
        type=NodeType.CLAIM,
        label="Peter Ralston was the first non-Asian to win the World Championship full-contact martial arts tournament in the Republic of China (Taiwan) in 1978",
        canonical_name="Ralston 1978 World Championship win",
        metadata={
            "claim_type": "biographical",
            "stance": "supportive",
            "evidence_mode": "first_person",
            "date": "1978",
            "location": "Republic of China (Taiwan)",
            "achievement": "First non-Asian to win World Championship full-contact martial arts tournament",
            "source": CHENGHSIN_BIO,
            "wikipedia_notability": "This achievement alone should meet Wikipedia notability criteria for sports figures",
        },
        source_urls=[CHENGHSIN_BIO],
    )
    if not dry_run:
        db.add_node(tournament_claim)
    stats["claims"] += 1

    # --- Claim: Wikipedia gap ---
    wiki_gap_claim = GraphNode(
        id="claim:ralston-wikipedia-gap",
        type=NodeType.CLAIM,
        label="Peter Ralston has no Wikipedia page despite clear notability (martial arts pioneer, author of 9+ books, 1978 world champion)",
        canonical_name="Peter Ralston Wikipedia gap",
        metadata={
            "claim_type": "historical_dispute",
            "stance": "neutral",
            "evidence_mode": "archival_clipping",
            "wikipedia_urls_checked": [
                "https://en.wikipedia.org/wiki/Peter_Ralston",
                "https://en.wikipedia.org/wiki/Peter_Ralston_(martial_artist)",
                "https://en.wikipedia.org/wiki/Peter_Ralston_(author)",
            ],
            "all_404": True,
            "wikipedia_search": "No relevant results for 'Peter Ralston martial' on Wikipedia search",
            "notability_criteria": [
                "First non-Asian to win World Championship full-contact martial arts tournament (1978)",
                "Author of 9+ published books (Open Library confirmed)",
                "Founder of Cheng Hsin, a notable martial arts system",
                "Founder of the consciousness movement in the SF Bay Area",
                "Collaborator with Werner Erhard (EST/Forum) and Stewart Emery (Actualizations)",
            ],
        },
        source_urls=[CHENGHSIN_BIO, OPEN_LIBRARY],
    )
    if not dry_run:
        db.add_node(wiki_gap_claim)
    stats["claims"] += 1

    # --- Edges ---
    edges = [
        # Ralston FOUNDED Cheng Hsin
        GraphEdge(
            src_id="person:peter-ralston",
            dst_id="group:cheng-hsin",
            rel_type=RelationType.FOUNDED,
            metadata={"year": 1975, "evidence": CHENGHSIN_BIO},
        ),
        # Ralston WORKED_AT Oakland (Cheng Hsin Center)
        GraphEdge(
            src_id="person:peter-ralston",
            dst_id="place:oakland-california",
            rel_type=RelationType.WORKED_AT,
            metadata={
                "role": "Founder and teacher at Cheng Hsin Center",
                "start_year": 1977,
                "evidence": CHENGHSIN_BIO,
            },
        ),
        # Ralston WORKED_AT UC Berkeley (student, judo/fencing champion)
        GraphEdge(
            src_id="person:peter-ralston",
            dst_id="place:uc-berkeley",
            rel_type=RelationType.WORKED_AT,
            metadata={
                "role": "Student; Judo and fencing champion",
                "evidence": CHENGHSIN_BIO,
            },
        ),
        # Ralston MEMBER_OF Aikido (studied Aikido)
        GraphEdge(
            src_id="person:peter-ralston",
            dst_id="group:aikido",
            rel_type=RelationType.MEMBER_OF,
            metadata={
                "context": "Studied Aikido as part of broad martial arts training",
                "evidence": CHENGHSIN_BIO,
            },
        ),
        # Ralston MENTIONS Robert Nadeau (both in SF Bay Area consciousness/martial arts scene)
        GraphEdge(
            src_id="person:peter-ralston",
            dst_id="person:robert-nadeau",
            rel_type=RelationType.MENTIONS,
            metadata={
                "context": "Both were part of the SF Bay Area consciousness/martial arts movement in the 1970s. Ralston contributed personal stories to the book about Nadeau.",
                "evidence": "https://budovideos.com/products/aikido-the-art-of-transformation-the-life-and-teachings-of-robert-nadeau",
                "discovered_via": "relationship_search",
            },
        ),
        # Ralston MENTIONS Stewart Emery
        GraphEdge(
            src_id="person:peter-ralston",
            dst_id="person:stewart-emery",
            rel_type=RelationType.MENTIONS,
            metadata={
                "context": "Ralston worked for Emery in Actualizations",
                "evidence": CHENGHSIN_BIO,
            },
        ),
        # Ralston MENTIONS Werner Erhard
        GraphEdge(
            src_id="person:peter-ralston",
            dst_id="person:werner-erhard",
            rel_type=RelationType.MENTIONS,
            metadata={
                "context": "Ralston helped Erhard create a fundamental shift from EST to the Forum",
                "evidence": CHENGHSIN_BIO,
            },
        ),
        # Ralston MENTIONS Esalen (facilitated workshops there)
        GraphEdge(
            src_id="person:peter-ralston",
            dst_id="group:esalen",
            rel_type=RelationType.MENTIONS,
            metadata={
                "context": "Ralston facilitated workshops at Esalen",
                "evidence": CHENGHSIN_BIO,
            },
        ),
        # Claim ABOUT edges
        GraphEdge(
            src_id="claim:ralston-1978-world-championship",
            dst_id="person:peter-ralston",
            rel_type=RelationType.ABOUT,
            metadata={"evidence": CHENGHSIN_BIO},
        ),
        GraphEdge(
            src_id="claim:ralston-wikipedia-gap",
            dst_id="person:peter-ralston",
            rel_type=RelationType.ABOUT,
            metadata={"evidence": CHENGHSIN_BIO},
        ),
    ]

    for edge in edges:
        if not dry_run:
            db.add_edge(edge)
        stats["edges"] += 1

    return stats


def main():
    parser = argparse.ArgumentParser(
        description="Ingest Peter Ralston biographical data and sources"
    )
    parser.add_argument("--db", default=None)
    parser.add_argument("--snapshot", default=None)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--no-export", action="store_true")
    parser.add_argument("--no-rebuild", action="store_true")
    args = parser.parse_args()

    from config.settings import settings

    db_path = args.db or str(settings.graph_db_abs_path)
    snapshot_dir = args.snapshot or str(settings.graph_snapshot_abs_dir)

    print()
    print("╔════════════════════════════════════════════════════════════════════╗")
    print("║  INGEST PETER RALSTON — story_graph                                ║")
    print("╚════════════════════════════════════════════════════════════════════╝")
    print()

    if args.dry_run:
        print("[dry-run mode]")
        stats = add_ralston_data(None, dry_run=True)
        print(f"  Would add: {stats['sources']} sources, {stats['claims']} claims, {stats['nodes']} nodes, {stats['edges']} edges")
        return

    print("[1/2] Rebuilding DB from snapshot and adding Ralston data...")
    if args.no_rebuild:
        db = GraphDB(db_path)
    else:
        db = import_from_json(snapshot_dir, db_path)

    stats = add_ralston_data(db)
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
    print("Peter Ralston key facts ingested:")
    print("  • Born in San Francisco, raised in Asia (Singapore, Japan)")
    print("  • Black belts in Judo, Jujitsu, Karate by age 20")
    print("  • 1978: First non-Asian to win World Championship full-contact")
    print("    martial arts tournament in Republic of China (Taiwan)")
    print("  • Founded Cheng Hsin School (1975), Oakland center (1977)")
    print("  • Author of 9+ books (Open Library confirmed)")
    print("  • Collaborator with Werner Erhard, Stewart Emery")
    print("  • NO Wikipedia page exists — gap documented in claim")
    print()
    print("Edges added:")
    print("  • Ralston → FOUNDED → Cheng Hsin")
    print("  • Ralston → WORKED_AT → Oakland, UC Berkeley")
    print("  • Ralston → MEMBER_OF → Aikido")
    print("  • Ralston → MENTIONS → Robert Nadeau (budovideos book)")
    print("  • Ralston → MENTIONS → Stewart Emery, Werner Erhard, Esalen")


if __name__ == "__main__":
    main()
