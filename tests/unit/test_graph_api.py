"""Unit tests for the graph enrichment API server (scripts/09_graph_api.py).

Uses Flask's test client against a temporary GraphDB rebuilt from an empty
snapshot, exercising every endpoint: GET /api/graph, POST /api/nodes,
/api/edges, /api/sources, /api/claims, /api/export, and GET /api/node/<id>.
"""

import importlib.util
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
SCRIPT_PATH = PROJECT_ROOT / "scripts" / "09_graph_api.py"


def _load_api_module():
    """Load scripts/09_graph_api.py as a module (filename starts with a digit)."""
    spec = importlib.util.spec_from_file_location("_graph_api_module", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


api_mod = _load_api_module()
app = api_mod.app


@pytest.fixture
def tmp_db(tmp_path):
    """Point the API server's global _DB at a fresh temp GraphDB."""
    db_path = tmp_path / "test_graph.db"
    from src.storage.graph_db import GraphDB

    db = GraphDB(db_path)
    saved_db, saved_snap = api_mod._DB, api_mod._SNAPSHOT_DIR
    api_mod._DB = db
    api_mod._SNAPSHOT_DIR = tmp_path / "snapshot"
    yield db
    db.close()
    api_mod._DB = saved_db
    api_mod._SNAPSHOT_DIR = saved_snap


@pytest.fixture
def client(tmp_db):
    app.config["TESTING"] = True
    return app.test_client()


# --- GET /api/graph ---

class TestGetGraph:
    def test_empty_graph(self, client):
        r = client.get("/api/graph")
        assert r.status_code == 200
        data = r.get_json()
        assert data["counts"] == {"nodes": 0, "edges": 0, "sources": 0}
        assert data["nodes"] == [] and data["edges"] == [] and data["sources"] == []

    def test_returns_nodes_edges_sources(self, client, tmp_db):
        from src.storage.graph_db import GraphDB
        from src.storage.models import GraphEdge, GraphNode, NodeType, RelationType, SourceRecord, SourceClass
        tmp_db.add_node(GraphNode(id="person:a", type=NodeType.PERSON, label="Person A"))
        tmp_db.add_node(GraphNode(id="group:b", type=NodeType.GROUP, label="Group B"))
        tmp_db.add_edge(GraphEdge(src_id="person:a", rel_type=RelationType.WORKED_AT, dst_id="group:b"))
        tmp_db.add_source(SourceRecord(id="source:s1", url="https://example.com", source_class=SourceClass.JOURNALISTIC))
        r = client.get("/api/graph")
        data = r.get_json()
        assert data["counts"]["nodes"] == 2
        assert data["counts"]["edges"] == 1
        assert data["counts"]["sources"] == 1
        ids = [n["id"] for n in data["nodes"]]
        assert "person:a" in ids and "group:b" in ids


# --- POST /api/nodes ---

class TestAddNode:
    def test_add_person(self, client):
        r = client.post("/api/nodes", json={"type": "Person", "label": "Test Person"})
        assert r.status_code == 200
        data = r.get_json()
        assert data["ok"] is True
        assert data["id"] == "person:test-person"
        assert data["node"]["type"] == "Person"

    def test_missing_label(self, client):
        r = client.post("/api/nodes", json={"type": "Person"})
        assert r.status_code == 400
        assert "label" in r.get_json()["error"]

    def test_invalid_type(self, client):
        r = client.post("/api/nodes", json={"type": "Alien", "label": "X"})
        assert r.status_code == 400
        assert "type" in r.get_json()["error"]

    def test_explicit_id(self, client):
        r = client.post("/api/nodes", json={"type": "Group", "label": "My Group", "id": "group:custom-id"})
        assert r.get_json()["id"] == "group:custom-id"

    def test_metadata_and_source_urls(self, client):
        r = client.post("/api/nodes", json={
            "type": "Place", "label": "Sunset Strip",
            "metadata": {"note": "test"}, "source_urls": ["https://example.com"],
        })
        data = r.get_json()
        assert data["node"]["metadata"] == {"note": "test"}
        assert data["node"]["source_urls"] == ["https://example.com"]


# --- POST /api/edges ---

class TestAddEdge:
    def test_add_edge(self, client):
        client.post("/api/nodes", json={"type": "Person", "label": "P1"})
        client.post("/api/nodes", json={"type": "Group", "label": "G1"})
        r = client.post("/api/edges", json={
            "src_id": "person:p1", "rel_type": "WORKED_AT", "dst_id": "group:g1"})
        assert r.status_code == 200
        assert r.get_json()["ok"] is True

    def test_missing_rel_type(self, client):
        client.post("/api/nodes", json={"type": "Person", "label": "P1"})
        r = client.post("/api/edges", json={"src_id": "person:p1", "dst_id": "person:p1"})
        assert r.status_code == 400

    def test_invalid_rel_type(self, client):
        client.post("/api/nodes", json={"type": "Person", "label": "P1"})
        r = client.post("/api/edges", json={"src_id": "person:p1", "rel_type": "LOVES", "dst_id": "person:p1"})
        assert r.status_code == 400

    def test_src_not_found(self, client):
        client.post("/api/nodes", json={"type": "Person", "label": "P1"})
        r = client.post("/api/edges", json={"src_id": "person:nope", "rel_type": "MENTIONS", "dst_id": "person:p1"})
        assert r.status_code == 404

    def test_dst_not_found(self, client):
        client.post("/api/nodes", json={"type": "Person", "label": "P1"})
        r = client.post("/api/edges", json={"src_id": "person:p1", "rel_type": "MENTIONS", "dst_id": "person:nope"})
        assert r.status_code == 404


# --- POST /api/sources ---

class TestAddSource:
    def test_add_source(self, client):
        r = client.post("/api/sources", json={
            "url": "https://example.com/article", "title": "An Article",
            "platform": "example.com", "source_class": "journalistic"})
        assert r.status_code == 200
        data = r.get_json()
        assert data["ok"] is True
        assert data["id"] == "source:https-example-com-article"

    def test_missing_url(self, client):
        r = client.post("/api/sources", json={"title": "No URL"})
        assert r.status_code == 400

    def test_invalid_source_class(self, client):
        r = client.post("/api/sources", json={"url": "https://x.com", "source_class": "bogus"})
        assert r.status_code == 400


# --- POST /api/claims ---

class TestAddClaim:
    def test_add_claim_with_source_url(self, client):
        client.post("/api/nodes", json={"type": "Person", "label": "Father Yod"})
        r = client.post("/api/claims", json={
            "claim_text": "He was a controversial figure.",
            "about_id": "person:father-yod",
            "stance": "critical",
            "claim_type": "biographical",
            "confidence": 0.8,
            "source_url": "https://example.com/yod",
            "source_title": "Yod Article",
        })
        assert r.status_code == 200
        data = r.get_json()
        assert data["ok"] is True
        assert data["claim_id"].startswith("claim:ui:")
        assert data["source_id"] is not None
        # Verify claim node + ABOUT edge created
        from src.storage.models import NodeType, RelationType
        claim = api_mod.get_db().get_node(data["claim_id"])
        assert claim is not None
        assert claim.type == NodeType.CLAIM
        about_edges = api_mod.get_db().get_edges_from(data["claim_id"])
        assert any(e.rel_type == RelationType.ABOUT and e.dst_id == "person:father-yod" for e in about_edges)

    def test_add_claim_with_asserted_by(self, client):
        client.post("/api/nodes", json={"type": "Person", "label": "Father Yod"})
        client.post("/api/nodes", json={"type": "Person", "label": "Witness"})
        r = client.post("/api/claims", json={
            "claim_text": "Witness saw something.",
            "about_id": "person:father-yod",
            "asserted_by_id": "person:witness",
        })
        data = r.get_json()
        assert data["asserted_by_id"] == "person:witness"
        from src.storage.models import RelationType
        edges = api_mod.get_db().get_edges_from(data["claim_id"])
        assert any(e.rel_type == RelationType.ASSERTED_BY and e.dst_id == "person:witness" for e in edges)

    def test_missing_claim_text(self, client):
        client.post("/api/nodes", json={"type": "Person", "label": "P"})
        r = client.post("/api/claims", json={"about_id": "person:p"})
        assert r.status_code == 400

    def test_missing_about_id(self, client):
        r = client.post("/api/claims", json={"claim_text": "Something."})
        assert r.status_code == 400

    def test_about_not_found(self, client):
        r = client.post("/api/claims", json={"claim_text": "X", "about_id": "person:nope"})
        assert r.status_code == 404


# --- POST /api/export ---

class TestExport:
    def test_export_writes_jsonl(self, client, tmp_db):
        client.post("/api/nodes", json={"type": "Person", "label": "Export Test"})
        r = client.post("/api/export")
        assert r.status_code == 200
        data = r.get_json()
        assert data["ok"] is True
        assert data["counts"]["nodes.jsonl"] >= 1
        snap = api_mod._SNAPSHOT_DIR
        assert (snap / "nodes.jsonl").exists()
        lines = (snap / "nodes.jsonl").read_text().splitlines()
        assert any("Export Test" in line for line in lines)


# --- GET /api/node/<id> ---

class TestNodeDetail:
    def test_node_detail(self, client):
        client.post("/api/nodes", json={"type": "Person", "label": "Detail Person"})
        r = client.get("/api/node/person:detail-person")
        assert r.status_code == 200
        data = r.get_json()
        assert data["node"]["id"] == "person:detail-person"
        assert data["node"]["label"] == "Detail Person"

    def test_node_not_found(self, client):
        r = client.get("/api/node/person:nope")
        assert r.status_code == 404


# --- GET / (index) ---

class TestIndex:
    def test_serves_html(self, client):
        r = client.get("/")
        assert r.status_code == 200
        assert b"Story Graph" in r.data
