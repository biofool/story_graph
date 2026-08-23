"""Integration test: store the Cyprus CRTG leads' claims into a real SQLite
graph DB. No network involved — only exercises the DB-writing helpers in
scripts._cyprus_crtg_helpers, mirroring the style of
tests/integration/test_pipeline.py."""

import os
import sys
import tempfile
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from src.storage.graph_db import GraphDB
from src.storage.models import NodeType, RelationType
from scripts._cyprus_crtg_helpers import (
    CRTG_GROUP_NAME,
    DEFAULT_LEADS,
    KKRON_SOURCE_PERSON_ID,
    KKRON_WORK_ID,
    store_lead_claim,
)


def _kkron_lead():
    return next(
        l for l in DEFAULT_LEADS
        if l.subject_name == "Douglas Stone" and l.object_name == CRTG_GROUP_NAME
    )


def _citation_lead():
    return next(l for l in DEFAULT_LEADS if l.provenance() == "citation")


def _public_record_lead():
    return next(l for l in DEFAULT_LEADS if l.provenance() == "public_record")


def test_store_kkron_lead_builds_expected_graph():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    db = GraphDB(db_path)
    try:
        lead = _kkron_lead()
        cid = store_lead_claim(db, lead)

        claim = db.get_node(cid)
        assert claim is not None
        assert claim.type == NodeType.CLAIM
        assert claim.metadata["pending_independent_corroboration"] is True
        assert claim.metadata["confidence"] < lead.kkron_confidence

        speaker = db.get_node(KKRON_SOURCE_PERSON_ID)
        assert speaker is not None
        assert speaker.type == NodeType.PERSON

        subject = db.get_node(lead.subject_id())
        obj = db.get_node(lead.object_id())
        assert subject is not None and subject.type == NodeType.PERSON
        assert obj is not None and obj.type == NodeType.GROUP
        assert obj.metadata.get("group_type") == "conflict_resolution_training_group"

        edge_triples = {(e.src_id, e.rel_type, e.dst_id) for e in db.get_all_edges()}
        assert (cid, RelationType.ASSERTED_BY, KKRON_SOURCE_PERSON_ID) in edge_triples
        assert (cid, RelationType.ABOUT, lead.subject_id()) in edge_triples
        assert (cid, RelationType.ABOUT, lead.object_id()) in edge_triples
        assert (lead.subject_id(), lead.relation, lead.object_id()) in edge_triples
        assert (KKRON_WORK_ID, RelationType.CONTAINS, cid) in edge_triples
    finally:
        db.close()
        os.unlink(db_path)


def test_store_citation_lead_uses_wikipedia_source_not_kkron():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    db = GraphDB(db_path)
    try:
        lead = _citation_lead()
        cid = store_lead_claim(db, lead)

        claim = db.get_node(cid)
        assert claim is not None
        assert claim.metadata["provenance"] == "citation"

        source = db.get_source_by_url(lead.source_url)
        assert source is not None

        edge_triples = {(e.src_id, e.rel_type, e.dst_id) for e in db.get_all_edges()}
        # Not attributed to kkron.
        assert (cid, RelationType.ASSERTED_BY, KKRON_SOURCE_PERSON_ID) not in edge_triples
        # SUPPORTED_BY the cited Work node instead.
        supported_by = [e for e in db.get_all_edges() if e.src_id == cid and e.rel_type == RelationType.SUPPORTED_BY]
        assert len(supported_by) == 1

        # kkron's Person/Work nodes are not created by a citation-only lead.
        assert db.get_node(KKRON_SOURCE_PERSON_ID) is None
    finally:
        db.close()
        os.unlink(db_path)


def test_store_public_record_lead_has_higher_confidence_and_no_speaker():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    db = GraphDB(db_path)
    try:
        lead = _public_record_lead()
        cid = store_lead_claim(db, lead)

        claim = db.get_node(cid)
        assert claim is not None
        assert claim.metadata["provenance"] == "public_record"
        assert claim.metadata["confidence"] == lead.public_record_confidence

        edge_triples = {(e.src_id, e.rel_type, e.dst_id) for e in db.get_all_edges()}
        assert not any(
            e[0] == cid and e[1] == RelationType.ASSERTED_BY for e in edge_triples
        )
    finally:
        db.close()
        os.unlink(db_path)


def test_store_lead_claim_is_idempotent():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    db = GraphDB(db_path)
    try:
        lead = _kkron_lead()
        cid1 = store_lead_claim(db, lead)
        node_count_1 = db.get_node_count()
        edge_count_1 = db.get_edge_count()

        cid2 = store_lead_claim(db, lead)
        node_count_2 = db.get_node_count()
        edge_count_2 = db.get_edge_count()

        assert cid1 == cid2
        assert node_count_1 == node_count_2
        assert edge_count_1 == edge_count_2
    finally:
        db.close()
        os.unlink(db_path)


def test_all_default_leads_can_be_stored_and_produce_one_claim_each():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    db = GraphDB(db_path)
    try:
        for lead in DEFAULT_LEADS:
            store_lead_claim(db, lead)
        claims = db.get_nodes_by_type(NodeType.CLAIM)
        assert len(claims) == len(DEFAULT_LEADS)
        assert all(c.metadata["pending_independent_corroboration"] for c in claims)

        # kkron-sourced claims stay capped; public-record/citation claims can
        # exceed the kkron ceiling.
        kkron_claims = [c for c in claims if c.metadata["provenance"] == "kkron"]
        assert kkron_claims
        assert all(c.metadata["confidence"] <= 0.5 for c in kkron_claims)

        higher_conf_claims = [c for c in claims if c.metadata["provenance"] != "kkron"]
        assert higher_conf_claims
        assert any(c.metadata["confidence"] > 0.5 for c in higher_conf_claims)
    finally:
        db.close()
        os.unlink(db_path)


def test_crtg_group_node_created_once_across_multiple_leads():
    """Several leads point at the same CRTG Group node — confirm they
    converge on one node (upsert-by-id) rather than duplicating it."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    db = GraphDB(db_path)
    try:
        crtg_leads = [l for l in DEFAULT_LEADS if CRTG_GROUP_NAME in (l.subject_name, l.object_name)]
        assert len(crtg_leads) >= 3
        for lead in crtg_leads:
            store_lead_claim(db, lead)

        groups = db.get_nodes_by_type(NodeType.GROUP)
        crtg_nodes = [g for g in groups if g.label == CRTG_GROUP_NAME]
        assert len(crtg_nodes) == 1
    finally:
        db.close()
        os.unlink(db_path)
