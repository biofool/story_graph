#!/usr/bin/env python3
"""
Add kkron's assertions about the Kufferath-Nadeau-Bunch connection to the
story graph.

Per AGENTS.md, kkron's assertions are first-class evidence and go into the
graph by default. These assertions document:

1. Sig Kufferath and Robert Nadeau shared dojo space at 194-198 Castro St,
   Mountain View (the Jurian Building) starting ~1966.
2. Richard Bunch was the operational link between Nadeau's Aikido and
   Kufferath's Danzan Ryu Jujitsu communities.
3. Bunch trained under Kufferath as a teenager, became Chief Instructor at
   the Nikko Ju Jitsu School in San Jose.
4. Nadeau later shared space with Bunch (not Kufferath directly) as the
   schools expanded.
5. This alliance led to the formation of the California Aikido Association
   (CAA), where Nadeau became a central division head.
6. The Wikipedia article draft for Sig Kufferath (biographical summary).

Usage:
    python scripts/18_add_kkron_assertions.py
    python scripts/18_add_kkron_assertions.py --dry-run
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

# kkron source identifiers (per AGENTS.md)
KKRON_PLATFORM = "kkron (personal communication)"
KKRON_SOURCE_URL = "kkron://personal-communication/kufferath-nadeau-bunch"
KKRON_SOURCE_ID = "kkron:kufferath-nadeau-bunch-research"
WIKI_DRAFT_SOURCE_URL = "kkron://wikipedia-draft/sig-kufferath"
WIKI_DRAFT_SOURCE_ID = "kkron:wikipedia-draft-sig-kufferath"


def make_id(prefix: str, text: str) -> str:
    """Generate a stable ID from a text string."""
    h = hashlib.sha256(text.encode()).hexdigest()[:16]
    return f"{prefix}:{h}"


def add_kkron_assertions(db: GraphDB, dry_run: bool = False) -> dict:
    """Add kkron's assertions about the Kufferath-Nadeau-Bunch connection."""

    stats = {"nodes": 0, "edges": 0, "claims": 0, "sources": 0, "claim_sources": 0}

    # --- Source records ---

    # kkron's research summary (the ChatGPT conversation)
    kkron_source = SourceRecord(
        id=KKRON_SOURCE_ID,
        url=KKRON_SOURCE_URL,
        title="Kufferath-Nadeau-Bunch connection research (kkron personal communication)",
        author="kkron",
        platform=KKRON_PLATFORM,
        raw_text=(
            "Research summary documenting the historical connection between "
            "Prof. Sig Kufferath (Danzan Ryu Jujitsu) and Robert Nadeau "
            "(Aikido) in Northern California. Key findings: (1) Nadeau and "
            "Kufferath shared dojo space at 194-198 Castro St, Mountain View "
            "(the Jurian Building) starting ~1966. (2) Richard Bunch was the "
            "operational link between the two communities. (3) Bunch trained "
            "under Kufferath as a teenager, became Chief Instructor at Nikko "
            "Ju Jitsu School in San Jose. (4) Nadeau later shared space with "
            "Bunch as schools expanded. (5) This alliance led to the "
            "formation of the California Aikido Association (CAA)."
        ),
        source_class=SourceClass.PRIMARY_FIRST_PERSON,
        bias_hint=BiasHint.NEUTRAL_ISH,
    )

    # Wikipedia article draft for Sig Kufferath
    wiki_draft_source = SourceRecord(
        id=WIKI_DRAFT_SOURCE_ID,
        url=WIKI_DRAFT_SOURCE_URL,
        title="Wikipedia article draft: Siegfried Kufferath (kkron)",
        author="kkron",
        platform=KKRON_PLATFORM,
        raw_text=(
            "Wikipedia article draft for Siegfried 'Sig' Kufferath "
            "(February 16, 1911 - 1999), German-Japanese martial artist and "
            "physical therapist, grandmaster (Shihan) of Danzan-ryu Jujitsu, "
            "head of the American Jujitsu Institute. Born in Honolulu, Hawaii, "
            "one of eleven children, German/Japanese descent. Began studying "
            "Danzan-ryu under Seishiro Henry Okazaki in 1937 at the Kodenkan "
            "dojo in Honolulu. Earned black belt May 1941. Opened his own "
            "school 1942. Instructed Honolulu Police and US military during "
            "WWII. Succeeded Okazaki as head of AJI in 1951. Relocated to "
            "California 1960, opened Nikko Kodenkan in Mountain View. "
            "Cross-trained in Judo (Nidan) and Aikido (Nidan). Joined AJJF "
            "1983, awarded Shihan 1988. Co-founded Kodenkan Danzan Ryu "
            "Jujitsu Association and Kilohana Martial Arts Association. "
            "Mastered Seifukujutsu (Japanese restoration therapy) from "
            "Okazaki's Nikko Restoration Sanatorium."
        ),
        source_class=SourceClass.PRIMARY_FIRST_PERSON,
        bias_hint=BiasHint.NEUTRAL_ISH,
    )

    if not dry_run:
        db.add_source(kkron_source)
        db.add_source(wiki_draft_source)
    stats["sources"] = 2

    # --- Key Person nodes (ensure they exist) ---
    # These may already exist from the crawled pages, but we upsert to be safe.

    persons = [
        ("person:sig-kufferath", "Sig Kufferath", "Siegfried Kufferath"),
        ("person:robert-nadeau", "Robert Nadeau", "Robert Nadeau"),
        ("person:richard-bunch", "Richard Bunch", "Richard Bunch"),
        ("person:henry-seishiro-okazaki", "Henry Seishiro Okazaki", "Seishiro Henry Okazaki"),
    ]

    for node_id, label, canonical in persons:
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

    # --- Place node: the Jurian Building / Castro St dojo ---

    place_node = GraphNode(
        id="place:castro-st-mountain-view-jurian-building",
        type=NodeType.PLACE,
        label="194-198 Castro Street, Mountain View, CA (Jurian Building)",
        canonical_name="Castro Street Dojo, Mountain View",
        metadata={
            "address": "194-198 Castro Street, Mountain View, CA 94041",
            "building": "Jurian Building",
            "era": "1960s",
            "asserted_by": "kkron",
        },
        source_urls=[KKRON_SOURCE_URL],
    )
    if not dry_run:
        db.add_node(place_node)
    stats["nodes"] += 1

    # --- Group nodes ---

    groups = [
        ("group:california-aikido-association", "California Aikido Association", "CAA"),
        ("group:nikko-jujitsu-school", "Nikko Ju Jitsu School", "Nikko Jujitsu"),
        ("group:american-jujitsu-institute", "American Jujitsu Institute", "AJI"),
        ("group:kodenkan", "Kodenkan", "Kodenkan Dojo"),
    ]

    for node_id, label, canonical in groups:
        node = GraphNode(
            id=node_id,
            type=NodeType.GROUP,
            label=label,
            canonical_name=canonical,
            metadata={"asserted_by": "kkron"},
            source_urls=[KKRON_SOURCE_URL],
        )
        if not dry_run:
            db.add_node(node)
        stats["nodes"] += 1

    # --- Claim nodes ---

    claims_data = [
        {
            "text": "Robert Nadeau and Sig Kufferath shared dojo space at 194-198 Castro Street, Mountain View (the Jurian Building) starting around 1966, when Nadeau returned from Japan after training under Morihei Ueshiba.",
            "type": ClaimType.BIOGRAPHICAL,
            "stance": ClaimStance.NEUTRAL,
            "evidence_mode": EvidenceMode.FIRST_PERSON,
        },
        {
            "text": "Because they operated out of the same facility on Castro Street, Kufferath and Nadeau met frequently and cross-pollinated their respective martial arts knowledge, allowing Aikido and Danzan Ryu Jujitsu students to interact closely.",
            "type": ClaimType.BIOGRAPHICAL,
            "stance": ClaimStance.NEUTRAL,
            "evidence_mode": EvidenceMode.FIRST_PERSON,
        },
        {
            "text": "Richard Bunch was the operational link between Robert Nadeau's Aikido and Sig Kufferath's Danzan Ryu Jujitsu communities in Northern California.",
            "type": ClaimType.BIOGRAPHICAL,
            "stance": ClaimStance.SUPPORTIVE,
            "evidence_mode": EvidenceMode.FIRST_PERSON,
        },
        {
            "text": "Richard Bunch began training under Professor Kufferath as a teenager and became Kufferath's Associate and Chief Instructor at the Nikko Ju Jitsu School in San Jose, California.",
            "type": ClaimType.BIOGRAPHICAL,
            "stance": ClaimStance.NEUTRAL,
            "evidence_mode": EvidenceMode.SECONDARY_REPORT,
        },
        {
            "text": "When Nadeau expanded his schools, he transitioned from sharing space with Kufferath directly to sharing space with Richard Bunch.",
            "type": ClaimType.BIOGRAPHICAL,
            "stance": ClaimStance.NEUTRAL,
            "evidence_mode": EvidenceMode.FIRST_PERSON,
        },
        {
            "text": "Through the tight-knit working relationship with Richard Bunch, Nadeau maintained ongoing contact with several major Ju-Jitsu schools, which directly led to the landmark formation of the California Aikido Association (CAA), where Nadeau became a central division head.",
            "type": ClaimType.BIOGRAPHICAL,
            "stance": ClaimStance.SUPPORTIVE,
            "evidence_mode": EvidenceMode.FIRST_PERSON,
        },
        {
            "text": "Sig Kufferath was born on February 16, 1911 in Honolulu, Hawaii, one of eleven children, of German/Japanese descent. His father served as a German consulate official to Japan and his mother was Japanese. As many as eleven languages were spoken in the household.",
            "type": ClaimType.BIOGRAPHICAL,
            "stance": ClaimStance.NEUTRAL,
            "evidence_mode": EvidenceMode.SECONDARY_REPORT,
        },
        {
            "text": "Kufferath began studying Danzan-ryu Jujitsu under Seishiro Henry Okazaki in 1937 at the Kodenkan dojo in Honolulu. Because Kufferath was fluent in Japanese, Okazaki taught him the complete system in Japanese. He trained six days a week and earned his black belt in May 1941.",
            "type": ClaimType.BIOGRAPHICAL,
            "stance": ClaimStance.NEUTRAL,
            "evidence_mode": EvidenceMode.SECONDARY_REPORT,
        },
        {
            "text": "Following Okazaki's death in 1951, Kufferath was promoted to Shichidan (7th degree black belt) and named Professor by the American Jujitsu Institute. He was elected to succeed Okazaki as head of the AJI.",
            "type": ClaimType.BIOGRAPHICAL,
            "stance": ClaimStance.NEUTRAL,
            "evidence_mode": EvidenceMode.SECONDARY_REPORT,
        },
        {
            "text": "Kufferath relocated to California in 1960 and opened the Nikko Kodenkan dojo in Mountain View. He cross-trained in Judo (Nidan, 1956) and Aikido (Nidan, 1965).",
            "type": ClaimType.BIOGRAPHICAL,
            "stance": ClaimStance.NEUTRAL,
            "evidence_mode": EvidenceMode.SECONDARY_REPORT,
        },
        {
            "text": "Kufferath joined the American Judo & Jujitsu Federation (AJJF) in 1983, which awarded him the title of Shihan in 1988. He co-founded the Kodenkan Danzan Ryu Jujitsu Association and the Kilohana Martial Arts Association.",
            "type": ClaimType.BIOGRAPHICAL,
            "stance": ClaimStance.NEUTRAL,
            "evidence_mode": EvidenceMode.SECONDARY_REPORT,
        },
        {
            "text": "Kufferath graduated from Okazaki's Nikko Restoration Sanatorium, mastering Seifukujutsu (Japanese physical therapy, adjustment, and restorative arts). He maintained an active practice and taught these healing arts alongside jujitsu until shortly before his death in 1999.",
            "type": ClaimType.BIOGRAPHICAL,
            "stance": ClaimStance.NEUTRAL,
            "evidence_mode": EvidenceMode.SECONDARY_REPORT,
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

    # Claim 0: Nadeau & Kufferath shared dojo space at Castro St
    edges_data = [
        # (claim_idx, rel_type, dst_id) — claim MENTIONS person/place
        (0, RelationType.MENTIONS, "person:sig-kufferath"),
        (0, RelationType.MENTIONS, "person:robert-nadeau"),
        (0, RelationType.MENTIONS, "place:castro-st-mountain-view-jurian-building"),
        # Claim 1: cross-pollination at Castro St
        (1, RelationType.MENTIONS, "person:sig-kufferath"),
        (1, RelationType.MENTIONS, "person:robert-nadeau"),
        (1, RelationType.MENTIONS, "place:castro-st-mountain-view-jurian-building"),
        # Claim 2: Bunch was the operational link
        (2, RelationType.MENTIONS, "person:richard-bunch"),
        (2, RelationType.MENTIONS, "person:robert-nadeau"),
        (2, RelationType.MENTIONS, "person:sig-kufferath"),
        # Claim 3: Bunch trained under Kufferath, Chief Instructor at Nikko
        (3, RelationType.MENTIONS, "person:richard-bunch"),
        (3, RelationType.MENTIONS, "person:sig-kufferath"),
        (3, RelationType.MENTIONS, "group:nikko-jujitsu-school"),
        # Claim 4: Nadeau shared space with Bunch
        (4, RelationType.MENTIONS, "person:robert-nadeau"),
        (4, RelationType.MENTIONS, "person:richard-bunch"),
        (4, RelationType.MENTIONS, "person:sig-kufferath"),
        # Claim 5: CAA formation
        (5, RelationType.MENTIONS, "person:robert-nadeau"),
        (5, RelationType.MENTIONS, "person:richard-bunch"),
        (5, RelationType.MENTIONS, "group:california-aikido-association"),
        # Claim 6: Kufferath birth/early life
        (6, RelationType.MENTIONS, "person:sig-kufferath"),
        # Claim 7: Kufferath studied under Okazaki
        (7, RelationType.MENTIONS, "person:sig-kufferath"),
        (7, RelationType.MENTIONS, "person:henry-seishiro-okazaki"),
        (7, RelationType.MENTIONS, "group:kodenkan"),
        # Claim 8: Kufferath succeeded Okazaki
        (8, RelationType.MENTIONS, "person:sig-kufferath"),
        (8, RelationType.MENTIONS, "person:henry-seishiro-okazaki"),
        (8, RelationType.MENTIONS, "group:american-jujitsu-institute"),
        # Claim 9: Kufferath relocated to California
        (9, RelationType.MENTIONS, "person:sig-kufferath"),
        (9, RelationType.MENTIONS, "group:nikko-jujitsu-school"),
        # Claim 10: AJJF Shihan
        (10, RelationType.MENTIONS, "person:sig-kufferath"),
        # Claim 11: Seifukujutsu
        (11, RelationType.MENTIONS, "person:sig-kufferath"),
        (11, RelationType.MENTIONS, "person:henry-seishiro-okazaki"),
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

    # --- Direct relationship edges (not just MENTIONS) ---

    # Kufferath WORKED_AT Castro St dojo
    edge = GraphEdge(
        src_id="person:sig-kufferath",
        rel_type=RelationType.WORKED_AT,
        dst_id="place:castro-st-mountain-view-jurian-building",
        metadata={"asserted_by": "kkron", "source": KKRON_SOURCE_URL, "era": "1960s"},
    )
    if not dry_run:
        db.add_edge(edge)
    stats["edges"] += 1

    # Nadeau WORKED_AT Castro St dojo
    edge = GraphEdge(
        src_id="person:robert-nadeau",
        rel_type=RelationType.WORKED_AT,
        dst_id="place:castro-st-mountain-view-jurian-building",
        metadata={"asserted_by": "kkron", "source": KKRON_SOURCE_URL, "era": "1966+"},
    )
    if not dry_run:
        db.add_edge(edge)
    stats["edges"] += 1

    # Bunch MEMBER_OF Nikko Ju Jitsu School (Chief Instructor)
    edge = GraphEdge(
        src_id="person:richard-bunch",
        rel_type=RelationType.MEMBER_OF,
        dst_id="group:nikko-jujitsu-school",
        metadata={"asserted_by": "kkron", "role": "Chief Instructor", "source": KKRON_SOURCE_URL},
    )
    if not dry_run:
        db.add_edge(edge)
    stats["edges"] += 1

    # Nadeau MEMBER_OF California Aikido Association (division head)
    edge = GraphEdge(
        src_id="person:robert-nadeau",
        rel_type=RelationType.MEMBER_OF,
        dst_id="group:california-aikido-association",
        metadata={"asserted_by": "kkron", "role": "division head", "source": KKRON_SOURCE_URL},
    )
    if not dry_run:
        db.add_edge(edge)
    stats["edges"] += 1

    # Kufferath MEMBER_OF American Jujitsu Institute (head)
    edge = GraphEdge(
        src_id="person:sig-kufferath",
        rel_type=RelationType.MEMBER_OF,
        dst_id="group:american-jujitsu-institute",
        metadata={"asserted_by": "kkron", "role": "head/successor to Okazaki", "source": KKRON_SOURCE_URL},
    )
    if not dry_run:
        db.add_edge(edge)
    stats["edges"] += 1

    # Kufferath MEMBER_OF Kodenkan
    edge = GraphEdge(
        src_id="person:sig-kufferath",
        rel_type=RelationType.MEMBER_OF,
        dst_id="group:kodenkan",
        metadata={"asserted_by": "kkron", "role": "student of Okazaki, 1937+", "source": KKRON_SOURCE_URL},
    )
    if not dry_run:
        db.add_edge(edge)
    stats["edges"] += 1

    return stats


def main():
    parser = argparse.ArgumentParser(
        description="Add kkron's assertions about the Kufferath-Nadeau-Bunch connection"
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
    print("║  ADD KKRON ASSERTIONS — Kufferath/Nadeau/Bunch                      ║")
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
