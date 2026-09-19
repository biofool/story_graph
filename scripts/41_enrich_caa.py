#!/usr/bin/env python3
"""
Enrich the California Aikido Association (CAA) node with sourced historical
details and add the precursor organizations (AANC, Northern California
Yudansha Kai) to the story graph.

Sources:
- https://ai-ki-do.org/about-the-caa (CAA official about page)
- https://maytt.home.blog/2020/07/15/interview-with-aikido-shihan-bill-witt-the-early-days-of-aikido-in-northern-california/ (Bill Witt interview)
- https://aikidojournal.com/2025/05/12/a-journey-through-aikido-robert-nadeau-on-spirituality-o-sensei-and-the-golden-age-of-aikido-in-california/ (Aikido Journal)

Usage:
    python scripts/41_enrich_caa.py
    python scripts/41_enrich_caa.py --dry-run
"""

import argparse
import hashlib
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.storage.graph_db import GraphDB
from src.storage.json_export import export_to_json, import_from_json
from src.storage.models import (
    BiasHint,
    ClaimSourceLink,
    ClaimStance,
    ClaimType,
    EvidenceMode,
    GraphEdge,
    GraphNode,
    NodeType,
    RelationType,
    SourceClass,
    SourceRecord,
)

CAA_ABOUT_URL = "https://ai-ki-do.org/about-the-caa"
CAA_MAIN_URL = "https://ai-ki-do.org/"
WITT_INTERVIEW_URL = "https://maytt.home.blog/2020/07/15/interview-with-aikido-shihan-bill-witt-the-early-days-of-aikido-in-northern-california/"
AJ_NADEAU_JOURNEY_URL = "https://aikidojournal.com/2025/05/12/a-journey-through-aikido-robert-nadeau-on-spirituality-o-sensei-and-the-golden-age-of-aikido-in-california/"


def make_id(prefix: str, text: str) -> str:
    h = hashlib.sha256(text.encode()).hexdigest()[:16]
    return f"{prefix}:{h}"


