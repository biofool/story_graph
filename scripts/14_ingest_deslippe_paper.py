#!/usr/bin/env python3
"""
Ingest Philip Deslippe's "From Maharaj to Mahan Tantric: The Construction of
Yogi Bhajan's Kundalini Yoga" (Sikh Formations 8(3), Dec 2012, pp. 369-387)
into the story_graph.

This is a peer-reviewed scholarly paper hosted on eScholarship (UC Santa
Barbara). It is the primary academic source on the constructed origins of
Yogi Bhajan's Kundalini Yoga, arguing that the practice was a bricolage
derived from Swami Dhirendra Brahmachari and Maharaj Virsa Singh — not an
ancient secret tradition as 3HO's official history claims.

The script:
1. Enriches the existing minimal SourceRecord + Work node for the paper
   with proper metadata (author, title, publish_date, platform, raw_text
   excerpt, journal citation).
2. Creates Person nodes for the two key previously-unmentioned figures:
   - Swami Dhirendra Brahmachari (1924-1994) — hatha yoga teacher
   - Maharaj Virsa Singh (1934-2007) — Sikh sant, Yogi Bhajan's actual teacher
   - Sant Hazara Singh — the claimed (likely fabricated) teacher
   - Lama Lilan Po — the claimed (likely fabricated) Tibetan lama
3. Extracts key claims from the paper as Claim nodes with proper attribution.
4. Wires all edges (ABOUT, ASSERTED_BY, SUPPORTED_BY, CONTAINS, MENTIONS,
   DESCRIBES, CONTRADICTS).
5. Exports to graph_snapshot/.

The paper PDF was downloaded and text-extracted; key passages are encoded
as claims with quote spans where possible.

Usage:
    python scripts/14_ingest_deslippe_paper.py
    python scripts/14_ingest_deslippe_paper.py --dry-run
    python scripts/14_ingest_deslippe_paper.py --db data/graph.db
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.storage.graph_db import GraphDB
from src.storage.json_export import export_to_json
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

# --- Paper metadata ---------------------------------------------------------

PAPER_URL = (
    "https://escholarship.org/content/qt6r63q6qn/"
    "qt6r63q6qn_noSplash_fbbba186685c0619c35208f88b1f29ec.pdf"
)
PAPER_TANDFONLINE_URL = "http://www.tandfonline.com/doi/abs/10.1080/17448727.2012.745303"
PAPER_TITLE = (
    "From Maharaj to Mahan Tantric: The Construction of Yogi Bhajan's "
    "Kundalini Yoga"
)
PAPER_AUTHOR = "Philip Deslippe"
PAPER_JOURNAL = "Sikh Formations"
PAPER_VOLUME = "8"
PAPER_ISSUE = "3"
PAPER_PAGES = "369-387"
PAPER_DATE = "2012-12"
PAPER_CITATION = (
    f"Deslippe, P. (2012). From Maharaj to Mahan Tantric: The Construction "
    f"of Yogi Bhajan's Kundalini Yoga. {PAPER_JOURNAL}, {PAPER_VOLUME}({PAPER_ISSUE}), "
    f"{PAPER_PAGES}."
)

# Existing source/work IDs from prior ingestion
EXISTING_WORK_ID = "work:3ceaefb5ffac8d5b"
EXISTING_SOURCE_ID = "work:3ceaefb5ffac8d5b"  # same ID used for source record

# Stable IDs for new entities
PAPER_WORK_ID = "work:deslippe-2012-maharaj-to-mahan-tantric"
PAPER_SOURCE_ID = "source:deslippe-2012-maharaj-to-mahan-tantric"
AUTHOR_PERSON_ID = "person:philip-deslippe"  # already exists

DHIRENDRA_ID = "person:swami-dhirendra-brahmachari"
VIRSA_SINGH_ID = "person:maharaj-virsa-singh"
HAZARA_SINGH_ID = "person:sant-hazara-singh"
LILAN_PO_ID = "person:lama-lilan-po"

# Existing entity IDs
YOGI_BHAJAN_ID = "person:yogi-bhajan"
HARBHAJAN_PURI_ID = "person:yoga-harbhajan-singh-puri"
THREE_HO_ID = "group:yoga-3ho-happy-healthy-holy-organization"
THREE_HO_SHORT_ID = "group:3ho"
KUNDALINI_YOGA_ID = "group:international-kundalini-yoga-teachers-association"
KRI_ID = "group:yoga-kri"

# --- Key claims extracted from the paper ------------------------------------
#
# Each claim is a structured assertion from the paper, with:
# - id: stable slug
# - text: the claim text
# - claim_type: ClaimType
# - stance: ClaimStance
# - confidence: float (Deslippe is a careful scholar; high confidence for
#   well-sourced claims, moderate for interpretive ones)
# - evidence_mode: secondary_report (Deslippe is reporting/researching)
# - about: list of node IDs the claim is about
# - contradicts: list of node IDs (claims) this contradicts, if any
# - quote: optional direct quote from the paper

CLAIMS = [
    {
        "id": "claim:deslippe-2012-kundalini-yoga-bricolage",
        "text": (
            "Yogi Bhajan's Kundalini Yoga was not an ancient and secret "
            "tradition as 3HO's official history claims, but a bricolage "
            "created by Yogi Bhajan himself, derived from two main figures: "
            "Swami Dhirendra Brahmachari (1924-1994), a hatha yoga teacher, "
            "and Maharaj Virsa Singh (1934-2007), a Sikh sant. The practice "
            "was constructed in the late 1960s-1970s, not passed down through "
            "an ancient 'Golden Chain' of masters."
        ),
        "claim_type": ClaimType.HISTORICAL_DISPUTE,
        "stance": ClaimStance.CRITICAL,
        "confidence": 0.9,
        "about": [YOGI_BHAJAN_ID, KUNDALINI_YOGA_ID, DHIRENDRA_ID, VIRSA_SINGH_ID],
        "quote": (
            "this article argues that it was a bricolage created by Yogi "
            "Bhajan himself and derived from two main figures: a hatha yoga "
            "teacher named Swami Dhirendra Brahmachari (1924-1994) and the "
            "Sikh sant Maharaj Virsa Singh (1934-2007)"
        ),
    },
    {
        "id": "claim:deslippe-2012-golden-chain-unravels",
        "text": (
            "The 'Golden Chain' lineage of Kundalini Yoga — the claim that "
            "the practice was passed from antiquity through Sant Hazara "
            "Singh to Yogi Bhajan — unravels under investigation. Sant "
            "Hazara Singh was first mentioned in print only in July 1970, "
            "a year and a half after Yogi Bhajan began teaching. No "
            "independent evidence for Sant Hazara Singh's existence has "
            "been found, including by Yogi Bhajan's own biographer."
        ),
        "claim_type": ClaimType.HISTORICAL_DISPUTE,
        "stance": ClaimStance.CRITICAL,
        "confidence": 0.85,
        "about": [YOGI_BHAJAN_ID, HAZARA_SINGH_ID, KUNDALINI_YOGA_ID],
        "quote": (
            "But when the Golden Chain of Kundalini Yoga is investigated "
            "rather than invoked, it unravels."
        ),
    },
    {
        "id": "claim:deslippe-2012-virsa-singh-was-actual-teacher",
        "text": (
            "Maharaj Virsa Singh of Gobind Sadan was Yogi Bhajan's actual "
            "teacher in the early years of 3HO. Early students echo the "
            "claim that the early years of 3HO were 'all about Virsa Singh.' "
            "Yogi Bhajan originally told students he washed bathrooms for "
            "Virsa Singh and kept his teacher's sandals on his bed. This "
            "relationship was later erased from 3HO's official history."
        ),
        "claim_type": ClaimType.BIOGRAPHICAL,
        "stance": ClaimStance.CRITICAL,
        "confidence": 0.9,
        "about": [YOGI_BHAJAN_ID, VIRSA_SINGH_ID, THREE_HO_ID],
        "quote": (
            "Many early students, unaware of one another, echo the claim "
            "that the early years of 3HO were 'all about Virsa Singh.'"
        ),
    },
    {
        "id": "claim:deslippe-2012-dhirendra-brahmachari-source",
        "text": (
            "Swami Dhirendra Brahmachari (1924-1994) was a hatha yoga "
            "teacher whose Sūkṣma Vyāyāma (subtle exercises) and "
            "Yogāsana Vijñāna formed the physical practice basis of "
            "Yogi Bhajan's Kundalini Yoga. Yogi Bhajan publicly claimed "
            "Dhirendra Brahmachari as a credential (calling himself "
            "'Senior Professor of Yoga' at his ashram) while privately "
            "minimizing him to students. The parallels between specific "
            "exercises are documented in Deslippe's paper."
        ),
        "claim_type": ClaimType.BIOGRAPHICAL,
        "stance": ClaimStance.NEUTRAL,
        "confidence": 0.85,
        "about": [DHIRENDRA_ID, YOGI_BHAJAN_ID, KUNDALINI_YOGA_ID],
        "quote": (
            "Parallels to these rhythmic exercises can be found in Swami "
            "Dhirendra Brahmachari's Sūkṣma Vyāyāma (1973 edition) as "
            "exercises #9, 10, 13, 16, 22, 41, and 43."
        ),
    },
    {
        "id": "claim:deslippe-2012-india-trip-1970-break",
        "text": (
            "During the December 1970 – March 1971 trip to India with ~84 "
            "students, Yogi Bhajan dramatically broke from Maharaj Virsa "
            "Singh at Gobind Sadan. Virsa Singh told the group he never "
            "taught anyone yoga and that yoga had nothing to do with "
            "Sikhism. After the break, Sant Hazara Singh and Guru Ram Das "
            "became central to 3HO's lineage narrative, and Virsa Singh "
            "became persona non grata. The trip ended with Yogi Bhajan "
            "being arrested for defrauding a man of 10,000 rupees, then "
            "fleeing the country."
        ),
        "claim_type": ClaimType.BIOGRAPHICAL,
        "stance": ClaimStance.CRITICAL,
        "confidence": 0.85,
        "about": [YOGI_BHAJAN_ID, VIRSA_SINGH_ID, THREE_HO_ID],
        "quote": (
            "Maharaj Virsa Singh was struck from the record within 3HO, "
            "as were the minor living teachers that were listed in the "
            "July 1970 'Who Is Yogi Bhajan?' article in Beads of Truth."
        ),
    },
    {
        "id": "claim:deslippe-2012-mahan-tantric-fabricated",
        "text": (
            "Yogi Bhajan's claim to the title of 'Mahan Tantric' — "
            "supposedly a unique title held by only one person on earth "
            "at a time, passed from Sant Hazara Singh via Lama Lilan Po — "
            "was announced in spring 1971 shortly after the India trip. "
            "The title appears fabricated: White Tantric Yoga courses "
            "were taught before the title was supposedly bestowed, and "
            "all of Yogi Bhajan's claimed lineage teachers were "
            "conveniently inaccessible (dead or unverifiable)."
        ),
        "claim_type": ClaimType.HISTORICAL_DISPUTE,
        "stance": ClaimStance.CRITICAL,
        "confidence": 0.8,
        "about": [YOGI_BHAJAN_ID, HAZARA_SINGH_ID, LILAN_PO_ID, KUNDALINI_YOGA_ID],
        "quote": (
            "All of Yogi Bhajan's claims about lineage or teachers were "
            "not able to be substantiated since all teachers that he "
            "referred to were (conveniently) expired."
        ),
    },
    {
        "id": "claim:deslippe-2012-shifting-yoga-study-dates",
        "text": (
            "Yogi Bhajan's own statements contradict the Sant Hazara Singh "
            "narrative. The official 3HO story claims he trained under "
            "Sant Hazara Singh from age 7 to 16½. But in 1968-1969, Yogi "
            "Bhajan told reporters he had been studying yoga 'since he was "
            "eighteen' and claimed 'twenty-two years' of study — placing "
            "the start of his yogic study after his claimed completion of "
            "studies under Sant Hazara Singh. This is strong internal "
            "evidence against Sant Hazara Singh's existence as described."
        ),
        "claim_type": ClaimType.BIOGRAPHICAL,
        "stance": ClaimStance.CRITICAL,
        "confidence": 0.9,
        "about": [YOGI_BHAJAN_ID, HAZARA_SINGH_ID],
        "quote": (
            "Yogi Bhajan initially told reporters that he had been "
            "studying yoga 'since he was eighteen' and in interviews in "
            "both 1968 and 1969, he claimed to have studied for "
            "twenty-two years"
        ),
    },
    {
        "id": "claim:deslippe-2012-history-revised",
        "text": (
            "The early history of 3HO was thoroughly revised and replaced "
            "as the organization aged. Maharaj Virsa Singh — initially "
            "revered — was eliminated from the narrative, while Sant "
            "Hazara Singh — a figure introduced only after 1.5 years — "
            "became central. This revision was possible because the "
            "changes occurred in the first two years, there was less past "
            "to revise, and the passing of time solidified the new "
            "narrative as early members cycled out."
        ),
        "claim_type": ClaimType.HISTORICAL_DISPUTE,
        "stance": ClaimStance.CRITICAL,
        "confidence": 0.85,
        "about": [THREE_HO_ID, YOGI_BHAJAN_ID, VIRSA_SINGH_ID, HAZARA_SINGH_ID],
        "quote": (
            "the early history of 3HO is remarkable in the extent that it "
            "was so thoroughly revised and replaced as the organization "
            "aged, with a figure so initially revered as Maharaj Virsa "
            "Singh eliminated and a theoretically essential figure as "
            "Sant Hazara Singh introduced only after a year and a half"
        ),
    },
    {
        "id": "claim:deslippe-2012-single-source-problem",
        "text": (
            "All information about the lineage and practice of Yogi Bhajan's "
            "Kundalini Yoga originates from the singular person of Yogi "
            "Bhajan himself. From his lectures and class notes came the "
            "instruction manuals, books, and 3HO periodicals. Outside "
            "writers and scholars relied on 3HO's own materials, creating "
            "a long and citable bibliography that seems to verify the "
            "claims — but the ultimate source is one person."
        ),
        "claim_type": ClaimType.HISTORICAL_DISPUTE,
        "stance": ClaimStance.CRITICAL,
        "confidence": 0.85,
        "about": [YOGI_BHAJAN_ID, KUNDALINI_YOGA_ID, THREE_HO_ID],
        "quote": (
            "it is from the singular person of Yogi Bhajan that all "
            "information about the lineage and practice of his Kundalini "
            "Yoga originates"
        ),
    },
]


# --- Person nodes to create -------------------------------------------------

NEW_PERSONS = [
    {
        "id": DHIRENDRA_ID,
        "label": "Swami Dhirendra Brahmachari",
        "canonical_name": "Swami Dhirendra Brahmachari",
        "metadata": {
            "life_dates": "1924-1994",
            "description": (
                "Hatha yoga teacher and author of Sūkṣma Vyāyāma and "
                "Yogāsana Vijñāna. Taught at Vishwayatan Ashram in New "
                "Delhi. His students included Indira Gandhi and "
                "Jawaharlal Nehru. Identified by Philip Deslippe as a "
                "primary source of the physical exercises in Yogi Bhajan's "
                "Kundalini Yoga."
            ),
            "source": "Deslippe (2012), Sikh Formations 8(3)",
        },
        "source_urls": [PAPER_URL],
    },
    {
        "id": VIRSA_SINGH_ID,
        "label": "Maharaj Virsa Singh",
        "canonical_name": "Maharaj Virsa Singh",
        "metadata": {
            "life_dates": "1934-2007",
            "description": (
                "Sikh sant and founder of Gobind Sadan, outside New Delhi. "
                "Identified by Philip Deslippe as Yogi Bhajan's actual "
                "teacher in the early years of 3HO. The early years of 3HO "
                "were 'all about Virsa Singh.' Yogi Bhajan later erased "
                "Virsa Singh from 3HO's official history after a dramatic "
                "break during the 1970-71 India trip. Also known as Baba "
                "Virsa Singh in his later years."
            ),
            "source": "Deslippe (2012), Sikh Formations 8(3)",
        },
        "source_urls": [PAPER_URL],
    },
    {
        "id": HAZARA_SINGH_ID,
        "label": "Sant Hazara Singh",
        "canonical_name": "Sant Hazara Singh",
        "metadata": {
            "description": (
                "Figure claimed by Yogi Bhajan as his Kundalini Yoga "
                "teacher from age 7 to 16½. First mentioned in print in "
                "July 1970, 1.5 years after Yogi Bhajan began teaching. "
                "No independent evidence for his existence has been found, "
                "including by Yogi Bhajan's own biographer. Deslippe "
                "argues this figure was likely fabricated or greatly "
                "embellished to provide a lineage provenance for "
                "Kundalini Yoga."
            ),
            "claimed_role": "Yogi Bhajan's Kundalini Yoga teacher",
            "existence_evidence": "no independent verification found",
            "source": "Deslippe (2012), Sikh Formations 8(3)",
        },
        "source_urls": [PAPER_URL],
    },
    {
        "id": LILAN_PO_ID,
        "label": "Lama Lilan Po",
        "canonical_name": "Lama Lilan Po",
        "metadata": {
            "description": (
                "Tibetan lama claimed by Yogi Bhajan as a previous holder "
                "of the 'Mahan Tantric' title, supposedly a student of "
                "Sant Hazara Singh. This claim is historically improbable: "
                "a Tibetan lama studying under a Sikh teacher in the "
                "Punjab at a time when Tibet was closed off. No "
                "independent evidence for this figure has been found."
            ),
            "claimed_role": "previous Mahan Tantric",
            "existence_evidence": "no independent verification found",
            "source": "Deslippe (2012), Sikh Formations 8(3)",
        },
        "source_urls": [PAPER_URL],
    },
]


# --- Edges from paper work to entities (MENTIONS) ---------------------------

MENTION_TARGETS = [
    YOGI_BHAJAN_ID,
    HARBHAJAN_PURI_ID,
    THREE_HO_ID,
    THREE_HO_SHORT_ID,
    KUNDALINI_YOGA_ID,
    KRI_ID,
    DHIRENDRA_ID,
    VIRSA_SINGH_ID,
    HAZARA_SINGH_ID,
    LILAN_PO_ID,
    AUTHOR_PERSON_ID,
]


# --- Main -------------------------------------------------------------------


def ingest(db: GraphDB, dry_run: bool = False) -> int:
    added = 0

    # 1. Create/enrich the Work node for the paper
    print("  Creating/enriching Work node for the paper...")
    if not dry_run:
        db.add_node(GraphNode(
            id=PAPER_WORK_ID,
            type=NodeType.WORK,
            label=PAPER_TITLE,
            canonical_name=None,
            metadata={
                "url": PAPER_URL,
                "platform": "eScholarship (UC Santa Barbara)",
                "work_type": "academic_journal_article",
                "journal": PAPER_JOURNAL,
                "volume": PAPER_VOLUME,
                "issue": PAPER_ISSUE,
                "pages": PAPER_PAGES,
                "publish_date": PAPER_DATE,
                "author": PAPER_AUTHOR,
                "citation": PAPER_CITATION,
                "publisher_url": PAPER_TANDFONLINE_URL,
                "note": (
                    "Peer-reviewed scholarly paper. The primary academic "
                    "source on the constructed origins of Yogi Bhajan's "
                    "Kundalini Yoga."
                ),
            },
            source_urls=[PAPER_URL, PAPER_TANDFONLINE_URL],
        ))
        added += 1

    # Also enrich the existing minimal work node
    if not dry_run:
        db.add_node(GraphNode(
            id=EXISTING_WORK_ID,
            type=NodeType.WORK,
            label=PAPER_TITLE,
            canonical_name=None,
            metadata={
                "url": PAPER_URL,
                "platform": "eScholarship (UC Santa Barbara)",
                "work_type": "academic_journal_article",
                "journal": PAPER_JOURNAL,
                "volume": PAPER_VOLUME,
                "issue": PAPER_ISSUE,
                "pages": PAPER_PAGES,
                "publish_date": PAPER_DATE,
                "author": PAPER_AUTHOR,
                "citation": PAPER_CITATION,
                "enriched_by": "scripts/14_ingest_deslippe_paper.py",
            },
            source_urls=[PAPER_URL, PAPER_TANDFONLINE_URL],
        ))

    # 2. Enrich the existing SourceRecord (UNIQUE constraint on url
    #    prevents creating a second source with the same URL, so we
    #    upsert the existing record by its ID)
    print("  Enriching SourceRecord for the paper...")
    if not dry_run:
        db.add_source(SourceRecord(
            id=EXISTING_SOURCE_ID,
            url=PAPER_URL,
            title=PAPER_TITLE,
            author=PAPER_AUTHOR,
            publish_date=PAPER_DATE,
            platform=f"{PAPER_JOURNAL} (eScholarship)",
            source_class=SourceClass.ARCHIVAL,
            bias_hint=BiasHint.NEUTRAL_ISH,
        ))
        added += 1

    # 3. Enrich the author Person node
    print(f"  Enriching author Person node ({AUTHOR_PERSON_ID})...")
    if not dry_run:
        db.add_node(GraphNode(
            id=AUTHOR_PERSON_ID,
            type=NodeType.PERSON,
            label=PAPER_AUTHOR,
            canonical_name="Philip Deslippe",
            metadata={
                "affiliation": "Religious Studies Department, UC Santa Barbara",
                "role": "academic_researcher",
                "note": (
                    "Author of 'From Maharaj to Mahan Tantric' (Sikh "
                    "Formations, 2012). Leading academic researcher on "
                    "Yogi Bhajan, 3HO, and the construction of Kundalini Yoga."
                ),
            },
            source_urls=[PAPER_URL],
        ))

    # 4. Create/enrich Person nodes (upsert — enriches existing nodes)
    print("  Creating/enriching Person nodes...")
    for person in NEW_PERSONS:
        existing = db.get_node(person["id"])
        if existing:
            print(f"    [exists] {person['id']} — enriching metadata")
        elif dry_run:
            print(f"    [dry-run] would add: {person['label']}")
            continue
        else:
            print(f"    Added: {person['id']} — {person['label']}")
            added += 1
        if not dry_run:
            # Merge source_urls with existing
            merged_urls = sorted(set(
                (existing.source_urls if existing else []) +
                person["source_urls"]
            ))
            db.add_node(GraphNode(
                id=person["id"],
                type=NodeType.PERSON,
                label=person["label"],
                canonical_name=person["canonical_name"],
                metadata=person["metadata"],
                source_urls=merged_urls,
            ))

    # 5. Create Claim nodes + edges
    print("  Creating Claim nodes...")
    for claim_data in CLAIMS:
        claim_id = claim_data["id"]
        existing = db.get_node(claim_id)
        if existing:
            print(f"    [exists] {claim_id}")
        elif dry_run:
            print(f"    [dry-run] would add claim: {claim_data['text'][:80]}...")
        else:
            db.add_node(GraphNode(
                id=claim_id,
                type=NodeType.CLAIM,
                label=claim_data["text"][:200],
                canonical_name=None,
                metadata={
                    "claim_text": claim_data["text"],
                    "claim_type": claim_data["claim_type"].value,
                    "stance": claim_data["stance"].value,
                    "confidence": claim_data["confidence"],
                    "evidence_mode": EvidenceMode.SECONDARY_REPORT.value,
                    "pending_independent_corroboration": False,
                    "source": PAPER_CITATION,
                    "quote": claim_data.get("quote", ""),
                },
                source_urls=[PAPER_URL],
            ))
            print(f"    Added claim: {claim_id}")
            added += 1

            # ASSERTED_BY Philip Deslippe
            db.add_edge(GraphEdge(
                src_id=claim_id,
                rel_type=RelationType.ASSERTED_BY,
                dst_id=AUTHOR_PERSON_ID,
                metadata={"evidence": PAPER_CITATION},
            ))

            # CONTAINS — the paper contains this claim
            db.add_edge(GraphEdge(
                src_id=PAPER_WORK_ID,
                rel_type=RelationType.CONTAINS,
                dst_id=claim_id,
                metadata={"evidence": PAPER_URL},
            ))

            # ABOUT — claim is about each entity
            for about_id in claim_data["about"]:
                db.add_edge(GraphEdge(
                    src_id=claim_id,
                    rel_type=RelationType.ABOUT,
                    dst_id=about_id,
                    metadata={"evidence": PAPER_CITATION},
                ))

            # SUPPORTED_BY — claim is supported by the paper source
            db.add_edge(GraphEdge(
                src_id=claim_id,
                rel_type=RelationType.SUPPORTED_BY,
                dst_id=PAPER_WORK_ID,
                metadata={"evidence": PAPER_URL},
            ))

            # Link claim to the paper's source record
            db.add_claim_source_link(ClaimSourceLink(
                claim_id=claim_id,
                source_id=EXISTING_SOURCE_ID,
            ))

    # 6. MENTIONS edges from the paper work to all entities
    print("  Creating MENTIONS edges from paper...")
    if not dry_run:
        for target_id in MENTION_TARGETS:
            db.add_edge(GraphEdge(
                src_id=PAPER_WORK_ID,
                rel_type=RelationType.MENTIONS,
                dst_id=target_id,
                metadata={"evidence": PAPER_CITATION},
            ))

    # 7. DESCRIBES edge: paper DESCRIBES Yogi Bhajan, 3HO, Kundalini Yoga
    print("  Creating DESCRIBES edges...")
    if not dry_run:
        for target_id in [YOGI_BHAJAN_ID, THREE_HO_ID, KUNDALINI_YOGA_ID]:
            db.add_edge(GraphEdge(
                src_id=PAPER_WORK_ID,
                rel_type=RelationType.DESCRIBES,
                dst_id=target_id,
                metadata={"evidence": PAPER_CITATION},
            ))

    # 8. CONTRADICTS edges — the bricolage claim contradicts 3HO's official
    #    history (represented by the 3HO group node and any existing
    #    self-mythologizing claims about the Golden Chain)
    print("  Creating CONTRADICTS edges...")
    if not dry_run:
        # The bricolage claim contradicts 3HO's official narrative
        # (represented as the 3HO group node's self-presentation)
        bricolage_claim = CLAIMS[0]["id"]
        db.add_edge(GraphEdge(
            src_id=bricolage_claim,
            rel_type=RelationType.CONTRADICTS,
            dst_id=THREE_HO_ID,
            metadata={
                "evidence": PAPER_CITATION,
                "note": "Contradicts 3HO's official history of Kundalini Yoga as an ancient secret tradition",
            },
        ))

    # 9. ALIAS_OF edges — Harbhajan Singh Puri is Yogi Bhajan
    print("  Creating ALIAS_OF edges...")
    if not dry_run:
        db.add_edge(GraphEdge(
            src_id=HARBHAJAN_PURI_ID,
            rel_type=RelationType.ALIAS_OF,
            dst_id=YOGI_BHAJAN_ID,
            metadata={"evidence": PAPER_CITATION},
        ))

    # 10. Link the existing paper work node to the new enriched one
    print("  Linking existing and new work nodes...")
    if not dry_run:
        db.add_edge(GraphEdge(
            src_id=PAPER_WORK_ID,
            rel_type=RelationType.ALIAS_OF,
            dst_id=EXISTING_WORK_ID,
            metadata={"note": "Same paper, enriched metadata"},
        ))

    return added


def main():
    parser = argparse.ArgumentParser(
        description="Ingest Deslippe (2012) paper into story_graph"
    )
    parser.add_argument("--db", default="data/graph.db", help="Database path")
    parser.add_argument("--dry-run", action="store_true", help="No DB writes")
    parser.add_argument("--no-export", action="store_true", help="Skip snapshot export")
    args = parser.parse_args()

    print()
    print("╔════════════════════════════════════════════════════════════════════╗")
    print("║  DESLIPPE (2012) PAPER INGESTION — story_graph                     ║")
    print(f"║  {PAPER_TITLE[:60]:60s}  ║")
    print("╚════════════════════════════════════════════════════════════════════╝")
    print()

    if args.dry_run:
        print("[dry-run mode — no DB writes]\n")

    db = GraphDB(Path(args.db))
    try:
        added = ingest(db, dry_run=args.dry_run)
        print(f"\nAdded {added} new nodes/edges")

        if not args.dry_run and not args.no_export:
            print("\nExporting snapshot...")
            counts = export_to_json(db, Path("graph_snapshot"))
            print(f"Exported snapshot: {counts}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
