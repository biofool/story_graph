#!/usr/bin/env python3
"""
Add kkron's assertions about the origins of the Mountain View dojo and the
California Aikido Association to the story graph.

Per AGENTS.md, kkron's assertions are first-class evidence and go into the
graph by default. These assertions document:

1. The Mountain View dojo was NOT started by Sig Kufferath and Robert Nadeau.
   It opened while Nadeau was still in Japan. It was started by Sig Kufferath
   and Ed Riggs (a retired army officer who studied Aikido in Japan while
   stationed there). Ed Dressen provided the financing to get the school
   started.
2. After the school was in operation, Nadeau Sensei returned from Japan and
   became head Aikido instructor. Sig and Ed Riggs continued to teach even
   after Nadeau Sensei came on the scene.
3. The California Aikido Association was already in existence before Nadeau
   Sensei's return from Japan. It was headquartered in Southern California
   and led (at least in kkron's time with it) by Rod Kobayashi and Clem
   Yoshida, both Southern California teachers. They came up from LA and
   administered kkron's Shodan test in 1969.
4. The Association may have been started by Isao Takahashi, who had
   relocated to LA from Hawaii and then moved to Chicago.
5. Ed Riggs retired from teaching shortly before kkron left for the East
   Coast in 1970.

These assertions partially CONTRADICT the Wikipedia article on Robert Nadeau,
which states Nadeau "opened a series of martial art schools sharing space
with first Professor Sig Kuferat and later Richard Bunch." kkron's account
indicates the dojo was already operating before Nadeau returned from Japan,
and was co-founded by Kufferath, Ed Riggs, and Ed Dressen — not Nadeau.

Usage:
    python scripts/40_add_kkron_dojo_origins.py
    python scripts/40_add_kkron_dojo_origins.py --dry-run
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

# kkron source identifiers (per AGENTS.md)
KKRON_PLATFORM = "kkron (personal communication)"
KKRON_SOURCE_URL = "kkron://personal-communication/dojo-origins-caa"
KKRON_SOURCE_ID = "kkron:dojo-origins-caa-research"


def make_id(prefix: str, text: str) -> str:
    """Generate a stable ID from a text string."""
    h = hashlib.sha256(text.encode()).hexdigest()[:16]
    return f"{prefix}:{h}"


def add_kkron_assertions(db: GraphDB, dry_run: bool = False) -> dict:
    """Add kkron's assertions about the Mountain View dojo origins and CAA."""

    stats = {"nodes": 0, "edges": 0, "claims": 0, "sources": 0, "claim_sources": 0}

    # --- Source record ---

    kkron_source = SourceRecord(
        id=KKRON_SOURCE_ID,
        url=KKRON_SOURCE_URL,
        title="Mountain View dojo origins and California Aikido Association history (kkron personal communication)",
        author="kkron",
        platform=KKRON_PLATFORM,
        raw_text=(
            "kkron's first-person account of the founding of the Mountain View "
            "dojo and the early history of the California Aikido Association. "
            "Key points: (1) The Mountain View dojo was started by Sig "
            "Kufferath and Ed Riggs (retired army officer who studied Aikido "
            "in Japan), with Ed Dressen providing financing. It opened while "
            "Nadeau was still in Japan. (2) Nadeau returned from Japan and "
            "became head Aikido instructor; Sig and Ed Riggs continued to "
            "teach. (3) The California Aikido Association was already in "
            "existence before Nadeau's return, headquartered in Southern "
            "California, led by Rod Kobayashi and Clem Yoshida. They "
            "administered kkron's Shodan test in 1969. (4) The Association "
            "may have been started by Isao Takahashi. (5) Ed Riggs retired "
            "from teaching shortly before kkron left for the East Coast in "
            "1970."
        ),
        source_class=SourceClass.PRIMARY_FIRST_PERSON,
        bias_hint=BiasHint.NEUTRAL_ISH,
    )

    if not dry_run:
        db.add_source(kkron_source)
    stats["sources"] = 1

    # --- New Person nodes (Ed Riggs, Rod Kobayashi, Clem Yoshida, Isao Takahashi) ---

    new_persons = [
        ("person:ed-riggs", "Ed Riggs", "Edward Riggs"),
        ("person:rod-kobayashi", "Rod Kobayashi", "Roderick T. Kobayashi"),
        ("person:clem-yoshida", "Clem Yoshida", "Clem Yoshida"),
        ("person:isao-takahashi", "Isao Takahashi", "Isao Takahashi"),
    ]

    for node_id, label, canonical in new_persons:
        node = GraphNode(
            id=node_id,
            type=NodeType.PERSON,
            label=label,
            canonical_name=canonical,
            metadata={"asserted_by": "kkron"},
            source_urls=[KKRON_SOURCE_URL],
        )
        if not dry_run:
            db.add_node(node)
        stats["nodes"] += 1

    # --- New Group node: California Aikido Federation (pre-CAA organization) ---
    # The Aikido Journal source refers to "California Aikido Federation" led
    # by Kobayashi, which may be the precursor organization kkron refers to
    # as the "California Aikido Association" that existed before Nadeau's
    # return. The current CAA (ai-ki-do.org) was formed in 2002 from the AANC.
    # kkron may be referring to an earlier organization with a similar name.

    caf_node = GraphNode(
        id="group:california-aikido-federation",
        type=NodeType.GROUP,
        label="California Aikido Federation (pre-1974)",
        canonical_name="California Aikido Federation",
        metadata={
            "asserted_by": "kkron",
            "note": (
                "kkron refers to the 'California Aikido Association' being "
                "already in existence before Nadeau's return from Japan, "
                "headquartered in Southern California. The Aikido Journal "
                "entry for Rod Kobayashi refers to the 'California Aikido "
                "Federation' which he led through 1974. This may be the same "
                "or a precursor organization. The current CAA (ai-ki-do.org) "
                "was formed in 2002 from the AANC (1980), which was preceded "
                "by the Northern California Yudansha Kai (1974)."
            ),
        },
        source_urls=[KKRON_SOURCE_URL],
    )
    if not dry_run:
        db.add_node(caf_node)
    stats["nodes"] += 1

    # --- Claim nodes ---

    claims_data = [
        {
            "text": (
                "The Mountain View dojo was not started by Sig Kufferath and "
                "Robert Nadeau. It opened while Nadeau was still in Japan. "
                "It was started by Sig Kufferath and Ed Riggs, who was a "
                "retired army officer who studied Aikido in Japan while he "
                "was stationed there. Also involved was Ed Dressen who "
                "provided the financing to get the school started."
            ),
            "type": ClaimType.BIOGRAPHICAL,
            "stance": ClaimStance.CRITICAL,
            "evidence_mode": EvidenceMode.FIRST_PERSON,
        },
        {
            "text": (
                "After the school was in operation, Nadeau Sensei returned "
                "from Japan and became head Aikido instructor. Sig and Ed "
                "Riggs continued to teach even after Nadeau Sensei came on "
                "the scene."
            ),
            "type": ClaimType.BIOGRAPHICAL,
            "stance": ClaimStance.NEUTRAL,
            "evidence_mode": EvidenceMode.FIRST_PERSON,
        },
        {
            "text": (
                "The California Aikido Association was already in existence "
                "even before Nadeau Sensei's return from Japan. It was "
                "headquartered in Southern California and led, at least in "
                "kkron's time with it, by Rod Kobayashi and Clem Yoshida, "
                "both Southern California teachers. They came up from LA "
                "and administered kkron's Shodan test in 1969."
            ),
            "type": ClaimType.BIOGRAPHICAL,
            "stance": ClaimStance.NEUTRAL,
            "evidence_mode": EvidenceMode.FIRST_PERSON,
        },
        {
            "text": (
                "The Association may have been started by Isao Takahashi, "
                "who had relocated to LA from Hawaii and then moved to "
                "Chicago."
            ),
            "type": ClaimType.BIOGRAPHICAL,
            "stance": ClaimStance.NEUTRAL,
            "evidence_mode": EvidenceMode.FIRST_PERSON,
        },
        {
            "text": "Ed Riggs retired from teaching shortly before kkron left for the East Coast in 1970.",
            "type": ClaimType.BIOGRAPHICAL,
            "stance": ClaimStance.NEUTRAL,
            "evidence_mode": EvidenceMode.FIRST_PERSON,
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
                "confidence": 0.9,
                "evidence_mode": cd["evidence_mode"].value,
                "stance": cd["stance"].value,
                "asserted_by": "kkron",
            },
            source_urls=[KKRON_SOURCE_URL],
        )
        if not dry_run:
            db.add_node(node)
        stats["claims"] += 1
        stats["nodes"] += 1

        # Link claim to kkron source
        link = ClaimSourceLink(
            claim_id=claim_id,
            source_id=KKRON_SOURCE_ID,
        )
        if not dry_run:
            db.add_claim_source_link(link)
        stats["claim_sources"] += 1

    # --- Edges: connect claims to the people/places/groups they mention ---

    edges_data = [
        # Claim 0: Dojo founding — Sig, Ed Riggs, Ed Dressen, Nadeau
        (0, RelationType.MENTIONS, "person:sig-kufferath"),
        (0, RelationType.MENTIONS, "person:ed-riggs"),
        (0, RelationType.MENTIONS, "person:ed-dressen"),
        (0, RelationType.MENTIONS, "person:robert-nadeau"),
        (0, RelationType.MENTIONS, "place:mountain-view"),
        (0, RelationType.MENTIONS, "group:nikko-jujitsu-school"),
        # Claim 1: Nadeau returned, became head instructor; Sig & Riggs continued
        (1, RelationType.MENTIONS, "person:robert-nadeau"),
        (1, RelationType.MENTIONS, "person:sig-kufferath"),
        (1, RelationType.MENTIONS, "person:ed-riggs"),
        (1, RelationType.MENTIONS, "place:mountain-view"),
        # Claim 2: CAA already existed, led by Kobayashi & Yoshida, Shodan test 1969
        (2, RelationType.MENTIONS, "group:california-aikido-federation"),
        (2, RelationType.MENTIONS, "group:california-aikido-association"),
        (2, RelationType.MENTIONS, "person:rod-kobayashi"),
        (2, RelationType.MENTIONS, "person:clem-yoshida"),
        (2, RelationType.MENTIONS, "person:robert-nadeau"),
        (2, RelationType.MENTIONS, "place:southern-california"),
        # Claim 3: Association may have been started by Takahashi
        (3, RelationType.MENTIONS, "group:california-aikido-federation"),
        (3, RelationType.MENTIONS, "person:isao-takahashi"),
        (3, RelationType.MENTIONS, "place:los-angeles"),
        # Claim 4: Ed Riggs retired ~1970
        (4, RelationType.MENTIONS, "person:ed-riggs"),
    ]

    for claim_idx, rel_type, dst_id in edges_data:
        edge = GraphEdge(
            src_id=claim_ids[claim_idx],
            rel_type=rel_type,
            dst_id=dst_id,
            metadata={"asserted_by": "kkron", "source": KKRON_SOURCE_URL},
        )
        if not dry_run:
            db.add_edge(edge)
        stats["edges"] += 1

    # --- Direct relationship edges ---

    # Ed Riggs WORKED_AT Mountain View dojo (co-founder, teacher)
    edge = GraphEdge(
        src_id="person:ed-riggs",
        rel_type=RelationType.WORKED_AT,
        dst_id="place:mountain-view",
        metadata={
            "asserted_by": "kkron",
            "role": "co-founder and teacher",
            "source": KKRON_SOURCE_URL,
            "era": "pre-1970",
        },
    )
    if not dry_run:
        db.add_edge(edge)
    stats["edges"] += 1

    # Ed Riggs MEMBER_OF Nikko Ju Jitsu School (co-founder)
    edge = GraphEdge(
        src_id="person:ed-riggs",
        rel_type=RelationType.MEMBER_OF,
        dst_id="group:nikko-jujitsu-school",
        metadata={
            "asserted_by": "kkron",
            "role": "co-founder",
            "source": KKRON_SOURCE_URL,
        },
    )
    if not dry_run:
        db.add_edge(edge)
    stats["edges"] += 1

    # Ed Dressen MEMBER_OF Nikko Ju Jitsu School (financier/founder)
    edge = GraphEdge(
        src_id="person:ed-dressen",
        rel_type=RelationType.MEMBER_OF,
        dst_id="group:nikko-jujitsu-school",
        metadata={
            "asserted_by": "kkron",
            "role": "financier/co-founder",
            "source": KKRON_SOURCE_URL,
        },
    )
    if not dry_run:
        db.add_edge(edge)
    stats["edges"] += 1

    # Rod Kobayashi MEMBER_OF California Aikido Federation (leader)
    edge = GraphEdge(
        src_id="person:rod-kobayashi",
        rel_type=RelationType.MEMBER_OF,
        dst_id="group:california-aikido-federation",
        metadata={
            "asserted_by": "kkron",
            "role": "leader (with Clem Yoshida)",
            "source": KKRON_SOURCE_URL,
            "era": "1960s",
        },
    )
    if not dry_run:
        db.add_edge(edge)
    stats["edges"] += 1

    # Clem Yoshida MEMBER_OF California Aikido Federation (leader)
    edge = GraphEdge(
        src_id="person:clem-yoshida",
        rel_type=RelationType.MEMBER_OF,
        dst_id="group:california-aikido-federation",
        metadata={
            "asserted_by": "kkron",
            "role": "leader (with Rod Kobayashi)",
            "source": KKRON_SOURCE_URL,
            "era": "1960s",
        },
    )
    if not dry_run:
        db.add_edge(edge)
    stats["edges"] += 1

    # Isao Takahashi FOUNDED California Aikido Federation (possible founder)
    edge = GraphEdge(
        src_id="person:isao-takahashi",
        rel_type=RelationType.FOUNDED,
        dst_id="group:california-aikido-federation",
        metadata={
            "asserted_by": "kkron",
            "note": "kkron says 'may have been started by' — expressed uncertainty",
            "source": KKRON_SOURCE_URL,
        },
    )
    if not dry_run:
        db.add_edge(edge)
    stats["edges"] += 1

    # Nadeau WORKED_AT Mountain View dojo (head Aikido instructor, after return)
    edge = GraphEdge(
        src_id="person:robert-nadeau",
        rel_type=RelationType.WORKED_AT,
        dst_id="place:mountain-view",
        metadata={
            "asserted_by": "kkron",
            "role": "head Aikido instructor (after return from Japan, post-1964)",
            "source": KKRON_SOURCE_URL,
        },
    )
    if not dry_run:
        db.add_edge(edge)
    stats["edges"] += 1

    return stats


def main():
    parser = argparse.ArgumentParser(
        description="Add kkron's assertions about Mountain View dojo origins and CAA history"
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
    print("║  ADD KKRON ASSERTIONS — Dojo Origins & CAA History                 ║")
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

    print(f"\n[2/3] Adding kkron assertions...")
    if args.dry_run:
        print("  [dry-run mode — no writes]")
    stats = add_kkron_assertions(db, dry_run=args.dry_run)
    print(f"  Added: {stats['sources']} sources, {stats['nodes']} nodes "
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
