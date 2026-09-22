"""Jev (TypeSafe System One) decision client for bounded verification.

Jev answers typed questions about a ``state`` — a choice from declared
options, a rubric score, or a yes/no probability — in ~70-500 ms at a
fraction of LLM cost. It cannot generate text, so it only fits decisions
with a declared answer space; extraction and synthesis stay on Gemini
(JEV assessment, ClipQuotes ticket #129).

Transport: OpenRouter Decisions API —
``POST https://openrouter.ai/api/alpha/decisions`` with
``{"model", "state", "questions"}``; the response is
``{"answers": {<question_name>: {"choice"|"noul"|"score", ...}}}``.

Lazy by design: importing this module never requires ``requests`` or an
API key, and ``decide()`` returns ``None`` on any failure so callers keep
their existing behavior.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Optional

_log = logging.getLogger(__name__)

DEFAULT_MODEL = "typesafe/jev-1.13"
DEFAULT_BASE_URL = "https://openrouter.ai/api/alpha/decisions"

# Bounded verdict set for claim verification — see verify_claim().
VERDICTS = ("supported", "contradicted", "unresolved")


class JevClient:
    """Thin wrapper over the OpenRouter Decisions API for Jev.

    Args:
        api_key: Defaults to ``JEV_API_KEY`` env var, falling back to
            ``OPENROUTER_API_KEY`` (Jev is accessed through OpenRouter).
        model: Defaults to ``JEV_MODEL`` or ``typesafe/jev-1.13``.
        base_url: Defaults to ``JEV_BASE_URL`` or the OpenRouter
            Decisions endpoint.
        timeout: Seconds; defaults to ``JEV_TIMEOUT_SECONDS`` or 10.
    """

    def __init__(self, api_key: Optional[str] = None,
                 model: Optional[str] = None,
                 base_url: Optional[str] = None,
                 timeout: Optional[float] = None):
        self.api_key = api_key if api_key is not None else (
            os.getenv("JEV_API_KEY") or os.getenv("OPENROUTER_API_KEY", "")
        )
        self.model = model or os.getenv("JEV_MODEL", DEFAULT_MODEL)
        self.base_url = base_url or os.getenv("JEV_BASE_URL", DEFAULT_BASE_URL)
        self.timeout = (
            timeout if timeout is not None
            else float(os.getenv("JEV_TIMEOUT_SECONDS", "10"))
        )

    def is_available(self) -> bool:
        """True when an API key is configured."""
        return bool(self.api_key)

    def decide(self, state: str, questions: dict) -> Optional[dict]:
        """Ask Jev typed questions about ``state``.

        Returns the response ``answers`` dict, or ``None`` when
        unconfigured, the request fails, or the response is malformed.
        Never raises.
        """
        if not self.api_key:
            return None
        try:
            import requests
        except ImportError:
            _log.warning("requests not installed; Jev decision skipped.")
            return None
        try:
            resp = requests.post(
                self.base_url,
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": self.model,
                    "state": state,
                    "questions": questions,
                },
                timeout=self.timeout,
            )
            if resp.status_code != 200:
                _log.warning("Jev decision failed: status=%d", resp.status_code)
                return None
            answers = (resp.json() or {}).get("answers")
            return answers if isinstance(answers, dict) else None
        except Exception as exc:  # noqa: BLE001 — degrade, never crash callers
            _log.warning("Jev decision failed: %s", exc)
            return None


def answer_confidence(answer: dict) -> float:
    """Extract a 0-1 confidence from a Jev answer dict.

    ``choice`` answers carry an explicit ``confidence`` plus a per-option
    ``probabilities`` map; when confidence is absent the chosen option's
    probability is used. ``noul`` answers carry only the probability, so
    confidence is distance from 0.5 scaled to [0, 1].
    """
    if not isinstance(answer, dict):
        return 0.0
    conf = answer.get("confidence")
    if isinstance(conf, (int, float)):
        return float(conf)
    choice = answer.get("choice")
    probs = answer.get("probabilities") or {}
    if choice and isinstance(probs.get(choice), (int, float)):
        return float(probs[choice])
    noul = answer.get("noul")
    if isinstance(noul, (int, float)):
        return abs(float(noul) - 0.5) * 2.0
    return 0.0


def verify_claim(claim_text: str, source_text: str,
                 client: Optional[JevClient] = None) -> Optional[dict[str, Any]]:
    """Verify a claim against its source text via a bounded Jev choice.

    Returns ``{"jev_verdict": ..., "jev_confidence": ...}`` with verdict in
    {supported, contradicted, unresolved}, or ``None`` when Jev is
    unavailable or the answer is malformed. Verification is metadata only
    — it annotates claims, it never drops them.
    """
    client = client or JevClient()
    if not client.is_available() or not claim_text:
        return None
    answers = client.decide(
        state=source_text[:12000],
        questions={"verdict": {
            "type": "choice",
            "instructions": (
                "Does the source text support this claim? Claim: "
                f"\"{claim_text[:1000]}\". Answer 'supported' only when the "
                "text directly states or clearly entails it; 'contradicted' "
                "when the text says the opposite; 'unresolved' when the "
                "text is silent or ambiguous."
            ),
            "criteria": {
                "supported": "The source text directly supports the claim.",
                "contradicted": "The source text contradicts the claim.",
                "unresolved": "The source text neither supports nor contradicts it.",
            },
        }},
    )
    answer = (answers or {}).get("verdict")
    verdict = (answer or {}).get("choice")
    if verdict not in VERDICTS:
        return None
    return {
        "jev_verdict": verdict,
        "jev_confidence": answer_confidence(answer),
    }
