"""Extended unit tests for Graph Q&A edge cases (src/llm/graph_qa.py).

Covers cases not tested in test_gemini_extractors.py:
- Conflicting claims about the same person (opposing stances)
- Claims with no speaker (no ASSERTED_BY edge)
- No matching nodes for the question ("context is insufficient")
- Gemini unavailable (returns context with unavailable message)
- Very long context truncated to max_nodes limit
- GeminiError during generation
- Question with only stopword-like terms

All tests use a fake GeminiClient — no API keys or network required.
"""

from __future__ import annotations

import os
import tempfile
from typing import Any

import pytest

from src.llm.gemini_client import GeminiError
from src.llm.graph_qa import GraphQA, QAResponse
from src.storage.graph_db import GraphDB
from src.storage.models import (
    GraphEdge,
    GraphNode,
    NodeType,
    RelationType,
    SourceRecord,
)


# --- shared fake client ---


class FakeGeminiClient:
    """Fake GeminiClient that records calls and returns canned text."""

    def __init__(self, *, text="", available=True, error=None):
        self._text = text
        self._available = available
        self._error = error
        self.calls: list[dict[str, Any]] = []

    def is_available(self) -> bool:
        return self._available

    def generate_text(self, prompt, *, model=None, system_instruction=None):
        self.calls.append({"prompt": prompt, "system_instruction": system_instruction})
        if self._error:
            raise self._error
        return self._text


# --- fixture: DB with conflicting claims ---


@pytest.fixture
def conflict_db():
    """DB with two conflicting claims about the same person."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        path = f.name
    db = GraphDB(path)

    # Person
    db.add_node(GraphNode(
        id="person:yod", type=NodeType.PERSON, label="Father Yod",
        canonical_name="Father Yod",
    ))

    # Two sources
    db.add_source(SourceRecord(id="src:blog1", url="https://blog1.com", title="Blog 1"))
    db.add_source(SourceRecord(id="src:blog2", url="https://blog2.com", title="Blog 2"))

    # Work nodes for the sources
    db.add_node(GraphNode(id="src:blog1", type=NodeType.WORK, label="Blog 1"))
    db.add_node(GraphNode(id="src:blog2", type=NodeType.WORK, label="Blog 2"))

    # Claim 1: critical stance
    db.add_node(GraphNode(
        id="claim:c1", type=NodeType.CLAIM,
        label="Baker was abusive to family members.",
        metadata={
            "stance": "critical",
            "claim_text": "Baker was abusive to family members.",
            "claim_type": "behavioral",
        },
    ))
    db.add_edge(GraphEdge(src_id="claim:c1", rel_type=RelationType.ABOUT, dst_id="person:yod"))
    db.add_edge(GraphEdge(src_id="src:blog1", rel_type=RelationType.CONTAINS, dst_id="claim:c1"))

    # Claim 2: supportive stance (conflicting)
    db.add_node(GraphNode(
        id="claim:c2", type=NodeType.CLAIM,
        label="Baker was a loving father and spiritual leader.",
        metadata={
            "stance": "supportive",
            "claim_text": "Baker was a loving father and spiritual leader.",
            "claim_type": "behavioral",
        },
    ))
    db.add_edge(GraphEdge(src_id="claim:c2", rel_type=RelationType.ABOUT, dst_id="person:yod"))
    db.add_edge(GraphEdge(src_id="src:blog2", rel_type=RelationType.CONTAINS, dst_id="claim:c2"))

    # Claim with speaker (ASSERTED_BY)
    db.add_node(GraphNode(
        id="person:laura", type=NodeType.PERSON, label="Laura Garon",
    ))
    db.add_edge(GraphEdge(
        src_id="claim:c1", rel_type=RelationType.ASSERTED_BY, dst_id="person:laura",
    ))

    # Claim WITHOUT speaker (no ASSERTED_BY edge) — claim:c2 has no speaker

    yield db
    db.close()
    os.unlink(path)


# --- fixture: DB with many nodes (for truncation test) ---


@pytest.fixture
def large_db():
    """DB with many person nodes to test max_nodes truncation."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        path = f.name
    db = GraphDB(path)

    # Create 50 persons with "test" in their label
    for i in range(50):
        db.add_node(GraphNode(
            id=f"person:test{i}", type=NodeType.PERSON,
            label=f"Test Person {i}",
        ))

    yield db
    db.close()
    os.unlink(path)


# --- fixture: empty DB ---


@pytest.fixture
def empty_db():
    """DB with no nodes at all."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        path = f.name
    db = GraphDB(path)
    yield db
    db.close()
    os.unlink(path)


# ---------------------------------------------------------------------------
#  Conflicting claims
# ---------------------------------------------------------------------------


class TestConflictingClaims:
    def test_both_sides_in_context(self, conflict_db):
        """Both conflicting claims should appear in the retrieved context."""
        client = FakeGeminiClient(
            text="Sources conflict: Blog 1 says Baker was abusive, "
                 "Blog 2 says Baker was loving."
        )
        qa = GraphQA(conflict_db, client)
        result = qa.answer("Was Baker abusive?")

        claim_texts = [c["text"] for c in result.context["claims"]]
        assert "Baker was abusive to family members." in claim_texts
        assert "Baker was a loving father and spiritual leader." in claim_texts

    def test_stances_preserved(self, conflict_db):
        """Each claim's stance should be preserved in the context."""
        client = FakeGeminiClient(text="answer")
        qa = GraphQA(conflict_db, client)
        result = qa.answer("Baker")

        stances = {c["text"]: c["stance"] for c in result.context["claims"]}
        assert stances.get("Baker was abusive to family members.") == "critical"
        assert stances.get("Baker was a loving father and spiritual leader.") == "supportive"

    def test_sources_for_both_claims(self, conflict_db):
        """Sources for both conflicting claims should be in context."""
        client = FakeGeminiClient(text="answer")
        qa = GraphQA(conflict_db, client)
        result = qa.answer("Baker")

        source_urls = {s["url"] for s in result.context["sources"]}
        assert "https://blog1.com" in source_urls
        assert "https://blog2.com" in source_urls


