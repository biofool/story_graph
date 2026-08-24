"""Integration test: store kkron's first-hand claims into a real SQLite
graph DB. No network involved — only exercises the DB-writing helpers in
scripts._targeted_research_helpers, mirroring the style of
tests/integration/test_pipeline.py."""

import os
import sys
import tempfile
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from src.storage.graph_db import GraphDB
from src.storage.models import NodeType, RelationType
from scripts._targeted_research_helpers import (
    DEFAULT_LEADS,
    KKRON_SOURCE_PERSON_ID,
    KKRON_WORK_ID,
    build_kkron_claim_record,
    store_kkron_claim,
)


def test_store_kkron_claim_builds_expected_graph():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    db = GraphDB(db_path)
    try:
        lead = DEFAULT_LEADS[0]  # Richard Moon WORKED_AT The Source
        cid = store_kkron_claim(db, lead)

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
        assert obj.metadata.get("group_type") == "restaurant"

        edge_triples = {(e.src_id, e.rel_type, e.dst_id) for e in db.get_all_edges()}
        assert (cid, RelationType.ASSERTED_BY, KKRON_SOURCE_PERSON_ID) in edge_triples
        assert (cid, RelationType.ABOUT, lead.subject_id()) in edge_triples
        assert (cid, RelationType.ABOUT, lead.object_id()) in edge_triples
        assert (lead.subject_id(), lead.relation, lead.object_id()) in edge_triples
        assert (KKRON_WORK_ID, RelationType.CONTAINS, cid) in edge_triples
    finally:
        db.close()
        os.unlink(db_path)


def test_store_kkron_claim_is_idempotent():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    db = GraphDB(db_path)
    try:
        lead = DEFAULT_LEADS[0]
        cid1 = store_kkron_claim(db, lead)
        node_count_1 = db.get_node_count()
        edge_count_1 = db.get_edge_count()

        cid2 = store_kkron_claim(db, lead)
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
            store_kkron_claim(db, lead)
        claims = db.get_nodes_by_type(NodeType.CLAIM)
        assert len(claims) == len(DEFAULT_LEADS)
        # Every claim from this pipeline is pending independent
        # corroboration, whichever provenance path it took.
        assert all(c.metadata["pending_independent_corroboration"] for c in claims)

        # The KKRON_CONFIDENCE_CEILING applies only to kkron's own
        # first-hand claims — it exists to stop his unverified word
        # outranking something independently found, which is not a risk for
        # a claim that already cites a real published source. Citation
        # claims therefore keep their own source_confidence, which can and
        # does exceed the ceiling (e.g. the peer-reviewed Deslippe lead).
        by_id = {c.id: c for c in claims}
        for lead in DEFAULT_LEADS:
            claim = by_id[build_kkron_claim_record(lead)["id"]]
            if lead.source_url:
                assert claim.metadata["confidence"] == lead.source_confidence
            else:
                assert claim.metadata["confidence"] <= 0.5
    finally:
        db.close()
        os.unlink(db_path)
