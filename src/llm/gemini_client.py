"""Thin wrapper around the Google Gen AI SDK.

Centralizes client construction and the three call shapes used by the
project (plain text, structured JSON, and Google-Search-grounded) so the
higher-level modules don't each import the SDK directly. This also makes
the Gemini surface easy to mock in tests by substituting
:meth:`GeminiClient.generate_content`.

``TieredGeminiClient`` extends this with a multi-tier fallback strategy:
free-tier AI Studio API keys are tried first (round-robin across all
configured keys), and when all are quota-exhausted (429), it falls back to
Vertex AI (paid) via Application Default Credentials. This lets
``scripts/03_targeted_entity_research.py`` use free quota first and only
incur paid API costs for leads that couldn't be searched for free.
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

    An optional ``cost_tracker`` (a :class:`src.llm.cost_tracker.GeminiCostTracker`)
    may be attached. When present, each successful API call is reported to the
    CloudManagement hub as an incremental actual (best-effort, never blocks).
    This makes any caller of ``GeminiClient`` cost-tracked without each call
    site wiring its own reporting — mirroring how ``TieredGeminiClient``
    reports via its own ``_report_call``. The inner ``GeminiClient`` instances
    built by ``TieredGeminiClient`` never carry a tracker, so there is no
    double-reporting when a ``TieredGeminiClient`` delegates to them.
    """

    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        cost_tracker: Any = None,
    ):
        self._api_key = api_key if api_key is not None else settings.gemini_api_key
        self._model = model or settings.gemini_model
        self._client: Any = None
        # Optional cost tracker (src.llm.cost_tracker.GeminiCostTracker).
        # When attached, _report_call is invoked after each successful API
        # call (best-effort, never blocks). Plain GeminiClient always uses
        # an AI Studio key (free tier), so calls are reported as tier="free"
        # with cost_usd=0.0 — matching TieredGeminiClient's free-tier reporting.
        self._cost_tracker = cost_tracker
        # Local call counter (mirrors TieredGeminiClient.free_calls).
        self.free_calls = 0

    def _report_call(self, tier: str, model: str, cost_usd: float) -> None:
        """Best-effort cost-tracker report after a successful API call.

        Never raises — all errors are logged at WARNING inside the tracker.
        """
        tracker = self._cost_tracker
        if tracker is None:
            return
        try:
            tracker.report_call(tier=tier, model=model, cost_usd=cost_usd)
        except Exception as e:
            _log.warning("cost_tracker report_call failed (best-effort): %s", e)

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
            response = client.models.generate_content(
                model=model or self._model,
                contents=contents,
                config=config,
            )
        except Exception as e:
            raise GeminiError(f"Gemini generate_content failed: {e}") from e
        # Report the successful call to the cost tracker (best-effort).
        # Plain GeminiClient uses an AI Studio key (free tier), so tier="free"
        # and cost_usd=0.0 — matching TieredGeminiClient's free-tier reporting.
        self.free_calls += 1
        self._report_call(tier="free", model=model or self._model, cost_usd=0.0)
        return response

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

    @property
    def stats(self) -> dict[str, Any]:
        """Summary stats for reporting (mirrors TieredGeminiClient.stats shape)."""
        s: dict[str, Any] = {
            "free_calls": self.free_calls,
            "paid_calls": 0,
        }
        if self._cost_tracker is not None:
            s["total_cost_usd"] = self._cost_tracker.total_cost_usd
            s["cost_tracker_enabled"] = self._cost_tracker.is_available()
        return s


