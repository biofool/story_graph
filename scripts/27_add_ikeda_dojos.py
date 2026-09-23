#!/usr/bin/env python3
"""
Add dojos that Hiroshi Ikeda Shihan visited frequently as Dojo nodes in the
story graph, with DOJO_AFFILIATION edges to person:hiroshi-ikeda.

The school list was provided by the user (working on Ikeda's Wikipedia
article) and matched against WorldStudioFinder's pipeline.db. The normalized
records live in data/ikeda_visited_dojos.json, including match_type and
confidence so exact matches stay distinguishable from city/country leads.

Edge semantics (issue #65 — Kohala Aikikai refutation):
    * match_type "exact" — the user named this specific school; a
      DOJO_AFFILIATION edge with association="frequent_visited_teacher" is
      created (still evidence_status=unverified pending outreach).
    * match_type "variant" / "city_or_country_lead" — fuzzy name or
      geographic candidates only. A visit was never claimed for these, so NO
      DOJO_AFFILIATION edge is created. The Dojo node is still added (it is a
      real dojo with WSF provenance) and its match_type/confidence metadata
      records that it is only a lead.

The script also prunes stale person:hiroshi-ikeda DOJO_AFFILIATION edges for
lead records: GraphDB.add_edge is INSERT OR IGNORE, so re-running cannot
downgrade an edge written by the pre-fix version — the stale rows must be
deleted.

Kristina Varjan (owner, Kohala Aikikai, Kapaau HI) replied to outreach on
2026-09-24 stating Ikeda has never visited Kohala Aikikai. Her denial is
recorded as a first-party SourceRecord + Claim node (MENTIONS edges to
person:hiroshi-ikeda and the Big Island lead dojos) — see
add_varjan_denial().

Usage:
    python scripts/27_add_ikeda_dojos.py --dry-run
    python scripts/27_add_ikeda_dojos.py
"""

import argparse
import hashlib
import json
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

DATA_FILE = PROJECT_ROOT / "data" / "ikeda_visited_dojos.json"
SOURCE_URL = "worldstudiofinder:pipeline.db#studios_flat"

# Match types that may assert an actual visit. Everything else is a lead.
ASSERTIVE_MATCH_TYPES = {"exact"}

# Kristina Varjan's 2026-09-24 denial email (issue #65). Non-kkron personal
# communications follow the source:.../kkron://personal-communication/<slug>
# convention already used for source:kenneth-email-dobson-2026.
VARJAN_SOURCE_ID = "source:kristina-varjan-kohala-email-2026-09-24"
VARJAN_SOURCE_URL = "kkron://personal-communication/kristina-varjan-kohala-email"
VARJAN_CLAIM_TEXT = (
    "Kristina Varjan, owner of Kohala Aikikai (Kapaau, Big Island, HI), "
    "stated by email on 2026-09-24 that Hiroshi Ikeda Shihan has never "
    "visited Kohala Aikikai — refuting the claim that the dojo was one Ikeda "
    "visited frequently. She also stated she has no information on the other "
    "Big Island dojos listed (Kealamakani Aikido, Aikido of Hilo), which "
    "remain unconfirmed geographic leads."
)
VARJAN_CLAIM_ID = "claim:" + hashlib.sha256(VARJAN_CLAIM_TEXT.encode()).hexdigest()[:16]


def add_ikeda_dojos(db: GraphDB, dry_run: bool = False) -> dict:
    """Add Dojo nodes; DOJO_AFFILIATION edges only for exact matches."""
    stats = {"nodes": 0, "edges": 0, "leads": 0, "skipped": 0}

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

        if rec["match_type"] not in ASSERTIVE_MATCH_TYPES:
            # Lead only — a visit was never claimed for this dojo, so no
            # DOJO_AFFILIATION edge. The node's match_type/confidence
            # metadata marks it as an unconfirmed candidate.
            stats["leads"] += 1
            continue

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


def prune_lead_edges(db: GraphDB) -> int:
    """Delete stale Ikeda DOJO_AFFILIATION edges for non-exact records.

    Pre-fix runs wrote association="frequent_visited_teacher" edges for every
    record including leads; add_edge is INSERT OR IGNORE so it cannot remove
    or downgrade them — they must be deleted explicitly. Only edges pointing
    at dojo ids present in the data file as non-exact are touched.
    """
    records = json.loads(DATA_FILE.read_text(encoding="utf-8"))
    person_id = records["person_id"]
    lead_ids = [
        rec["id"]
        for rec in records["dojos"]
        if rec["match_type"] not in ASSERTIVE_MATCH_TYPES
    ]
    if not lead_ids:
        return 0
    cur = db._conn.execute(
        "DELETE FROM edges WHERE src_id = ? AND rel_type = ? "
        f"AND dst_id IN ({','.join('?' * len(lead_ids))})",
        (person_id, RelationType.DOJO_AFFILIATION.value, *lead_ids),
    )
    db._conn.commit()
    return cur.rowcount


