"""Unit tests for the generalized person-ingestion pipeline.

Tests the enrichment capabilities merged from one-off scripts:
- create_wikipedia_gap_claim (from 25_ingest_peter_ralston.py)
- record_to_lineage_db (from 28_ingest_ralston_noha.py, 30_ingest_moon_ralston_edge.py)
"""

import os
import tempfile
import importlib

import pytest

from src.storage.graph_db import GraphDB
from src.storage.lineage_db import LineageDB
from src.storage.models import (
    GraphEdge,
    GraphNode,
    NodeType,
    RelationType,
)
from scripts.ingest_a_person import (
    create_wikipedia_gap_claim,
    record_to_lineage_db,
)

# Import LINEAGE_DDL from the numbered script module (can't use normal import
# because the module name starts with a digit)
_lineage_tables_mod = importlib.import_module("scripts.26_create_lineage_tables")
LINEAGE_DDL = _lineage_tables_mod.LINEAGE_DDL


@pytest.fixture
def db():
    """Create a temporary GraphDB."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    db = GraphDB(db_path)
    yield db
    db.close()
    os.unlink(db_path)


@pytest.fixture
def lineage_db():
    """Create a temporary LineageDB with the lineage schema initialized."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    # Initialize the lineage tables
    import sqlite3
    conn = sqlite3.connect(db_path)
    conn.executescript(LINEAGE_DDL)
    conn.commit()
    conn.close()
    ldb = LineageDB(db_path)
    yield ldb
    ldb.close()
    os.unlink(db_path)


class TestWikipediaGapClaim:
    """Tests for create_wikipedia_gap_claim — generalized from
    scripts/25_ingest_peter_ralston.py's Wikipedia gap claim pattern."""

    def test_creates_claim_node(self, db):
        """A Wikipedia gap claim is created as a Claim node."""
        claim_id = create_wikipedia_gap_claim(
            "Peter Ralston",
            db,
            context="aikido",
            discovered_urls=["https://chenghsin.com/who-is-peter-ralston/"],
            notability_notes="1978 world champion, 9+ books",
        )
        assert claim_id == "claim:peter-ralston-wikipedia-gap"

        node = db.get_node(claim_id)
        assert node is not None
        assert node.type == NodeType.CLAIM
        assert "Peter Ralston" in node.label
        assert "no Wikipedia" in node.label

    def test_claim_has_wikipedia_urls_checked(self, db):
        """The claim metadata includes the Wikipedia URLs that were checked."""
        create_wikipedia_gap_claim(
            "Peter Ralston",
            db,
            context="aikido",
            discovered_urls=["https://chenghsin.com/"],
        )
        node = db.get_node("claim:peter-ralston-wikipedia-gap")
        urls_checked = node.metadata.get("wikipedia_urls_checked", [])
        assert len(urls_checked) >= 1
        assert any("en.wikipedia.org" in u for u in urls_checked)

    def test_claim_has_notability_notes(self, db):
        """The claim metadata includes the notability notes."""
        create_wikipedia_gap_claim(
            "Test Person",
            db,
            notability_notes="Notable for XYZ achievement",
        )
        node = db.get_node("claim:test-person-wikipedia-gap")
        assert node.metadata.get("notability_notes") == "Notable for XYZ achievement"

    def test_claim_has_discovered_source_count(self, db):
        """The claim metadata records how many sources were discovered."""
        urls = ["https://a.com", "https://b.com", "https://c.com"]
        create_wikipedia_gap_claim(
            "Test Person",
            db,
            discovered_urls=urls,
        )
        node = db.get_node("claim:test-person-wikipedia-gap")
        assert node.metadata.get("discovered_source_count") == 3

    def test_custom_wikipedia_urls_checked(self, db):
        """Custom Wikipedia URLs can be provided."""
        custom_urls = [
            "https://en.wikipedia.org/wiki/Custom_Person",
            "https://en.wikipedia.org/wiki/Custom_Person_(artist)",
        ]
        create_wikipedia_gap_claim(
            "Custom Person",
            db,
            wikipedia_urls_checked=custom_urls,
        )
        node = db.get_node("claim:custom-person-wikipedia-gap")
        assert node.metadata.get("wikipedia_urls_checked") == custom_urls

    def test_links_to_person_node(self, db):
        """The claim creates an ABOUT edge to the person node if it exists."""
        # Add a person node first
        db.add_node(GraphNode(
            id="person:test-person",
            type=NodeType.PERSON,
            label="Test Person",
            canonical_name="Test Person",
            metadata={},
            source_urls=[],
        ))

        create_wikipedia_gap_claim(
            "Test Person",
            db,
            discovered_urls=["https://example.com"],
        )

        # Check that an ABOUT edge was created
        about_edges = [
            e for e in db.get_all_edges()
            if e.src_id == "claim:test-person-wikipedia-gap"
            and e.rel_type == RelationType.ABOUT
            and e.dst_id == "person:test-person"
        ]
        assert len(about_edges) == 1

    def test_idempotent(self, db):
        """Creating the claim twice returns None the second time."""
        claim_id_1 = create_wikipedia_gap_claim("Test Person", db)
        assert claim_id_1 is not None

        claim_id_2 = create_wikipedia_gap_claim("Test Person", db)
        assert claim_id_2 is None

    def test_dry_run_does_not_write(self, db):
        """In dry-run mode, the claim is not written to the DB."""
        claim_id = create_wikipedia_gap_claim(
            "Dry Run Person",
            db,
            dry_run=True,
        )
        assert claim_id == "claim:dry-run-person-wikipedia-gap"
        assert db.get_node(claim_id) is None