class TieredGeminiClient:
    """Multi-tier Gemini client: free-tier AI Studio keys first, then Vertex AI paid.

    Tries each configured AI Studio API key in order. On 429
    (RESOURCE_EXHAUSTED), marks that key as exhausted and moves to the
    next. When all free-tier keys are exhausted, falls back to Vertex AI
    (paid) via Application Default Credentials — but only for calls
    explicitly opted in via ``allow_paid=True`` (default False), so
    non-targeted-research callers never accidentally incur paid costs.

    The ``paid_calls`` counter tracks how many calls went to the paid
    tier, surfaced in the script summary so the operator can see the
    cost split.
    """

    def __init__(
        self,
        free_tier_keys: Optional[list[str]] = None,
        vertexai_enabled: Optional[bool] = None,
        vertexai_project: Optional[str] = None,
        vertexai_location: Optional[str] = None,
        vertexai_model: Optional[str] = None,
        ai_studio_model: Optional[str] = None,
        cost_tracker: Any = None,
    ):
        # Collect non-empty free-tier keys.
        if free_tier_keys is not None:
            self._free_keys = [k for k in free_tier_keys if k]
        else:
            self._free_keys = [
                k for k in (
                    settings.gemini_api_key,
                    settings.google_api_key,
                    settings.movement_arts_google_api_key,
                ) if k
            ]
        self._exhausted_keys: set[int] = set()
        self._current_key_idx = 0

        self._vertexai_enabled = (
            vertexai_enabled if vertexai_enabled is not None
            else settings.gemini_vertexai_enabled
        )
        self._vertexai_project = (
            vertexai_project if vertexai_project is not None
            else settings.gemini_vertexai_project
        )
        self._vertexai_location = (
            vertexai_location if vertexai_location is not None
            else settings.gemini_vertexai_location
        )
        self._vertexai_model = (
            vertexai_model if vertexai_model is not None
            else settings.gemini_vertexai_model
        )
        self._ai_studio_model = ai_studio_model or settings.gemini_model

        self._vertexai_client: Any = None
        self._vertexai_available: Optional[bool] = None

        # Optional cost tracker (src.llm.cost_tracker.GeminiCostTracker).
        # When attached, report_call is invoked after each successful API
        # call (best-effort, never blocks).
        self._cost_tracker = cost_tracker

        # Stats
        self.free_calls = 0
        self.paid_calls = 0
        self.free_keys_exhausted_count = 0

    def is_available(self) -> bool:
        """True if at least one free-tier key has quota OR Vertex AI is reachable."""
        if self._has_free_quota():
            return True
        if self._vertexai_enabled:
            return self._ensure_vertexai_client() is not None
        return False

    def _report_call(self, tier: str, model: str, cost_usd: float) -> None:
        """Best-effort cost-tracker report after a successful API call.

        Never raises — all errors are logged at WARNING inside the tracker.
        """
        tracker = self._cost_tracker
        if tracker is None:
            return
        try:
            tracker.report_call(tier=tier, model=model, cost_usd=cost_usd)
        except Exception as e:
            _log.warning("cost_tracker report_call failed (best-effort): %s", e)

    def _has_free_quota(self) -> bool:
        return any(i not in self._exhausted_keys for i in range(len(self._free_keys)))

    def _current_free_client(self) -> Optional[GeminiClient]:
        """Return a GeminiClient for the first non-exhausted free-tier key."""
        for i in range(len(self._free_keys)):
            if i not in self._exhausted_keys:
                self._current_key_idx = i
                return GeminiClient(
                    api_key=self._free_keys[i],
                    model=self._ai_studio_model,
                )
        return None

    def _ensure_vertexai_client(self) -> Any:
        """Lazily construct the Vertex AI client via ADC. Returns None on failure."""
        if self._vertexai_client is not None:
            return self._vertexai_client
        if not self._vertexai_enabled:
            return None
        try:
            from google import genai  # type: ignore
            from google.auth import default as _adc_default  # type: ignore
        except ImportError as e:
            _log.warning("Vertex AI fallback unavailable (missing SDK): %s", e)
            self._vertexai_available = False
            return None
        try:
            creds, project = _adc_default()
            project = self._vertexai_project or project
            if not project:
                _log.warning("Vertex AI fallback unavailable: no GCP project resolved")
                self._vertexai_available = False
                return None
            self._vertexai_client = genai.Client(
                vertexai=True,
                credentials=creds,
                project=project,
                location=self._vertexai_location,
            )
            self._vertexai_available = True
            _log.info("Vertex AI paid-tier fallback ready (project=%s, model=%s)",
                      project, self._vertexai_model)
            return self._vertexai_client
        except Exception as e:
            _log.warning("Vertex AI fallback construction failed: %s", e)
            self._vertexai_available = False
            return None

    def generate_grounded(
        self,
        prompt: str,
        *,
        allow_paid: bool = False,
        model: Optional[str] = None,
    ) -> GroundingResult:
        """Google-Search-grounded generation with tiered fallback.

        Args:
            prompt: The search/grounding prompt.
            allow_paid: If True, fall back to Vertex AI (paid) when all
                free-tier keys are exhausted. If False (default), raise
                GeminiError when free quota is gone — so non-targeted-
                research callers never accidentally incur paid costs.
            model: Override model name (applies to AI Studio tier only;
                Vertex AI always uses its own configured model).
        """
        from google.genai import types  # type: ignore

        config = types.GenerateContentConfig(
            tools=[types.Tool(google_search=types.GoogleSearch())]
        )

        # --- Tier 1: free-tier AI Studio keys ---
        while self._has_free_quota():
            client = self._current_free_client()
            if client is None:
                break
            key_idx = self._current_key_idx
            try:
                response = client.generate_content(
                    prompt, model=model or self._ai_studio_model, config=config,
                )
                self.free_calls += 1
                self._report_call(tier="free", model=model or self._ai_studio_model, cost_usd=0.0)
                text = _response_text(response)
                sources = _extract_grounding_sources(response)
                return GroundingResult(text=text, sources=sources, raw=response)
            except GeminiError as e:
                if "429" in str(e) or "RESOURCE_EXHAUSTED" in str(e):
                    _log.warning(
                        "Free-tier key #%d quota exhausted (429); moving to next key",
                        key_idx,
                    )
                    self._exhausted_keys.add(key_idx)
                    self.free_keys_exhausted_count += 1
                    continue
                # Non-quota error — don't try other keys, just raise.
                raise
            except Exception as e:
                # Treat unexpected errors from a free key as potentially
                # key-specific; try the next key before giving up.
                _log.warning("Free-tier key #%d error: %s; trying next", key_idx, e)
                self._exhausted_keys.add(key_idx)
                continue

        # --- Tier 2: Vertex AI (paid) ---
        if not allow_paid:
            raise GeminiError(
                "All free-tier Gemini keys exhausted and allow_paid=False. "
                f"Free calls: {self.free_calls}, keys exhausted: "
                f"{len(self._exhausted_keys)}/{len(self._free_keys)}. "
                "Set allow_paid=True to fall back to Vertex AI (paid)."
            )

        va_client = self._ensure_vertexai_client()
        if va_client is None:
            raise GeminiError(
                "All free-tier keys exhausted and Vertex AI fallback is not "
                "available. Check GEMINI_VERTEXAI_ENABLED and ADC credentials."
            )

        _log.info("Falling back to Vertex AI paid tier for this call")
        try:
            response = va_client.models.generate_content(
                model=self._vertexai_model,
                contents=prompt,
                config=config,
            )
            self.paid_calls += 1
            self._report_call(tier="paid", model=self._vertexai_model, cost_usd=0.01)
            text = _response_text(response)
            sources = _extract_grounding_sources(response)
            return GroundingResult(text=text, sources=sources, raw=response)
        except Exception as e:
            raise GeminiError(f"Vertex AI paid-tier call failed: {e}") from e

    def generate_content(
        self,
        contents: str,
        *,
        allow_paid: bool = False,
        model: Optional[str] = None,
        config: Any = None,
    ) -> Any:
        """Plain generate_content with the same tiered fallback as generate_grounded."""
        # --- Tier 1: free-tier AI Studio keys ---
        while self._has_free_quota():
            client = self._current_free_client()
            if client is None:
                break
            key_idx = self._current_key_idx
            try:
                response = client.generate_content(
                    contents, model=model or self._ai_studio_model, config=config,
                )
                self.free_calls += 1
                self._report_call(tier="free", model=model or self._ai_studio_model, cost_usd=0.0)
                return response
            except GeminiError as e:
                if "429" in str(e) or "RESOURCE_EXHAUSTED" in str(e):
                    _log.warning(
                        "Free-tier key #%d quota exhausted (429); moving to next key",
                        key_idx,
                    )
                    self._exhausted_keys.add(key_idx)
                    self.free_keys_exhausted_count += 1
                    continue
                raise
            except Exception as e:
                _log.warning("Free-tier key #%d error: %s; trying next", key_idx, e)
                self._exhausted_keys.add(key_idx)
                continue

        # --- Tier 2: Vertex AI (paid) ---
        if not allow_paid:
            raise GeminiError(
                "All free-tier Gemini keys exhausted and allow_paid=False."
            )
        va_client = self._ensure_vertexai_client()
        if va_client is None:
            raise GeminiError(
                "All free-tier keys exhausted and Vertex AI fallback unavailable."
            )
        try:
            response = va_client.models.generate_content(
                model=self._vertexai_model,
                contents=contents,
                config=config,
            )
            self.paid_calls += 1
            self._report_call(tier="paid", model=self._vertexai_model, cost_usd=0.01)
            return response
        except Exception as e:
            raise GeminiError(f"Vertex AI paid-tier call failed: {e}") from e

    def generate_json(
        self,
        prompt: str,
        response_schema: dict[str, Any],
        *,
        allow_paid: bool = False,
        model: Optional[str] = None,
        system_instruction: Optional[str] = None,
    ) -> Any:
        """Structured JSON generation with tiered fallback.

        Mirrors ``GeminiClient.generate_json`` but routes through the
        tiered ``generate_content`` so free-tier keys are used first.
        """
        from google.genai import types  # type: ignore

        cfg_kwargs: dict[str, Any] = {
            "response_mime_type": "application/json",
            "response_json_schema": response_schema,
        }
        if system_instruction:
            cfg_kwargs["system_instruction"] = system_instruction
        config = types.GenerateContentConfig(**cfg_kwargs)
        response = self.generate_content(
            prompt, allow_paid=allow_paid,
            model=model or self._ai_studio_model, config=config,
        )
        text = _response_text(response)
        try:
            return json.loads(text)
        except json.JSONDecodeError as e:
            raise GeminiError(f"Gemini returned invalid JSON: {e}\n{text}") from e

    def generate_text(
        self,
        prompt: str,
        *,
        allow_paid: bool = False,
        model: Optional[str] = None,
        system_instruction: Optional[str] = None,
    ) -> str:
        """Plain text generation with tiered fallback."""
        from google.genai import types  # type: ignore

        cfg_kwargs: dict[str, Any] = {}
        if system_instruction:
            cfg_kwargs["system_instruction"] = system_instruction
        config = types.GenerateContentConfig(**cfg_kwargs) if cfg_kwargs else None
        response = self.generate_content(
            prompt, allow_paid=allow_paid,
            model=model or self._ai_studio_model, config=config,
        )
        return _response_text(response)

    @property
    def stats(self) -> dict[str, Any]:
        """Summary stats for reporting."""
        s: dict[str, Any] = {
            "free_calls": self.free_calls,
            "paid_calls": self.paid_calls,
            "free_keys_total": len(self._free_keys),
            "free_keys_exhausted": len(self._exhausted_keys),
        }
        if self._cost_tracker is not None:
            s["total_cost_usd"] = self._cost_tracker.total_cost_usd
            s["cost_tracker_enabled"] = self._cost_tracker.is_available()
        return s


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