def add_varjan_denial(db: GraphDB, dry_run: bool = False) -> dict:
    """Record Kristina Varjan's 2026-09-24 denial (issue #65) as evidence.

    Adds a first-party SourceRecord for her email and a Claim node carrying
    the denial, linked via claim_sources and MENTIONS edges to the entities
    it concerns. The refuted DOJO_AFFILIATION edge itself is removed by
    prune_lead_edges().
    """
    stats = {"sources": 0, "claims": 0, "edges": 0, "claim_sources": 0}

    source = SourceRecord(
        id=VARJAN_SOURCE_ID,
        url=VARJAN_SOURCE_URL,
        title="Kristina Varjan (Kohala Aikikai) email re: Ikeda visit claim (2026-09-24, received by kkron)",
        author="Kristina Varjan",
        publish_date="2026-09-24",
        platform="personal_communication",
        raw_text=(
            "Hiroshi Ikeda Shihan has never visited our dojo. Not sure who "
            "gave you this information but it's incorrect. Also, I do not "
            "have any information on the dojo's you have listed below. "
            "Wishing you luck with your continuing search for your project. "
            "Best, Kristina Varjan kvarjan@gmail.com"
        ),
        source_class=SourceClass.PRIMARY_FIRST_PERSON,
        bias_hint=BiasHint.NEUTRAL_ISH,
    )
    if not dry_run:
        db.add_source(source)
    stats["sources"] = 1

    claim = GraphNode(
        id=VARJAN_CLAIM_ID,
        type=NodeType.CLAIM,
        label=VARJAN_CLAIM_TEXT[:120],
        metadata={
            "claim_text": VARJAN_CLAIM_TEXT,
            "claim_type": ClaimType.HISTORICAL_DISPUTE.value,
            "confidence": 1.0,
            "evidence_mode": EvidenceMode.FIRST_PERSON.value,
            "stance": ClaimStance.CRITICAL.value,
            "asserted_by": "kristina-varjan",
            "refutes": "person:hiroshi-ikeda frequent_visited_teacher of dojo:kohala-aikikai",
        },
        source_urls=[VARJAN_SOURCE_URL],
    )
    if not dry_run:
        db.add_node(claim)
        db.add_claim_source_link(
            ClaimSourceLink(claim_id=VARJAN_CLAIM_ID, source_id=VARJAN_SOURCE_ID)
        )
    stats["claims"] = 1
    stats["claim_sources"] = 1

    for dst_id in (
        "person:hiroshi-ikeda",
        "dojo:kohala-aikikai",
        "dojo:kealamakani-aikido",
        "dojo:aikido-of-hilo",
    ):
        edge = GraphEdge(
            src_id=VARJAN_CLAIM_ID,
            rel_type=RelationType.MENTIONS,
            dst_id=dst_id,
            metadata={"asserted_by": "kristina-varjan", "source": VARJAN_SOURCE_URL},
        )
        if not dry_run:
            db.add_edge(edge)
        stats["edges"] += 1

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
        print(f"  Lead-only records (node, no edge): {stats['leads']}")
        print(f"  Unmatched requests (no node): {stats['skipped']}")
        vstats = add_varjan_denial(None, dry_run=True)
        print(f"  Varjan denial: {vstats['claims']} claim, {vstats['edges']} MENTIONS edges")
        return

    print("[1/3] Rebuilding DB from snapshot and adding nodes/edges...")
    if args.no_rebuild:
        db = GraphDB(db_path)
    else:
        db = import_from_json(snapshot_dir, db_path)

    stats = add_ikeda_dojos(db)
    print(f"  Added: {stats['nodes']} dojo nodes, {stats['edges']} edges")
    print(f"  Lead-only records (node, no edge): {stats['leads']}")
    print(f"  Unmatched requests (no node): {stats['skipped']}")

    pruned = prune_lead_edges(db)
    print(f"  Pruned stale lead DOJO_AFFILIATION edges: {pruned}")

    print("\n[2/3] Recording Varjan denial (issue #65)...")
    vstats = add_varjan_denial(db)
    print(f"  Added: {vstats['sources']} source, {vstats['claims']} claim, "
          f"{vstats['edges']} MENTIONS edges")

    print(f"  Graph now has {db.get_node_count()} nodes")

    if not args.no_export:
        print("\n[3/3] Exporting to snapshot...")
        counts = export_to_json(db, snapshot_dir)
        print(f"  Exported: {counts}")
    else:
        print("\n[3/3] Skipping export (--no-export)")

    print("\nDone.")


if __name__ == "__main__":
    main()
