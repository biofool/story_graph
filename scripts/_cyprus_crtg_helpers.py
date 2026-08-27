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
   is capped at ``KKRON_CONFIDENCE_CEILING``, same rationale as other
   kkron-first-hand leads elsewhere in this project — real signal, not yet
   independent corroboration.
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

2026-08-23 update — kkron's Wikipedia Talk-page COI disclosure/proposal
--------------------------------------------------------------------------
kkron drafted (but has not posted — posting is his own action) a Talk-page
disclosure disclosing that he personally knows Richard Moon, Christopher
Thorsen, and Douglas Stone, and that he was present for an unpublished
interview that may have informed part of Keith E. Peterson's account. Per
kkron's explicit instruction, none of that personal knowledge/unpublished
interview material is usable as an article source — only two published
sources are: a 2008 case study, and Keith E. Peterson's account/book. This
adds a fourth provenance sub-kind and a couple of small schema extensions to
support it:

- **citation, pending exact identification** (``ResearchLead.source_pending_label``/
  ``source_pending_author``, used when ``source_url`` is not yet known): the
  claim is still attributed to a specific named, citable publication (not
  kkron's own account) — just one this session hasn't pinned down an exact
  title/author/URL for yet. Stored like a normal "citation" lead (same
  ``provenance()`` value, not run through the kkron confidence ceiling)
  under a ``pseudo://citation-needed/...`` placeholder Work/Source, with
  ``citation_needed: True`` recorded in both the Work node's metadata and
  the claim's metadata as an explicit TODO for a future run's SeedDiscoverer
  search to resolve. See :func:`citation_source_url` and
  :func:`ensure_citation_source`.
- **also_known_as** (``ResearchLead.subject_also_known_as``/
  ``object_also_known_as``, free text merged into the entity's node
  metadata): records alternate name spellings and which source uses which
  — e.g. Christopher Thorsen is "Chris Thorsen" in the 2008 case study but
  "Thorson" in Peterson's book. The two spellings are also cross-linked via
  ``src/extractor/alias_resolver.ALIAS_MAP`` so both canonicalize onto the
  same ``person:christopher-thorsen`` node rather than fragmenting.
- **claim_type** (``ResearchLead.claim_type``, defaults to
  ``ClaimType.BIOGRAPHICAL``): previously every "citation" lead was
  hardcoded to ``ClaimType.HISTORICAL_DISPUTE``, which fit the one
  Wikipedia-Talk-page lead that existed at the time but does not fit the
  newer biographical citation-pending leads below. The one existing
  Wikipedia Talk lead now sets ``claim_type=ClaimType.HISTORICAL_DISPUTE``
  explicitly so its stored behavior is unchanged.
- **open research gap as a lead** (still "citation" provenance, just with a
  low ``source_confidence`` and a ``role_note`` explicitly marking it as a
  TODO, not a stated fact): used for Douglas Stone's connection (or lack of
  one) to the Cyprus Fulbright Commission programme Peterson describes — no
  source has been identified yet either way. Framed this way (rather than
  inventing a fourth provenance kind) so it still flows through the normal
  ``build_search_queries``/``SeedDiscoverer`` pipeline like every other
  lead, i.e. it actually gets searched for on a real run instead of sitting
  inert as a comment.

OPEN DISAMBIGUATION FLAG — NOT RESOLVED, DO NOT ASSUME AN ANSWER
--------------------------------------------------------------------------
Peterson's account (per kkron's draft) describes an Aikido instructor named
Richard Moon, brought into the Cyprus Fulbright Commission's conflict-
resolution work by Louise Diamond. This lead necessarily creates a
``person:richard-moon`` node (full-name "Richard Moon", via the ordinary
``person_id()``/``canonical_person()`` path — no alias entry changes this).

That is the exact same node id that a *separate, unmerged* research topic in
this project (MR !3, `kkron/targeted-entity-research-1787520638` — the
Father Yod / Source Family topic) would produce for its own "Richard Moon"
leads (WORKED_AT The Source restaurant / Aware Inn / Wild Mountain Cafe,
1960s-70s Los Angeles). That earlier research separately found a modern web
presence for a "Richard Moon" who is a Quantum Aikido instructor said to
study under Robert Nadeau since 1971, and treated him there as an unrelated
namesake to the 1969 Source Family restaurant claim.

