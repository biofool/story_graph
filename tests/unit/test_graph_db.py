"""Unit tests for SQLite graph storage."""

import pytest
import tempfile
import os
from pathlib import Path

from src.storage.graph_db import GraphDB
from src.storage.models import (
    GraphNode,
    GraphEdge,
    NodeType,
    RelationType,
    SourceRecord,
    ClaimSourceLink,
    SourceClass,
    BiasHint,
)


@pytest.fixture
def db():
    """Create a temporary GraphDB."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    db = GraphDB(db_path)
    yield db
    db.close()
    os.unlink(db_path)


class TestNodeOperations:
    def test_add_and_get(self, db):
        node = GraphNode(
            id="person:test",
            type=NodeType.PERSON,
            label="Test Person",
            canonical_name="test person",
            metadata={"aliases": ["TP"]},
            source_urls=["https://example.com"],
        )
        db.add_node(node)
        retrieved = db.get_node("person:test")
        assert retrieved is not None
        assert retrieved.label == "Test Person"
        assert retrieved.canonical_name == "test person"
        assert "TP" in retrieved.metadata["aliases"]
        assert "https://example.com" in retrieved.source_urls

    def test_upsert_merges(self, db):
        node1 = GraphNode(
            id="person:test",
            type=NodeType.PERSON,
            label="Test Person",
            source_urls=["https://a.com"],
        )
        db.add_node(node1)

        node2 = GraphNode(
            id="person:test",
            type=NodeType.PERSON,
            label="Test Person Updated",
            source_urls=["https://b.com"],
        )
        db.add_node(node2)

        retrieved = db.get_node("person:test")
        assert "https://a.com" in retrieved.source_urls
        assert "https://b.com" in retrieved.source_urls

    def test_get_nonexistent(self, db):
        assert db.get_node("nonexistent") is None

    def test_get_by_type(self, db):
        for i in range(3):
            db.add_node(GraphNode(
                id=f"person:p{i}",
                type=NodeType.PERSON,
                label=f"Person {i}",
            ))
        db.add_node(GraphNode(
            id="group:g1",
            type=NodeType.GROUP,
            label="Group 1",
        ))
        persons = db.get_nodes_by_type(NodeType.PERSON)
        assert len(persons) == 3
        groups = db.get_nodes_by_type(NodeType.GROUP)
        assert len(groups) == 1


class TestEdgeOperations:
    def test_add_and_query(self, db):
        db.add_node(GraphNode(id="person:a", type=NodeType.PERSON, label="A"))
        db.add_node(GraphNode(id="group:b", type=NodeType.GROUP, label="B"))

        db.add_edge(GraphEdge(
            src_id="person:a",
            rel_type=RelationType.MEMBER_OF,
            dst_id="group:b",
        ))

        from_edges = db.get_edges_from("person:a")
        assert len(from_edges) == 1
        assert from_edges[0].rel_type == RelationType.MEMBER_OF

        to_edges = db.get_edges_to("group:b")
        assert len(to_edges) == 1

    def test_duplicate_ignored(self, db):
        db.add_node(GraphNode(id="person:a", type=NodeType.PERSON, label="A"))
        db.add_node(GraphNode(id="group:b", type=NodeType.GROUP, label="B"))

        edge = GraphEdge(
            src_id="person:a",
            rel_type=RelationType.MEMBER_OF,
            dst_id="group:b",
        )
        db.add_edge(edge)
        db.add_edge(edge)  # Should be ignored

        from_edges = db.get_edges_from("person:a")
        assert len(from_edges) == 1


class TestSourceOperations:
    def test_add_and_get(self, db):
        source = SourceRecord(
            id="work:test",
            url="https://example.com/page",
            title="Test Page",
            author="Author",
            platform="example.com",
            source_class=SourceClass.JOURNALISTIC,
            bias_hint=BiasHint.NEUTRAL_ISH,
        )
        db.add_source(source)

        retrieved = db.get_source_by_url("https://example.com/page")
        assert retrieved is not None
        assert retrieved.title == "Test Page"
        assert retrieved.source_class == SourceClass.JOURNALISTIC

    def test_get_nonexistent(self, db):
        assert db.get_source_by_url("https://nope.com") is None


class TestClaimSourceLink:
    def test_add_link(self, db):
        db.add_source(SourceRecord(id="work:w1", url="https://example.com"))
        db.add_claim_source_link(ClaimSourceLink(
            claim_id="claim:c1",
            source_id="work:w1",
        ))
        # No error means success


class TestQueryHelpers:
    def test_claims_about(self, db):
        db.add_node(GraphNode(id="person:yod", type=NodeType.PERSON, label="Father Yod"))
        db.add_node(GraphNode(
            id="claim:c1",
            type=NodeType.CLAIM,
            label="Baker was abusive",
            metadata={"stance": "critical"},
        ))
        db.add_edge(GraphEdge(
            src_id="claim:c1",
            rel_type=RelationType.ABOUT,
            dst_id="person:yod",
        ))

        claims = db.get_claims_about("person:yod")
        assert len(claims) == 1
        assert claims[0].label == "Baker was abusive"

    def test_persons_connected_to_group(self, db):
        db.add_node(GraphNode(id="person:p1", type=NodeType.PERSON, label="Person 1"))
        db.add_node(GraphNode(id="group:source", type=NodeType.GROUP, label="The Source Restaurant"))
        db.add_edge(GraphEdge(
            src_id="person:p1",
            rel_type=RelationType.WORKED_AT,
            dst_id="group:source",
        ))

        results = db.get_persons_connected_to_group("Source Restaurant")
        assert len(results) == 1
        assert results[0][0] == "Person 1"
        assert results[0][1] == "WORKED_AT"


class TestCounts:
    def test_counts(self, db):
        db.add_node(GraphNode(id="person:a", type=NodeType.PERSON, label="A"))
        db.add_node(GraphNode(id="group:b", type=NodeType.GROUP, label="B"))
        db.add_edge(GraphEdge(src_id="person:a", rel_type=RelationType.MEMBER_OF, dst_id="group:b"))
        db.add_source(SourceRecord(id="work:w1", url="https://example.com"))

        assert db.get_node_count() == 2
        assert db.get_edge_count() == 1
        assert db.get_source_count() == 1
