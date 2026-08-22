"""Unit tests for the Gemini client wrapper.

Uses a fake client to avoid hitting the network and to sidestep the
google-genai SDK's response shapes. The wrapper's response-parsing
helpers are exercised via the fake response objects below.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest

from src.llm.gemini_client import (
    GeminiClient,
    GeminiError,
    _extract_grounding_sources,
    _response_text,
)

# --- fake SDK response shapes ---


@dataclass
class _Web:
    uri: str = ""
    title: str = ""


@dataclass
class _Chunk:
    web: _Web = field(default_factory=_Web)


@dataclass
class _GroundingMeta:
    grounding_chunks: list[_Chunk] = field(default_factory=list)


@dataclass
class _Candidate:
    content: Any = None
    grounding_metadata: Any = None


@dataclass
class _Content:
    parts: list[Any] = field(default_factory=list)


@dataclass
class _Part:
    text: str = ""


@dataclass
class _Response:
    """Minimal stand-in for a google.genai response object."""

    text: str = ""
    candidates: list[_Candidate] = field(default_factory=list)


class _FakeClient:
    """Fake google.genai.Client that records calls and returns canned data."""

    def __init__(self, response: Any):
        self._response = response
        self.calls: list[dict[str, Any]] = []

    class _Models:
        def __init__(self, outer):
            self._outer = outer

        def generate_content(self, *, model, contents, config):
            self._outer.calls.append({
                "model": model, "contents": contents, "config": config,
            })
            return self._outer._response

    @property
    def models(self):
        return self._Models(self)


class _FakeGeminiClient(GeminiClient):
    """GeminiClient that bypasses the real SDK and returns canned responses.

    Constructed with either a raw response object (for generate_content)
    or a parsed JSON object (for generate_json). Overrides the three
    public convenience methods so no SDK import is needed.
    """

    def __init__(self, *, raw_response: Any = None, json_obj: Any = None,
                 grounded: Any = None, available: bool = True):
        super().__init__(api_key="fake-key", model="gemini-fake")
        self._raw_response = raw_response
        self._json_obj = json_obj
        self._grounded = grounded
        self._available = available
        self.calls: list[dict[str, Any]] = []

    def is_available(self) -> bool:
        return self._available

    def generate_content(self, contents, *, model=None, config=None):
        self.calls.append({"contents": contents, "model": model, "config": config})
        return self._raw_response

    def generate_text(self, prompt, *, model=None, system_instruction=None):
        self.calls.append({"prompt": prompt, "system_instruction": system_instruction})
        return _response_text(self._raw_response)

    def generate_json(self, prompt, response_schema, *, model=None, system_instruction=None):
        self.calls.append({
            "prompt": prompt, "schema": response_schema,
            "system_instruction": system_instruction,
        })
        return self._json_obj

    def generate_grounded(self, prompt, *, model=None):
        self.calls.append({"prompt": prompt})
        return self._grounded


# --- tests ---


class TestResponseText:
    def test_prefers_response_text_attribute(self):
        resp = _Response(text="hello world")
        assert _response_text(resp) == "hello world"

    def test_falls_back_to_candidates_parts(self):
        resp = _Response(
            text="",
            candidates=[_Candidate(content=_Content(parts=[_Part(text="abc"), _Part(text="def")]))],
        )
        assert _response_text(resp) == "abcdef"

    def test_raises_when_no_text(self):
        with pytest.raises(GeminiError):
            _response_text(_Response())


class TestExtractGroundingSources:
    def test_extracts_uri_and_title(self):
        resp = _Response(candidates=[_Candidate(
            grounding_metadata=_GroundingMeta(grounding_chunks=[
                _Chunk(web=_Web(uri="https://a.com/1", title="A")),
                _Chunk(web=_Web(uri="https://b.com/2", title="B")),
            ])
        )])
        sources = _extract_grounding_sources(resp)
        assert sources == [
            {"uri": "https://a.com/1", "title": "A"},
            {"uri": "https://b.com/2", "title": "B"},
        ]

    def test_skips_chunks_without_uri(self):
        resp = _Response(candidates=[_Candidate(
            grounding_metadata=_GroundingMeta(grounding_chunks=[
                _Chunk(web=_Web(uri="", title="no uri")),
                _Chunk(web=_Web(uri="https://c.com/3", title="C")),
            ])
        )])
        sources = _extract_grounding_sources(resp)
        assert sources == [{"uri": "https://c.com/3", "title": "C"}]

    def test_no_candidates_returns_empty(self):
        assert _extract_grounding_sources(_Response()) == []

    def test_no_metadata_returns_empty(self):
        assert _extract_grounding_sources(
            _Response(candidates=[_Candidate()])
        ) == []


class TestGeminiClientAvailability:
    def test_unavailable_without_api_key(self, monkeypatch):
        # Force empty key
        from config import settings as settings_mod
        monkeypatch.setattr(settings_mod.settings, "_api_key", "", raising=False)
        client = GeminiClient(api_key="")
        assert not client.is_available()

    def test_generate_content_raises_without_key(self):
        client = GeminiClient(api_key="")
        with pytest.raises(GeminiError):
            client.generate_content("hi")
