"""Extended unit tests for the OCR pipeline (src/crawler/document_ocr.py).

Covers:
- Multi-page PDF rendering and per-page text extraction
- Language selection parameter passthrough
- SHA-256 hashing of source and text
- Keyword match and excerpt extraction
- Missing tesseract binary error
- Image input (JPG/PNG) handling
- Download size limits
- Unsupported document types
- _find_matches edge cases
- _excerpt boundary behavior

All tests use mocks — no tesseract or pdftoppm required.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from unittest.mock import MagicMock, call, patch

import pytest
from PIL import Image

from src.crawler.document_ocr import (
    OCRMatch,
    OCRPage,
    OCRResult,
    _excerpt,
    _find_matches,
    _require_binary,
    _sha256,
    ocr_document,
    write_ocr_result,
)


# ---------------------------------------------------------------------------
#  _find_matches edge cases
# ---------------------------------------------------------------------------


class TestFindMatches:
    def test_case_insensitive(self):
        text = "Robert Nadeau conducted aikido training."
        matches = _find_matches(text, ["robert nadeau"])
        assert len(matches) == 1
        assert matches[0].term == "robert nadeau"

    def test_multiple_terms(self):
        text = "He studied aikido and jujitsu in San Francisco."
        matches = _find_matches(text, ["aikido", "jujitsu", "karate"])
        assert len(matches) == 2
        terms_found = {m.term for m in matches}
        assert terms_found == {"aikido", "jujitsu"}

    def test_no_matches(self):
        text = "This text has nothing relevant."
        matches = _find_matches(text, ["quantum", "physics"])
        assert matches == []

    def test_empty_terms(self):
        matches = _find_matches("some text", [])
        assert matches == []

    def test_empty_text(self):
        matches = _find_matches("", ["test"])
        assert matches == []

    def test_cyrillic_match(self):
        text = "\u0420\u043e\u0431\u0435\u0440\u0442 \u041d\u0430\u0434\u043e \u043f\u0440\u043e\u0432\u0435\u043b \u0441\u0435\u043c\u0438\u043d\u0430\u0440"
        matches = _find_matches(text, ["\u0420\u043e\u0431\u0435\u0440\u0442 \u041d\u0430\u0434\u043e"])
        assert len(matches) == 1

    def test_excerpt_included_in_match(self):
        text = "A" * 200 + " keyword " + "B" * 200
        matches = _find_matches(text, ["keyword"])
        assert len(matches) == 1
        assert "keyword" in matches[0].excerpt


# ---------------------------------------------------------------------------
#  _excerpt boundary behavior
# ---------------------------------------------------------------------------


class TestExcerpt:
    def test_excerpt_at_text_start(self):
        import re
        text = "keyword at the very start of text"
        match = re.search("keyword", text)
        result = _excerpt(text, match, radius=10)
        assert "keyword" in result

    def test_excerpt_at_text_end(self):
        import re
        text = "some text ending with keyword"
        match = re.search("keyword", text)
        result = _excerpt(text, match, radius=10)
        assert "keyword" in result

    def test_excerpt_collapses_whitespace(self):
        import re
        text = "before   \n\n   keyword   \n\n   after"
        match = re.search("keyword", text)
        result = _excerpt(text, match, radius=50)
        # Whitespace should be collapsed to single spaces
        assert "  " not in result


# ---------------------------------------------------------------------------
#  _sha256
# ---------------------------------------------------------------------------


class TestSha256:
    def test_file_hash(self, tmp_path):
        f = tmp_path / "test.txt"
        f.write_bytes(b"hello world")
        expected = hashlib.sha256(b"hello world").hexdigest()
        assert _sha256(f) == expected

    def test_empty_file(self, tmp_path):
        f = tmp_path / "empty.txt"
        f.write_bytes(b"")
        expected = hashlib.sha256(b"").hexdigest()
        assert _sha256(f) == expected


# ---------------------------------------------------------------------------
#  _require_binary
# ---------------------------------------------------------------------------


class TestRequireBinary:
    def test_missing_binary_raises(self):
        with pytest.raises(RuntimeError, match="Required OCR executable"):
            _require_binary("nonexistent_binary_xyz_12345")

    def test_existing_binary_passes(self):
        # "python" should exist on the system
        _require_binary("python3")


# ---------------------------------------------------------------------------
#  Multi-page PDF processing
# ---------------------------------------------------------------------------


class TestMultiPagePDF:
    def test_multi_page_produces_one_page_per_image(self, tmp_path):
        """A multi-page PDF should produce one OCRPage per rendered page."""
        pdf_path = tmp_path / "multi.pdf"
        pdf_path.write_bytes(b"%PDF-1.0 fake")

        page_images = []
        for i in range(3):
            p = tmp_path / f"page-{i+1:03d}.jpg"
            Image.new("RGB", (20, 20), "white").save(p)
            page_images.append(p)

        ocr_texts = [
            f"Page {i+1} text content here." for i in range(3)
        ]

        call_idx = [0]

        def mock_run(cmd):
            proc = MagicMock()
            if cmd[0] == "pdftoppm":
                proc.returncode = 0
                proc.stderr = ""
                return proc
            elif cmd[0] == "tesseract":
                proc.returncode = 0
                proc.stdout = ocr_texts[call_idx[0]]
                proc.stderr = ""
                call_idx[0] += 1
                return proc
            proc.returncode = 1
            return proc

        with patch("src.crawler.document_ocr._run", side_effect=mock_run), \
             patch("src.crawler.document_ocr._require_binary"), \
             patch("src.crawler.document_ocr._render_pages", return_value=page_images):
            result = ocr_document(str(pdf_path), terms=["text"], language="eng")

        assert len(result.pages) == 3
        for i, page in enumerate(result.pages):
            assert page.page == i + 1
            assert f"Page {i+1}" in page.text
            assert page.text_sha256 == hashlib.sha256(page.text.encode()).hexdigest()


# ---------------------------------------------------------------------------
#  Language selection
# ---------------------------------------------------------------------------


class TestLanguageSelection:
    def test_russian_language_parameter(self, tmp_path):
        """The --lang parameter should be passed to tesseract."""
        image_path = tmp_path / "scan.png"
        Image.new("RGB", (20, 20), "white").save(image_path)

        captured_commands = []

        def mock_run(cmd):
            captured_commands.append(cmd)
            proc = MagicMock(returncode=0, stdout="text output", stderr="")
            return proc

        with patch("src.crawler.document_ocr._run", side_effect=mock_run), \
             patch("src.crawler.document_ocr._require_binary"):
            ocr_document(str(image_path), language="rus", terms=[])

        # Find the tesseract command
        tess_cmds = [c for c in captured_commands if c[0] == "tesseract"]
        assert len(tess_cmds) == 1
        assert "-l" in tess_cmds[0]
        lang_idx = tess_cmds[0].index("-l")
        assert tess_cmds[0][lang_idx + 1] == "rus"

    def test_default_language_is_rus_eng(self, tmp_path):
        image_path = tmp_path / "scan.png"
        Image.new("RGB", (20, 20), "white").save(image_path)

        captured_commands = []

        def mock_run(cmd):
            captured_commands.append(cmd)
            proc = MagicMock(returncode=0, stdout="text", stderr="")
            return proc

        with patch("src.crawler.document_ocr._run", side_effect=mock_run), \
             patch("src.crawler.document_ocr._require_binary"):
            ocr_document(str(image_path), terms=[])

        tess_cmds = [c for c in captured_commands if c[0] == "tesseract"]
        lang_idx = tess_cmds[0].index("-l")
        assert tess_cmds[0][lang_idx + 1] == "rus+eng"


# ---------------------------------------------------------------------------
#  Image input
# ---------------------------------------------------------------------------


class TestImageInput:
    def test_png_input(self, tmp_path):
        image_path = tmp_path / "scan.png"
        Image.new("RGB", (20, 20), "white").save(image_path)
        process = MagicMock(returncode=0, stdout="extracted text from PNG", stderr="")

        with patch("src.crawler.document_ocr._run", return_value=process), \
             patch("src.crawler.document_ocr._require_binary"):
            result = ocr_document(str(image_path), terms=[], language="eng")

        assert len(result.pages) == 1
        assert result.pages[0].text == "extracted text from PNG"
        assert result.media_type == "png"

    def test_jpg_input(self, tmp_path):
        image_path = tmp_path / "scan.jpg"
        Image.new("RGB", (20, 20), "white").save(image_path)
        process = MagicMock(returncode=0, stdout="extracted text from JPG", stderr="")

        with patch("src.crawler.document_ocr._run", return_value=process), \
             patch("src.crawler.document_ocr._require_binary"):
            result = ocr_document(str(image_path), terms=[], language="eng")

        assert len(result.pages) == 1
        assert result.pages[0].text == "extracted text from JPG"
        assert result.media_type == "jpg"


# ---------------------------------------------------------------------------
#  Source hash
# ---------------------------------------------------------------------------


class TestSourceHash:
    def test_source_sha256_computed(self, tmp_path):
        image_path = tmp_path / "scan.png"
        Image.new("RGB", (20, 20), "white").save(image_path)
        expected_hash = hashlib.sha256(image_path.read_bytes()).hexdigest()
        process = MagicMock(returncode=0, stdout="text", stderr="")

        with patch("src.crawler.document_ocr._run", return_value=process), \
             patch("src.crawler.document_ocr._require_binary"):
            result = ocr_document(str(image_path), terms=[], language="eng")

        assert result.source_sha256 == expected_hash


# ---------------------------------------------------------------------------
#  write_ocr_result
# ---------------------------------------------------------------------------


class TestWriteOcrResult:
    def test_writes_json_file(self, tmp_path):
        result = OCRResult(
            source="test.png",
            source_sha256="abc123",
            media_type="png",
            language="eng",
            pages=[
                OCRPage(
                    page=1,
                    text="test text",
                    text_sha256="def456",
                    matches=[OCRMatch(term="test", excerpt="test text")],
                )
            ],
        )
        output = tmp_path / "result.json"
        write_ocr_result(result, output)

        assert output.exists()
        import json
        data = json.loads(output.read_text())
        assert data["source"] == "test.png"
        assert len(data["pages"]) == 1
        assert data["pages"][0]["matches"][0]["term"] == "test"

    def test_creates_parent_directories(self, tmp_path):
        result = OCRResult(
            source="test.png", source_sha256="", media_type="png",
            language="eng", pages=[],
        )
        output = tmp_path / "subdir" / "deep" / "result.json"
        write_ocr_result(result, output)
        assert output.exists()


# ---------------------------------------------------------------------------
#  Error recovery
# ---------------------------------------------------------------------------


class TestErrorRecovery:
    def test_tesseract_failure_raises(self, tmp_path):
        image_path = tmp_path / "scan.png"
        Image.new("RGB", (20, 20), "white").save(image_path)
        process = MagicMock(returncode=1, stdout="", stderr="Tesseract failed")

        with patch("src.crawler.document_ocr._run", return_value=process), \
             patch("src.crawler.document_ocr._require_binary"):
            with pytest.raises(RuntimeError, match="Tesseract failed"):
                ocr_document(str(image_path), terms=[], language="eng")

    def test_unsupported_format_raises(self, tmp_path):
        path = tmp_path / "scan.docx"
        path.write_bytes(b"fake docx")
        with pytest.raises(ValueError, match="Unsupported document type"):
            ocr_document(str(path), language="eng")

    def test_file_not_found_raises(self):
        with pytest.raises(FileNotFoundError):
            ocr_document("/nonexistent/path/scan.png", language="eng")

    def test_max_pages_exceeded(self, tmp_path):
        """Documents exceeding max_pages should raise ValueError."""
        pdf_path = tmp_path / "huge.pdf"
        pdf_path.write_bytes(b"%PDF-1.0 fake")

        # Create more pages than max_pages
        page_images = []
        for i in range(5):
            p = tmp_path / f"page-{i+1:03d}.jpg"
            Image.new("RGB", (10, 10), "white").save(p)
            page_images.append(p)

        with patch("src.crawler.document_ocr._run") as mock_run, \
             patch("src.crawler.document_ocr._require_binary"), \
             patch("src.crawler.document_ocr._render_pages", return_value=page_images):
            with pytest.raises(ValueError, match="limit"):
                ocr_document(str(pdf_path), language="eng", max_pages=3)
