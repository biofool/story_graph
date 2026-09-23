"""Unit tests for data/ingest/ikeda_dojos.json (issue #65).

The legacy script (27_add_ikeda_dojos.py) was migrated to a declarative
ingest spec applied via scripts/ingest.py's apply_spec(). The pre-fix script
wrote a DOJO_AFFILIATION edge with association="frequent_visited_teacher" for
EVERY record in data/ikeda_visited_dojos.json — including "variant" and
"city_or_country_lead" records that are only unconfirmed candidates. That
produced the false "Ikeda visited Kohala Aikikai" assertion refuted by dojo
owner Kristina Varjan (email 2026-09-24).

These tests lock in the fix:
- only match_type "exact" records produce a DOJO_AFFILIATION edge
- delete_edges prunes stale lead edges from a pre-fix snapshot/DB
- Varjan's denial is recorded as a source + claim mentioning the right nodes
"""

import json
import os
import tempfile
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
SPEC_PATH = PROJECT_ROOT / "data" / "ingest" / "ikeda_dojos.json"
DATA_FILE = PROJECT_ROOT / "data" / "ikeda_visited_dojos.json"

import sys

sys.path.insert(0, str(PROJECT_ROOT))

from scripts.ingest import apply_spec
from src.storage.graph_db import GraphDB
from src.storage.models import GraphEdge, RelationType

VARJAN_SOURCE_ID = "source:kristina-varjan-kohala-email-2026-09-24"
VARJAN_CLAIM_ID = "claim:27ab36180b29ce11"


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
def spec():
    return json.loads(SPEC_PATH.read_text(encoding="utf-8"))


@pytest.fixture
def records():
    return json.loads(DATA_FILE.read_text(encoding="utf-8"))


def _ikeda_dojo_edges(db):
    return [
        e for e in db.get_all_edges()
        if e.src_id == "person:hiroshi-ikeda"
        and e.rel_type == RelationType.DOJO_AFFILIATION
    ]


def test_only_exact_matches_get_affiliation_edges(db, spec, records):
    """DOJO_AFFILIATION edges are created only for match_type 'exact'."""
    apply_spec(spec, db)

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
    for e in edges:
        assert e.metadata["association"] == "frequent_visited_teacher"
        assert e.metadata["match_type"] == "exact"


def test_lead_nodes_still_created_without_edges(db, spec):
    """Lead dojos keep their Dojo nodes (real WSF dojos) but no edge."""
    apply_spec(spec, db)
    kohala = db.get_node("dojo:kohala-aikikai")
    assert kohala is not None
    assert kohala.metadata["match_type"] == "city_or_country_lead"
    assert "REFUTED" in kohala.metadata["notes"]
    assert all(
        e.dst_id != "dojo:kohala-aikikai" for e in _ikeda_dojo_edges(db)
    )


def test_delete_edges_removes_stale_lead_edges(db, spec, records):
    """delete_edges prunes pre-fix stale edges for lead records."""
    person_id = records["person_id"]
    # Simulate the stale snapshot state: an assertive edge on every record.
    for rec in records["dojos"]:
        db.add_edge(GraphEdge(
            src_id=person_id,
            rel_type=RelationType.DOJO_AFFILIATION,
            dst_id=rec["id"],
            metadata={"association": "frequent_visited_teacher"},
        ))
    assert len(_ikeda_dojo_edges(db)) == len(records["dojos"])

    apply_spec(spec, db)

    remaining = {e.dst_id for e in _ikeda_dojo_edges(db)}
    assert remaining == {
        r["id"] for r in records["dojos"] if r["match_type"] == "exact"
    }


def test_varjan_denial_recorded(db, spec):
    """Varjan's 2026-09-24 email becomes a source + claim + MENTIONS edges."""
    apply_spec(spec, db)

    src = db.get_source(VARJAN_SOURCE_ID)
    assert src is not None
    assert src.author == "Kristina Varjan"
    assert src.publish_date == "2026-09-24"
    assert "never visited" in (src.raw_text or "")

    claim = db.get_node(VARJAN_CLAIM_ID)
    assert claim is not None
    assert claim.metadata["asserted_by"] == "kristina-varjan"

    mentions = {e.dst_id for e in db.get_edges_from(VARJAN_CLAIM_ID)}
    assert "dojo:kohala-aikikai" in mentions
    assert "person:hiroshi-ikeda" in mentions

    links = db.get_all_claim_source_links()
    assert any(
        c.claim_id == VARJAN_CLAIM_ID and c.source_id == VARJAN_SOURCE_ID
        for c in links
    )
