"""Seed URL discovery via Gemini + Google Search grounding.

Asks Gemini to find web pages about The Source Family / Father Yod and
returns the grounded source URLs. These can be merged into
``settings.seed_urls`` (or used as one-off crawl seeds) to broaden the
corpus beyond the hand-curated seeds.

Supports both ``GeminiClient`` (single key) and ``TieredGeminiClient``
(free-tier-first with Vertex AI paid fallback). When a TieredGeminiClient
is passed, ``allow_paid`` controls whether the paid tier is used once
free quota is exhausted.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from src.llm.gemini_client import GeminiClient, GeminiError, TieredGeminiClient
from src.utils.text_utils import get_domain

_log = logging.getLogger(__name__)

# Default topic prompt used when no query is supplied.
DEFAULT_TOPIC = (
    "The Source Family, Father Yod (Jim Baker / Ya Ho Wa), and The Source "
    "Restaurant on the Sunset Strip in Los Angeles — memoirs, interviews, "
    "documentary coverage, criticism, and archival sources."
)


@dataclass
class DiscoveredSeed:
    """A single discovered seed URL with provenance."""

    url: str
    title: str
    domain: str
    via_query: str


class SeedDiscoverer:
    """Discovers new seed URLs using Gemini's Google Search grounding."""

    def __init__(self, client: GeminiClient | TieredGeminiClient | None = None):
        self._client = client or GeminiClient()
        self._is_tiered = isinstance(self._client, TieredGeminiClient)

    def discover(
        self,
        query: str | None = None,
        *,
        exclude_urls: set[str] | None = None,
        allow_paid: bool = False,
    ) -> list[DiscoveredSeed]:
        """Run a grounded search and return discovered seed URLs.

        Args:
            query: Optional natural-language query. Defaults to the
                Source Family topic.
            exclude_urls: URLs to filter out (e.g. existing seeds).
            allow_paid: If using a TieredGeminiClient, allow falling back
                to Vertex AI (paid) when free-tier keys are exhausted.
                Ignored for plain GeminiClient.
        """
        if not self._client.is_available():
            _log.warning("Gemini unavailable; seed discovery skipped.")
            return []

        topic = query or DEFAULT_TOPIC
        prompt = self._build_prompt(topic)
        try:
            if self._is_tiered:
                result = self._client.generate_grounded(prompt, allow_paid=allow_paid)
            else:
                result = self._client.generate_grounded(prompt)
        except GeminiError as e:
            _log.error("Seed discovery failed: %s", e)
            return []

        excluded = exclude_urls or set()
        seen: set[str] = set()
        seeds: list[DiscoveredSeed] = []
        for src in result.sources:
            url = src.get("uri", "")
            if not url or url in excluded or url in seen:
                continue
            # Skip search-result wrapper URLs / non-http schemes.
            if not url.startswith("http"):
                continue
            seen.add(url)
            seeds.append(DiscoveredSeed(
                url=url,
                title=src.get("title", ""),
                domain=get_domain(url),
                via_query=topic,
            ))

        _log.info("Discovered %d seed URLs via Gemini grounding", len(seeds))
        return seeds

    @staticmethod
    def _build_prompt(topic: str) -> str:
        return (
            f"Find authoritative and primary web sources about: {topic}\n\n"
            "Prioritize first-person memoirs, journalistic profiles, "
            "Wikipedia, documentary sites, and archival clippings. Return "
            "a brief summary with citations."
        )
