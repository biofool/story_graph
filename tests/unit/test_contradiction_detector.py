"""Unit tests for contradiction detection."""

import pytest
import tempfile
import os

from src.storage.graph_db import GraphDB
from src.storage.models import GraphNode, GraphEdge, NodeType, RelationType
from src.extractor.contradiction_detector import ContradictionDetector


@pytest.fixture
def db():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        path = f.name
    db = GraphDB(path)
    yield db
    db.close()
    os.unlink(path)


class TestContradictionDetection:
    def test_detects_opposite_stances(self, db):
        # Person node
        db.add_node(GraphNode(id="person:yod", type=NodeType.PERSON, label="Father Yod"))

        # Critical claim
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

        # Supportive claim
        db.add_node(GraphNode(
            id="claim:c2",
            type=NodeType.CLAIM,
            label="Baker was loving",
            metadata={"stance": "supportive"},
        ))
        db.add_edge(GraphEdge(
            src_id="claim:c2",
            rel_type=RelationType.ABOUT,
            dst_id="person:yod",
        ))

        detector = ContradictionDetector(db)
        contradictions = detector.detect_contradictions()
        assert len(contradictions) == 1

    def test_no_contradiction_same_stance(self, db):
        db.add_node(GraphNode(id="person:yod", type=NodeType.PERSON, label="Father Yod"))

        for i in range(2):
            db.add_node(GraphNode(
                id=f"claim:c{i}",
                type=NodeType.CLAIM,
                label=f"Claim {i}",
                metadata={"stance": "critical"},
            ))
            db.add_edge(GraphEdge(
                src_id=f"claim:c{i}",
                rel_type=RelationType.ABOUT,
                dst_id="person:yod",
            ))

        detector = ContradictionDetector(db)
        contradictions = detector.detect_contradictions()
        assert len(contradictions) == 0


class TestTimelineEdges:
    def test_precedes_ordering(self, db):
        db.add_node(GraphNode(
            id="event:e1",
            type=NodeType.EVENT,
            label="Opened restaurant",
            metadata={"start_date": "1969-01-01"},
        ))
        db.add_node(GraphNode(
            id="event:e2",
            type=NodeType.EVENT,
            label="Moved to Kauai",
            metadata={"start_date": "1974-06-01"},
        ))

        detector = ContradictionDetector(db)
        timeline = detector.build_timeline_edges()
        assert len(timeline) >= 1
        assert ("event:e1", "event:e2") in timeline
