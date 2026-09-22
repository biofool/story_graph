"""Unit tests for the person-enrichment pipeline (scripts/34_enrich_person.py).

Covers:
- Magazine archive discovery constants and domain filtering
- Enrichment method ordering (ALL_METHODS)
- Idempotent skip logic (method_already_tried)
- Vertex AI redirect resolution
- Query building (contamination-safe single-entity templates)

All tests use mocks — no API keys or network required.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

_SCRIPT_PATH = (
    Path(__file__).resolve().parent.parent.parent
    / "scripts"
    / "34_enrich_person.py"
)

# We need to mock heavy imports before loading the enrichment script.
# The script imports from src.crawler, src.llm, etc. which may have
# system-level dependencies (tesseract, etc.) that we don't want to
# trigger in unit tests.


@pytest.fixture(scope="module")
def enrich():
    """Load the enrichment module.

    Must register the module in sys.modules before exec so that Python 3.14's
    dataclass decorator can look up cls.__module__ successfully.
    """
    spec = importlib.util.spec_from_file_location("enrich", str(_SCRIPT_PATH))
    mod = importlib.util.module_from_spec(spec)
    sys.modules["enrich"] = mod
    spec.loader.exec_module(mod)
    return mod


# ---------------------------------------------------------------------------
#  Magazine archive constants
# ---------------------------------------------------------------------------


class TestMagazineArchiveConstants:
    def test_all_nine_magazines_present(self, enrich):
        """All 9 martial-arts magazines should be in _MARTIAL_ARTS_MAGAZINES."""
        names = [m["name"] for m in enrich._MARTIAL_ARTS_MAGAZINES]
        assert len(names) == 9
        expected = {
            "Black Belt Magazine",
            "Karate Illustrated",
            "Blitz Magazine",
            "Aikido Journal",
            "Fighting Stars",
            "Inside Kung-Fu",
            "Aikido Today Magazine",
            "Tai Chi Chuan Journal",
            "Journal of Asian Martial Arts",
        }
        assert set(names) == expected

    def test_doc_archive_domains(self, enrich):
        """Doc-archive domains should include key document hosts."""
        domains = enrich._DOC_ARCHIVE_DOMAINS
        assert "archive.org" in domains
        assert "scribd.com" in domains
        assert "doczz.net" in domains

    def test_wiki_mirror_domains(self, enrich):
        """Wiki-mirror domains should be recognized for citation tracing."""
        mirrors = enrich._WIKI_MIRROR_DOMAINS
        assert "wikitia.com" in mirrors
        assert "en-academic.com" in mirrors
        assert "alchetron.com" in mirrors

    def test_magazine_archive_domains(self, enrich):
        """Google Books locales should be in magazine archive domains."""
        archives = enrich._MAGAZINE_ARCHIVE_DOMAINS
        assert "books.google.com" in archives
        assert "books.google.co.nz" in archives

    def test_combined_relevant_domains(self, enrich):
        """_MAGAZINE_RELEVANT_DOMAINS should be a superset of all component lists."""
        combined = enrich._MAGAZINE_RELEVANT_DOMAINS
        for d in enrich._DOC_ARCHIVE_DOMAINS:
            assert d in combined
        for d in enrich._WIKI_MIRROR_DOMAINS:
            assert d in combined
        for d in enrich._MAGAZINE_ARCHIVE_DOMAINS:
            assert d in combined
        # Magazine domains with non-empty domain field
        for m in enrich._MARTIAL_ARTS_MAGAZINES:
            if m["domain"]:
                assert m["domain"] in combined

    def test_facebook_not_in_relevant_domains(self, enrich):
        """Social media URLs should not be in the magazine-relevant set."""
        assert "facebook.com" not in enrich._MAGAZINE_RELEVANT_DOMAINS
        assert "twitter.com" not in enrich._MAGAZINE_RELEVANT_DOMAINS
        assert "instagram.com" not in enrich._MAGAZINE_RELEVANT_DOMAINS


# ---------------------------------------------------------------------------
#  Enrichment method ordering
# ---------------------------------------------------------------------------


class TestMethodOrdering:
    def test_all_methods_list(self, enrich):
        """ALL_METHODS should contain the 8 ordered methods."""
        assert enrich.ALL_METHODS == [
            "google_kg",
            "gemini_grounded",
            "brave",
            "bing",
            "duckduckgo",
            "magazine_archive",
            "reference_discovery",
            "arctic_shift",
        ]

    def test_all_methods_count(self, enrich):
        assert len(enrich.ALL_METHODS) == 8

    def test_google_kg_is_first(self, enrich):
        """google_kg should be tried first (most authoritative, free)."""
        assert enrich.ALL_METHODS[0] == "google_kg"

    def test_arctic_shift_is_last(self, enrich):
        """arctic_shift (Reddit archive) should be tried last."""
        assert enrich.ALL_METHODS[-1] == "arctic_shift"


# ---------------------------------------------------------------------------
#  Idempotent skip logic (method_already_tried)
# ---------------------------------------------------------------------------


class TestMethodAlreadyTried:
    def _make_ctx(self, enrich, cache=None, person_node_id=None, db=None):
        """Build a minimal EnrichmentContext for skip-logic tests."""
        return enrich.EnrichmentContext(
            person_name="Test Person",
            person_node_id=person_node_id,
            dates=[],
            cities=[],
            context="",
            db=db or MagicMock(),
            cache=cache,
            quota=None,
            kg_client=None,
            gemini_client=None,
            gemini_ext=None,
            gemini_claim_ext=None,
            brave_client=None,
            bing_client=None,
            ddg_client=None,
        )

    def test_google_kg_not_tried_without_metadata(self, enrich):
        db = MagicMock()
        db.get_node.return_value = MagicMock(metadata={})
        ctx = self._make_ctx(enrich, person_node_id="person:test", db=db)
        assert enrich.method_already_tried(ctx, "google_kg") is False

    def test_google_kg_already_tried(self, enrich):
        db = MagicMock()
        db.get_node.return_value = MagicMock(metadata={"kg_enriched": True})
        ctx = self._make_ctx(enrich, person_node_id="person:test", db=db)
        assert enrich.method_already_tried(ctx, "google_kg") is True

    def test_reference_discovery_not_tried(self, enrich):
        db = MagicMock()
        db.get_node.return_value = MagicMock(metadata={})
        ctx = self._make_ctx(enrich, person_node_id="person:test", db=db)
        assert enrich.method_already_tried(ctx, "reference_discovery") is False

    def test_reference_discovery_already_done(self, enrich):
        db = MagicMock()
        db.get_node.return_value = MagicMock(metadata={"ref_discovery_done": True})
        ctx = self._make_ctx(enrich, person_node_id="person:test", db=db)
        assert enrich.method_already_tried(ctx, "reference_discovery") is True

    def test_search_method_not_tried_without_cache(self, enrich):
        """With no cache, search methods report as not tried."""
        ctx = self._make_ctx(enrich, cache=None)
        assert enrich.method_already_tried(ctx, "brave") is False
        assert enrich.method_already_tried(ctx, "bing") is False
        assert enrich.method_already_tried(ctx, "duckduckgo") is False

    def test_arctic_shift_not_tried_without_cache(self, enrich):
        ctx = self._make_ctx(enrich, cache=None)
        assert enrich.method_already_tried(ctx, "arctic_shift") is False


# ---------------------------------------------------------------------------
#  Vertex AI redirect resolution
# ---------------------------------------------------------------------------


class TestVertexAIRedirect:
    def test_non_vertex_url_passthrough(self, enrich):
        """Non-Vertex URLs should be returned unchanged."""
        url = "https://example.com/article"
        assert enrich._resolve_redirect_url(url) == url

    def test_vertex_redirect_resolved(self, enrich):
        """A Vertex redirect URL should be resolved to the final URL."""
        vertex_url = (
            "https://vertexaisearch.cloud.google.com/grounding-api-redirect/abc123"
        )
        final_url = "https://aikidojournal.com/article"
        mock_resp = MagicMock()
        mock_resp.url = final_url
        mock_resp.headers = {}
        with patch("requests.get", return_value=mock_resp) as mock_get:
            result = enrich._resolve_redirect_url(vertex_url)
        assert result == final_url
        mock_get.assert_called_once()

    def test_vertex_redirect_failure_returns_original(self, enrich):
        """If redirect resolution fails, return the original URL."""
        vertex_url = (
            "https://vertexaisearch.cloud.google.com/grounding-api-redirect/xyz789"
        )
        with patch("requests.get", side_effect=Exception("timeout")):
            result = enrich._resolve_redirect_url(vertex_url)
        assert result == vertex_url

    def test_vertex_redirect_circular_returns_original(self, enrich):
        """If redirect leads back to another Vertex URL, return original."""
        vertex_url = (
            "https://vertexaisearch.cloud.google.com/grounding-api-redirect/abc"
        )
        mock_resp = MagicMock()
        mock_resp.url = (
            "https://vertexaisearch.cloud.google.com/grounding-api-redirect/def"
        )
        mock_resp.headers = {"Location": ""}
        with patch("requests.get", return_value=mock_resp):
            result = enrich._resolve_redirect_url(vertex_url)
        assert result == vertex_url


# ---------------------------------------------------------------------------
#  Query building (contamination-safe)
# ---------------------------------------------------------------------------


class TestQueryBuilding:
    def test_base_templates_generated(self, enrich):
        queries = enrich.build_queries("Robert Nadeau", [], [], "aikido")
        assert len(queries) >= 1
        # All queries should contain the person name in quotes
        for q in queries:
            assert "Robert Nadeau" in q

    def test_city_queries(self, enrich):
        queries = enrich.build_queries(
            "Robert Nadeau", [], ["san francisco"], "aikido"
        )
        city_queries = [q for q in queries if "san francisco" in q.lower()]
        assert len(city_queries) >= 1

    def test_date_queries(self, enrich):
        queries = enrich.build_queries(
            "Robert Nadeau", ["1987"], [], "aikido"
        )
        date_queries = [q for q in queries if "1987" in q]
        assert len(date_queries) >= 1

    def test_cross_product_capped(self, enrich):
        """City x date cross-product should be capped at 12."""
        queries = enrich.build_queries(
            "Robert Nadeau",
            [str(y) for y in range(1980, 2000)],  # 20 dates
            [f"city{i}" for i in range(20)],       # 20 cities
            "aikido",
        )
        # Cross-product would be 400, but it's capped at 12
        cross_queries = [
            q for q in queries if "city" in q and any(str(y) in q for y in range(1980, 2000))
        ]
        assert len(cross_queries) <= 12

    def test_no_duplicate_queries(self, enrich):
        queries = enrich.build_queries(
            "Robert Nadeau", ["1990"], ["moscow"], "aikido"
        )
        assert len(queries) == len(set(queries))

    def test_single_entity_templates_exist(self, enrich):
        """Verify that single-entity templates are contamination-safe."""
        templates = enrich._single_entity_templates("aikido")
        assert len(templates) >= 1
        # Every template should have {a} placeholder (single entity)
        for t in templates:
            assert "{a}" in t
        # No pair templates (no {b} placeholder)
        for t in templates:
            assert "{b}" not in t


# ---------------------------------------------------------------------------
#  MethodResult
# ---------------------------------------------------------------------------


class TestMethodResult:
    def test_as_row_tried(self, enrich):
        r = enrich.MethodResult(
            method="brave", tried=True, new_urls=5, new_nodes=3, new_edges=7,
            status="OK",
        )
        row = r.as_row()
        assert row[0] == "brave"
        assert row[1] == "Yes"
        assert row[2] == "5"

    def test_as_row_skipped(self, enrich):
        r = enrich.MethodResult(
            method="bing", skipped=True, skip_reason="no API key",
        )
        row = r.as_row()
        assert "Skipped" in row[1]
        assert "no API key" in row[1]

    def test_as_row_not_tried(self, enrich):
        r = enrich.MethodResult(method="duckduckgo")
        row = r.as_row()
        assert row[1] == "No"
