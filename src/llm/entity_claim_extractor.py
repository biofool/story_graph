"""Gemini-powered entity, claim, and relation extraction.

Produces the same dict shape as
:class:`src.extractor.entity_extractor.EntityExtractor` so it can be a
drop-in replacement in :func:`scripts._pipeline_helpers.process_page`.

The schema sent to Gemini covers all six node types plus typed relations
in a single structured-output call, then the response is reshaped into
the per-key lists the pipeline expects.
"""

from __future__ import annotations

import hashlib
import logging
from typing import Any

from src.extractor.alias_resolver import (
    canonical_group,
    canonical_person,
    canonical_place,
    person_id,
)
from src.llm.gemini_client import GeminiClient, GeminiError
from src.utils.text_utils import stable_hash

_log = logging.getLogger(__name__)

# JSON Schema constraining Gemini's structured output. Keeps the model
# from hallucinating free-form fields. Lowercase snake_case matches the
# shape consumed by process_page.
EXTRACTION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "persons": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Canonical full name"},
                    "raw_name": {"type": "string", "description": "Name as it appears in the text"},
                    "aliases": {"type": "array", "items": {"type": "string"}},
                    "roles": {"type": "array", "items": {"type": "string"}},
                    "bio_summary": {"type": "string"},
                },
                "required": ["name", "raw_name"],
            },
        },
        "groups": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "group_type": {"type": "string", "description": "e.g. commune, restaurant, band"},
                    "founded_date": {"type": "string"},
                },
                "required": ["name"],
            },
        },
        "places": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "place_type": {"type": "string"},
                    "address": {"type": "string"},
                },
                "required": ["name"],
            },
        },
        "events": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "label": {"type": "string"},
                    "event_type": {"type": "string"},
                    "start_date": {"type": "string", "description": "ISO YYYY-MM-DD if known, else null"},
                    "end_date": {"type": "string"},
                    "description": {"type": "string"},
                },
                "required": ["label", "description"],
            },
        },
        "claims": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "text": {"type": "string", "description": "The claim sentence as it appears in the source"},
                    "claim_type": {
                        "type": "string",
                        "enum": [
                            "biographical", "abuse_allegation", "financial_control",
                            "sexual_control", "documentary_critique", "historical_dispute",
                        ],
                    },
                    "stance": {
                        "type": "string",
                        "enum": ["critical", "supportive", "neutral", "self-mythologizing"],
                    },
                    "confidence": {"type": "number"},
                    "speaker": {"type": "string", "description": "Name of the person asserting the claim, or null"},
                    "targets": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "type": {"type": "string", "enum": ["person", "group", "place"]},
                                "name": {"type": "string"},
                            },
                            "required": ["type", "name"],
                        },
                    },
                    "evidence_mode": {
                        "type": "string",
                        "enum": [
                            "first_person", "archival_clipping", "commentary",
                            "audio_tape_summary", "secondary_report",
                        ],
                    },
                },
                "required": ["text", "claim_type", "stance", "evidence_mode"],
            },
        },
        "relations": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "rel_type": {
                        "type": "string",
                        "enum": ["FOUNDED", "MEMBER_OF", "WORKED_AT", "LIVED_AT", "CREATED", "LOCATED_IN"],
                    },
                    "src": {
                        "type": "object",
                        "properties": {
                            "type": {"type": "string", "enum": ["person", "group", "place", "work"]},
                            "name": {"type": "string"},
                        },
                        "required": ["type", "name"],
                    },
                    "dst": {
                        "type": "object",
                        "properties": {
                            "type": {"type": "string", "enum": ["person", "group", "place", "work"]},
                            "name": {"type": "string"},
                        },
                        "required": ["type", "name"],
                    },
                },
                "required": ["rel_type", "src", "dst"],
            },
        },
    },
    "required": ["persons", "groups", "places", "events", "claims", "relations"],
}

_SYSTEM_INSTRUCTION = (
    "You are an information-extraction system for a property-graph pipeline "
    "about The Source Family / Father Yod (Jim Baker). Extract entities, "
    "contested claims, and typed relations from the given source text. "
    "Distinguish facts from claims: a claim is an assertion made by a "
    "speaker, with a stance (critical / supportive / neutral / "
    "self-mythologizing). Only emit relations explicitly stated in the text. "
    "Use null for unknown dates. Do not invent entities not present in the text."
)


class GeminiExtractor:
    """LLM-based entity/claim/relation extractor.

    Drop-in replacement for :class:`EntityExtractor`: ``extract(text)``
    returns the same dict shape (``persons``, ``groups``, ``places``,
    ``events``, ``claims``, ``relations``).
    """

    def __init__(self, client: GeminiClient | None = None, allow_paid: bool = False):
        self._client = client or GeminiClient()
        self._allow_paid = allow_paid
        # Cache the last extraction by text hash so a paired
        # GeminiClaimExtractor can reuse it without a second API call.
        self._cache_key: str = ""
        self._cache_val: dict[str, Any] = {}

    def is_available(self) -> bool:
        return self._client.is_available()

    def extract(self, text: str) -> dict[str, Any]:
        """Extract entities/claims/relations from text via Gemini."""
        if not text or not text.strip():
            return _empty_result()

        if not self._client.is_available():
            _log.warning("Gemini unavailable; returning empty extraction.")
            return _empty_result()

        key = hashlib.sha256(text.encode("utf-8")).hexdigest()
        if key == self._cache_key:
            return self._cache_val

        prompt = (
            "Extract entities, claims, and relations from the following "
            "source text. Return ONLY the structured JSON.\n\n"
            f"SOURCE TEXT:\n{text[:20000]}"
        )
        try:
            # TieredGeminiClient.generate_json accepts allow_paid;
            # plain GeminiClient.generate_json does not.
            if hasattr(self._client, "stats"):
                data = self._client.generate_json(
                    prompt,
                    EXTRACTION_SCHEMA,
                    allow_paid=self._allow_paid,
                    system_instruction=_SYSTEM_INSTRUCTION,
                )
            else:
                data = self._client.generate_json(
                    prompt,
                    EXTRACTION_SCHEMA,
                    system_instruction=_SYSTEM_INSTRUCTION,
                )
        except GeminiError as e:
            _log.error("Gemini extraction failed: %s", e)
            data = _empty_result()

        result = _normalize(data)
        self._cache_key = key
        self._cache_val = result
        return result


