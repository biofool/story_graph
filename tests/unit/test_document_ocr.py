from __future__ import annotations

import hashlib
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from PIL import Image

from src.crawler.document_ocr import _find_matches, ocr_document


def test_find_matches_preserves_page_excerpt():
    text = "Предисловие. Учредительная конференция Федерации Айкидо СССР состоялась. Конец."

    matches = _find_matches(text, ["Федерации Айкидо СССР", "Роберт Надо"])

    assert len(matches) == 1
    assert matches[0].term == "Федерации Айкидо СССР"
    assert "Учредительная конференция" in matches[0].excerpt


def test_ocr_image_returns_page_hash_and_matches(tmp_path: Path):
    image_path = tmp_path / "scan.png"
    Image.new("RGB", (20, 20), "white").save(image_path)
    process = MagicMock(returncode=0, stdout="Роберт Надо провел тренировку", stderr="")

    with patch("src.crawler.document_ocr._run", return_value=process):
        result = ocr_document(str(image_path), terms=["Роберт Надо"], language="eng")

    assert result.source_sha256 == hashlib.sha256(image_path.read_bytes()).hexdigest()
    assert len(result.pages) == 1
    assert result.pages[0].matches[0].term == "Роберт Надо"
    assert result.pages[0].text_sha256 == hashlib.sha256(result.pages[0].text.encode()).hexdigest()


def test_rejects_unsupported_document(tmp_path: Path):
    path = tmp_path / "scan.txt"
    path.write_text("not a scan")

    with pytest.raises(ValueError, match="Unsupported document type"):
        ocr_document(str(path), language="eng")
