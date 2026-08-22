"""Seed URL discovery via Gemini + Google Search grounding.

Asks Gemini to find web pages about The Source Family / Father Yod and
returns the grounded source URLs. These can be merged into
``settings.seed_urls`` (or used as one-off crawl seeds) to broaden the
corpus beyond the hand-curated seeds.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from src.llm.gemini_client import GeminiClient, GeminiError
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

    def __init__(self, client: GeminiClient | None = None):
        self._client = client or GeminiClient()

    def discover(
        self,
        query: str | None = None,
        *,
        exclude_urls: set[str] | None = None,
    ) -> list[DiscoveredSeed]:
        """Run a grounded search and return discovered seed URLs.

        Args:
            query: Optional natural-language query. Defaults to the
                Source Family topic.
            exclude_urls: URLs to filter out (e.g. existing seeds).
        """
        if not self._client.is_available():
            _log.warning("Gemini unavailable; seed discovery skipped.")
            return []

        topic = query or DEFAULT_TOPIC
        prompt = self._build_prompt(topic)
        try:
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
