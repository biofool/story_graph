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


# --- POST /api/node/<id>/mark_not_connected ---

class TestNotConnected:
    def test_mark_not_connected(self, client):
        client.post("/api/nodes", json={"type": "Person", "label": "Test NC"})
        r = client.post("/api/node/person:test-nc/mark_not_connected")
        assert r.status_code == 200
        data = r.get_json()
        assert data["ok"] is True
        assert data["not_connected"] is True
        # Verify metadata was updated
        r2 = client.get("/api/node/person:test-nc")
        node = r2.get_json()["node"]
        assert node["metadata"]["not_connected"] is True
        assert "not_connected_set_at" in node["metadata"]

    def test_unmark_not_connected(self, client):
        client.post("/api/nodes", json={"type": "Person", "label": "Test NC2"})
        client.post("/api/node/person:test-nc2/mark_not_connected")
        r = client.post("/api/node/person:test-nc2/unmark_not_connected")
        assert r.status_code == 200
        data = r.get_json()
        assert data["ok"] is True
        assert data["not_connected"] is False
        # Verify flag removed
        r2 = client.get("/api/node/person:test-nc2")
        node = r2.get_json()["node"]
        assert "not_connected" not in node["metadata"]
        assert "not_connected_set_at" not in node["metadata"]

    def test_mark_not_connected_node_not_found(self, client):
        r = client.post("/api/node/person:nope/mark_not_connected")
        assert r.status_code == 404

    def test_not_connected_flag_in_graph_payload(self, client, tmp_db):
        from src.storage.models import GraphNode, NodeType
        tmp_db.add_node(GraphNode(
            id="person:nc-test", type=NodeType.PERSON, label="NC Test",
            metadata={"not_connected": True},
        ))
        r = client.get("/api/graph")
        node = next(n for n in r.get_json()["nodes"] if n["id"] == "person:nc-test")
        assert node["not_connected"] is True

    def test_mark_not_connected_preserves_existing_metadata(self, client):
        client.post("/api/nodes", json={
            "type": "Person", "label": "Meta Person",
            "metadata": {"description": "important", "birth_date": "1969-05"},
        })
        r = client.post("/api/node/person:meta-person/mark_not_connected")
        assert r.status_code == 200
        r2 = client.get("/api/node/person:meta-person")
        meta = r2.get_json()["node"]["metadata"]
        assert meta["not_connected"] is True
        assert meta["description"] == "important"
        assert meta["birth_date"] == "1969-05"

    def test_mark_not_connected_idempotent(self, client):
        client.post("/api/nodes", json={"type": "Person", "label": "Idem NC"})
        client.post("/api/node/person:idem-nc/mark_not_connected")
        # Second mark should succeed and not duplicate keys
        r = client.post("/api/node/person:idem-nc/mark_not_connected")
        assert r.status_code == 200
        meta = client.get("/api/node/person:idem-nc").get_json()["node"]["metadata"]
        assert meta["not_connected"] is True
        assert "not_connected_set_at" in meta

    def test_unmark_not_connected_idempotent(self, client):
        client.post("/api/nodes", json={"type": "Person", "label": "Idem NC2"})
        # Unmark without first marking — should succeed
        r = client.post("/api/node/person:idem-nc2/unmark_not_connected")
        assert r.status_code == 200
        meta = client.get("/api/node/person:idem-nc2").get_json()["node"]["metadata"]
        assert "not_connected" not in meta


# --- Issue #10: route ambiguity — <path:node_id> must not swallow suffixes ---

class TestRouteDisambiguation:
    """Issue #10: the mark/unmark routes used the greedy ``<path:>`` converter,
    which matches slashes. A node id containing ``/mark_not_connected`` would be
    misrouted. Node ids follow ``type:slug`` and never contain slashes, so the
    routes should use the plain string converter (no slashes) instead.
    """

    def test_node_routes_use_string_converter_not_path(self):
        rules = {r.rule for r in app.url_map.iter_rules()}
        assert "/api/node/<node_id>" in rules
        assert "/api/node/<node_id>/mark_not_connected" in rules
        assert "/api/node/<node_id>/unmark_not_connected" in rules
        # No node route should use the greedy <path:node_id> converter.
        assert not any("<path:node_id>" in r for r in rules)

    def test_mark_not_connected_path_not_swallowed_by_detail_route(self, client):
        """A GET against the mark_not_connected path must NOT be silently handled
        by the detail route (which would treat ``<id>/mark_not_connected`` as a
        single node id and return a misleading 404).

        With the string converter the only rule matching the path is the
        POST-only mark route, so a GET yields 405 Method Not Allowed. With the
        old ``<path:>`` converter the detail route would match and return 404.
        """
        client.post("/api/nodes", json={"type": "Person", "label": "Foo"})
        r = client.get("/api/node/person:foo/mark_not_connected")
        assert r.status_code == 405

    def test_node_id_with_slash_is_not_a_valid_detail_path(self, client):
        """A node id containing a slash can never exist (ids are ``type:slug``),
        and the routing layer must not treat ``person:foo/bar`` as a single
        ``<path:node_id>``. With the string converter no rule matches, so the
        request 404s at the routing layer rather than reaching the detail
        handler with a fabricated slash-containing id.
        """
        r = client.get("/api/node/person:foo/bar")
        assert r.status_code == 404