# ---------------------------------------------------------------------------
#  Claims with no speaker
# ---------------------------------------------------------------------------


class TestNoSpeaker:
    def test_claim_without_speaker_included(self, conflict_db):
        """Claims without an ASSERTED_BY edge should still appear
        in the context without causing a KeyError."""
        client = FakeGeminiClient(text="answer")
        qa = GraphQA(conflict_db, client)
        result = qa.answer("Baker loving")

        # claim:c2 has no speaker — it should still be included
        claim_c2 = [
            c for c in result.context["claims"]
            if "loving" in c["text"]
        ]
        assert len(claim_c2) >= 1
        # speaker should be None, not raise an error
        assert claim_c2[0]["speaker"] is None

    def test_claim_with_speaker_has_speaker_id(self, conflict_db):
        """Claims WITH an ASSERTED_BY edge should have the speaker ID."""
        client = FakeGeminiClient(text="answer")
        qa = GraphQA(conflict_db, client)
        result = qa.answer("Baker abusive")

        claim_c1 = [
            c for c in result.context["claims"]
            if "abusive" in c["text"]
        ]
        assert len(claim_c1) >= 1
        assert claim_c1[0]["speaker"] == "person:laura"


# ---------------------------------------------------------------------------
#  No matching nodes / insufficient context
# ---------------------------------------------------------------------------


class TestInsufficientContext:
    def test_no_matching_nodes(self, empty_db):
        """When no nodes match, context should have empty lists."""
        client = FakeGeminiClient(text="The context is insufficient to answer.")
        qa = GraphQA(empty_db, client)
        result = qa.answer("Who was Father Yod?")

        assert result.context["matched_nodes"] == []
        assert result.context["claims"] == []
        assert result.context["sources"] == []

    def test_question_about_nonexistent_entity(self, conflict_db):
        """Asking about something not in the graph should return
        empty matches (or only partial)."""
        client = FakeGeminiClient(text="No information found.")
        qa = GraphQA(conflict_db, client)
        result = qa.answer("Who was Genghis Khan?")

        # "genghis" and "khan" are not in any node label
        assert result.context["matched_nodes"] == []


# ---------------------------------------------------------------------------
#  Gemini unavailable
# ---------------------------------------------------------------------------


class TestGeminiUnavailable:
    def test_returns_context_with_unavailable_message(self, conflict_db):
        """When Gemini is not available, should return retrieved context
        with a clear message about unavailability."""
        client = FakeGeminiClient(available=False)
        qa = GraphQA(conflict_db, client)
        result = qa.answer("Baker")

        assert "not configured" in result.answer.lower() or "unavailable" in result.answer.lower()
        # Context should still be populated even without Gemini
        assert len(result.context["claims"]) >= 1
        # No generate_text call should have been made
        assert len(client.calls) == 0


# ---------------------------------------------------------------------------
#  GeminiError during generation
# ---------------------------------------------------------------------------


class TestGeminiError:
    def test_error_returns_error_message(self, conflict_db):
        """When Gemini raises GeminiError, should return error message
        without crashing."""
        client = FakeGeminiClient(error=GeminiError("quota exceeded"))
        qa = GraphQA(conflict_db, client)
        result = qa.answer("Baker")

        assert "failed" in result.answer.lower() or "quota" in result.answer.lower()
        # Context should still be populated
        assert len(result.context["claims"]) >= 1


# ---------------------------------------------------------------------------
#  max_nodes truncation
# ---------------------------------------------------------------------------


class TestMaxNodesTruncation:
    def test_nodes_truncated_to_limit(self, large_db):
        """matched_nodes should not exceed max_nodes."""
        client = FakeGeminiClient(text="Many people found.")
        qa = GraphQA(large_db, client)
        result = qa.answer("Test Person", max_nodes=5)

        assert len(result.context["matched_nodes"]) <= 5

    def test_default_limit_applied(self, large_db):
        """Default max_nodes=25 should truncate 50 matching nodes."""
        client = FakeGeminiClient(text="answer")
        qa = GraphQA(large_db, client)
        result = qa.answer("Test Person")

        assert len(result.context["matched_nodes"]) <= 25


# ---------------------------------------------------------------------------
#  Question with short/stopword terms
# ---------------------------------------------------------------------------


class TestEdgeCaseQuestions:
    def test_very_short_question(self, conflict_db):
        """A very short question should still work without error."""
        client = FakeGeminiClient(text="answer")
        qa = GraphQA(conflict_db, client)
        result = qa.answer("a")  # Single character
        # Should not crash; may return empty or partial results
        assert isinstance(result, QAResponse)

    def test_question_with_punctuation(self, conflict_db):
        """Punctuation should be stripped from terms for matching."""
        client = FakeGeminiClient(text="answer")
        qa = GraphQA(conflict_db, client)
        result = qa.answer("Baker?")

        claim_texts = [c["text"] for c in result.context["claims"]]
        # "baker" (stripped of ?) should still match claims with "Baker"
        assert len(claim_texts) >= 1
