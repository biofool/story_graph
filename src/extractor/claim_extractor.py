"""
Claim extraction with stance labels.
Wraps the entity extractor's claim detection and provides structured output.
"""

from __future__ import annotations

import logging

from src.extractor.alias_resolver import person_id
from src.extractor.entity_extractor import CLAIM_TRIGGERS, EntityExtractor
from src.utils.text_utils import stable_hash

_log = logging.getLogger(__name__)


class ClaimExtractor:
    """Extracts claims from text with stance labels and speaker attribution."""

    def __init__(self, extractor: EntityExtractor | None = None):
        self._extractor = extractor or EntityExtractor()

    def extract_claims(self, text: str, source_url: str = "") -> list[dict]:
        """Extract claims from text, enriched with source URL and stable IDs."""
        raw_claims = self._extractor._extract_claims(text)
        enriched = []

        for claim in raw_claims:
            cid = f"claim:{stable_hash(claim['text'], source_url)}"
            speaker_id = None
            if claim.get("speaker"):
                speaker_id = person_id(claim["speaker"], source_url or None)

            enriched.append({
                "id": cid,
                "claim_text": claim["text"],
                "claim_type": claim["claim_type"],
                "stance": claim["stance"],
                "confidence": claim["confidence"],
                "speaker": claim.get("speaker"),
                "speaker_id": speaker_id,
                "targets": claim.get("targets", []),
                "evidence_mode": claim["evidence_mode"],
                "source_url": source_url,
            })

        return enriched

    @staticmethod
    def has_claim_verb(sentence: str) -> bool:
        """Check if a sentence contains a claim trigger verb."""
        sent_lower = sentence.lower()
        return any(trigger in sent_lower for trigger in CLAIM_TRIGGERS)
