"""Unit tests for scripts/27_add_ikeda_dojos.py (issue #65).

The pre-fix script wrote a DOJO_AFFILIATION edge with
association="frequent_visited_teacher" for EVERY record in
data/ikeda_visited_dojos.json — including "variant" and
"city_or_country_lead" records that are only unconfirmed candidates. That
produced the false "Ikeda visited Kohala Aikikai" assertion refuted by dojo
owner Kristina Varjan (email 2026-09-24).

These tests lock in the fix:
- only match_type "exact" records produce a DOJO_AFFILIATION edge
- prune_lead_edges() removes stale lead edges from a pre-fix snapshot/DB
- Varjan's denial is recorded as a source + claim mentioning the right nodes
"""

import importlib.util
import json
import os
import tempfile
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
SCRIPT_PATH = PROJECT_ROOT / "scripts" / "27_add_ikeda_dojos.py"
DATA_FILE = PROJECT_ROOT / "data" / "ikeda_visited_dojos.json"


def _load_module():
    """Load scripts/27_add_ikeda_dojos.py (filename starts with a digit)."""
    spec = importlib.util.spec_from_file_location("_ikeda_dojos_module", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


mod = _load_module()

from src.storage.graph_db import GraphDB
from src.storage.models import GraphEdge, RelationType


@pytest.fixture
def db():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    db = GraphDB(db_path)
    yield db
    db.close()
    if os.path.exists(db_path):
        os.unlink(db_path)


@pytest.fixture
def records():
    return json.loads(DATA_FILE.read_text(encoding="utf-8"))


def _ikeda_dojo_edges(db):
    return [
        e for e in db.get_all_edges()
        if e.src_id == "person:hiroshi-ikeda"
        and e.rel_type == RelationType.DOJO_AFFILIATION
    ]


def test_only_exact_matches_get_affiliation_edges(db, records):
    """DOJO_AFFILIATION edges are created only for match_type 'exact'."""
    stats = mod.add_ikeda_dojos(db)

    expected_exact = {
        r["id"] for r in records["dojos"] if r["match_type"] == "exact"
    }
    expected_leads = {
        r["id"] for r in records["dojos"] if r["match_type"] != "exact"
    }
    assert expected_leads, "fixture: data file must contain lead records"

    edges = _ikeda_dojo_edges(db)
    edge_dsts = {e.dst_id for e in edges}

    assert edge_dsts == expected_exact
    assert not (edge_dsts & expected_leads)
    assert stats["edges"] == len(expected_exact)
    assert stats["leads"] == len(expected_leads)
    assert stats["nodes"] == len(records["dojos"])
    for e in edges:
        assert e.metadata["association"] == "frequent_visited_teacher"
        assert e.metadata["match_type"] == "exact"


def test_lead_nodes_still_created_without_edges(db):
    """Lead dojos keep their Dojo nodes (real WSF dojos) but no edge."""
    mod.add_ikeda_dojos(db)
    kohala = db.get_node("dojo:kohala-aikikai")
    assert kohala is not None
    assert kohala.metadata["match_type"] == "city_or_country_lead"
    assert "REFUTED" in kohala.metadata["notes"]
    assert all(
        e.dst_id != "dojo:kohala-aikikai" for e in _ikeda_dojo_edges(db)
    )


def test_prune_lead_edges_removes_stale_edges(db, records):
    """prune_lead_edges deletes pre-fix stale edges for lead records."""
    person_id = records["person_id"]
    lead_ids = [
        r["id"] for r in records["dojos"] if r["match_type"] != "exact"
    ]
    # Simulate the stale snapshot state: an assertive edge on every record.
    for rec in records["dojos"]:
        db.add_edge(GraphEdge(
            src_id=person_id,
            rel_type=RelationType.DOJO_AFFILIATION,
            dst_id=rec["id"],
            metadata={"association": "frequent_visited_teacher"},
        ))
    assert len(_ikeda_dojo_edges(db)) == len(records["dojos"])

    pruned = mod.prune_lead_edges(db)
    assert pruned == len(lead_ids)

    remaining = {e.dst_id for e in _ikeda_dojo_edges(db)}
    assert remaining == {
        r["id"] for r in records["dojos"] if r["match_type"] == "exact"
    }


def test_varjan_denial_recorded(db):
    """Varjan's 2026-09-24 email becomes a source + claim + MENTIONS edges."""
    mod.add_ikeda_dojos(db)
    stats = mod.add_varjan_denial(db)
    assert stats["sources"] == 1 and stats["claims"] == 1

    src = db.get_source(mod.VARJAN_SOURCE_ID)
    assert src is not None
    assert src.author == "Kristina Varjan"
    assert src.publish_date == "2026-09-24"
    assert "never visited" in (src.raw_text or "")

    claim = db.get_node(mod.VARJAN_CLAIM_ID)
    assert claim is not None
    assert claim.metadata["asserted_by"] == "kristina-varjan"

    mentions = {e.dst_id for e in db.get_edges_from(mod.VARJAN_CLAIM_ID)}
    assert "dojo:kohala-aikikai" in mentions
    assert "person:hiroshi-ikeda" in mentions

    link = db.get_all_claim_source_links()
    assert any(
        c.claim_id == mod.VARJAN_CLAIM_ID and c.source_id == mod.VARJAN_SOURCE_ID
        for c in link
    )
