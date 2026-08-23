"""
Pure(ish) helpers for scripts/04_cyprus_crtg_research.py.

Kept in a separate, dash-free module — mirroring scripts/_pipeline_helpers.py
and the (currently unmerged) scripts/_targeted_research_helpers.py pattern —
because a script filename that starts with a digit (04_...) can't be imported
with a normal `import` statement. Tests and the CLI script both import from
here instead.

Two kinds of helpers live in this module:

- Pure functions/data with no I/O at all (``ResearchLead``, ``DEFAULT_LEADS``,
  ``build_search_queries``, ``effective_kkron_confidence``,
  ``build_claim_record``, ``filter_new_urls``) — covered by
  tests/unit/test_cyprus_crtg_helpers.py.
- DB-writing (but not network-calling) helpers (``ensure_kkron_source``,
  ``store_lead_claim``) that store leads using the same
  GraphDB/GraphNode/GraphEdge storage layer as scripts/_pipeline_helpers —
  covered by tests/integration/test_cyprus_crtg_pipeline.py.

PRIVACY NOTE — do not add raw email addresses here or anywhere else in this
module. The underlying source material is forwarded personal email (kkron's
own inbox), not a public web page like the rest of this project's normal
inputs. Every fact below is attributed by name only; see
``KKRON_SOURCE_LABEL``/``KKRON_SOURCE_PERSON_ID`` for how kkron's own
first-hand account is represented as a graph source.

Three provenance kinds
-----------------------
Unlike the single kkron-first-hand-account path used elsewhere in this
project so far, this module's leads come in three flavors — see
``ResearchLead`` for how each is selected:

1. **kkron first-hand account** (``kkron_claim_text``/``kkron_confidence``):
   kkron's own recollection of the forwarded email thread. Stored confidence
   is capped at ``KKRON_CONFIDENCE_CEILING``, same rationale as the Richard
   Moon leads elsewhere in this project — real signal, not yet independent
   corroboration.
2. **citation-sourced** (``source_url``/``source_claim_text``/
   ``source_confidence``): a claim tied to an already-known, citable URL —
   here, the Wikipedia Talk page documenting the dispute itself. Not
   attributed to kkron; not run through the kkron confidence ceiling.
3. **public-record** (``public_record_text``/``public_record_confidence``):
   a well-established public fact (e.g. Douglas Stone/Sheila Heen's Harvard
   Negotiation Project affiliation and "Difficult Conversations" co-
   authorship) that this module treats as independently verifiable but has
   not yet been tied to one specific fetched URL by this run (the network
   was unavailable — see scripts/04_cyprus_crtg_research.py's module
   docstring). Stored at ``public_record_confidence`` as given (not clamped
   by the kkron ceiling, since it is not kkron's own uncorroborated word),
   under a placeholder ``pseudo://`` source pending a real citing URL from a
   future search/crawl run.

No RelationType value precisely captures "training-group participant of
unconfirmed/unspecified role" or "is the subject of a Wikipedia editing
dispute". Rather than adding a new enum value to src/storage/models.py for
this one feature, MEMBER_OF and MENTIONS (already used elsewhere for
person/group participation and generic "connected to" links, respectively)
are reused as the closest existing fits — flagged here as a finding per
project convention, not a silent workaround.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from src.extractor.alias_resolver import (
    canonical_group,
    canonical_person,
    event_id,
    group_id,
    person_id,
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
from src.utils.text_utils import get_domain, slugify, stable_hash

# ---------------------------------------------------------------------------
# The "asserter" identity used for every claim that originates from kkron's
# own first-hand account. Uses the same id/label convention as the (currently
# unmerged, separate) targeted-entity-research feature so the two "kkron as a
# source" nodes upsert into a single node if/when both land on main — see
# GraphDB.add_node's upsert-by-id behavior.
# ---------------------------------------------------------------------------
KKRON_SOURCE_PERSON_ID = "person:kkron-project-owner"
KKRON_SOURCE_LABEL = "kkron (project owner, first-hand account)"

KKRON_WORK_ID = "work:kkron-personal-communication"
KKRON_SOURCE_URL = "kkron://personal-communication"

# Ceiling applied to every kkron first-hand claim's *stored* confidence, no
# matter how sure kkron says he is (see ResearchLead.kkron_confidence). This
# guarantees a first-hand, not-yet-independently-corroborated account can
# never outrank a claim that *was* corroborated by an independently found
# web source (GeminiExtractor claims can score up to 1.0).
KKRON_CONFIDENCE_CEILING = 0.5

_ENTITY_ID_FN = {
    "person": person_id,
    "group": group_id,
    "event": event_id,
    "work": lambda label: work_id(f"pseudo://cyprus-crtg-work/{slugify(label)}"),
}

_CANONICAL_FN = {
    "person": canonical_person,
    "group": canonical_group,
    # Events and (here) pseudo-URL Works have no alias-canonicalization
    # table — mirrors how scripts/_pipeline_helpers.process_page sets an
    # Event node's canonical_name straight from its label.
    "event": lambda name: name,
    "work": lambda name: name,
}

_NODE_TYPE_FOR = {
    "person": NodeType.PERSON,
    "group": NodeType.GROUP,
    "event": NodeType.EVENT,
    "work": NodeType.WORK,
}

_RELATION_SEARCH_PHRASE: dict[RelationType, str] = {
    RelationType.WORKED_AT: "worked at",
    RelationType.MEMBER_OF: "member of",
    RelationType.CREATED: "wrote",
    RelationType.MENTIONS: "mentioned in connection with",
}


@dataclass(frozen=True)
class ResearchLead:
    """One targeted (subject, relation, object) claim to corroborate.

    Exactly one of three provenance groups should be set (see module
    docstring for the rationale of each):

    - ``kkron_claim_text``/``kkron_confidence`` — kkron's own first-hand
      account. Run through :func:`effective_kkron_confidence` before being
      stored.
    - ``source_url``/``source_claim_text``/``source_confidence`` — a claim
      tied to an already-known, citable URL (here, the Wikipedia Talk page).
      Stored confidence is used as-is.
    - ``public_record_text``/``public_record_confidence`` — a well-
      established public fact not yet tied to one specific fetched URL.
      Stored confidence is used as-is (not clamped by the kkron ceiling).

    ``subject_group_type``/``object_group_type`` are optional hints (e.g.
    "conflict_resolution_training_group", "academic_program") merged into a
    Group node's metadata when the entity is created. ``role_note`` is an
    optional free-text clarification stored on the claim (e.g. "surname
    unconfirmed"; "described role is a potential ally in the Wikipedia
    dispute, not a confirmed trainer").
    """

    subject_name: str
    subject_type: str  # "person" | "group" | "event" | "work"
    relation: RelationType
    object_name: str
    object_type: str  # "person" | "group" | "event" | "work"
    subject_group_type: Optional[str] = None
    object_group_type: Optional[str] = None
    extra_queries: tuple[str, ...] = field(default_factory=tuple)
    role_note: Optional[str] = None

    # kkron first-hand account
    kkron_claim_text: Optional[str] = None
    kkron_confidence: Optional[float] = None

    # citation-sourced (known, citable URL — not kkron's own account)
    source_url: Optional[str] = None
    source_claim_text: Optional[str] = None
    source_confidence: Optional[float] = None

    # public-record (well-established fact, no specific fetched URL yet)
    public_record_text: Optional[str] = None
    public_record_confidence: Optional[float] = None

    def provenance(self) -> str:
        """Which of the three provenance kinds this lead uses."""
        if self.source_url:
            return "citation"
        if self.public_record_text is not None:
            return "public_record"
        return "kkron"

    def subject_id(self) -> str:
        return _ENTITY_ID_FN[self.subject_type](self.subject_name)

    def object_id(self) -> str:
        return _ENTITY_ID_FN[self.object_type](self.object_name)

    def lead_key(self) -> str:
        """Stable identifier for this lead, used to build the claim id."""
        return stable_hash(f"{self.subject_name}|{self.relation.value}|{self.object_name}")


# ---------------------------------------------------------------------------
# Wikipedia article under dispute (real, public, citable — see
# https://en.wikipedia.org/wiki/Talk:Cyprus_Conflict_Resolution_Trainers_Group).
# ---------------------------------------------------------------------------
CRTG_WIKIPEDIA_TALK_URL = (
    "https://en.wikipedia.org/wiki/Talk:Cyprus_Conflict_Resolution_Trainers_Group"
)
CRTG_GROUP_NAME = "Cyprus Conflict Resolution Trainers Group"
CRTG_DISPUTE_EVENT_NAME = (
    "2026 Wikipedia editing dispute over the Cyprus Conflict Resolution "
    "Trainers Group's credited trainer count"
)

# ---------------------------------------------------------------------------
# Seed leads, per kkron (project owner) first-hand account of a forwarded
# email thread (2026-08-14 to 2026-08-16) about the Wikipedia dispute over
# the "Cyprus Conflict Resolution Trainers Group" article. Edit this list to
# add/remove targeted research targets — no other code changes are required
# for a new lead to be picked up by scripts/04_cyprus_crtg_research.py.
#
# "Richard", "Louise", and "Diana" are placeholder Person nodes: their
# surnames were not given in the forwarded email and are NOT guessed here.
# "Richard" is explicitly a *different, unidentified* person from "Richard
# Moon" in the (separate, unmerged) targeted-entity-research feature —
# do not conflate them.
# ---------------------------------------------------------------------------
DEFAULT_LEADS: list[ResearchLead] = [
    # -- kkron's own account of the dispute + who was involved ------------
    ResearchLead(
        subject_name="Kenneth Kron",
        subject_type="person",
        relation=RelationType.MEMBER_OF,
        object_name=CRTG_GROUP_NAME,
        object_type="group",
        object_group_type="conflict_resolution_training_group",
        kkron_claim_text=(
            "kkron states he was himself one of the outside trainers for the "
            "Cyprus Conflict Resolution Trainers Group (CRTG), alongside "
            "roughly 30 Cypriot trainees and several other outside trainers."
        ),
        kkron_confidence=0.95,
        extra_queries=('"Kenneth Kron" Cyprus conflict resolution trainer',),
    ),
    ResearchLead(
        subject_name="Kenneth Kron",
        subject_type="person",
        relation=RelationType.MENTIONS,
        object_name=CRTG_DISPUTE_EVENT_NAME,
        object_type="event",
        kkron_claim_text=(
            "kkron states the Wikipedia article on CRTG currently credits "
            "only 4 initial trainers, which he says is inaccurate/"
            "incomplete given the group's actual size (~30 Cypriot trainees "
            "plus multiple outside trainers), and that he is disputing this "
            "with Wikipedia editors."
        ),
        kkron_confidence=0.9,
        extra_queries=(
            '"Cyprus Conflict Resolution Trainers Group" Wikipedia dispute',
        ),
    ),
    ResearchLead(
        subject_name="Douglas Stone",
        subject_type="person",
        relation=RelationType.MEMBER_OF,
        object_name=CRTG_GROUP_NAME,
        object_type="group",
        object_group_type="conflict_resolution_training_group",
        kkron_claim_text=(
            "kkron states Douglas Stone (Harvard Negotiation Project; "
            "co-author of 'Difficult Conversations') was one of the outside "
            "trainers for CRTG, per Stone's own forwarded email account."
        ),
        kkron_confidence=0.8,
        extra_queries=('"Douglas Stone" Cyprus conflict resolution training',),
    ),
    ResearchLead(
        subject_name="Sheila Heen",
        subject_type="person",
        relation=RelationType.MEMBER_OF,
        object_name=CRTG_GROUP_NAME,
        object_type="group",
        object_group_type="conflict_resolution_training_group",
        kkron_claim_text=(
            "Per Douglas Stone's forwarded email (relayed by kkron): Sheila "
            "Heen (now a professor of practice at Harvard Law School) was "
            "involved with CRTG 'as much as' Stone was, and led one of the "
            "projects at one point."
        ),
        kkron_confidence=0.75,
        role_note="led one of the projects at one point (per Stone's account)",
        extra_queries=('"Sheila Heen" Cyprus conflict resolution',),
    ),
    ResearchLead(
        subject_name="Richard",
        subject_type="person",
        relation=RelationType.MEMBER_OF,
        object_name=CRTG_GROUP_NAME,
        object_type="group",
        object_group_type="conflict_resolution_training_group",
        kkron_claim_text=(
            "kkron's forwarded email names an outside trainer/participant "
            "referred to only as 'Richard' (surname not given). This is a "
            "distinct, unidentified person — not to be conflated with "
            "'Richard Moon' from unrelated Source Family research."
        ),
        kkron_confidence=0.3,
        role_note="surname unconfirmed; distinct from 'Richard Moon' (unrelated research)",
    ),
    ResearchLead(
        subject_name="Richard",
        subject_type="person",
        relation=RelationType.MENTIONS,
        object_name="George Mason University",
        object_type="group",
        object_group_type="university",
        kkron_claim_text=(
            "kkron's forwarded email states Richard suggested having a "
            "graduate student at George Mason University review 'Louise's "
            "papers' related to the CRTG dispute."
        ),
        kkron_confidence=0.3,
        role_note="surname unconfirmed",
        extra_queries=('George Mason University conflict resolution Cyprus',),
    ),
    ResearchLead(
        subject_name="Louise",
        subject_type="person",
        relation=RelationType.MEMBER_OF,
        object_name=CRTG_GROUP_NAME,
        object_type="group",
        object_group_type="conflict_resolution_training_group",
        kkron_claim_text=(
            "kkron's forwarded email refers to 'Louise's papers' in "
            "connection with CRTG (surname not given). Her exact role is "
            "unclear from the email beyond having relevant papers."
        ),
        kkron_confidence=0.3,
        role_note="surname unconfirmed; role inferred only from 'Louise's papers'",
    ),
    ResearchLead(
        subject_name="Louise",
        subject_type="person",
        relation=RelationType.CREATED,
        object_name="Louise's papers (referenced in the CRTG Wikipedia dispute)",
        object_type="work",
        kkron_claim_text=(
            "kkron's forwarded email refers to unpublished/unspecified "
            "papers by 'Louise' that Richard suggested a George Mason "
            "University grad student review in connection with the CRTG "
            "dispute."
        ),
        kkron_confidence=0.3,
        role_note="surname unconfirmed; papers not otherwise identified in the email",
    ),
    ResearchLead(
        subject_name="Diana",
        subject_type="person",
        relation=RelationType.MEMBER_OF,
        object_name=CRTG_GROUP_NAME,
        object_type="group",
        object_group_type="conflict_resolution_training_group",
        kkron_claim_text=(
            "kkron's forwarded email names 'Diana' (surname not given) as "
            "someone who might support the Wikipedia edit kkron is pursuing. "
            "The email does not clearly establish her as a CRTG trainer or "
            "participant — this is the weakest-confidence lead in this set."
        ),
        kkron_confidence=0.15,
        role_note=(
            "surname unconfirmed; described role is a potential ally in the "
            "Wikipedia edit dispute, not a confirmed CRTG trainer/participant"
        ),
    ),
    # -- citation-sourced: the Wikipedia Talk page itself (real, public) ---
    ResearchLead(
        subject_name=CRTG_GROUP_NAME,
        subject_type="group",
        subject_group_type="conflict_resolution_training_group",
        relation=RelationType.MENTIONS,
        object_name=CRTG_DISPUTE_EVENT_NAME,
        object_type="event",
        source_url=CRTG_WIKIPEDIA_TALK_URL,
        source_claim_text=(
            "The Wikipedia Talk page for 'Cyprus Conflict Resolution "
            "Trainers Group' documents a dispute over whether the article's "
            "credited trainer count (4 initial trainers) is accurate/"
            "complete. This session could not fetch the page directly "
            "(network access to en.wikipedia.org was blocked); the URL "
            "itself is real and was supplied directly by kkron. Confirm the "
            "exact discussion content on a future run with real network "
            "access."
        ),
        source_confidence=0.55,
        extra_queries=(
            '"Cyprus Conflict Resolution Trainers Group" Wikipedia talk',
        ),
    ),
    # -- public-record: Stone/Heen's Harvard Negotiation Project / --------
    # -- "Difficult Conversations" affiliation (independently verifiable, --
    # -- distinct from kkron's own uncorroborated claims above) -----------
    ResearchLead(
        subject_name="Douglas Stone",
        subject_type="person",
        relation=RelationType.MEMBER_OF,
        object_name="Harvard Negotiation Project",
        object_type="group",
        object_group_type="academic_program",
        public_record_text=(
            "Douglas Stone is affiliated with the Harvard Negotiation "
            "Project, a well-known, independently-documented public "
            "affiliation distinct from kkron's own uncorroborated CRTG "
            "claims above."
        ),
        public_record_confidence=0.85,
        extra_queries=('"Douglas Stone" "Harvard Negotiation Project"',),
    ),
    ResearchLead(
        subject_name="Sheila Heen",
        subject_type="person",
        relation=RelationType.MEMBER_OF,
        object_name="Harvard Negotiation Project",
        object_type="group",
        object_group_type="academic_program",
        public_record_text=(
            "Sheila Heen is affiliated with the Harvard Negotiation Project, "
            "a well-known, independently-documented public affiliation."
        ),
        public_record_confidence=0.85,
        extra_queries=('"Sheila Heen" "Harvard Negotiation Project"',),
    ),
    ResearchLead(
        subject_name="Sheila Heen",
        subject_type="person",
        relation=RelationType.WORKED_AT,
        object_name="Harvard Law School",
        object_type="group",
        object_group_type="academic_institution",
        public_record_text=(
            "Sheila Heen is a professor of practice at Harvard Law School, "
            "a well-known, independently-documented public fact."
        ),
        public_record_confidence=0.85,
        extra_queries=('"Sheila Heen" "Harvard Law School" professor',),
    ),
    ResearchLead(
        subject_name="Douglas Stone",
        subject_type="person",
        relation=RelationType.CREATED,
        object_name="Difficult Conversations",
        object_type="work",
        public_record_text=(
            "Douglas Stone co-authored the book 'Difficult Conversations', "
            "a well-known, independently-documented public fact."
        ),
        public_record_confidence=0.85,
        extra_queries=('"Douglas Stone" "Difficult Conversations" book',),
    ),
    ResearchLead(
        subject_name="Sheila Heen",
        subject_type="person",
        relation=RelationType.CREATED,
        object_name="Difficult Conversations",
        object_type="work",
        public_record_text=(
            "Sheila Heen co-authored the book 'Difficult Conversations', "
            "a well-known, independently-documented public fact."
        ),
        public_record_confidence=0.85,
        extra_queries=('"Sheila Heen" "Difficult Conversations" book',),
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


def build_claim_record(lead: ResearchLead) -> dict:
    """Build the claim dict for a lead, dispatching on its provenance kind
    (see :meth:`ResearchLead.provenance`).

    Shape mirrors the enriched claim dicts produced by
    ``GeminiClaimExtractor.extract_claims`` / ``ClaimExtractor.extract_claims``
    (id, claim_text, claim_type, stance, confidence, speaker, speaker_id,
    evidence_mode, source_url) so it stores the same way any other claim
    does; see :func:`store_lead_claim`.
    """
    kind = lead.provenance()
    if kind == "citation":
        return {
            "id": f"claim:citation:{lead.lead_key()}",
            "claim_text": lead.source_claim_text,
            "claim_type": ClaimType.HISTORICAL_DISPUTE.value,
            "stance": ClaimStance.NEUTRAL.value,
            "confidence": lead.source_confidence,
            "evidence_mode": EvidenceMode.SECONDARY_REPORT.value,
            "speaker": None,
            "speaker_id": None,
            "source_url": lead.source_url,
        }
    if kind == "public_record":
        return {
            "id": f"claim:public-record:{lead.lead_key()}",
            "claim_text": lead.public_record_text,
            "claim_type": ClaimType.BIOGRAPHICAL.value,
            "stance": ClaimStance.NEUTRAL.value,
            "confidence": lead.public_record_confidence,
            "evidence_mode": EvidenceMode.SECONDARY_REPORT.value,
            "speaker": None,
            "speaker_id": None,
            "source_url": _public_record_pseudo_url(lead),
        }
    # kkron first-hand account
    return {
        "id": f"claim:kkron:{lead.lead_key()}",
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


def _public_record_pseudo_url(lead: ResearchLead) -> str:
    """Placeholder pseudo-URL for a public-record lead pending a real citing
    URL from a future search/crawl run (see module docstring)."""
    return f"pseudo://public-record/{slugify(lead.lead_key())}"


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
# DB-writing helpers (no network calls).
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
                "Project owner's first-hand personal account (forwarded "
                "email, not a public web source). Claims ASSERTED_BY this "
                f"node are capped at confidence <= {KKRON_CONFIDENCE_CEILING} "
                "until independently corroborated."
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
    (``lead.source_url``). Returns the Work node id."""
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


def ensure_public_record_source(db: GraphDB, lead: ResearchLead) -> str:
    """Idempotently create a placeholder Work/Source record for a
    public-record lead that has no specific fetched URL yet (see module
    docstring). Returns the Work node id."""
    pseudo_url = _public_record_pseudo_url(lead)
    wid = work_id(pseudo_url)
    db.add_node(GraphNode(
        id=wid,
        type=NodeType.WORK,
        label=f"public record (pending citation): {lead.object_name}",
        canonical_name=None,
        metadata={
            "url": pseudo_url,
            "work_type": "public_record_placeholder",
            "note": (
                "Well-established public fact not yet tied to a specific "
                "fetched URL by this run — see "
                "scripts/_cyprus_crtg_helpers.py module docstring."
            ),
        },
        source_urls=[pseudo_url],
    ))
    db.add_source(SourceRecord(
        id=wid,
        url=pseudo_url,
        title=f"public record (pending citation): {lead.object_name}",
        author=None,
        platform="public-record-placeholder",
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


def store_lead_claim(db: GraphDB, lead: ResearchLead) -> str:
    """Store one lead's claim + its relation edge, dispatching on the
    lead's provenance kind (see :meth:`ResearchLead.provenance`).

    Idempotent: safe to call repeatedly (e.g. on every cron run) — node
    upserts merge metadata/labels and edge/claim-source-link inserts use
    ``INSERT OR IGNORE`` under the hood (see GraphDB), so re-running never
    duplicates data.

    Returns the claim node id.
    """
    kind = lead.provenance()
    if kind == "citation":
        wid = ensure_citation_source(db, lead)
        evidence_url = lead.source_url
    elif kind == "public_record":
        wid = ensure_public_record_source(db, lead)
        evidence_url = _public_record_pseudo_url(lead)
    else:
        ensure_kkron_source(db)
        wid = KKRON_WORK_ID
        evidence_url = KKRON_SOURCE_URL

    subject_id = _ensure_entity_node(
        db, lead.subject_name, lead.subject_type, lead.subject_group_type,
        source_url=evidence_url,
    )
    object_id = _ensure_entity_node(
        db, lead.object_name, lead.object_type, lead.object_group_type,
        source_url=evidence_url,
    )

    claim = build_claim_record(lead)
    cid = claim["id"]
    metadata = {
        "claim_text": claim["claim_text"],
        "claim_type": claim["claim_type"],
        "stance": claim["stance"],
        "confidence": claim["confidence"],
        "evidence_mode": claim["evidence_mode"],
        "pending_independent_corroboration": True,
        "provenance": kind,
    }
    if "raw_kkron_confidence" in claim:
        metadata["raw_kkron_confidence"] = claim["raw_kkron_confidence"]
    if lead.role_note:
        metadata["role_note"] = lead.role_note

    db.add_node(GraphNode(
        id=cid,
        type=NodeType.CLAIM,
        label=claim["claim_text"][:200],
        canonical_name=None,
        metadata=metadata,
        source_urls=[evidence_url],
    ))

    # Work -> entity edges: DESCRIBES for an Event (mirrors
    # scripts/_pipeline_helpers.process_page), MENTIONS otherwise.
    for entity_id, entity_type in (
        (subject_id, lead.subject_type),
        (object_id, lead.object_type),
    ):
        rel = RelationType.DESCRIBES if entity_type == "event" else RelationType.MENTIONS
        db.add_edge(GraphEdge(src_id=wid, rel_type=rel, dst_id=entity_id,
                               metadata={"evidence": evidence_url}))

    db.add_edge(GraphEdge(src_id=wid, rel_type=RelationType.CONTAINS, dst_id=cid,
                           metadata={"evidence": evidence_url}))
    if kind == "kkron":
        db.add_edge(GraphEdge(src_id=cid, rel_type=RelationType.ASSERTED_BY, dst_id=KKRON_SOURCE_PERSON_ID,
                               metadata={"evidence": evidence_url}))
    else:
        db.add_edge(GraphEdge(src_id=cid, rel_type=RelationType.SUPPORTED_BY, dst_id=wid,
                               metadata={"evidence": evidence_url}))
    db.add_edge(GraphEdge(src_id=cid, rel_type=RelationType.ABOUT, dst_id=subject_id,
                           metadata={"evidence": evidence_url}))
    db.add_edge(GraphEdge(src_id=cid, rel_type=RelationType.ABOUT, dst_id=object_id,
                           metadata={"evidence": evidence_url}))
    db.add_claim_source_link(ClaimSourceLink(claim_id=cid, source_id=wid))

    # The relation itself (e.g. Douglas Stone MEMBER_OF CRTG), tagged with
    # its provenance and not yet independently verified. A later
    # independent-source relation edge with the same (src, rel, dst) is a
    # no-op thanks to the UNIQUE(src_id, rel_type, dst_id) constraint — the
    # *claim* is what carries the confidence distinction, not the edge.
    db.add_edge(GraphEdge(
        src_id=subject_id,
        rel_type=lead.relation,
        dst_id=object_id,
        metadata={
            "evidence": evidence_url,
            "trigger": f"{kind}_lead",
            "verified_independently": False,
        },
    ))
    return cid
