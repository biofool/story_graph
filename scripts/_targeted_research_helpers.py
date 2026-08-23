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

None of this module writes to or reads from ``graph_snapshot/`` directly —
that JSON-snapshot-is-source-of-truth load/export lifecycle lives in
scripts/03_targeted_entity_research.py's ``main()``, via
src/storage/json_export.py. This module only ever touches the ``GraphDB``
instance it is handed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from src.extractor.alias_resolver import (
    canonical_group,
    canonical_person,
    canonical_place,
    event_id,
    group_id,
    person_id,
    place_id,
    work_id,
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
from src.utils.text_utils import get_domain, stable_hash

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
    "event": event_id,
}

_CANONICAL_FN = {
    "person": canonical_person,
    "group": canonical_group,
    "place": canonical_place,
    # Events have no alias-canonicalization table (mirrors how
    # scripts/_pipeline_helpers.process_page sets an Event node's
    # canonical_name straight from its label) — the label itself is used.
    "event": lambda name: name,
}

_NODE_TYPE_FOR = {
    "person": NodeType.PERSON,
    "group": NodeType.GROUP,
    "place": NodeType.PLACE,
    "event": NodeType.EVENT,
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

    Most leads originate from kkron's own first-hand account: set
    ``kkron_claim_text``/``kkron_confidence`` for those. ``kkron_confidence``
    is kkron's own stated certainty (0-1) in his first-hand account; it is
    clamped down by :func:`effective_kkron_confidence` before being stored,
    since it is not yet independently verified.

    A lead can instead originate from an already-known cited source (e.g. a
    specific claim spotted in one of the project's configured seed URLs,
    rather than kkron's own word) — set ``source_url``/``source_claim_text``/
    ``source_confidence`` for those and leave ``kkron_claim_text``/
    ``kkron_confidence`` at their defaults. This is a *different* provenance
    from kkron's personal testimony, so it is stored via a separate path
    (see :func:`build_citation_claim_record`/:func:`store_kkron_claim`) that
    does not run the confidence through the kkron-specific ceiling and does
    not attribute the claim to kkron.

    ``subject_group_type``/``object_group_type`` are optional hints (e.g.
    "restaurant") merged into the Group node's metadata when the entity is
    created.
    """

    subject_name: str
    subject_type: str  # "person" | "group" | "place" | "event"
    relation: RelationType
    object_name: str
    object_type: str  # "person" | "group" | "place" | "event"
    kkron_claim_text: str
    kkron_confidence: float
    subject_group_type: Optional[str] = None
    object_group_type: Optional[str] = None
    extra_queries: tuple[str, ...] = field(default_factory=tuple)
    # Set these three (instead of kkron_claim_text/kkron_confidence) for a
    # lead sourced from an already-known citation rather than kkron himself.
    source_url: Optional[str] = None
    source_claim_text: Optional[str] = None
    source_confidence: Optional[float] = None

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
    # ---------------------------------------------------------------------
    # Citation-sourced lead (not kkron's own account): pleasekillme.com's
    # Father Yod profile is already one of the project's configured seed
    # URLs (see README), but this specific claim — a March 1971 meeting of
    # Richard Moon, Father Yod, and Yogi Bhajan — is called out explicitly
    # here so it gets verified/extracted (confirm the article actually
    # supports it, capture the exact wording, and look for independent
    # corroboration) rather than waiting to be noticed incidentally by the
    # broad crawl. Modeled as one lead per participant, all pointing at the
    # same Event node (a shared, stable event label — see event_id()).
    # ---------------------------------------------------------------------
    ResearchLead(
        subject_name="Richard Moon",
        subject_type="person",
        relation=RelationType.MENTIONS,
        object_name="March 1971 meeting of Richard Moon, Father Yod, and Yogi Bhajan",
        object_type="event",
        # kkron_claim_text/kkron_confidence are N/A for a citation-sourced
        # lead (this is not kkron's own account) — see source_* below.
        kkron_claim_text="N/A — citation-sourced lead, see source_claim_text.",
        kkron_confidence=1.0,
        source_url="https://pleasekillme.com/father-yod/",
        source_claim_text=(
            "pleasekillme.com's Father Yod profile claims that in March 1971, "
            "Richard Moon, Father Yod (Jim Baker), and Yogi Bhajan met one "
            "another."
        ),
        source_confidence=0.4,
        extra_queries=(
            '"Richard Moon" "Father Yod" "Yogi Bhajan" 1971',
            'pleasekillme "Father Yod" "Yogi Bhajan" March 1971',
        ),
    ),
    ResearchLead(
        subject_name="Jim Baker",
        subject_type="person",
        relation=RelationType.MENTIONS,
        object_name="March 1971 meeting of Richard Moon, Father Yod, and Yogi Bhajan",
        object_type="event",
        kkron_claim_text="N/A — citation-sourced lead, see source_claim_text.",
        kkron_confidence=1.0,
        source_url="https://pleasekillme.com/father-yod/",
        source_claim_text=(
            "pleasekillme.com's Father Yod profile claims that in March 1971, "
            "Jim Baker (Father Yod), Richard Moon, and Yogi Bhajan met one "
            "another."
        ),
        source_confidence=0.4,
    ),
    ResearchLead(
        subject_name="Yogi Bhajan",
        subject_type="person",
        relation=RelationType.MENTIONS,
        object_name="March 1971 meeting of Richard Moon, Father Yod, and Yogi Bhajan",
        object_type="event",
        kkron_claim_text="N/A — citation-sourced lead, see source_claim_text.",
        kkron_confidence=1.0,
        source_url="https://pleasekillme.com/father-yod/",
        source_claim_text=(
            "pleasekillme.com's Father Yod profile claims that in March 1971, "
            "Yogi Bhajan, Richard Moon, and Father Yod (Jim Baker) met one "
            "another."
        ),
        source_confidence=0.4,
        extra_queries=('"Yogi Bhajan" "Father Yod" OR "Jim Baker" 1971',),
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
    """Build the claim dict for a lead's sourced claim.

    Delegates to :func:`build_citation_claim_record` for a lead sourced from
    an already-known citation (``lead.source_url`` set) rather than kkron's
    own first-hand account — see :class:`ResearchLead`.

    Shape mirrors the enriched claim dicts produced by
    ``GeminiClaimExtractor.extract_claims`` / ``ClaimExtractor.extract_claims``
    (id, claim_text, claim_type, stance, confidence, speaker, speaker_id,
    evidence_mode, source_url) so it stores the same way any other claim
    does; see :func:`store_kkron_claim`.
    """
    if lead.source_url:
        return build_citation_claim_record(lead)
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


def build_citation_claim_record(lead: ResearchLead) -> dict:
    """Build the claim dict for a lead sourced from an already-known cited
    URL (``lead.source_url``) rather than kkron's own first-hand account.

    Unlike :func:`build_kkron_claim_record`'s kkron path, ``source_confidence``
    is stored as-is — it is *not* run through :func:`effective_kkron_confidence`
    / ``KKRON_CONFIDENCE_CEILING``, since that ceiling exists specifically to
    keep kkron's own unverified word from outranking independently found
    claims. A citation claim has no ``speaker``/``speaker_id`` (it is not
    attributed to a person asserting it first-hand); see
    :func:`ensure_citation_source`/:func:`store_kkron_claim` for how it is
    linked to its source instead (SUPPORTED_BY, not ASSERTED_BY).
    """
    cid = f"claim:citation:{lead.lead_key()}"
    return {
        "id": cid,
        "claim_text": lead.source_claim_text,
        "claim_type": ClaimType.BIOGRAPHICAL.value,
        "stance": ClaimStance.NEUTRAL.value,
        "confidence": lead.source_confidence,
        "raw_kkron_confidence": None,
        "evidence_mode": EvidenceMode.SECONDARY_REPORT.value,
        "speaker": None,
        "speaker_id": None,
        "source_url": lead.source_url,
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


def ensure_citation_source(db: GraphDB, lead: ResearchLead) -> str:
    """Idempotently create the Work/Source record for a lead's cited URL
    (``lead.source_url``) that has not yet been fetched/extracted by the
    crawl pipeline.

    Mirrors how scripts/_pipeline_helpers.process_page creates a Work node +
    SourceRecord for every crawled page. If that URL is later actually
    crawled (e.g. it's already a project seed URL, per README), that crawl's
    ``process_page`` call upserts the same Work/Source id — this placeholder
    just makes sure the citation exists in the graph now, before any crawl
    runs. Returns the Work node id.
    """
    wid = work_id(lead.source_url)
    db.add_node(GraphNode(
        id=wid,
        type=NodeType.WORK,
        label=f"cited source: {lead.source_url}",
        canonical_name=None,
        metadata={
            "url": lead.source_url,
            "platform": get_domain(lead.source_url),
            "work_type": "web_page",
        },
        source_urls=[lead.source_url],
    ))
    db.add_source(SourceRecord(
        id=wid,
        url=lead.source_url,
        title=None,
        author=None,
        platform=get_domain(lead.source_url),
        source_class=SourceClass.JOURNALISTIC,
        bias_hint=BiasHint.NEUTRAL_ISH,
    ))
    return wid


def _ensure_entity_node(
    db: GraphDB,
    name: str,
    entity_type: str,
    group_type: Optional[str],
    source_url: str = KKRON_SOURCE_URL,
) -> str:
    node_id = _ENTITY_ID_FN[entity_type](name)
    canonical = _CANONICAL_FN[entity_type](name)
    metadata = {"group_type": group_type} if (entity_type == "group" and group_type) else {}
    db.add_node(GraphNode(
        id=node_id,
        type=_NODE_TYPE_FOR[entity_type],
        label=name,
        canonical_name=canonical,
        metadata=metadata,
        source_urls=[source_url],
    ))
    return node_id


def store_kkron_claim(db: GraphDB, lead: ResearchLead) -> str:
    """Store one lead's sourced claim + its relation edge.

    Dispatches to :func:`_store_citation_claim` for a lead sourced from an
    already-known citation (``lead.source_url`` set) rather than kkron's own
    first-hand account — see :class:`ResearchLead`. Kept as a single entry
    point (same name, same call site in scripts/03_targeted_entity_research.py)
    so no other code changes are required for a new lead of either kind to be
    picked up.

    Idempotent: safe to call repeatedly (e.g. on every cron run) — node
    upserts merge metadata/labels and edge/claim-source-link inserts use
    ``INSERT OR IGNORE`` under the hood (see GraphDB), so re-running never
    duplicates data.

    Returns the claim node id.
    """
    if lead.source_url:
        return _store_citation_claim(db, lead)

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


def _store_citation_claim(db: GraphDB, lead: ResearchLead) -> str:
    """Store one lead's citation-sourced claim + its relation edge.

    Counterpart to the kkron-first-hand-account body of
    :func:`store_kkron_claim`, for a lead sourced from an already-known cited
    URL (``lead.source_url``) rather than kkron's own account: the claim is
    linked to a Work/Source node for that URL (SUPPORTED_BY, not
    ASSERTED_BY — there is no first-hand speaker to name) instead of to the
    kkron Person/Work nodes, and its confidence is stored as-is (see
    :func:`build_citation_claim_record`) rather than clamped by
    ``KKRON_CONFIDENCE_CEILING``. Still marked
    ``pending_independent_corroboration`` — a citation is a lead to verify,
    not a confirmed fact, until scripts/03_targeted_entity_research.py's
    search/crawl/extraction phase finds (or fails to find) corroboration.

    Idempotent for the same reasons as :func:`store_kkron_claim`.
    """
    wid = ensure_citation_source(db, lead)
    subject_id = _ensure_entity_node(
        db, lead.subject_name, lead.subject_type, lead.subject_group_type,
        source_url=lead.source_url,
    )
    object_id = _ensure_entity_node(
        db, lead.object_name, lead.object_type, lead.object_group_type,
        source_url=lead.source_url,
    )

    claim = build_citation_claim_record(lead)
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
            "evidence_mode": claim["evidence_mode"],
            "pending_independent_corroboration": True,
        },
        source_urls=[lead.source_url],
    ))

    # Work -> entity edges: DESCRIBES for an Event (mirrors
    # scripts/_pipeline_helpers.process_page), MENTIONS otherwise.
    for entity_id, entity_type in (
        (subject_id, lead.subject_type),
        (object_id, lead.object_type),
    ):
        rel = RelationType.DESCRIBES if entity_type == "event" else RelationType.MENTIONS
        db.add_edge(GraphEdge(src_id=wid, rel_type=rel, dst_id=entity_id,
                               metadata={"evidence": lead.source_url}))

    db.add_edge(GraphEdge(src_id=wid, rel_type=RelationType.CONTAINS, dst_id=cid,
                           metadata={"evidence": lead.source_url}))
    db.add_edge(GraphEdge(src_id=cid, rel_type=RelationType.SUPPORTED_BY, dst_id=wid,
                           metadata={"evidence": lead.source_url}))
    db.add_edge(GraphEdge(src_id=cid, rel_type=RelationType.ABOUT, dst_id=subject_id,
                           metadata={"evidence": lead.source_url}))
    db.add_edge(GraphEdge(src_id=cid, rel_type=RelationType.ABOUT, dst_id=object_id,
                           metadata={"evidence": lead.source_url}))
    db.add_claim_source_link(ClaimSourceLink(claim_id=cid, source_id=wid))

    # The relation itself (e.g. Richard Moon MENTIONS <the March 1971
    # meeting event>), tagged as coming from the cited source and not yet
    # independently verified.
    db.add_edge(GraphEdge(
        src_id=subject_id,
        rel_type=lead.relation,
        dst_id=object_id,
        metadata={
            "evidence": lead.source_url,
            "trigger": "cited_source_lead",
            "asserted_by": "cited_source",
            "verified_independently": False,
        },
    ))
    return cid
