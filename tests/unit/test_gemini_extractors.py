"""Unit tests for the Gemini-backed seed discovery, extraction, and Q&A.

All tests use a fake GeminiClient so no network or API key is required.
"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass, field
from typing import Any

import pytest

from src.llm.gemini_client import GroundingResult
from src.llm.seed_discoverer import SeedDiscoverer
from src.llm.entity_claim_extractor import GeminiExtractor, GeminiClaimExtractor
from src.llm.graph_qa import GraphQA
from src.storage.graph_db import GraphDB
from src.storage.models import GraphNode, GraphEdge, NodeType, RelationType


# --- shared fake client ---


class FakeGeminiClient:
    """Fake GeminiClient recording calls and returning canned data."""

    def __init__(self, *, json_obj=None, grounded=None, text=""):
        self._json_obj = json_obj
        self._grounded = grounded
        self._text = text
        self.calls: list[dict[str, Any]] = []

    def is_available(self) -> bool:
        return True

    def generate_text(self, prompt, *, model=None, system_instruction=None):
        self.calls.append({"prompt": prompt, "system_instruction": system_instruction})
        return self._text

    def generate_json(self, prompt, response_schema, *, model=None, system_instruction=None):
        self.calls.append({
            "prompt": prompt, "schema": response_schema,
            "system_instruction": system_instruction,
        })
        return self._json_obj

    def generate_grounded(self, prompt, *, model=None):
        self.calls.append({"prompt": prompt})
        return self._grounded


# --- seed discovery ---


class TestSeedDiscoverer:
    def test_returns_grounded_sources_as_seeds(self):
        grounded = GroundingResult(
            text="summary",
            sources=[
                {"uri": "https://example.com/a", "title": "A"},
                {"uri": "https://example.com/b", "title": "B"},
            ],
        )
        client = FakeGeminiClient(grounded=grounded)
        disc = SeedDiscoverer(client)  # type: ignore[arg-type]
        seeds = disc.discover()
        assert len(seeds) == 2
        assert seeds[0].url == "https://example.com/a"
        assert seeds[0].title == "A"
        assert seeds[0].domain == "example.com"

    def test_filters_excluded_urls(self):
        grounded = GroundingResult(
            text="",
            sources=[
                {"uri": "https://existing.com/x", "title": "old"},
                {"uri": "https://new.com/y", "title": "new"},
            ],
        )
        client = FakeGeminiClient(grounded=grounded)
        disc = SeedDiscoverer(client)  # type: ignore[arg-type]
        seeds = disc.discover(exclude_urls={"https://existing.com/x"})
        assert len(seeds) == 1
        assert seeds[0].url == "https://new.com/y"

    def test_skips_non_http_uris(self):
        grounded = GroundingResult(
            text="",
            sources=[
                {"uri": "gemini://internal", "title": "internal"},
                {"uri": "https://good.com/z", "title": "good"},
            ],
        )
        client = FakeGeminiClient(grounded=grounded)
        disc = SeedDiscoverer(client)  # type: ignore[arg-type]
        seeds = disc.discover()
        assert len(seeds) == 1
        assert seeds[0].url == "https://good.com/z"

    def test_dedups_duplicate_urls(self):
        grounded = GroundingResult(
            text="",
            sources=[
                {"uri": "https://dup.com/a", "title": "first"},
                {"uri": "https://dup.com/a", "title": "second"},
            ],
        )
        client = FakeGeminiClient(grounded=grounded)
        disc = SeedDiscoverer(client)  # type: ignore[arg-type]
        seeds = disc.discover()
        assert len(seeds) == 1


# --- entity / claim extraction ---


_SAMPLE_EXTRACTION = {
    "persons": [
        {"name": "Jim Baker", "raw_name": "Father Yod", "aliases": ["Father Yod"], "roles": ["leader"]},
        {"name": "Isis Aquarian", "raw_name": "Isis Aquarian"},
    ],
    "groups": [
        {"name": "The Source Family", "group_type": "commune", "founded_date": "1968"},
        {"name": "Source Family", "group_type": "commune"},
    ],
    "places": [
        {"name": "Kauai", "place_type": "island"},
    ],
    "events": [
        {"label": "Opened The Source Restaurant", "event_type": "founding",
         "start_date": "1969-01-01", "description": "Baker opened the restaurant."},
    ],
    "claims": [
        {"text": "Baker withheld support from wives.",
         "claim_type": "financial_control", "stance": "critical",
         "confidence": 0.8, "speaker": "Laura Garon",
         "targets": [{"type": "person", "name": "Jim Baker"}],
         "evidence_mode": "first_person"},
    ],
    "relations": [
        {"rel_type": "FOUNDED",
         "src": {"type": "person", "name": "Jim Baker"},
         "dst": {"type": "group", "name": "The Source Restaurant"}},
        {"rel_type": "MEMBER_OF",
         "src": {"type": "person", "name": "Isis Aquarian"},
         "dst": {"type": "group", "name": "The Source Family"}},
    ],
}


class TestGeminiExtractor:
    def test_extract_returns_expected_shape(self):
        client = FakeGeminiClient(json_obj=_SAMPLE_EXTRACTION)
        ext = GeminiExtractor(client)  # type: ignore[arg-type]
        result = ext.extract("Father Yod opened The Source Restaurant.")
        assert set(result.keys()) == {"persons", "groups", "places", "events", "claims", "relations"}

    def test_persons_canonicalized_and_tagged_gemini(self):
        client = FakeGeminiClient(json_obj=_SAMPLE_EXTRACTION)
        ext = GeminiExtractor(client)  # type: ignore[arg-type]
        result = ext.extract("text")
        names = [p["name"] for p in result["persons"]]
        # "Jim Baker" -> canonical "james edward baker"
        assert "james edward baker" in names
        assert all(p["source"] == "gemini" for p in result["persons"])

    def test_groups_deduped_by_canonical(self):
        client = FakeGeminiClient(json_obj=_SAMPLE_EXTRACTION)
        ext = GeminiExtractor(client)  # type: ignore[arg-type]
        result = ext.extract("text")
        canonicals = [g["canonical"] for g in result["groups"]]
        # "The Source Family" and "Source Family" both canonicalize to
        # "the source family" — both entries kept but share a canonical,
        # matching EntityExtractor's per-page dedup behavior.
        assert "the source family" in canonicals

    def test_relations_preserved(self):
        client = FakeGeminiClient(json_obj=_SAMPLE_EXTRACTION)
        ext = GeminiExtractor(client)  # type: ignore[arg-type]
        result = ext.extract("text")
        rel_types = {r["rel_type"] for r in result["relations"]}
        assert "FOUNDED" in rel_types
        assert "MEMBER_OF" in rel_types

    def test_empty_text_returns_empty_result(self):
        client = FakeGeminiClient(json_obj=_SAMPLE_EXTRACTION)
        ext = GeminiExtractor(client)  # type: ignore[arg-type]
        assert ext.extract("") == {
            "persons": [], "groups": [], "places": [],
            "events": [], "claims": [], "relations": [],
        }

    def test_caches_by_text(self):
        client = FakeGeminiClient(json_obj=_SAMPLE_EXTRACTION)
        ext = GeminiExtractor(client)  # type: ignore[arg-type]
        ext.extract("same text")
        ext.extract("same text")
        # Only one generate_json call thanks to caching
        assert len(client.calls) == 1


class TestGeminiClaimExtractor:
    def test_extract_claims_enriches_with_id_and_speaker_id(self):
        client = FakeGeminiClient(json_obj=_SAMPLE_EXTRACTION)
        ext = GeminiExtractor(client)  # type: ignore[arg-type]
        claim_ext = GeminiClaimExtractor(ext)
        claims = claim_ext.extract_claims("text", source_url="https://x.com")
        assert len(claims) == 1
        c = claims[0]
        assert c["id"].startswith("claim:")
        assert c["source_url"] == "https://x.com"
        assert c["speaker"] == "Laura Garon"
        assert c["speaker_id"] is not None
        assert c["stance"] == "critical"

    def test_extract_claims_reuses_extractor_cache(self):
        client = FakeGeminiClient(json_obj=_SAMPLE_EXTRACTION)
        ext = GeminiExtractor(client)  # type: ignore[arg-type]
        ext.extract("shared text")  # populates cache
        claim_ext = GeminiClaimExtractor(ext)
        claim_ext.extract_claims("shared text", source_url="https://y.com")
        # No additional generate_json call beyond the first
        assert len(client.calls) == 1


# --- graph Q&A ---


@pytest.fixture
def qa_db():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        path = f.name
    db = GraphDB(path)
    # Person + a critical and a supportive claim about them.
    db.add_node(GraphNode(id="person:yod", type=NodeType.PERSON, label="Father Yod"))
    db.add_node(GraphNode(id="work:w1", type=NodeType.WORK, label="Blog"))
    db.add_source(__import__("src.storage.models", fromlist=["SourceRecord"]).SourceRecord(
        id="work:w1", url="https://blog.com/1", title="Blog post",
    ))
    for i, (cid, stance, text) in enumerate([
        ("claim:c1", "critical", "Baker was abusive."),
        ("claim:c2", "supportive", "Baker was loving."),
    ]):
        db.add_node(GraphNode(id=cid, type=NodeType.CLAIM, label=text, metadata={"stance": stance, "claim_text": text}))
        db.add_edge(GraphEdge(src_id="work:w1", rel_type=RelationType.CONTAINS, dst_id=cid))
        db.add_edge(GraphEdge(src_id=cid, rel_type=RelationType.ABOUT, dst_id="person:yod"))
    yield db
    db.close()
    os.unlink(path)


class TestGraphQA:
    def test_retrieval_matches_nodes_and_claims(self, qa_db):
        client = FakeGeminiClient(text="Baker was both abusive and loving per sources.")
        qa = GraphQA(qa_db, client)  # type: ignore[arg-type]
        result = qa.answer("What about Baker?")
        # Father Yod node matched via "baker" in canonical name? No —
        # label is "Father Yod", canonical_name is None here. Claims
        # match via "baker" in claim text.
        assert "Baker was abusive." in [c["text"] for c in result.context["claims"]]
        assert "Baker was loving." in [c["text"] for c in result.context["claims"]]
        assert result.answer == "Baker was both abusive and loving per sources."

    def test_retrieval_includes_sources(self, qa_db):
        client = FakeGeminiClient(text="answer")
        qa = GraphQA(qa_db, client)  # type: ignore[arg-type]
        result = qa.answer("Baker")
        urls = [s["url"] for s in result.context["sources"]]
        assert "https://blog.com/1" in urls

    def test_answer_records_prompt_with_context(self, qa_db):
        client = FakeGeminiClient(text="answer")
        qa = GraphQA(qa_db, client)  # type: ignore[arg-type]
        qa.answer("Baker")
        assert len(client.calls) == 1
        assert "Baker" in client.calls[0]["prompt"]
