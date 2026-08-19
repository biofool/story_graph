"""Thin wrapper around the Google Gen AI SDK.

Centralizes client construction and the three call shapes used by the
project (plain text, structured JSON, and Google-Search-grounded) so the
higher-level modules don't each import the SDK directly. This also makes
the Gemini surface easy to mock in tests by substituting
:meth:`GeminiClient.generate_content`.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any

from config.settings import settings

_log = logging.getLogger(__name__)


@dataclass
class GroundingResult:
    """Result of a grounded (Google Search) generation."""

    text: str
    sources: list[dict[str, str]] = field(default_factory=list)
    """List of ``{"uri": ..., "title": ...}`` dicts from grounding metadata."""

    raw: Any = None
    """The raw SDK response, for advanced callers."""


class GeminiError(RuntimeError):
    """Raised when the Gemini API call fails or the SDK is unavailable."""


class GeminiClient:
    """Thin wrapper over ``google.genai.Client``.

    Construction is lazy: the real SDK client is only created on first
    use (or when :meth:`is_available` is called), so importing this
    module never requires the SDK or an API key.
    """

    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
    ):
        self._api_key = api_key if api_key is not None else settings.gemini_api_key
        self._model = model or settings.gemini_model
        self._client: Any = None

    # --- availability / construction ---

    def is_available(self) -> bool:
        """Return True if an API key is configured and the SDK imports."""
        if not self._api_key:
            return False
        try:
            self._ensure_client()
            return True
        except Exception as e:  # pragma: no cover - environment dependent
            _log.warning("Gemini SDK unavailable: %s", e)
            return False

    @property
    def model(self) -> str:
        return self._model

    def _ensure_client(self) -> Any:
        if self._client is not None:
            return self._client
        if not self._api_key:
            raise GeminiError(
                "GEMINI_API_KEY is not set; configure it in .env to use "
                "Gemini features."
            )
        try:
            from google import genai  # type: ignore
        except ImportError as e:
            raise GeminiError(
                "google-genai package is not installed (pip install google-genai)"
            ) from e
        self._client = genai.Client(api_key=self._api_key)
        return self._client

    # --- core call ---

    def generate_content(
        self,
        contents: str,
        *,
        model: str | None = None,
        config: Any = None,
    ) -> Any:
        """Call ``client.models.generate_content`` and return the raw response.

        Centralized so tests can monkeypatch this single method to fake
        the entire Gemini surface.
        """
        client = self._ensure_client()
        try:
            return client.models.generate_content(
                model=model or self._model,
                contents=contents,
                config=config,
            )
        except Exception as e:
            raise GeminiError(f"Gemini generate_content failed: {e}") from e

    # --- convenience shapes ---

    def generate_text(
        self,
        prompt: str,
        *,
        model: str | None = None,
        system_instruction: str | None = None,
    ) -> str:
        """Plain text generation. Returns the model's text output."""
        from google.genai import types  # type: ignore

        cfg_kwargs: dict[str, Any] = {}
        if system_instruction:
            cfg_kwargs["system_instruction"] = system_instruction
        config = types.GenerateContentConfig(**cfg_kwargs) if cfg_kwargs else None
        response = self.generate_content(prompt, model=model, config=config)
        return _response_text(response)

    def generate_json(
        self,
        prompt: str,
        response_schema: dict[str, Any],
        *,
        model: str | None = None,
        system_instruction: str | None = None,
    ) -> Any:
        """Structured JSON generation constrained to ``response_schema``.

        ``response_schema`` is a low-level JSON Schema dict passed via
        ``response_json_schema``. Returns the parsed Python object
        (dict / list).
        """
        from google.genai import types  # type: ignore

        cfg_kwargs: dict[str, Any] = {
            "response_mime_type": "application/json",
            "response_json_schema": response_schema,
        }
        if system_instruction:
            cfg_kwargs["system_instruction"] = system_instruction
        config = types.GenerateContentConfig(**cfg_kwargs)
        response = self.generate_content(prompt, model=model, config=config)
        text = _response_text(response)
        try:
            return json.loads(text)
        except json.JSONDecodeError as e:
            raise GeminiError(f"Gemini returned invalid JSON: {e}\n{text}") from e

    def generate_grounded(self, prompt: str, *, model: str | None = None) -> GroundingResult:
        """Generation with Google Search grounding.

        Returns the text plus the cited web sources extracted from
        grounding metadata.
        """
        from google.genai import types  # type: ignore

        config = types.GenerateContentConfig(
            tools=[types.Tool(google_search=types.GoogleSearch())]
        )
        response = self.generate_content(prompt, model=model, config=config)
        text = _response_text(response)
        sources = _extract_grounding_sources(response)
        return GroundingResult(text=text, sources=sources, raw=response)


# --- helpers (module-level so tests can reuse) ---


def _response_text(response: Any) -> str:
    """Extract text from a Gemini response, tolerating shape variations."""
    # Preferred: response.text (SDK convenience accessor).
    try:
        txt = getattr(response, "text", None)
        if txt:
            return txt
    except Exception:
        pass
    # Fallback: candidates[0].content.parts[*].text
    candidates = getattr(response, "candidates", None) or []
    if candidates:
        content = getattr(candidates[0], "content", None)
        parts = getattr(content, "parts", None) if content else None
        if parts:
            return "".join(p.text for p in parts if getattr(p, "text", None))
    raise GeminiError("Gemini response contained no text content")


def _extract_grounding_sources(response: Any) -> list[dict[str, str]]:
    """Pull ``{uri, title}`` dicts from grounding metadata."""
    out: list[dict[str, str]] = []
    candidates = getattr(response, "candidates", None) or []
    if not candidates:
        return out
    meta = getattr(candidates[0], "grounding_metadata", None)
    if meta is None:
        return out
    chunks = getattr(meta, "grounding_chunks", None) or []
    for chunk in chunks:
        web = getattr(chunk, "web", None)
        if web is None:
            continue
        uri = getattr(web, "uri", "") or ""
        title = getattr(web, "title", "") or ""
        if uri:
            out.append({"uri": uri, "title": title})
    return out
