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


class TestImplicitTargetInference:
    def test_inherits_targets_from_source_work(self, db):
        """A claim with no ABOUT edges should inherit the person/group
        targets mentioned by its source work, enabling contradiction
        detection against claims that DO have explicit targets."""
        # Work node
        db.add_node(GraphNode(id="work:w1", type=NodeType.WORK, label="Blog post"))
        # Person mentioned by the work
        db.add_node(GraphNode(id="person:yod", type=NodeType.PERSON, label="Father Yod"))
        db.add_edge(GraphEdge(
            src_id="work:w1",
            rel_type=RelationType.MENTIONS,
            dst_id="person:yod",
        ))

        # Critical claim with NO explicit ABOUT target (sentence refers to
        # the subject by pronoun, like the real "Just Be Kind" claim).
        db.add_node(GraphNode(
            id="claim:crit",
            type=NodeType.CLAIM,
            label="What a mockery Just Be Kind is",
            metadata={"stance": "critical"},
        ))
        db.add_edge(GraphEdge(
            src_id="work:w1",
            rel_type=RelationType.CONTAINS,
            dst_id="claim:crit",
        ))

        # Self-mythologizing claim with an explicit ABOUT target.
        db.add_node(GraphNode(
            id="claim:myth",
            type=NodeType.CLAIM,
            label="I was the chosen one",
            metadata={"stance": "self-mythologizing"},
        ))
        db.add_edge(GraphEdge(
            src_id="work:w1",
            rel_type=RelationType.CONTAINS,
            dst_id="claim:myth",
        ))
        db.add_edge(GraphEdge(
            src_id="claim:myth",
            rel_type=RelationType.ABOUT,
            dst_id="person:yod",
        ))

        detector = ContradictionDetector(db)
        added = detector.infer_implicit_targets()
        assert added >= 1

        contradictions = detector.detect_contradictions()
        # The critical claim (now implicitly about Father Yod) should
        # contradict the self-mythologizing claim.
        assert len(contradictions) == 1

    def test_skips_claims_with_existing_about(self, db):
        """Claims that already have ABOUT edges should not get inferred ones."""
        db.add_node(GraphNode(id="work:w1", type=NodeType.WORK, label="Blog post"))
        db.add_node(GraphNode(id="person:yod", type=NodeType.PERSON, label="Father Yod"))
        db.add_node(GraphNode(id="person:other", type=NodeType.PERSON, label="Other"))
        db.add_edge(GraphEdge(src_id="work:w1", rel_type=RelationType.MENTIONS, dst_id="person:yod"))
        db.add_edge(GraphEdge(src_id="work:w1", rel_type=RelationType.MENTIONS, dst_id="person:other"))

        db.add_node(GraphNode(
            id="claim:c1",
            type=NodeType.CLAIM,
            label="Already targeted",
            metadata={"stance": "critical"},
        ))
        db.add_edge(GraphEdge(src_id="work:w1", rel_type=RelationType.CONTAINS, dst_id="claim:c1"))
        # Explicit ABOUT edge to yod only
        db.add_edge(GraphEdge(src_id="claim:c1", rel_type=RelationType.ABOUT, dst_id="person:yod"))

        detector = ContradictionDetector(db)
        added = detector.infer_implicit_targets()
        assert added == 0  # nothing inferred since claim already has ABOUT

    def test_does_not_inherit_place_targets(self, db):
        """Inference should only inherit person/group targets, not places,
        to avoid tagging every claim as being about every place mentioned."""
        db.add_node(GraphNode(id="work:w1", type=NodeType.WORK, label="Blog post"))
        db.add_node(GraphNode(id="place:kauai", type=NodeType.PLACE, label="Kauai"))
        db.add_edge(GraphEdge(src_id="work:w1", rel_type=RelationType.MENTIONS, dst_id="place:kauai"))

        db.add_node(GraphNode(
            id="claim:c1",
            type=NodeType.CLAIM,
            label="Untargeted claim",
            metadata={"stance": "critical"},
        ))
        db.add_edge(GraphEdge(src_id="work:w1", rel_type=RelationType.CONTAINS, dst_id="claim:c1"))

        detector = ContradictionDetector(db)
        added = detector.infer_implicit_targets()
        assert added == 0  # place mention not inherited


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
