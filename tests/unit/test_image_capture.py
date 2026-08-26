"""Unit tests for src/crawler/image_capture.py."""

from __future__ import annotations

from io import BytesIO
from unittest.mock import MagicMock, patch

import pytest
from PIL import Image

from src.crawler.image_capture import capture_image


def _png_bytes(size=(300, 300), color=(200, 50, 50)) -> bytes:
    buf = BytesIO()
    Image.new("RGB", size, color).save(buf, format="PNG")
    return buf.getvalue()


def _mock_response(content: bytes, content_type: str = "image/png"):
    resp = MagicMock()
    resp.headers = {"Content-Type": content_type, "Content-Length": str(len(content))}
    resp.content = content
    resp.raise_for_status = MagicMock()
    return resp


@pytest.fixture
def images_dir(tmp_path):
    return tmp_path / "images"


class TestCaptureImage:
    @patch("requests.get")
    def test_downloads_and_thumbnails(self, mock_get, images_dir):
        data = _png_bytes()
        mock_get.return_value = _mock_response(data)

        result = capture_image("https://example.com/photo.png", alt="a photo", base_dir=images_dir)

        assert result is not None
        assert result.width == 300 and result.height == 300
        assert result.image_path.exists()
        assert result.thumb_path.exists()
        assert result.image_path.read_bytes() == data

    @patch("requests.get")
    def test_dedupes_by_content_hash(self, mock_get, images_dir):
        data = _png_bytes()
        mock_get.return_value = _mock_response(data)

        first = capture_image("https://example.com/a.png", base_dir=images_dir)
        second = capture_image("https://example.com/b.png", base_dir=images_dir)

        assert first.content_hash == second.content_hash
        assert first.image_path == second.image_path

    @patch("requests.get")
    def test_rejects_non_image_content_type(self, mock_get, images_dir):
        mock_get.return_value = _mock_response(b"<html></html>", content_type="text/html")

        result = capture_image("https://example.com/notanimage", base_dir=images_dir)

        assert result is None

    @patch("requests.get")
    def test_rejects_undersized_image(self, mock_get, images_dir):
        data = _png_bytes(size=(16, 16))
        mock_get.return_value = _mock_response(data)

        result = capture_image("https://example.com/spacer.png", base_dir=images_dir)

        assert result is None

    def test_rejects_svg_by_extension_without_network(self, images_dir):
        result = capture_image("https://example.com/logo.svg", base_dir=images_dir)
        assert result is None

    @patch("requests.get")
    def test_handles_fetch_failure_gracefully(self, mock_get, images_dir):
        mock_get.side_effect = ConnectionError("boom")

        result = capture_image("https://example.com/photo.png", base_dir=images_dir)

        assert result is None
