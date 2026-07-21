"""Integration test: process a mock page and verify graph construction."""

import pytest
import tempfile
import os
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from src.storage.graph_db import GraphDB
from src.storage.models import NodeType
from src.crawler.web_crawler import CrawledPage
from src.extractor.entity_extractor import EntityExtractor
from src.extractor.claim_extractor import ClaimExtractor
from src.extractor.alias_resolver import person_id, group_id, work_id
from scripts._pipeline_helpers import process_page


def test_process_page_builds_graph():
    """Test that process_page correctly builds graph nodes and edges from a crawled page."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    db = GraphDB(db_path)

    try:
        page = CrawledPage(
            url="https://lifeinthesourcefamily.blogspot.com/2017/01/test.html",
            title="Life in the Source Family",
            text=(
                "Father Yod was the leader of The Source Family. "
                "Laura Garon said that Baker withheld support from wives and children. "
                "Isis Aquarian described the experience as beautiful and loving. "
                "The Source Restaurant was located on Sunset Strip. "
                "Jim Baker opened The Source Restaurant in 1969. "
                "The family moved to Kauai on 1974-06-01."
            ),
            links=["https://cultnews.com/article"],
            author="Isis Aquarian",
            publish_date="2017-01-15",
            status_code=200,
        )

        extractor = EntityExtractor(spacy_model_name="nonexistent")
        claim_extractor = ClaimExtractor(extractor)

        process_page(page, extractor, claim_extractor, db)

        # Verify nodes were created
        assert db.get_node_count() > 0
        assert db.get_source_count() == 1

        # Check for Father Yod / James Edward Baker
        yod_id = person_id("Father Yod")
        yod = db.get_node(yod_id)
        assert yod is not None
        assert yod.type == NodeType.PERSON

        # Check for The Source Family group
        sf_id = group_id("The Source Family")
        sf = db.get_node(sf_id)
        assert sf is not None
        assert sf.type == NodeType.GROUP

        # Check for Work node
        wid = work_id(page.url)
        work = db.get_node(wid)
        assert work is not None
        assert work.type == NodeType.WORK

        # Check for claims
        claims = db.get_nodes_by_type(NodeType.CLAIM)
        assert len(claims) >= 1

        # Check edge types
        all_edges = db.get_all_edges()
        rel_types = {e.rel_type.value for e in all_edges}
        assert "MENTIONS" in rel_types
        assert "CONTAINS" in rel_types
        assert "ABOUT" in rel_types

    finally:
        db.close()
        os.unlink(db_path)
