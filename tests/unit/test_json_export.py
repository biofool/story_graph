"""Unit tests for JSON/JSONL export + import (src/storage/json_export.py)."""

import json
import os
import tempfile
from pathlib import Path

import pytest

from src.storage.graph_db import GraphDB
from src.storage.json_export import (
    ALL_FILENAMES,
    CLAIM_SOURCES_FILENAME,
    EDGES_FILENAME,
    NODES_FILENAME,
    SOURCES_FILENAME,
    export_to_json,
    import_from_json,
    load_from_json,
    snapshot_exists,
)
from src.storage.models import (
    BiasHint,
    ClaimSourceLink,
    GraphEdge,
    GraphNode,
    NodeType,
    RelationType,
    SourceClass,
    SourceRecord,
)


@pytest.fixture
def db():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    db = GraphDB(db_path)
    yield db
    db.close()
    if os.path.exists(db_path):
        os.unlink(db_path)


def _populate(db: GraphDB) -> None:
    """Build a small, varied graph exercising every table."""
    db.add_node(GraphNode(
        id="person:a",
        type=NodeType.PERSON,
        label="Person A",
        canonical_name="person a",
        metadata={"aliases": ["A"]},
        source_urls=["https://example.com/a"],
    ))
    db.add_node(GraphNode(
        id="group:b",
        type=NodeType.GROUP,
        label="Group B",
        canonical_name="group b",
        metadata={"group_type": "restaurant"},
        source_urls=["https://example.com/b"],
    ))
    db.add_node(GraphNode(
        id="claim:c1",
        type=NodeType.CLAIM,
        label="A worked at B",
        metadata={"claim_text": "A worked at B", "confidence": 0.5},
        source_urls=["https://example.com/a"],
    ))

    db.add_edge(GraphEdge(
        src_id="person:a",
        rel_type=RelationType.WORKED_AT,
        dst_id="group:b",
        metadata={"evidence": "https://example.com/a"},
    ))
    db.add_edge(GraphEdge(
        src_id="claim:c1",
        rel_type=RelationType.ABOUT,
        dst_id="person:a",
    ))

    db.add_source(SourceRecord(
        id="work:w1",
        url="https://example.com/a",
        title="Page A",
        author="Author A",
        platform="example.com",
        raw_text="Some raw text.",
        source_class=SourceClass.JOURNALISTIC,
        bias_hint=BiasHint.NEUTRAL_ISH,
    ))

    db.add_claim_source_link(ClaimSourceLink(
        claim_id="claim:c1",
        source_id="work:w1",
        quote_span_start=0,
        quote_span_end=10,
    ))


def _snapshot(db: GraphDB) -> dict:
    """Comparable snapshot of everything GraphDB tracks."""
    return {
        "nodes": {n.id: n.model_dump(mode="json") for n in db.get_all_nodes()},
        "edges": sorted(
            (e.model_dump(mode="json") for e in db.get_all_edges()),
            key=lambda d: (d["src_id"], d["rel_type"], d["dst_id"]),
        ),
        "sources": {s.id: s.model_dump(mode="json") for s in db.get_all_sources()},
        "claim_sources": sorted(
            (c.model_dump(mode="json") for c in db.get_all_claim_source_links()),
            key=lambda d: (d["claim_id"], d["source_id"]),
        ),
    }


class TestExportToJson:
    def test_writes_all_four_files(self, db, tmp_path):
        _populate(db)
        counts = export_to_json(db, tmp_path)

        assert counts == {
            NODES_FILENAME: 3,
            EDGES_FILENAME: 2,
            SOURCES_FILENAME: 1,
            CLAIM_SOURCES_FILENAME: 1,
        }
        for fname in (NODES_FILENAME, EDGES_FILENAME, SOURCES_FILENAME, CLAIM_SOURCES_FILENAME):
            assert (tmp_path / fname).exists()

    def test_nodes_sorted_by_id(self, db, tmp_path):
        _populate(db)
        export_to_json(db, tmp_path)
        lines = (tmp_path / NODES_FILENAME).read_text().splitlines()
        ids = [json.loads(line)["id"] for line in lines]
        assert ids == sorted(ids)

    def test_export_is_deterministic_across_runs(self, db, tmp_path):
        _populate(db)
        export_to_json(db, tmp_path)
        first = {fname: (tmp_path / fname).read_text() for fname in ALL_FILENAMES}
        export_to_json(db, tmp_path)
        second = {fname: (tmp_path / fname).read_text() for fname in ALL_FILENAMES}
        assert first == second

    def test_empty_db_produces_empty_files(self, db, tmp_path):
        counts = export_to_json(db, tmp_path)
        assert all(c == 0 for c in counts.values())
        for fname in (NODES_FILENAME, EDGES_FILENAME, SOURCES_FILENAME, CLAIM_SOURCES_FILENAME):
            assert (tmp_path / fname).read_text() == ""


class TestSnapshotExists:
    def test_false_for_missing_dir(self, tmp_path):
        assert snapshot_exists(tmp_path / "nope") is False

    def test_false_for_empty_dir(self, tmp_path):
        assert snapshot_exists(tmp_path) is False

    def test_true_once_nodes_file_present(self, db, tmp_path):
        _populate(db)
        export_to_json(db, tmp_path)
        assert snapshot_exists(tmp_path) is True


class TestImportFromJson:
    def test_round_trip_matches_original(self, db, tmp_path):
        _populate(db)
        before = _snapshot(db)
        export_to_json(db, tmp_path)

        fresh_db_path = tmp_path / "rebuilt.db"
        rebuilt = import_from_json(tmp_path, fresh_db_path)
        try:
            after = _snapshot(rebuilt)
            assert after == before
        finally:
            rebuilt.close()

    def test_load_from_json_is_the_same_function(self):
        assert load_from_json is import_from_json

    def test_missing_snapshot_returns_empty_db(self, tmp_path):
        db_path = tmp_path / "fresh.db"
        empty_db = import_from_json(tmp_path / "no-such-snapshot", db_path)
        try:
            assert empty_db.get_node_count() == 0
            assert empty_db.get_edge_count() == 0
            assert empty_db.get_source_count() == 0
        finally:
            empty_db.close()

    def test_rebuilds_over_an_existing_db_file(self, db, tmp_path):
        """import_from_json always rebuilds fresh — a stale local DB at
        db_path must not leak leftover rows into the rebuilt copy."""
        _populate(db)
        export_to_json(db, tmp_path)

        db_path = tmp_path / "working.db"
        stale = GraphDB(db_path)
        stale.add_node(GraphNode(id="person:stale", type=NodeType.PERSON, label="Stale"))
        stale.close()

        rebuilt = import_from_json(tmp_path, db_path)
        try:
            assert rebuilt.get_node("person:stale") is None
            assert rebuilt.get_node_count() == 3
        finally:
            rebuilt.close()
