"""Tests for Jev claim verification in GeminiClaimExtractor (ticket #129).

The verifier annotates each extracted claim with a bounded
supported/contradicted/unresolved verdict — it never drops claims.
Claims verified on a page are sent as one batched ``decide()`` call
when the page fits the state window; longer pages fall back to
per-claim calls with the state windowed around each claim.
"""
import pytest

from src.llm.entity_claim_extractor import GeminiClaimExtractor
from src.llm.jev_client import (
    MAX_STATE_CHARS, JevClient, answer_confidence, verify_claim, verify_claims,
)


class FakeExtractor:
    """Stands in for GeminiExtractor — returns a fixed extraction."""

    def __init__(self, claims):
        self._claims = claims

    def extract(self, text, source_url=None):
        return {"persons": [], "groups": [], "places": [], "events": [],
                "claims": self._claims, "relations": []}


class FakeJev:
    """Stands in for JevClient — answers every question with ``answer``."""

    def __init__(self, answer=None, available=True):
        self._answer = answer
        self._available = available
        self.calls = []

    def is_available(self):
        return self._available

    def decide(self, state, questions):
        self.calls.append({"state": state, "questions": questions})
        if self._answer is None:
            return None
        return {name: self._answer for name in questions}


_CLAIMS = [
    {"text": "Father Yod founded the Source restaurant.",
     "claim_type": "biographical", "stance": "neutral",
     "evidence_mode": "secondary_report"},
    {"text": "The commune practiced free love.",
     "claim_type": "sexual_control", "stance": "critical",
     "evidence_mode": "commentary"},
]


def test_verify_claims_annotates_verdicts():
    jev = FakeJev({"choice": "supported", "confidence": 0.9})
    extractor = GeminiClaimExtractor(
        FakeExtractor(_CLAIMS), verify_claims=True, jev_client=jev)
    claims = extractor.extract_claims("source text", "http://x")
    assert len(claims) == 2
    assert all(c["jev_verdict"] == "supported" for c in claims)
    assert all(c["jev_confidence"] == 0.9 for c in claims)
    assert all(c["jev_truncated"] is False for c in claims)
    # short page: claims batched into one decide() call
    assert len(jev.calls) == 1
    assert set(jev.calls[0]["questions"]) == {"c0", "c1"}


def test_verify_disabled_by_default():
    jev = FakeJev({"choice": "supported", "confidence": 0.9})
    extractor = GeminiClaimExtractor(
        FakeExtractor(_CLAIMS), verify_claims=False, jev_client=jev)
    claims = extractor.extract_claims("source text", "http://x")
    assert all("jev_verdict" not in c for c in claims)
    assert jev.calls == []


def test_verify_no_key_marks_unavailable():
    jev = FakeJev(available=False)
    extractor = GeminiClaimExtractor(
        FakeExtractor(_CLAIMS), verify_claims=True, jev_client=jev)
    claims = extractor.extract_claims("source text", "http://x")
    # enabled but no key → explicit "unavailable", distinct from
    # "unverified" (call ran, no usable answer) and from an absent field
    # (verification never enabled)
    assert all(c["jev_verdict"] == "unavailable" for c in claims)


def test_verify_malformed_answer_marks_unverified():
    jev = FakeJev({"choice": "bogus"})
    extractor = GeminiClaimExtractor(
        FakeExtractor(_CLAIMS), verify_claims=True, jev_client=jev)
    claims = extractor.extract_claims("source text", "http://x")
    assert all(c["jev_verdict"] == "unverified" for c in claims)


def test_verify_claim_bounded_options():
    jev = FakeJev({"choice": "contradicted", "confidence": 0.7})
    result = verify_claim("claim", "source", client=jev)
    assert result == {"jev_verdict": "contradicted",
                      "jev_confidence": 0.7,
                      "jev_truncated": False}
    criteria = jev.calls[0]["questions"]["verdict"]["criteria"]
    assert set(criteria) == {"supported", "contradicted", "unresolved"}


def test_verify_claim_windows_long_source_around_claim():
    claim = "Father Yod founded the Source restaurant."
    source = "x" * 20000 + " " + claim + " " + "y" * 20000
    jev = FakeJev({"choice": "supported", "confidence": 0.9})
    result = verify_claim(claim, source, client=jev)
    assert result["jev_truncated"] is True
    state = jev.calls[0]["state"]
    assert len(state) == MAX_STATE_CHARS
    assert claim in state  # window centered on the claim, not the head


def test_verify_claims_long_page_falls_back_to_per_claim():
    tail_claim = "Father Yod founded the Source restaurant."
    texts = ["An unrelated early claim.", tail_claim]
    source = "z" * 20000 + " " + tail_claim
    jev = FakeJev({"choice": "supported", "confidence": 0.5})
    out = verify_claims(texts, source, client=jev)
    assert len(out) == 2
    assert len(jev.calls) == 2  # per-claim calls, not one batch
    assert all(r["jev_truncated"] for r in out)
    assert tail_claim in jev.calls[1]["state"]


def test_verify_claim_no_client_returns_none():
    assert verify_claim("c", "s", client=JevClient(api_key="")) is None


def test_process_page_persists_jev_verdicts(tmp_path):
    """jev_* fields on extracted claims survive into claim node metadata."""
    from scripts._pipeline_helpers import process_page
    from src.crawler.web_crawler import CrawledPage
    from src.storage.graph_db import GraphDB
    from src.storage.models import NodeType

    class ClaimOnlyExtractor:
        """process_page's claim_extractor arg, backed by FakeExtractor+FakeJev."""
        def extract_claims(self, text, source_url=""):
            ex = GeminiClaimExtractor(
                FakeExtractor(_CLAIMS), verify_claims=True,
                jev_client=FakeJev({"choice": "supported", "confidence": 0.9}))
            return ex.extract_claims(text, source_url)

    db = GraphDB(str(tmp_path / "g.db"))
    try:
        page = CrawledPage(
            url="http://x/p", title="t", text="source text",
            links=[], author=None, publish_date=None, status_code=200)
        process_page(page, FakeExtractor([]), ClaimOnlyExtractor(), db)
        claims = db.get_nodes_by_type(NodeType.CLAIM)
        assert len(claims) == 2
        for node in claims:
            assert node.metadata["jev_verdict"] == "supported"
            assert node.metadata["jev_confidence"] == 0.9
            assert node.metadata["jev_truncated"] is False
    finally:
        db.close()
