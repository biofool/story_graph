"""
Data models for the story graph: nodes, edges, sources, and claim-source links.
"""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class NodeType(str, Enum):
    PERSON = "Person"
    GROUP = "Group"
    PLACE = "Place"
    WORK = "Work"
    EVENT = "Event"
    CLAIM = "Claim"
    IMAGE = "Image"


class RelationType(str, Enum):
    ALIAS_OF = "ALIAS_OF"
    FOUNDED = "FOUNDED"
    MEMBER_OF = "MEMBER_OF"
    WORKED_AT = "WORKED_AT"
    LIVED_AT = "LIVED_AT"
    CREATED = "CREATED"
    PUBLISHED_AT = "PUBLISHED_AT"
    DESCRIBES = "DESCRIBES"
    ABOUT = "ABOUT"
    ASSERTED_BY = "ASSERTED_BY"
    CONTRADICTS = "CONTRADICTS"
    SUPPORTED_BY = "SUPPORTED_BY"
    LOCATED_IN = "LOCATED_IN"
    PRECEDES = "PRECEDES"
    MENTIONS = "MENTIONS"
    CONTAINS = "CONTAINS"
    DEPICTS = "DEPICTS"


class ClaimStance(str, Enum):
    CRITICAL = "critical"
    SUPPORTIVE = "supportive"
    NEUTRAL = "neutral"
    SELF_MYTHOLOGIZING = "self-mythologizing"


class ClaimType(str, Enum):
    BIOGRAPHICAL = "biographical"
    ABUSE_ALLEGATION = "abuse_allegation"
    FINANCIAL_CONTROL = "financial_control"
    SEXUAL_CONTROL = "sexual_control"
    DOCUMENTARY_CRITIQUE = "documentary_critique"
    HISTORICAL_DISPUTE = "historical_dispute"


class EvidenceMode(str, Enum):
    FIRST_PERSON = "first_person"
    ARCHIVAL_CLIPPING = "archival_clipping"
    COMMENTARY = "commentary"
    AUDIO_TAPE_SUMMARY = "audio_tape_summary"
    SECONDARY_REPORT = "secondary_report"


class SourceClass(str, Enum):
    PRIMARY_FIRST_PERSON = "primary_first_person"
    ARCHIVAL = "archival"
    JOURNALISTIC = "journalistic"
    DOCUMENTARY_PROMOTIONAL = "documentary_promotional"
    COMMENT_THREAD = "comment_thread"


class BiasHint(str, Enum):
    HOSTILE = "hostile"
    DEFENSIVE = "defensive"
    NOSTALGIC = "nostalgic"
    NEUTRAL_ISH = "neutral_ish"


class GraphNode(BaseModel):
    """A node in the property graph."""
    id: str
    type: NodeType
    label: str
    canonical_name: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    source_urls: list[str] = Field(default_factory=list)


class GraphEdge(BaseModel):
    """A directed edge in the property graph."""
    src_id: str
    rel_type: RelationType
    dst_id: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class SourceRecord(BaseModel):
    """A crawled source page."""
    id: str
    url: str
    title: str | None = None
    author: str | None = None
    publish_date: str | None = None
    platform: str | None = None
    raw_text: str | None = None
    source_class: SourceClass | None = None
    bias_hint: BiasHint | None = None


class ClaimSourceLink(BaseModel):
    """Links a claim to a source with optional quote span."""
    claim_id: str
    source_id: str
    quote_span_start: int | None = None
    quote_span_end: int | None = None


# --- Reviewer verdict overlay ---------------------------------------------
#
# Verdicts are a human-judgment *overlay* on top of the machine-extracted
# graph. They are NOT part of the crawled/LLM-extracted property graph and
# are stored in their own file (graph_snapshot/verdicts.jsonl) so that
# re-running the extraction pipeline never clobbers a reviewer's work.
# See src/storage/verdict_store.py for the read/write path.

class VerdictValue(str, Enum):
    """A reviewer's judgment on whether a claim is a correct assertion."""
    CORRECT = "correct"
    INCORRECT = "incorrect"
    UNCERTAIN = "uncertain"
    PARTIALLY_CORRECT = "partially_correct"


class Verdict(BaseModel):
    """A reviewer's verdict on a single claim, with reasoning and evidence.

    One verdict per (claim_id, reviewer). Upsert semantics: re-saving a
    verdict for the same claim+reviewer updates it in place and bumps
    ``updated_at`` rather than creating a duplicate.
    """
    id: str
    claim_id: str
    verdict: VerdictValue
    confidence: float = 0.5
    """The reviewer's confidence in their own verdict (0.0–1.0)."""
    reasoning: str = ""
    evidence_urls: list[str] = Field(default_factory=list)
    """URLs the reviewer used to decide — may differ from the claim's own sources."""
    corroborating_claim_ids: list[str] = Field(default_factory=list)
    """Other graph claims that support this verdict."""
    contradicting_claim_ids: list[str] = Field(default_factory=list)
    """Other graph claims that argue against this verdict."""
    reviewer: str = "reviewer"
    created_at: str
    """ISO-8601 UTC timestamp."""
    updated_at: str
    """ISO-8601 UTC timestamp; bumped on every upsert."""
    tags: list[str] = Field(default_factory=list)
    """Freeform review tags (e.g. 'well-sourced', 'needs-followup')."""