def enrich_caa(db: GraphDB, dry_run: bool = False) -> dict:
    stats = {"nodes": 0, "edges": 0, "claims": 0, "sources": 0, "claim_sources": 0}

    # --- Source records ---

    sources = [
        SourceRecord(
            id="source:caa-about-page",
            url=CAA_ABOUT_URL,
            title="About the CAA — California Aikido Association",
            author="California Aikido Association",
            platform="ai-ki-do.org",
            raw_text=(
                "The Aikido of Northern California Yudansha Kai was organized "
                "in 1974 by black belt holders dedicated to the task of "
                "exploring the path shown by Master Ueshiba, and to teaching "
                "Aikido philosophy and techniques to all those who wished to "
                "follow. In 1980, the name of the Yudansha Kai was changed to "
                "Aikido Association of Northern California (AANC) to take "
                "into consideration the many people represented by the "
                "association who are not black belt holders. By 2001 the AANC "
                "had evolved into 3 divisions and had grown to over 100 "
                "member dojos. The California Aikido Association (CAA) was "
                "formed in 2002, from a majority of the AANC membership, "
                "based upon the principle of training together in friendship "
                "with a minimum of formal organizational structure. The CAA "
                "is an officially recognized organization by the Aikikai "
                "Foundation, Hombu Dojo, Tokyo, Japan."
            ),
            source_class=SourceClass.JOURNALISTIC,
            bias_hint=BiasHint.NEUTRAL_ISH,
        ),
        SourceRecord(
            id="source:witt-interview-norcal-aikido",
            url=WITT_INTERVIEW_URL,
            title="Interview with Aikido Shihan Bill Witt: The Early Days of Aikido in Northern California",
            author="Martial Arts of Yesterday, Today and Tomorrow",
            platform="maytt.home.blog",
            raw_text=(
                "Bill Witt describes the formation of the Aikido of Northern "
                "California Yudansha Kai in 1974 after the Founder passed "
                "away and there was a leadership vacuum in California. Rod "
                "Kobayashi Sensei was connected with Tohei Sensei and senior "
                "to all in California in rank. In 1974 Tohei Sensei left the "
                "Aikikai; Kobayashi Sensei went with him. The Northern "
                "California Yudansha Kai banded together to develop a "
                "relationship with Aikido Hombu Dojo. In 1980 renamed to AANC. "
                "CAA formed in 2002."
            ),
            source_class=SourceClass.JOURNALISTIC,
            bias_hint=BiasHint.NEUTRAL_ISH,
        ),
    ]

    for s in sources:
        if not dry_run:
            db.add_source(s)
        stats["sources"] += 1

    # --- Enrich the existing CAA node with metadata ---

    caa_node = db.get_node("group:california-aikido-association")
    if caa_node:
        caa_node.metadata.update({
            "website": CAA_MAIN_URL,
            "about_page": CAA_ABOUT_URL,
            "formed": "2002",
            "predecessor": "Aikido Association of Northern California (AANC, 1980)",
            "predecessor_predecessor": "Aikido of Northern California Yudansha Kai (1974)",
            "recognition": "Officially recognized by the Aikikai Foundation, Hombu Dojo, Tokyo, Japan",
            "structure": "3 divisions, 100+ member dojos (as of 2001 AANC figures)",
            "sources": [CAA_ABOUT_URL, WITT_INTERVIEW_URL],
        })
        # Add the about page URL to source_urls
        if CAA_ABOUT_URL not in (caa_node.source_urls or []):
            caa_node.source_urls = list(caa_node.source_urls or []) + [CAA_ABOUT_URL, CAA_MAIN_URL]
        if not dry_run:
            db.add_node(caa_node)
        stats["nodes"] += 1  # enriched existing

    # --- New Group nodes: precursor organizations ---

    precursor_groups = [
        (
            "group:aikido-of-northern-california-yudansha-kai",
            "Aikido of Northern California Yudansha Kai",
            "Northern California Yudansha Kai",
            {
                "formed": "1974",
                "dissolved": "1980 (renamed to AANC)",
                "context": (
                    "Organized in 1974 by black belt holders after Morihei "
                    "Ueshiba's death created a leadership vacuum in "
                    "California. Banded together to develop a relationship "
                    "with Aikido Hombu Dojo."
                ),
                "sources": [CAA_ABOUT_URL, WITT_INTERVIEW_URL],
            },
        ),
        (
            "group:aikido-association-of-northern-california",
            "Aikido Association of Northern California",
            "AANC",
            {
                "formed": "1980",
                "dissolved": "2002 (majority became CAA)",
                "context": (
                    "Renamed from Yudansha Kai in 1980 to include non-black-"
                    "belt holders. By 2001 had 3 divisions and 100+ member "
                    "dojos. CAA formed in 2002 from majority of AANC "
                    "membership."
                ),
                "sources": [CAA_ABOUT_URL, WITT_INTERVIEW_URL],
            },
        ),
    ]

    for node_id, label, canonical, metadata in precursor_groups:
        node = GraphNode(
            id=node_id,
            type=NodeType.GROUP,
            label=label,
            canonical_name=canonical,
            metadata=metadata,
            source_urls=[CAA_ABOUT_URL, WITT_INTERVIEW_URL],
        )
        if not dry_run:
            db.add_node(node)
        stats["nodes"] += 1

    # --- Claim nodes: sourced historical facts about CAA ---

    claims_data = [
        {
            "text": (
                "The California Aikido Association (CAA) was formed in 2002 "
                "from a majority of the Aikido Association of Northern "
                "California (AANC) membership, based upon the principle of "
                "training together in friendship with a minimum of formal "
                "organizational structure."
            ),
            "type": ClaimType.BIOGRAPHICAL,
            "stance": ClaimStance.NEUTRAL,
            "evidence_mode": EvidenceMode.SECONDARY_REPORT,
            "source_id": "source:caa-about-page",
        },
        {
            "text": (
                "The Aikido of Northern California Yudansha Kai was organized "
                "in 1974 by black belt holders after the death of Morihei "
                "Ueshiba created a leadership vacuum in California. In 1980 "
                "it was renamed to the Aikido Association of Northern "
                "California (AANC)."
            ),
            "type": ClaimType.BIOGRAPHICAL,
            "stance": ClaimStance.NEUTRAL,
            "evidence_mode": EvidenceMode.SECONDARY_REPORT,
            "source_id": "source:caa-about-page",
        },
        {
            "text": (
                "The CAA is an officially recognized organization by the "
                "Aikikai Foundation, Hombu Dojo, Tokyo, Japan."
            ),
            "type": ClaimType.BIOGRAPHICAL,
            "stance": ClaimStance.NEUTRAL,
            "evidence_mode": EvidenceMode.SECONDARY_REPORT,
            "source_id": "source:caa-about-page",
        },
        {
            "text": (
                "Rod Kobayashi Sensei was connected with Tohei Sensei and "
                "senior to all in California in rank. He would come up to "
                "teach occasionally. In 1974 when Tohei Sensei left the "
                "Aikikai, Kobayashi Sensei went with him, and the Northern "
                "California teachers banded together as the Yudansha Kai to "
                "develop a relationship with Aikido Hombu Dojo."
            ),
            "type": ClaimType.BIOGRAPHICAL,
            "stance": ClaimStance.NEUTRAL,
            "evidence_mode": EvidenceMode.SECONDARY_REPORT,
            "source_id": "source:witt-interview-norcal-aikido",
        },
        {
            "text": (
                "Robert Nadeau co-founded first the Aikido Association of "
                "Northern California (AANC), and then the California Aikido "
                "Association (CAA), which has grown into an international "
                "community of more than 100 affiliated dojos."
            ),
            "type": ClaimType.BIOGRAPHICAL,
            "stance": ClaimStance.SUPPORTIVE,
            "evidence_mode": EvidenceMode.SECONDARY_REPORT,
            "source_id": "source:caa-about-page",  # also from AJ Nadeau journey
        },
    ]

    claim_ids = []
    for cd in claims_data:
        claim_id = make_id("claim", cd["text"])
        claim_ids.append(claim_id)
        node = GraphNode(
            id=claim_id,
            type=NodeType.CLAIM,
            label=cd["text"][:120],
            metadata={
                "claim_text": cd["text"],
                "claim_type": cd["type"].value,
                "confidence": 0.85,
                "evidence_mode": cd["evidence_mode"].value,
                "stance": cd["stance"].value,
            },
            source_urls=[
                CAA_ABOUT_URL if cd["source_id"] == "source:caa-about-page"
                else WITT_INTERVIEW_URL
            ],
        )
        if not dry_run:
            db.add_node(node)
        stats["claims"] += 1
        stats["nodes"] += 1

        link = ClaimSourceLink(
            claim_id=claim_id,
            source_id=cd["source_id"],
        )
        if not dry_run:
            db.add_claim_source_link(link)
        stats["claim_sources"] += 1

    # --- Edges: connect claims to groups/people ---

    edges_data = [
        # Claim 0: CAA formed 2002 from AANC
        (0, RelationType.MENTIONS, "group:california-aikido-association"),
        (0, RelationType.MENTIONS, "group:aikido-association-of-northern-california"),
        # Claim 1: Yudansha Kai 1974 -> AANC 1980
        (1, RelationType.MENTIONS, "group:aikido-of-northern-california-yudansha-kai"),
        (1, RelationType.MENTIONS, "group:aikido-association-of-northern-california"),
        # Claim 2: CAA recognized by Aikikai
        (2, RelationType.MENTIONS, "group:california-aikido-association"),
        (2, RelationType.MENTIONS, "group:aikikai-hombu-dojo"),
        # Claim 3: Kobayashi, Tohei, Yudansha Kai
        (3, RelationType.MENTIONS, "person:rod-kobayashi"),
        (3, RelationType.MENTIONS, "person:koichi-tohei"),
        (3, RelationType.MENTIONS, "group:aikido-of-northern-california-yudansha-kai"),
        # Claim 4: Nadeau co-founded AANC and CAA
        (4, RelationType.MENTIONS, "person:robert-nadeau"),
        (4, RelationType.MENTIONS, "group:aikido-association-of-northern-california"),
        (4, RelationType.MENTIONS, "group:california-aikido-association"),
    ]

    for claim_idx, rel_type, dst_id in edges_data:
        edge = GraphEdge(
            src_id=claim_ids[claim_idx],
            rel_type=rel_type,
            dst_id=dst_id,
            metadata={"source": CAA_ABOUT_URL if claim_idx != 3 else WITT_INTERVIEW_URL},
        )
        if not dry_run:
            db.add_edge(edge)
        stats["edges"] += 1

    # --- Direct relationship edges ---

    # CAA PRECEDES nothing, but AANC PRECEDES CAA
    edge = GraphEdge(
        src_id="group:aikido-association-of-northern-california",
        rel_type=RelationType.PRECEDES,
        dst_id="group:california-aikido-association",
        metadata={"source": CAA_ABOUT_URL, "note": "AANC (1980) -> CAA (2002)"},
    )
    if not dry_run:
        db.add_edge(edge)
    stats["edges"] += 1

    # Yudansha Kai PRECEDES AANC
    edge = GraphEdge(
        src_id="group:aikido-of-northern-california-yudansha-kai",
        rel_type=RelationType.PRECEDES,
        dst_id="group:aikido-association-of-northern-california",
        metadata={"source": CAA_ABOUT_URL, "note": "Yudansha Kai (1974) -> AANC (1980)"},
    )
    if not dry_run:
        db.add_edge(edge)
    stats["edges"] += 1

    # Nadeau FOUNDED CAA (co-founded)
    edge = GraphEdge(
        src_id="person:robert-nadeau",
        rel_type=RelationType.FOUNDED,
        dst_id="group:california-aikido-association",
        metadata={
            "source": CAA_ABOUT_URL,
            "role": "co-founder, division head",
            "note": "Also from AJ: 'co-founded first the AANC, and then the CAA'",
        },
    )
    if not dry_run:
        db.add_edge(edge)
    stats["edges"] += 1

    # Nadeau FOUNDED AANC (co-founded)
    edge = GraphEdge(
        src_id="person:robert-nadeau",
        rel_type=RelationType.FOUNDED,
        dst_id="group:aikido-association-of-northern-california",
        metadata={
            "source": AJ_NADEAU_JOURNEY_URL,
            "role": "co-founder",
        },
    )
    if not dry_run:
        db.add_edge(edge)
    stats["edges"] += 1

    # CAA LOCATED_IN California
    edge = GraphEdge(
        src_id="group:california-aikido-association",
        rel_type=RelationType.LOCATED_IN,
        dst_id="place:california",
        metadata={"source": CAA_ABOUT_URL},
    )
    if not dry_run:
        db.add_edge(edge)
    stats["edges"] += 1

    return stats


