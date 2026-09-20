"""Unit tests for the Knowledge Graph client (src/search/kg_client.py).

Covers:
- Entity resolution from fake API responses
- No-result handling
- API error handling (HTTP 4xx/5xx)
- Caching
- resolve_person helper
- Availability check

All tests use mocks — no API keys or network required.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from src.search.kg_client import KGEntity, KnowledgeGraphClient


# Sample API response
_SAMPLE_RESPONSE = {
    "itemListElement": [
        {
            "result": {
                "@id": "kg:/m/0test",
                "@type": ["Person", "Thing"],
                "name": "Peter Ralston",
                "description": "American martial artist",
                "url": "https://peterralston.com",
                "detailedDescription": {
                    "url": "https://en.wikipedia.org/wiki/Peter_Ralston",
                    "articleBody": "Peter Ralston is an American martial artist...",
                },
            },
            "resultScore": 100.0,
        }
    ]
}

_EMPTY_RESPONSE = {"itemListElement": []}

_MALFORMED_RESPONSE = {
    "itemListElement": [
        {"result": {"@type": ["Thing"]}},  # missing "name"
        {
            "result": {
                "@type": "Person",  # string instead of list
                "name": "Valid Person",
            }
        },
    ]
}


# ---------------------------------------------------------------------------
#  Entity resolution
# ---------------------------------------------------------------------------


def _mock_urlopen(response_data):
    """Create a context-manager mock for urllib.request.urlopen."""
    mock_resp = MagicMock()
    mock_resp.read.return_value = json.dumps(response_data).encode()
    mock_resp.__enter__ = lambda s: s
    mock_resp.__exit__ = lambda s, *a: None
    return mock_resp


class TestEntityResolution:
    def test_successful_search(self):
        client = KnowledgeGraphClient(api_key="fake-key")
        with patch("urllib.request.urlopen", return_value=_mock_urlopen(_SAMPLE_RESPONSE)):
            entities = client.search("Peter Ralston")

        assert len(entities) == 1
        e = entities[0]
        assert e.kg_id == "kg:/m/0test"
        assert e.name == "Peter Ralston"
        assert "Person" in e.types
        assert e.description == "American martial artist"
        assert e.wikipedia_url == "https://en.wikipedia.org/wiki/Peter_Ralston"
        assert e.url == "https://peterralston.com"
        assert e.article_body == "Peter Ralston is an American martial artist..."

    def test_empty_results(self):
        client = KnowledgeGraphClient(api_key="fake-key")
        with patch("urllib.request.urlopen", return_value=_mock_urlopen(_EMPTY_RESPONSE)):
            entities = client.search("Nonexistent Person XYZZY")

        assert entities == []

    def test_malformed_response_skips_nameless_items(self):
        client = KnowledgeGraphClient(api_key="fake-key")
        with patch("urllib.request.urlopen", return_value=_mock_urlopen(_MALFORMED_RESPONSE)):
            entities = client.search("Test")

        # First item has no name -> skipped; second has name -> included
        assert len(entities) == 1
        assert entities[0].name == "Valid Person"

    def test_string_type_normalized_to_list(self):
        client = KnowledgeGraphClient(api_key="fake-key")
        with patch("urllib.request.urlopen", return_value=_mock_urlopen(_MALFORMED_RESPONSE)):
            entities = client.search("Test")

        # Second item has @type as string "Person" -> should be normalized to list
        assert entities[0].types == ["Person"]


# ---------------------------------------------------------------------------
#  API error handling
# ---------------------------------------------------------------------------


class TestAPIErrorHandling:
    def test_http_error_returns_empty(self):
        client = KnowledgeGraphClient(api_key="fake-key")
        import urllib.error

        http_error = urllib.error.HTTPError(
            url="https://kgsearch.googleapis.com",
            code=403,
            msg="Forbidden",
            hdrs={},
            fp=MagicMock(read=lambda: b"Access denied"),
        )
        with patch("urllib.request.urlopen", side_effect=http_error):
            entities = client.search("Test")

        assert entities == []

    def test_network_error_returns_empty(self):
        client = KnowledgeGraphClient(api_key="fake-key")
        with patch("urllib.request.urlopen", side_effect=ConnectionError("timeout")):
            entities = client.search("Test")

        assert entities == []

    def test_json_decode_error_returns_empty(self):
        client = KnowledgeGraphClient(api_key="fake-key")
        mock_resp = MagicMock()
        mock_resp.read.return_value = b"not json"
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = lambda s, *a: None
        with patch("urllib.request.urlopen", return_value=mock_resp):
            entities = client.search("Test")

        assert entities == []


# ---------------------------------------------------------------------------
#  Caching
# ---------------------------------------------------------------------------


class TestCaching:
    def test_cache_hit(self):
        client = KnowledgeGraphClient(api_key="fake-key")
        with patch("urllib.request.urlopen", return_value=_mock_urlopen(_SAMPLE_RESPONSE)) as mock_url:
            result1 = client.search("Peter Ralston", limit=5)
            result2 = client.search("Peter Ralston", limit=5)

        # urlopen should only be called once; second call uses cache
        assert mock_url.call_count == 1
        assert len(result1) == len(result2)
        assert result1[0].name == result2[0].name

    def test_different_queries_not_cached(self):
        client = KnowledgeGraphClient(api_key="fake-key")
        with patch("urllib.request.urlopen", return_value=_mock_urlopen(_SAMPLE_RESPONSE)) as mock_url:
            client.search("Peter Ralston")
            client.search("Robert Nadeau")

        assert mock_url.call_count == 2


# ---------------------------------------------------------------------------
#  Availability
# ---------------------------------------------------------------------------


class TestAvailability:
    def test_available_with_key(self):
        client = KnowledgeGraphClient(api_key="fake-key")
        assert client.is_available() is True

    def test_unavailable_without_key(self):
        with patch.dict("os.environ", {}, clear=True):
            # Clear env vars that the constructor checks
            client = KnowledgeGraphClient(api_key="")
        assert client.is_available() is False

    def test_search_returns_empty_when_unavailable(self):
        client = KnowledgeGraphClient(api_key="")
        client.api_key = ""
        entities = client.search("Test")
        assert entities == []


# ---------------------------------------------------------------------------
#  resolve_person helper
# ---------------------------------------------------------------------------


class TestResolvePerson:
    def test_resolve_person_returns_first_match(self):
        client = KnowledgeGraphClient(api_key="fake-key")
        with patch("urllib.request.urlopen", return_value=_mock_urlopen(_SAMPLE_RESPONSE)):
            entity = client.resolve_person("Peter Ralston")

        assert entity is not None
        assert entity.name == "Peter Ralston"

    def test_resolve_person_with_context(self):
        client = KnowledgeGraphClient(api_key="fake-key")
        with patch("urllib.request.urlopen", return_value=_mock_urlopen(_SAMPLE_RESPONSE)):
            entity = client.resolve_person("Peter Ralston", context="aikido")

        assert entity is not None

    def test_resolve_person_falls_back_to_untyped(self):
        """If typed search returns nothing, falls back to untyped."""
        client = KnowledgeGraphClient(api_key="fake-key")
        call_count = [0]

        def mock_urlopen(req, timeout=None):
            call_count[0] += 1
            if call_count[0] == 1:
                # First call (typed) returns empty
                return _mock_urlopen(_EMPTY_RESPONSE)
            else:
                # Second call (untyped) returns result
                return _mock_urlopen(_SAMPLE_RESPONSE)

        with patch("urllib.request.urlopen", side_effect=mock_urlopen):
            entity = client.resolve_person("Peter Ralston")

        assert entity is not None

    def test_resolve_person_returns_none_when_nothing_found(self):
        client = KnowledgeGraphClient(api_key="fake-key")
        with patch("urllib.request.urlopen", return_value=_mock_urlopen(_EMPTY_RESPONSE)):
            entity = client.resolve_person("Nonexistent Person XYZZY")

        assert entity is None