class GeminiClaimExtractor:
    """Claim extractor backed by :class:`GeminiExtractor`.

    Mirrors the interface of
    :class:`src.extractor.claim_extractor.ClaimExtractor` so it can be
    passed to :func:`process_page`. Reuses the GeminiExtractor's cached
    extraction to avoid a second API call when used alongside
    :class:`GeminiExtractor`.
    """

    def __init__(self, extractor: GeminiExtractor):
        self._extractor = extractor

    def extract_claims(self, text: str, source_url: str = "") -> list[dict]:
        entities = self._extractor.extract(text)
        enriched = []
        for claim in entities.get("claims", []):
            claim_text = claim.get("text", "")
            cid = f"claim:{stable_hash(claim_text, source_url)}"
            speaker = claim.get("speaker")
            speaker_id = person_id(speaker) if speaker else None
            enriched.append({
                "id": cid,
                "claim_text": claim_text,
                "claim_type": claim.get("claim_type", "biographical"),
                "stance": claim.get("stance", "neutral"),
                "confidence": claim.get("confidence", 0.5),
                "speaker": speaker,
                "speaker_id": speaker_id,
                "targets": claim.get("targets", []),
                "evidence_mode": claim.get("evidence_mode", "secondary_report"),
                "source_url": source_url,
            })
        return enriched

    @staticmethod
    def has_claim_verb(sentence: str) -> bool:
        """Compatibility shim; Gemini detects claims structurally."""
        return True


# --- helpers ---


def _empty_result() -> dict[str, Any]:
    return {"persons": [], "groups": [], "places": [], "events": [], "claims": [], "relations": []}


def _normalize(data: Any) -> dict[str, Any]:
    """Normalize Gemini's JSON output to the EntityExtractor shape."""
    if not isinstance(data, dict):
        return _empty_result()

    persons = []
    for p in data.get("persons", []) or []:
        if not isinstance(p, dict) or not p.get("name"):
            continue
        canonical = canonical_person(p["name"])
        persons.append({
            "name": canonical,
            "raw_name": p.get("raw_name") or p["name"],
            "source": "gemini",
            "aliases": p.get("aliases", []),
            "roles": p.get("roles", []),
            "bio_summary": p.get("bio_summary", ""),
        })

    groups = []
    for g in data.get("groups", []) or []:
        if not isinstance(g, dict) or not g.get("name"):
            continue
        canonical = canonical_group(g["name"])
        groups.append({
            "name": g["name"],
            "canonical": canonical,
            "source": "gemini",
            "group_type": g.get("group_type", ""),
            "founded_date": g.get("founded_date"),
        })

    places = []
    for pl in data.get("places", []) or []:
        if not isinstance(pl, dict) or not pl.get("name"):
            continue
        canonical = canonical_place(pl["name"])
        places.append({
            "name": pl["name"],
            "canonical": canonical,
            "source": "gemini",
            "place_type": pl.get("place_type", ""),
            "address": pl.get("address", ""),
        })

    events = []
    for ev in data.get("events", []) or []:
        if not isinstance(ev, dict) or not ev.get("label"):
            continue
        events.append({
            "label": ev["label"],
            "event_type": ev.get("event_type", "unknown"),
            "start_date": ev.get("start_date"),
            "end_date": ev.get("end_date"),
            "description": ev.get("description", ""),
        })

    claims = []
    for c in data.get("claims", []) or []:
        if not isinstance(c, dict) or not c.get("text"):
            continue
        claims.append({
            "text": c["text"],
            "claim_type": c.get("claim_type", "biographical"),
            "stance": c.get("stance", "neutral"),
            "confidence": c.get("confidence", 0.5),
            "speaker": c.get("speaker"),
            "targets": c.get("targets", []),
            "evidence_mode": c.get("evidence_mode", "secondary_report"),
        })

    relations = []
    for r in data.get("relations", []) or []:
        if not isinstance(r, dict):
            continue
        rel_type = r.get("rel_type")
        src = r.get("src")
        dst = r.get("dst")
        if not rel_type or not isinstance(src, dict) or not isinstance(dst, dict):
            continue
        relations.append({
            "rel_type": rel_type,
            "src": {"type": src.get("type", "person"), "name": src.get("name", "")},
            "dst": {"type": dst.get("type", "person"), "name": dst.get("name", "")},
        })

    return {
        "persons": persons,
        "groups": groups,
        "places": places,
        "events": events,
        "claims": claims,
        "relations": relations,
    }
