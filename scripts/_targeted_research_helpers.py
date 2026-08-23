"""
Pure(ish) helpers for scripts/03_targeted_entity_research.py.

Kept in a separate, dash-free module — mirroring scripts/_pipeline_helpers.py
— because a script filename that starts with a digit (03_...) can't be
imported with a normal `import` statement. Tests and the CLI script both
import from here instead.

Two kinds of helpers live in this module:

- Pure functions/data with no I/O at all (``ResearchLead``, ``DEFAULT_LEADS``,
  ``build_search_queries``, ``effective_kkron_confidence``,
  ``build_kkron_claim_record``, ``filter_new_urls``) — covered by
  tests/unit/test_targeted_research_helpers.py.
- DB-writing (but not network-calling) helpers (``ensure_kkron_source``,
  ``store_kkron_claim``) that store kkron's own first-hand claims using the
  same GraphDB/GraphNode/GraphEdge storage layer as scripts/_pipeline_helpers
  — covered by tests/integration/test_targeted_research_pipeline.py.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from src.extractor.alias_resolver import (
    canonical_group,
    canonical_person,
    canonical_place,
    group_id,
    person_id,
    place_id,
)
from src.storage.graph_db import GraphDB
from src.storage.models import (
    BiasHint,
    ClaimStance,
    ClaimType,
    ClaimSourceLink,
    EvidenceMode,
    GraphEdge,
    GraphNode,
    NodeType,
    RelationType,
    SourceClass,
    SourceRecord,
)
from src.utils.text_utils import stable_hash

# ---------------------------------------------------------------------------
# The "asserter" identity used for every claim that originates from kkron's
# own first-hand account rather than an independently crawled/searched web
# source. Deliberately kept out of the alias_resolver historical-person
# registry: this is a *source* node (like a quoted speaker), not a Source
# Family historical figure.
# ---------------------------------------------------------------------------
KKRON_SOURCE_PERSON_ID = "person:kkron-project-owner"
KKRON_SOURCE_LABEL = "kkron (project owner, first-hand account)"

KKRON_WORK_ID = "work:kkron-personal-communication"
KKRON_SOURCE_URL = "kkron://personal-communication"

# Ceiling applied to every kkron first-hand claim's *stored* confidence, no
# matter how sure kkron says he is (see ResearchLead.kkron_confidence). This
# guarantees a first-hand, not-yet-independently-corroborated account can
# never outrank a claim that *was* corroborated by an independently found
# web source (GeminiExtractor claims can score up to 1.0). As scripts/03
# finds independent corroborating sources for the same relation, those
# claims are stored separately at their own (uncapped) confidence — the
# kkron claim itself is not silently upgraded, so the graph always shows
# both "what kkron said" and "what was independently found".
KKRON_CONFIDENCE_CEILING = 0.5

_ENTITY_ID_FN = {
    "person": person_id,
    "group": group_id,
    "place": place_id,
}

_CANONICAL_FN = {
    "person": canonical_person,
    "group": canonical_group,
    "place": canonical_place,
}

_NODE_TYPE_FOR = {
    "person": NodeType.PERSON,
    "group": NodeType.GROUP,
    "place": NodeType.PLACE,
}

_RELATION_SEARCH_PHRASE: dict[RelationType, str] = {
    RelationType.WORKED_AT: "worked at",
    RelationType.FOUNDED: "founded",
    RelationType.MEMBER_OF: "member of",
    RelationType.LIVED_AT: "lived at",
    RelationType.PRECEDES: "before",
    RelationType.CREATED: "created",
}


@dataclass(frozen=True)
class ResearchLead:
    """One targeted (subject, relation, object) claim to corroborate.

    ``kkron_confidence`` is kkron's own stated certainty (0-1) in his
    first-hand account; it is clamped down by
    :func:`effective_kkron_confidence` before being stored, since it is not
    yet independently verified. ``subject_group_type``/``object_group_type``
    are optional hints (e.g. "restaurant") merged into the Group node's
    metadata when the entity is created.
    """

    subject_name: str
    subject_type: str  # "person" | "group" | "place"
    relation: RelationType
    object_name: str
    object_type: str  # "person" | "group" | "place"
    kkron_claim_text: str
    kkron_confidence: float
    subject_group_type: Optional[str] = None
    object_group_type: Optional[str] = None
    extra_queries: tuple[str, ...] = field(default_factory=tuple)

    def subject_id(self) -> str:
        return _ENTITY_ID_FN[self.subject_type](self.subject_name)

    def object_id(self) -> str:
        return _ENTITY_ID_FN[self.object_type](self.object_name)

    def lead_key(self) -> str:
        """Stable identifier for this lead, used to build the claim id."""
        return stable_hash(f"{self.subject_name}|{self.relation.value}|{self.object_name}")


# ---------------------------------------------------------------------------
# Seed leads, per kkron (project owner) first-hand account, 2026-08-23 Slack
# thread. Edit this list to add/remove targeted research targets — no other
# code changes are required for a new lead to be picked up by
# scripts/03_targeted_entity_research.py.
# ---------------------------------------------------------------------------
DEFAULT_LEADS: list[ResearchLead] = [
    ResearchLead(
        subject_name="Richard Moon",
        subject_type="person",
        relation=RelationType.WORKED_AT,
        object_name="The Source",
        object_type="group",
        object_group_type="restaurant",
        kkron_claim_text=(
            "kkron states he knows Richard Moon personally and has confirmed "
            "that Richard Moon worked at The Source restaurant on the Sunset "
            "Strip, during Jim Baker (Father Yod)'s Source Family era."
        ),
        kkron_confidence=0.75,
    ),
    ResearchLead(
        subject_name="Richard Moon",
        subject_type="person",
        relation=RelationType.WORKED_AT,
        object_name="Aware Inn",
        object_type="group",
        object_group_type="restaurant",
        kkron_claim_text=(
            "kkron states he knows Richard Moon personally and has confirmed "
            "that Richard Moon also worked at the Aware Inn, Jim Baker's "
            "restaurant that predated The Source."
        ),
        kkron_confidence=0.75,
        extra_queries=('"Richard Moon" "Aware Inn" restaurant',),
    ),
    ResearchLead(
        subject_name="Jim Baker",
        subject_type="person",
        relation=RelationType.FOUNDED,
        object_name="Aware Inn",
        object_type="group",
        object_group_type="restaurant",
        kkron_claim_text=(
            "kkron states that Jim Baker (Father Yod) ran the Aware Inn "
            "restaurant before opening The Source."
        ),
        kkron_confidence=0.7,
        extra_queries=('"Aware Inn" "Jim Baker" OR "Father Yod"',),
    ),
    ResearchLead(
        subject_name="Aware Inn",
        subject_type="group",
        subject_group_type="restaurant",
        relation=RelationType.PRECEDES,
        object_name="The Source",
        object_type="group",
        object_group_type="restaurant",
        kkron_claim_text=(
            "kkron states the Aware Inn was Jim Baker's earlier restaurant, "
            "preceding The Source restaurant on the Sunset Strip."
        ),
        kkron_confidence=0.7,
        extra_queries=('"Aware Inn" "The Source" restaurant history Baker',),
    ),
    ResearchLead(
        subject_name="Jim Baker",
        subject_type="person",
        relation=RelationType.FOUNDED,
        object_name="The Source",
        object_type="group",
        object_group_type="restaurant",
        kkron_claim_text=(
            "kkron reaffirms that Jim Baker (Father Yod) founded The Source "
            "restaurant on the Sunset Strip."
        ),
        kkron_confidence=0.85,
    ),
    ResearchLead(
        subject_name="Richard Moon",
        subject_type="person",
        relation=RelationType.WORKED_AT,
        object_name="Wild Mountain Cafe",
        object_type="group",
        object_group_type="restaurant",
        kkron_claim_text=(
            "kkron says, with less certainty than the other leads here, "
            "that he believes some Wild Mountain Cafe locations are also "
            "linked to Richard Moon's history with the Source Family circle."
        ),
        kkron_confidence=0.35,
        extra_queries=(
            '"Richard Moon" "Wild Mountain Cafe"',
            '"Wild Mountain Cafe" "Source Family" OR "Father Yod"',
        ),
    ),
]


def effective_kkron_confidence(raw_confidence: float) -> float:
    """Clamp a kkron first-hand confidence into [0, KKRON_CONFIDENCE_CEILING].

    Ensures a first-hand, not-yet-independently-corroborated account never
    scores as high as (or higher than) a claim extracted from a real,
    independently found web source.
    """
    return max(0.0, min(raw_confidence, KKRON_CONFIDENCE_CEILING))


def build_search_queries(lead: ResearchLead) -> list[str]:
    """Build a de-duplicated list of web search queries for a lead.

    Hand-tuned ``extra_queries`` (usually the most targeted) come first,
    followed by a generic "<subject> <relation phrase> <object>" query and a
    quoted co-occurrence query.
    """
    phrase = _RELATION_SEARCH_PHRASE.get(lead.relation, "connected to")
    candidates = [
        *lead.extra_queries,
        f"{lead.subject_name} {phrase} {lead.object_name}",
        f'"{lead.subject_name}" "{lead.object_name}"',
    ]
    seen: set[str] = set()
    queries: list[str] = []
    for q in candidates:
        key = q.strip().lower()
        if key and key not in seen:
            seen.add(key)
            queries.append(q.strip())
    return queries


def build_kkron_claim_record(lead: ResearchLead) -> dict:
    """Build the claim dict for a lead's kkron-sourced first-hand claim.

    Shape mirrors the enriched claim dicts produced by
    ``GeminiClaimExtractor.extract_claims`` / ``ClaimExtractor.extract_claims``
    (id, claim_text, claim_type, stance, confidence, speaker, speaker_id,
    evidence_mode, source_url) so it stores the same way any other claim
    does; see :func:`store_kkron_claim`.
    """
    cid = f"claim:kkron:{lead.lead_key()}"
    return {
        "id": cid,
        "claim_text": lead.kkron_claim_text,
        "claim_type": ClaimType.BIOGRAPHICAL.value,
        "stance": ClaimStance.NEUTRAL.value,
        "confidence": effective_kkron_confidence(lead.kkron_confidence),
        "raw_kkron_confidence": lead.kkron_confidence,
        "evidence_mode": EvidenceMode.FIRST_PERSON.value,
        "speaker": KKRON_SOURCE_LABEL,
        "speaker_id": KKRON_SOURCE_PERSON_ID,
        "source_url": KKRON_SOURCE_URL,
    }


def filter_new_urls(urls: list[str], already_known: set[str]) -> list[str]:
    """Drop URLs already present in ``already_known`` (e.g. existing DB
    sources), de-duplicating the remainder while preserving order."""
    seen: set[str] = set(already_known)
    out: list[str] = []
    for u in urls:
        if u and u not in seen:
            seen.add(u)
            out.append(u)
    return out


# ---------------------------------------------------------------------------
# DB-writing helpers (no network calls) — store kkron's first-hand claims.
# ---------------------------------------------------------------------------


def ensure_kkron_source(db: GraphDB) -> None:
    """Idempotently create the Person node + pseudo Work/Source record that
    represent kkron himself as the asserter of his first-hand claims.

    Mirrors how scripts/_pipeline_helpers.process_page creates a Work node +
    SourceRecord for every crawled page, and how scripts/02_gemini_search.py
    uses a non-http pseudo-URL (``gemini://inline-text``) for inline text
    that has no real source URL.
    """
    db.add_node(GraphNode(
        id=KKRON_SOURCE_PERSON_ID,
        type=NodeType.PERSON,
        label=KKRON_SOURCE_LABEL,
        canonical_name=KKRON_SOURCE_LABEL,
        metadata={
            "role": "project_owner_source",
            "note": (
                "Project owner's first-hand personal account. Claims "
                f"ASSERTED_BY this node are capped at confidence <= "
                f"{KKRON_CONFIDENCE_CEILING} until independently "
                "corroborated by scripts/03_targeted_entity_research.py."
            ),
        },
        source_urls=[KKRON_SOURCE_URL],
    ))
    db.add_node(GraphNode(
        id=KKRON_WORK_ID,
        type=NodeType.WORK,
        label="kkron — personal communication (project owner)",
        canonical_name=None,
        metadata={
            "url": KKRON_SOURCE_URL,
            "platform": "kkron (personal communication)",
            "work_type": "personal_communication",
        },
        source_urls=[KKRON_SOURCE_URL],
    ))
    db.add_source(SourceRecord(
        id=KKRON_WORK_ID,
        url=KKRON_SOURCE_URL,
        title="kkron — personal communication (project owner)",
        author="kkron",
        platform="kkron (personal communication)",
        source_class=SourceClass.PRIMARY_FIRST_PERSON,
        bias_hint=BiasHint.NEUTRAL_ISH,
    ))


def _ensure_entity_node(db: GraphDB, name: str, entity_type: str, group_type: Optional[str]) -> str:
    node_id = _ENTITY_ID_FN[entity_type](name)
    canonical = _CANONICAL_FN[entity_type](name)
    metadata = {"group_type": group_type} if (entity_type == "group" and group_type) else {}
    db.add_node(GraphNode(
        id=node_id,
        type=_NODE_TYPE_FOR[entity_type],
        label=name,
        canonical_name=canonical,
        metadata=metadata,
        source_urls=[KKRON_SOURCE_URL],
    ))
    return node_id


def store_kkron_claim(db: GraphDB, lead: ResearchLead) -> str:
    """Store one lead's kkron first-hand claim + its relation edge.

    Idempotent: safe to call repeatedly (e.g. on every cron run) — node
    upserts merge metadata/labels and edge/claim-source-link inserts use
    ``INSERT OR IGNORE`` under the hood (see GraphDB), so re-running never
    duplicates data.

    Returns the claim node id.
    """
    ensure_kkron_source(db)
    subject_id = _ensure_entity_node(db, lead.subject_name, lead.subject_type, lead.subject_group_type)
    object_id = _ensure_entity_node(db, lead.object_name, lead.object_type, lead.object_group_type)

    claim = build_kkron_claim_record(lead)
    cid = claim["id"]
    db.add_node(GraphNode(
        id=cid,
        type=NodeType.CLAIM,
        label=claim["claim_text"][:200],
        canonical_name=None,
        metadata={
            "claim_text": claim["claim_text"],
            "claim_type": claim["claim_type"],
            "stance": claim["stance"],
            "confidence": claim["confidence"],
            "raw_kkron_confidence": claim["raw_kkron_confidence"],
            "evidence_mode": claim["evidence_mode"],
            "pending_independent_corroboration": True,
        },
        source_urls=[KKRON_SOURCE_URL],
    ))

    db.add_edge(GraphEdge(src_id=KKRON_WORK_ID, rel_type=RelationType.CONTAINS, dst_id=cid,
                           metadata={"evidence": KKRON_SOURCE_URL}))
    db.add_edge(GraphEdge(src_id=KKRON_WORK_ID, rel_type=RelationType.MENTIONS, dst_id=subject_id,
                           metadata={"evidence": KKRON_SOURCE_URL}))
    db.add_edge(GraphEdge(src_id=KKRON_WORK_ID, rel_type=RelationType.MENTIONS, dst_id=object_id,
                           metadata={"evidence": KKRON_SOURCE_URL}))
    db.add_edge(GraphEdge(src_id=cid, rel_type=RelationType.ASSERTED_BY, dst_id=KKRON_SOURCE_PERSON_ID,
                           metadata={"evidence": KKRON_SOURCE_URL}))
    db.add_edge(GraphEdge(src_id=cid, rel_type=RelationType.ABOUT, dst_id=subject_id,
                           metadata={"evidence": KKRON_SOURCE_URL}))
    db.add_edge(GraphEdge(src_id=cid, rel_type=RelationType.ABOUT, dst_id=object_id,
                           metadata={"evidence": KKRON_SOURCE_URL}))
    db.add_claim_source_link(ClaimSourceLink(claim_id=cid, source_id=KKRON_WORK_ID))

    # The relation itself (e.g. Richard Moon WORKED_AT The Source), tagged as
    # coming from kkron's account and not yet independently verified. A
    # later independent-source relation edge with the same (src, rel, dst)
    # is a no-op thanks to the UNIQUE(src_id, rel_type, dst_id) constraint —
    # the *claim* is what carries the (lower vs. independently-verified)
    # confidence distinction, not the edge.
    db.add_edge(GraphEdge(
        src_id=subject_id,
        rel_type=lead.relation,
        dst_id=object_id,
        metadata={
            "evidence": KKRON_SOURCE_URL,
            "trigger": "kkron_first_hand_account",
            "asserted_by": "kkron",
            "verified_independently": False,
        },
    ))
    return cid