Given the Cyprus "Richard Moon" is *also* described as an Aikido instructor,
there is a real possibility this is the SAME Richard Moon as that modern
Quantum Aikido instructor — which would mean (a) the earlier "unrelated
namesake" conclusion in the Father Yod research may have been wrong, and/or
(b) this one person could bridge two currently-separate research topics
(Father Yod/Source Family and Cyprus CRTG). This is NOT resolved or asserted
here in either direction — it is flagged (in this docstring, and again as a
``role_note`` on the "Richard Moon" leads below, so it lands in the stored
claim metadata too) for a future research pass with real network access,
and it should be raised with kkron directly rather than silently assumed.
Also note: if/when both MR !3 and this MR land on main and are run against
the same graph DB, their same-named "Richard Moon" nodes will upsert-merge
into one node purely because the id scheme is name-based, regardless of
whether a human has actually confirmed they're the same person — another
reason this needs a human decision, not a silent merge.
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
    claim_type: ClaimType = ClaimType.BIOGRAPHICAL

    # Free-text alias/spelling notes merged into the subject's/object's node
    # metadata (key "also_known_as") — e.g. "aka 'Thorson' per Peterson's
    # book". Not used for ID resolution (see src/extractor/alias_resolver.py
    # ALIAS_MAP for that) — purely a human-readable provenance-of-spelling
    # note attached to the entity itself.
    subject_also_known_as: Optional[str] = None
    object_also_known_as: Optional[str] = None

    # kkron first-hand account
    kkron_claim_text: Optional[str] = None
    kkron_confidence: Optional[float] = None

    # citation-sourced (known, citable URL — not kkron's own account)
    source_url: Optional[str] = None
    source_claim_text: Optional[str] = None
    source_confidence: Optional[float] = None

    # citation-sourced, pending exact identification of the publication
    # (still not kkron's own account — attributed to a specific named
    # source, just one this session hasn't pinned an exact title/author/URL
    # for yet). Mutually exclusive with source_url in practice, but if both
    # are set source_url wins (see citation_source_url()).
    source_pending_label: Optional[str] = None
    source_pending_author: Optional[str] = None

    # public-record (well-established fact, no specific fetched URL yet)
    public_record_text: Optional[str] = None
    public_record_confidence: Optional[float] = None

    def provenance(self) -> str:
        """Which of the three provenance kinds this lead uses ("citation"
        covers both a known source_url and a pending source_pending_label —
        see module docstring's 2026-08-23 update)."""
        if self.source_url or self.source_pending_label:
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
# Two published sources kkron's 2026-08-23 disclosure draft names as the
# *only* citable sources for the "Christopher Thorsen"/"Louise Diamond"
# material (his own personal knowledge and an unpublished interview/
# recording/transcription/email correspondence are explicitly NOT to be used
# as article sources — see module docstring). Neither source's exact
# title/author/publisher/URL has been identified yet by this session — see
# "citation, pending exact identification" in the module docstring.
# ---------------------------------------------------------------------------
CYPRUS_2008_CASE_STUDY_LABEL = (
    "2008 case study on the Cyprus Conflict Resolution Trainers Group "
    "(citation TBD)"
)
PETERSON_ACCOUNT_LABEL = (
    "Keith E. Peterson's account/book describing the Cyprus Fulbright "
    "Commission's conflict-resolution and peace-building work (citation TBD)"
)
PETERSON_AUTHOR = "Keith E. Peterson"

CYPRUS_CONSORTIUM_NAME = "Cyprus Consortium"
CYPRUS_FULBRIGHT_COMMISSION_NAME = "Cyprus Fulbright Commission"