class TestRecordToLineageDB:
    """Tests for record_to_lineage_db — generalized from
    scripts/28_ingest_ralston_noha.py and scripts/30_ingest_moon_ralston_edge.py."""

    def test_upserts_person(self, db, lineage_db):
        """The person is upserted into lineage_persons."""
        db.add_node(GraphNode(
            id="person:jack-wada",
            type=NodeType.PERSON,
            label="Jack Wada",
            canonical_name="Jack Wada",
            metadata={},
            source_urls=["https://aikidosj.com/"],
        ))

        record_to_lineage_db(
            db,
            lineage_db,
            person_name="Jack Wada",
            context="aikido",
            discovered_urls=["https://aikidosj.com/"],
        )

        person = lineage_db.get_person("person:jack-wada")
        assert person is not None
        assert person["canonical_name"] == "Jack Wada"
        assert person["primary_art"] == "aikido"

    def test_upserts_person_with_kg_metadata(self, db, lineage_db):
        """KG metadata (wikipedia_url, kg_id) is passed through to lineage."""
        db.add_node(GraphNode(
            id="person:robert-nadeau",
            type=NodeType.PERSON,
            label="Robert Nadeau",
            canonical_name="Robert Nadeau",
            metadata={},
            source_urls=[],
        ))

        kg_entity = {
            "name": "Robert Nadeau",
            "wikipedia_url": "https://en.wikipedia.org/wiki/Robert_Nadeau_(aikidoka)",
            "kg_id": "/m/0abc123",
        }

        record_to_lineage_db(
            db,
            lineage_db,
            person_name="Robert Nadeau",
            context="aikido",
            kg_entity=kg_entity,
        )

        person = lineage_db.get_person("person:robert-nadeau")
        assert person is not None
        assert person["wikipedia_url"] == "https://en.wikipedia.org/wiki/Robert_Nadeau_(aikidoka)"
        assert person["kg_id"] == "/m/0abc123"

    def test_records_lineage_edges(self, db, lineage_db):
        """Typed relation edges are recorded in lineage_edges."""
        db.add_node(GraphNode(
            id="person:robert-nadeau",
            type=NodeType.PERSON,
            label="Robert Nadeau",
            canonical_name="Robert Nadeau",
            metadata={},
            source_urls=[],
        ))
        db.add_node(GraphNode(
            id="person:jack-wada",
            type=NodeType.PERSON,
            label="Jack Wada",
            canonical_name="Jack Wada",
            metadata={},
            source_urls=[],
        ))
        db.add_edge(GraphEdge(
            src_id="person:robert-nadeau",
            rel_type=RelationType.TEACHER_STUDENT,
            dst_id="person:jack-wada",
            metadata={"evidence": "https://aikidosj.com/"},
        ))

        edges_recorded = record_to_lineage_db(
            db,
            lineage_db,
            person_name="Jack Wada",
            context="aikido",
        )

        assert edges_recorded >= 1
        lineage_edges = lineage_db.get_current_edges(
            src_id="person:robert-nadeau",
            edge_type="TEACHER_STUDENT",
        )
        assert len(lineage_edges) == 1
        assert lineage_edges[0]["dst_id"] == "person:jack-wada"
        assert lineage_edges[0]["discovered_via"] == "ingest_a_person"
        assert lineage_edges[0]["review_status"] == "auto"

    def test_fuzzy_matches_person_name(self, db, lineage_db):
        """Person name is fuzzy-matched when exact node ID is not found."""
        db.add_node(GraphNode(
            id="person:richard-moon-aikido",
            type=NodeType.PERSON,
            label="Richard Moon",
            canonical_name="Richard Moon",
            metadata={},
            source_urls=[],
        ))

        record_to_lineage_db(
            db,
            lineage_db,
            person_name="Richard Moon",
            context="aikido",
        )

        person = lineage_db.get_person("person:richard-moon-aikido")
        assert person is not None
        assert person["canonical_name"] == "Richard Moon"

    def test_no_person_name_records_all_edges(self, db, lineage_db):
        """When person_name is None, all typed edges are recorded."""
        db.add_node(GraphNode(
            id="person:a",
            type=NodeType.PERSON,
            label="Person A",
            canonical_name="Person A",
            metadata={},
            source_urls=[],
        ))
        db.add_node(GraphNode(
            id="person:b",
            type=NodeType.PERSON,
            label="Person B",
            canonical_name="Person B",
            metadata={},
            source_urls=[],
        ))
        db.add_edge(GraphEdge(
            src_id="person:a",
            rel_type=RelationType.TEACHER_STUDENT,
            dst_id="person:b",
            metadata={},
        ))

        edges_recorded = record_to_lineage_db(db, lineage_db)
        assert edges_recorded >= 1