# --- GET / (index) ---

class TestIndex:
    def test_serves_html(self, client):
        r = client.get("/")
        assert r.status_code == 200
        assert b"Story Graph" in r.data


# --- Image nodes / badges / media routes ---

def _add_image(db, work_id: str, content_hash: str = "a" * 64, alt: str = "a photo"):
    from src.storage.models import GraphEdge, GraphNode, NodeType, RelationType

    image_id = f"image:{content_hash}"
    db.add_node(GraphNode(
        id=image_id, type=NodeType.IMAGE, label=alt,
        metadata={"original_url": "https://example.com/x.jpg",
                  "content_hash": content_hash, "mime": "image/jpeg",
                  "width": 400, "height": 300, "alt": alt},
        source_urls=["https://example.com/page"],
    ))
    db.add_edge(GraphEdge(src_id=work_id, rel_type=RelationType.DEPICTS, dst_id=image_id))
    return image_id


class TestImages:
    def test_image_nodes_excluded_from_graph_canvas(self, client, tmp_db):
        from src.storage.models import GraphNode, NodeType
        tmp_db.add_node(GraphNode(id="work:w1", type=NodeType.WORK, label="Page"))
        _add_image(tmp_db, "work:w1")
        r = client.get("/api/graph")
        data = r.get_json()
        ids = [n["id"] for n in data["nodes"]]
        assert "work:w1" in ids
        assert not any(n["group"] == "Image" for n in data["nodes"])
        assert data["counts"]["nodes"] == 1

    def test_has_images_badge(self, client, tmp_db):
        from src.storage.models import GraphNode, NodeType
        tmp_db.add_node(GraphNode(id="work:w1", type=NodeType.WORK, label="Page"))
        _add_image(tmp_db, "work:w1")
        r = client.get("/api/graph")
        node = next(n for n in r.get_json()["nodes"] if n["id"] == "work:w1")
        assert node["has_images"] is True
        assert node["image_count"] == 1

    def test_node_detail_includes_images(self, client, tmp_db):
        from src.storage.models import GraphNode, NodeType
        tmp_db.add_node(GraphNode(id="work:w1", type=NodeType.WORK, label="Page"))
        image_id = _add_image(tmp_db, "work:w1", content_hash="b" * 64, alt="caption text")
        r = client.get("/api/node/work:w1")
        data = r.get_json()
        assert len(data["images"]) == 1
        img = data["images"][0]
        assert img["alt"] == "caption text"
        assert img["thumb_url"] == "/media/thumb/" + "b" * 64
        assert img["full_url"] == "/media/image/" + "b" * 64
        # DEPICTS edges shouldn't also show up in the generic connections list
        assert not any(e.get("dst_id") == image_id for e in data["edges"])

    def test_media_thumb_rejects_bad_hash(self, client):
        r = client.get("/media/thumb/not-a-hash")
        assert r.status_code == 400

    def test_media_thumb_404_when_missing(self, client):
        r = client.get("/media/thumb/" + "c" * 64)
        assert r.status_code == 404

    def test_media_image_404_when_missing(self, client):
        r = client.get("/media/image/" + "c" * 64)
        assert r.status_code == 404

    def test_media_thumb_serves_existing_file(self, client, monkeypatch, tmp_path):
        content_hash = "d" * 64
        thumbs_dir = tmp_path / "images" / "thumbs"
        thumbs_dir.mkdir(parents=True)
        (thumbs_dir / f"{content_hash}.jpg").write_bytes(b"\xff\xd8\xff fake jpeg")
        monkeypatch.setattr(api_mod, "DEFAULT_IMAGES_DIR", tmp_path / "images")
        r = client.get(f"/media/thumb/{content_hash}")
        assert r.status_code == 200
        assert r.mimetype == "image/jpeg"
