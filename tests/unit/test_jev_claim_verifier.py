"""Tests for Jev claim verification in GeminiClaimExtractor (ticket #129).

The verifier annotates each extracted claim with a bounded
supported/contradicted/unresolved verdict — it never drops claims.
"""
import pytest

from src.llm.entity_claim_extractor import GeminiClaimExtractor
from src.llm.jev_client import JevClient, answer_confidence, verify_claim


class FakeExtractor:
    """Stands in for GeminiExtractor — returns a fixed extraction."""

    def __init__(self, claims):
        self._claims = claims

    def extract(self, text, source_url=None):
        return {"persons": [], "groups": [], "places": [], "events": [],
                "claims": self._claims, "relations": []}


class FakeJev:
    """Stands in for JevClient — returns canned answers."""

    def __init__(self, answers=None, available=True):
        self._answers = answers
        self._available = available
        self.calls = []

    def is_available(self):
        return self._available

    def decide(self, state, questions):
        self.calls.append({"state": state, "questions": questions})
        return self._answers


_CLAIMS = [
    {"text": "Father Yod founded the Source restaurant.",
     "claim_type": "biographical", "stance": "neutral",
     "evidence_mode": "secondary_report"},
    {"text": "The commune practiced free love.",
     "claim_type": "sexual_control", "stance": "critical",
     "evidence_mode": "commentary"},
]


def test_verify_claims_annotates_verdicts():
    jev = FakeJev({"verdict": {"choice": "supported", "confidence": 0.9}})
    extractor = GeminiClaimExtractor(
        FakeExtractor(_CLAIMS), verify_claims=True, jev_client=jev)
    claims = extractor.extract_claims("source text", "http://x")
    assert len(claims) == 2
    assert all(c["jev_verdict"] == "supported" for c in claims)
    assert all(c["jev_confidence"] == 0.9 for c in claims)
    assert len(jev.calls) == 2


def test_verify_disabled_by_default():
    jev = FakeJev({"verdict": {"choice": "supported", "confidence": 0.9}})
    extractor = GeminiClaimExtractor(
        FakeExtractor(_CLAIMS), verify_claims=False, jev_client=jev)
    claims = extractor.extract_claims("source text", "http://x")
    assert all("jev_verdict" not in c for c in claims)
    assert jev.calls == []


def test_verify_failure_marks_unverified():
    jev = FakeJev(available=False)
    extractor = GeminiClaimExtractor(
        FakeExtractor(_CLAIMS), verify_claims=True, jev_client=jev)
    claims = extractor.extract_claims("source text", "http://x")
    # Unavailable client → verification skipped entirely, claims intact
    assert all("jev_verdict" not in c for c in claims)


def test_verify_malformed_answer_marks_unverified():
    jev = FakeJev({"verdict": {"choice": "bogus"}})
    extractor = GeminiClaimExtractor(
        FakeExtractor(_CLAIMS), verify_claims=True, jev_client=jev)
    claims = extractor.extract_claims("source text", "http://x")
    assert all(c["jev_verdict"] == "unverified" for c in claims)


def test_verify_claim_bounded_options():
    jev = FakeJev({"verdict": {"choice": "contradicted", "confidence": 0.7}})
    result = verify_claim("claim", "source", client=jev)
    assert result == {"jev_verdict": "contradicted",
                      "jev_confidence": 0.7}
    criteria = jev.calls[0]["questions"]["verdict"]["criteria"]
    assert set(criteria) == {"supported", "contradicted", "unresolved"}


def test_verify_claim_no_client_returns_none():
    assert verify_claim("c", "s", client=JevClient(api_key="")) is None