# ---------------------------------------------------------------------------
# Seed leads, per kkron (project owner) first-hand account of a forwarded
# email thread (2026-08-14 to 2026-08-16) about the Wikipedia dispute over
# the "Cyprus Conflict Resolution Trainers Group" article. Edit this list to
# add/remove targeted research targets — no other code changes are required
# for a new lead to be picked up by scripts/04_cyprus_crtg_research.py.
#
# "Richard", "Louise", and "Diana" are placeholder Person nodes: their
# surnames were not given in the forwarded email and are NOT guessed here.
# "Richard" here is an unidentified person, distinct from any similarly
# named person appearing in other, separate research topics in this
# project — do not conflate them.
# ---------------------------------------------------------------------------
DEFAULT_LEADS: list[ResearchLead] = [
    # -- kkron's own account of the dispute + who was involved ------------
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
            "distinct, unidentified person — not to be conflated with any "
            "similarly named person appearing in other, unrelated research "
            "in this project."
        ),
        kkron_confidence=0.3,
        role_note="surname unconfirmed; distinct from any similarly-named person in unrelated research",
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
        claim_type=ClaimType.HISTORICAL_DISPUTE,
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
    # -- citation-sourced (pending exact identification): kkron's ----------
    # -- 2026-08-23 Wikipedia Talk-page COI disclosure draft names two ------
    # -- published sources (a 2008 case study; Keith E. Peterson's account/-
    # -- book) as the only ones usable as article sources — NOT kkron's own
    # -- personal knowledge or the unpublished interview he mentions. See
    # -- module docstring's 2026-08-23 update for the citation-pending
    # -- mechanism and the OPEN DISAMBIGUATION flag on "Richard Moon". -----
    ResearchLead(
        subject_name="Christopher Thorsen",
        subject_type="person",
        relation=RelationType.WORKED_AT,
        object_name=CYPRUS_CONSORTIUM_NAME,
        object_type="group",
        object_group_type="conflict_resolution_consortium",
        subject_also_known_as=(
            "Also referred to as 'Chris Thorsen' in the 2008 case study "
            "(that source's spelling) and as 'Thorson' in Keith E. "
            "Peterson's account/book (a different spelling for the same "
            "person, per kkron's draft) — both spellings are also mapped "
            "to this canonical name in src/extractor/alias_resolver.py."
        ),
        source_pending_label=CYPRUS_2008_CASE_STUDY_LABEL,
        source_claim_text=(
            "A 2008 case study identifies the Cyprus Conflict Resolution "
            "Trainers Group as a body of Cypriot conflict-resolution "
            "trainers and separately records that Chris Thorsen was hired "
            "by the Cyprus Consortium in 1995 under the title 'Aikido' "
            "(instructor)."
        ),
        source_confidence=0.5,
        role_note=(
            "Job title recorded verbatim in the case study as 'Aikido' "
            "(read as Aikido instructor). Exact case study title/author/"
            "publisher not yet identified — citation needed; this is one "
            "of the leads a future run's search pipeline should actively "
            "try to resolve (see extra_queries)."
        ),
        extra_queries=(
            '"Cyprus Consortium" Thorsen 1995 Aikido',
            '"Chris Thorsen" Cyprus 1995',
            '2008 case study "Cyprus Conflict Resolution Trainers Group"',
        ),
    ),
    ResearchLead(
        subject_name="Richard Moon",
        subject_type="person",
        relation=RelationType.MEMBER_OF,
        object_name=CYPRUS_FULBRIGHT_COMMISSION_NAME,
        object_type="group",
        object_group_type="fulbright_commission_program",
        source_pending_label=PETERSON_ACCOUNT_LABEL,
        source_pending_author=PETERSON_AUTHOR,
        source_claim_text=(
            "According to Keith E. Peterson, Louise Diamond brought Aikido "
            "instructor Richard Moon and his colleague Christopher Thorsen "
            "into the Cyprus Fulbright Commission's conflict-resolution and "
            "peace-building work. Peterson describes them as working with "
            "Cypriot participants; the account does not establish that "
            "either was a member of the Cyprus Conflict Resolution "
            "Trainers Group."
        ),
        source_confidence=0.5,
        role_note=(
            "OPEN DISAMBIGUATION FLAG — NOT RESOLVED: this 'Richard Moon' "
            "(Aikido instructor per Peterson's Cyprus Fulbright Commission "
            "account) resolves to the same person:richard-moon graph node "
            "id that a separate, unmerged research topic in this project "
            "(MR !3, kkron/targeted-entity-research-1787520638 — Father "
            "Yod/Source Family) would use for its own 'Richard Moon' leads "
            "(1960s-70s Los Angeles restaurant work). That topic separately "
            "found a modern web presence for a 'Richard Moon' who is a "
            "Quantum Aikido instructor said to study under Robert Nadeau "
            "since 1971, treated there as an unrelated namesake. Since this "
            "Cyprus 'Richard Moon' is *also* an Aikido instructor, they may "
            "be the same person — which would mean that 'unrelated "
            "namesake' conclusion could be wrong, and/or that this person "
            "bridges the two topics. NOT asserted either way here; flag "
            "for a future research pass with real network access and for "
            "kkron to weigh in on directly, not a silent merge. Also "
            "distinct from the existing unconfirmed bare-first-name "
            "'Richard' placeholder lead elsewhere in this topic (surname "
            "unconfirmed there) — not asserted to be the same or a "
            "different person from that placeholder either."
        ),
        extra_queries=(
            '"Richard Moon" "Cyprus Fulbright Commission"',
            '"Richard Moon" Aikido Cyprus Louise Diamond',
        ),
    ),
    ResearchLead(
        subject_name="Christopher Thorsen",
        subject_type="person",
        relation=RelationType.MEMBER_OF,
        object_name=CYPRUS_FULBRIGHT_COMMISSION_NAME,
        object_type="group",
        object_group_type="fulbright_commission_program",
        subject_also_known_as=(
            "Also referred to as 'Chris Thorsen' in the 2008 case study "
            "and as 'Thorson' in Keith E. Peterson's account/book."
        ),
        source_pending_label=PETERSON_ACCOUNT_LABEL,
        source_pending_author=PETERSON_AUTHOR,
        source_claim_text=(
            "According to Keith E. Peterson, Louise Diamond brought Aikido "
            "instructor Richard Moon and his colleague Christopher Thorsen "
            "(referred to as 'Thorson' in Peterson's book) into the Cyprus "
            "Fulbright Commission's conflict-resolution and peace-building "
            "work. Peterson describes them as working with Cypriot "
            "participants; the account does not establish that either was "
            "a member of the Cyprus Conflict Resolution Trainers Group."
        ),
        source_confidence=0.5,
        role_note=(
            "Brought in per Louise Diamond, per Peterson's account. "
            "Explicitly does NOT establish CRTG membership — see the "
            "companion negative/scoping lead below."
        ),
        extra_queries=(
            '"Thorson" OR "Thorsen" "Cyprus Fulbright Commission"',
            '"Christopher Thorsen" Aikido Cyprus Louise Diamond',
        ),
    ),
    ResearchLead(
        subject_name="Louise Diamond",
        subject_type="person",
        relation=RelationType.MENTIONS,
        object_name="Richard Moon",
        object_type="person",
        source_pending_label=PETERSON_ACCOUNT_LABEL,
        source_pending_author=PETERSON_AUTHOR,
        source_claim_text=(
            "Per Keith E. Peterson's account, Louise Diamond brought Aikido "
            "instructor Richard Moon into the Cyprus Fulbright Commission's "
            "conflict-resolution and peace-building work."
        ),
        source_confidence=0.5,
        role_note=(
            "Distinct from the existing unconfirmed bare-first-name "
            "'Louise' placeholder lead elsewhere in this topic (surname "
            "unconfirmed there, referenced only via 'Louise's papers') — "
            "not asserted to be the same or a different person from that "
            "placeholder."
        ),
        extra_queries=('"Louise Diamond" Cyprus Fulbright Commission',),
    ),
    ResearchLead(
        subject_name="Louise Diamond",
        subject_type="person",
        relation=RelationType.MENTIONS,
        object_name="Christopher Thorsen",
        object_type="person",
        object_also_known_as=(
            "Also referred to as 'Chris Thorsen' in the 2008 case study "
            "and as 'Thorson' in Keith E. Peterson's account/book."
        ),
        source_pending_label=PETERSON_ACCOUNT_LABEL,
        source_pending_author=PETERSON_AUTHOR,
        source_claim_text=(
            "Per Keith E. Peterson's account, Louise Diamond brought Aikido "
            "instructor Christopher Thorsen (referred to as 'Thorson' in "
            "Peterson's book) into the Cyprus Fulbright Commission's "
            "conflict-resolution and peace-building work."
        ),
        source_confidence=0.5,
        extra_queries=('"Louise Diamond" Thorsen OR Thorson Cyprus',),
    ),
    ResearchLead(
        subject_name="Richard Moon",
        subject_type="person",
        relation=RelationType.MENTIONS,
        object_name=CRTG_GROUP_NAME,
        object_type="group",
        object_group_type="conflict_resolution_training_group",
        source_pending_label=PETERSON_ACCOUNT_LABEL,
        source_pending_author=PETERSON_AUTHOR,
        source_claim_text=(
            "Keith E. Peterson's account describes Richard Moon working "
            "with Cypriot participants via the Cyprus Fulbright "
            "Commission, brought in by Louise Diamond — but the account "
            "does NOT establish that Richard Moon was a member of the "
            "Cyprus Conflict Resolution Trainers Group specifically."
        ),
        source_confidence=0.5,
        role_note=(
            "NEGATIVE/SCOPING CLAIM — explicitly does NOT assert CRTG "
            "membership; recorded so the graph does not over-claim CRTG "
            "membership for Richard Moon from the Fulbright Commission "
            "facts alone. Uses MENTIONS rather than MEMBER_OF precisely "
            "because the source does not support a membership claim (see "
            "module docstring's RelationType note)."
        ),
    ),
    ResearchLead(
        subject_name="Christopher Thorsen",
        subject_type="person",
        relation=RelationType.MENTIONS,
        object_name=CRTG_GROUP_NAME,
        object_type="group",
        object_group_type="conflict_resolution_training_group",
        subject_also_known_as=(
            "Also referred to as 'Chris Thorsen' in the 2008 case study "
            "and as 'Thorson' in Keith E. Peterson's account/book."
        ),
        source_pending_label=PETERSON_ACCOUNT_LABEL,
        source_pending_author=PETERSON_AUTHOR,
        source_claim_text=(
            "Keith E. Peterson's account describes Christopher Thorsen "
            "(referred to as 'Thorson' in Peterson's book) working with "
            "Cypriot participants via the Cyprus Fulbright Commission, "
            "brought in by Louise Diamond — but the account does NOT "
            "establish that Thorsen was a member of the Cyprus Conflict "
            "Resolution Trainers Group specifically."
        ),
        source_confidence=0.5,
        role_note=(
            "NEGATIVE/SCOPING CLAIM — explicitly does NOT assert CRTG "
            "membership; see the companion Richard Moon lead above. Uses "
            "MENTIONS rather than MEMBER_OF for the same reason."
        ),
    ),
    ResearchLead(
        subject_name="Douglas Stone",
        subject_type="person",
        relation=RelationType.MENTIONS,
        object_name=CYPRUS_FULBRIGHT_COMMISSION_NAME,
        object_type="group",
        object_group_type="fulbright_commission_program",
        source_pending_label=(
            "Open research gap: search for a published source connecting "
            "Douglas Stone to the Cyprus Fulbright Commission / CRTG "
            "outside-trainer programme Peterson and the 2008 case study "
            "describe (none identified yet)"
        ),
        source_claim_text=(
            "No currently-identified reliable published source establishes "
            "that Douglas Stone served as an outside trainer in the Cyprus "
            "Fulbright Commission/CRTG programme described by Keith E. "
            "Peterson and the 2008 case study. This is recorded as an open "
            "research gap/TODO, not a stated fact in either direction, so "
            "a future run with real network access actively searches for "
            "one (see extra_queries)."
        ),
        source_confidence=0.1,
        role_note=(
            "OPEN RESEARCH GAP / TODO, not a fact claim (deliberately low "
            "confidence reflects 'no evidence found', not 'found "
            "unlikely'). Distinct from the existing kkron-sourced 'Douglas "
            "Stone MEMBER_OF Cyprus Conflict Resolution Trainers Group' "
            "lead elsewhere in this topic (kkron's own general CRTG "
            "membership account) — this lead specifically tracks whether "
            "Stone's presence in the Fulbright-Commission/Peterson-"
            "described programme is independently corroborable. Confirm "
            "or refute on a future run with live search; do not assert "
            "either way absent a source."
        ),
        extra_queries=(
            '"Douglas Stone" "Cyprus Fulbright Commission"',
            '"Douglas Stone" Peterson Cyprus conflict resolution',
            "Douglas Stone Cyprus Aikido conflict resolution trainer",
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


def citation_source_url(lead: ResearchLead) -> str:
    """The URL a "citation" lead's Work/Source record is stored under.

    ``lead.source_url`` if known; otherwise a stable ``pseudo://citation-
    needed/...`` placeholder derived from ``lead.source_pending_label`` (see
    module docstring's 2026-08-23 update — "citation, pending exact
    identification").
    """
    if lead.source_url:
        return lead.source_url
    return f"pseudo://citation-needed/{slugify(lead.source_pending_label or lead.lead_key())}"


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
            "claim_type": lead.claim_type.value,
            "stance": ClaimStance.NEUTRAL.value,
            "confidence": lead.source_confidence,
            "evidence_mode": EvidenceMode.SECONDARY_REPORT.value,
            "speaker": None,
            "speaker_id": None,
            "source_url": citation_source_url(lead),
            "citation_needed": lead.source_url is None,
        }
    if kind == "public_record":
        return {
            "id": f"claim:public-record:{lead.lead_key()}",
            "claim_text": lead.public_record_text,
            "claim_type": lead.claim_type.value,
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
        "claim_type": lead.claim_type.value,
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
            # Disclosure from kkron's 2026-08-23 draft Wikipedia Talk-page
            # COI disclosure (which he intends to post himself — this
            # project does not post to Wikipedia). Recorded here as
            # metadata/context on kkron-as-source, separate from and never
            # substituting for the citation-sourced claims in DEFAULT_LEADS
            # above — per kkron's explicit instruction, this personal
            # knowledge (and the unpublished interview/recording/
            # transcription/email correspondence it mentions) must NOT be
            # used as a source for the Wikipedia article itself; only the
            # 2008 case study and Keith E. Peterson's account/book may be
            # cited there.
            "personally_knows": ["Richard Moon", "Christopher Thorsen", "Douglas Stone"],
            "personally_knows_note": (
                "kkron discloses personally knowing Richard Moon, "
                "Christopher Thorsen, and Douglas Stone, and states he was "
                "present for an unpublished interview that may have "
                "informed part of Keith E. Peterson's account. This "
                "personal knowledge and the unpublished interview/"
                "recording/transcription/email correspondence are NOT "
                "usable as article sources (kkron's explicit instruction) "
                "— only the 2008 case study and Peterson's published "
                "account/book may be cited. Not a claim about any of the "
                "three people's CRTG/Cyprus involvement itself; see the "
                "citation-sourced leads in DEFAULT_LEADS for those."
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
    """Idempotently create the Work/Source record for a lead's cited
    publication — a known, fetchable ``lead.source_url``, or (see module
    docstring's 2026-08-23 update) a pending placeholder built from
    ``lead.source_pending_label`` when no URL is known yet. Returns the Work
    node id."""
    url = citation_source_url(lead)
    if lead.source_url:
        label = f"cited source: {lead.source_url}"
        platform = get_domain(lead.source_url)
        metadata = {"url": url, "platform": platform, "work_type": "web_page"}
        title = None
    else:
        label = f"citation pending: {lead.source_pending_label}"
        platform = "citation-pending"
        metadata = {
            "url": url,
            "platform": platform,
            "work_type": "citation_pending_placeholder",
            "citation_needed": True,
            "note": (
                "Attributed to a specific named published source, but this "
                "session has not identified its exact title/author/URL. "
                "See module docstring's 'citation, pending exact "
                "identification' note — the SeedDiscoverer/search pipeline "
                "should actively look for it (see the lead's extra_queries)."
            ),
        }
        if lead.source_pending_author:
            metadata["author"] = lead.source_pending_author
        title = lead.source_pending_label
    wid = work_id(url)
    db.add_node(GraphNode(
        id=wid,
        type=NodeType.WORK,
        label=label,
        canonical_name=None,
        metadata=metadata,
        source_urls=[url],
    ))
    db.add_source(SourceRecord(
        id=wid,
        url=url,
        title=title,
        author=lead.source_pending_author,
        platform=platform,
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
    source_url: str | None = KKRON_SOURCE_URL,
    also_known_as: Optional[str] = None,
) -> str:
    """Upsert an entity node. Pass source_url=None when the URL is a source
    for a *claim* about the entity, not for the entity itself (see GitHub #9).
    """
    node_id = _ENTITY_ID_FN[entity_type](name)
    canonical = _CANONICAL_FN[entity_type](name)
    metadata = {"group_type": group_type} if (entity_type == "group" and group_type) else {}
    if also_known_as:
        metadata["also_known_as"] = also_known_as
    db.add_node(GraphNode(
        id=node_id,
        type=_NODE_TYPE_FOR[entity_type],
        label=name,
        canonical_name=canonical,
        metadata=metadata,
        source_urls=[source_url] if source_url else [],
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
        evidence_url = citation_source_url(lead)
    elif kind == "public_record":
        wid = ensure_public_record_source(db, lead)
        evidence_url = _public_record_pseudo_url(lead)
    else:
        ensure_kkron_source(db)
        wid = KKRON_WORK_ID
        evidence_url = KKRON_SOURCE_URL

    # For kkron-sourced leads, the URL is a source for the *claim*, not for
    # the entity nodes — pass None to avoid polluting entity source_urls (#9).
    # Citation and public-record leads pass their real URL.
    entity_source_url = None if kind == "kkron" else evidence_url
    subject_id = _ensure_entity_node(
        db, lead.subject_name, lead.subject_type, lead.subject_group_type,
        source_url=entity_source_url, also_known_as=lead.subject_also_known_as,
    )
    object_id = _ensure_entity_node(
        db, lead.object_name, lead.object_type, lead.object_group_type,
        source_url=entity_source_url, also_known_as=lead.object_also_known_as,
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
    if "citation_needed" in claim:
        metadata["citation_needed"] = claim["citation_needed"]
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
