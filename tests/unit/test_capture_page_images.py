"""Unit tests for scripts/_pipeline_helpers.capture_page_images."""

from __future__ import annotations

from io import BytesIO
from unittest.mock import MagicMock, patch

import pytest
from PIL import Image

from scripts._pipeline_helpers import capture_page_images
from src.crawler.web_crawler import CrawledPage, ImageCandidate
from src.storage.graph_db import GraphDB
from src.storage.models import GraphNode, NodeType, RelationType


def _png_bytes(size=(300, 300)) -> bytes:
    buf = BytesIO()
    Image.new("RGB", size, (10, 20, 30)).save(buf, format="PNG")
    return buf.getvalue()


def _mock_response(content: bytes, content_type: str = "image/png"):
    resp = MagicMock()
    resp.headers = {"Content-Type": content_type, "Content-Length": str(len(content))}
    resp.content = content
    resp.raise_for_status = MagicMock()
    return resp


@pytest.fixture
def db(tmp_path):
    database = GraphDB(tmp_path / "graph.db")
    yield database
    database.close()


@pytest.fixture(autouse=True)
def images_dir(tmp_path, monkeypatch):
    from src.crawler import image_capture

    monkeypatch.setattr(image_capture, "DEFAULT_IMAGES_DIR", tmp_path / "images")
    monkeypatch.setattr(
        "scripts._pipeline_helpers.capture_image",
        lambda url, alt="": image_capture.capture_image(url, alt=alt, base_dir=tmp_path / "images"),
    )


class TestCapturePageImages:
    @patch("requests.get")
    def test_creates_image_node_and_depicts_edge(self, mock_get, db):
        mock_get.return_value = _mock_response(_png_bytes())
        db.add_node(GraphNode(id="work:w1", type=NodeType.WORK, label="Page"))
        page = CrawledPage(
            url="https://example.com/page",
            images=[ImageCandidate(url="https://example.com/photo.png", alt="a photo")],
        )

        capture_page_images(page, "work:w1", db)

        edges = db.get_edges_from("work:w1")
        depicts = [e for e in edges if e.rel_type == RelationType.DEPICTS]
        assert len(depicts) == 1
        image_node = db.get_node(depicts[0].dst_id)
        assert image_node.type == NodeType.IMAGE
        assert image_node.metadata["alt"] == "a photo"

    @patch("requests.get")
    def test_skips_images_that_fail_capture(self, mock_get, db):
        mock_get.return_value = _mock_response(b"<html></html>", content_type="text/html")
        db.add_node(GraphNode(id="work:w1", type=NodeType.WORK, label="Page"))
        page = CrawledPage(
            url="https://example.com/page",
            images=[ImageCandidate(url="https://example.com/notreally.png")],
        )

        capture_page_images(page, "work:w1", db)

        assert not any(e.rel_type == RelationType.DEPICTS for e in db.get_edges_from("work:w1"))

    @patch("requests.get")
    def test_idempotent_on_rerun(self, mock_get, db):
        mock_get.return_value = _mock_response(_png_bytes())
        db.add_node(GraphNode(id="work:w1", type=NodeType.WORK, label="Page"))
        page = CrawledPage(
            url="https://example.com/page",
            images=[ImageCandidate(url="https://example.com/photo.png", alt="a photo")],
        )

        capture_page_images(page, "work:w1", db)
        capture_page_images(page, "work:w1", db)

        depicts = [e for e in db.get_edges_from("work:w1") if e.rel_type == RelationType.DEPICTS]
        assert len(depicts) == 1