def main():
    parser = argparse.ArgumentParser(
        description="Enrich the California Aikido Association with sourced historical details"
    )
    parser.add_argument("--db", default=None, help="Database path")
    parser.add_argument("--snapshot", default=None, help="Snapshot directory")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be added without writing")
    parser.add_argument("--no-export", action="store_true", help="Skip snapshot export")
    parser.add_argument("--no-rebuild", action="store_true", help="Don't rebuild DB from snapshot first")
    args = parser.parse_args()

    from config.settings import settings

    print()
    print("╔════════════════════════════════════════════════════════════════════╗")
    print("║  ENRICH CAA — California Aikido Association                       ║")
    print("╚════════════════════════════════════════════════════════════════════╝")
    print()

    db_path = args.db or str(settings.graph_db_abs_path)
    snapshot_dir = args.snapshot or str(settings.graph_snapshot_abs_dir)

    if args.no_rebuild:
        db = GraphDB(db_path)
    else:
        print("[1/3] Rebuilding DB from snapshot...")
        db = import_from_json(snapshot_dir, db_path)
        print(f"  Loaded: {db.get_node_count()} nodes")

    print(f"\n[2/3] Enriching CAA...")
    if args.dry_run:
        print("  [dry-run mode — no writes]")
    stats = enrich_caa(db, dry_run=args.dry_run)
    print(f"  Added/enriched: {stats['sources']} sources, {stats['nodes']} nodes "
          f"({stats['claims']} claims), {stats['edges']} edges, "
          f"{stats['claim_sources']} claim-source links")

    if not args.dry_run:
        print(f"  Graph now has {db.get_node_count()} nodes")

    if not args.dry_run and not args.no_export:
        print(f"\n[3/3] Exporting to snapshot...")
        counts = export_to_json(db, snapshot_dir)
        print(f"  Exported: {counts}")
    else:
        print(f"\n[3/3] Skipping export")

    print("\nDone.")


if __name__ == "__main__":
    main()
