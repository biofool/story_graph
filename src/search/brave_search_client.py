"""Brave Search API client for relationship discovery.

Wraps the Brave Web Search API (https://api.search.brave.com/res/v1/web/search)
to find web pages documenting relationships between entities. Results are
cached in SearchCache and tracked by QuotaTracker.

Authentication: X-Subscription-Token header with BRAVE_SEARCH_API_KEY.
Free tier: 2,000 queries/month.
"""

from __future__ import annotations

import json
import logging
import os
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any

_log = logging.getLogger(__name__)

_BRAVE_ENDPOINT = "https://api.search.brave.com/res/v1/web/search"


@dataclass
class SearchResult:
    """Normalized search result from any provider."""

    url: str
    title: str
    snippet: str
    provider: str
    query: str
    domain: str = ""
    age: str = ""
    extra: dict[str, Any] | None = None


class BraveSearchClient:
    """Brave Web Search API wrapper with caching and quota tracking."""

    def __init__(
        self,
        api_key: str | None = None,
        cache=None,
        quota_tracker=None,
        delay_seconds: float = 2.0,
    ):
        self.api_key = api_key or os.environ.get("BRAVE_SEARCH_API_KEY", "")
        if not self.api_key:
            _log.warning("BRAVE_SEARCH_API_KEY not set; Brave search disabled")
        self.cache = cache
        self.quota = quota_tracker
        self.delay = delay_seconds

    def is_available(self) -> bool:
        return bool(self.api_key)

    def health_check(self) -> bool:
        """Verify the API key works and the endpoint is reachable.

        Makes a single test query and checks that the response contains
        web search results (not just an empty Answers-plan response).
        Caches the result so repeated health checks don't waste quota.
        """
        if not self.api_key:
            return False
        if hasattr(self, "_health_checked"):
            return self._health_checked
        try:
            results = self._call_api("test", count=1, country="US",
                                     search_lang="en", safesearch="moderate")
            # A working Search-plan key returns results for "test".
            # An Answers-plan key returns 0 results with no error.
            self._health_checked = len(results) > 0
        except Exception:
            self._health_checked = False
        return self._health_checked

    def search(
        self,
        query: str,
        count: int = 10,
        country: str = "US",
        search_lang: str = "en",
        safesearch: str = "moderate",
    ) -> list[SearchResult]:
        """Execute a web search and return normalized results.

        Checks cache first, then quota, then makes the API call.
        """
        if not self.is_available():
            _log.warning("Brave search unavailable (no API key)")
            return []

        params = {"count": count, "country": country, "search_lang": search_lang, "safesearch": safesearch}

        # Check cache
        if self.cache:
            cached = self.cache.get(query, "brave", params)
            if cached is not None:
                _log.debug("Cache hit for query: %s", query[:60])
                if self.quota:
                    self.quota.record_call("brave", query, result_count=len(cached), cached=True)
                return [SearchResult(**r) for r in cached]

        # Check quota
        if self.quota:
            self.quota.check_budget("brave")

        # Make the API call
        results = self._call_api(query, count, country, search_lang, safesearch)

        # Cache results
        if self.cache and results:
            self.cache.put(query, "brave", [r.__dict__ for r in results], params)

        # Record usage
        if self.quota:
            self.quota.record_call("brave", query, result_count=len(results))

        # Rate limit
        if self.delay > 0:
            time.sleep(self.delay)

        return results

    def _call_api(
        self,
        query: str,
        count: int,
        country: str,
        search_lang: str,
        safesearch: str,
    ) -> list[SearchResult]:
        """Make the actual HTTP call to Brave Search API."""
        url = _BRAVE_ENDPOINT + "?" + urllib.parse.urlencode({
            "q": query,
            "count": str(count),
            "country": country,
            "search_lang": search_lang,
            "safesearch": safesearch,
        })

        req = urllib.request.Request(
            url,
            headers={
                "Accept": "application/json",
                "X-Subscription-Token": self.api_key,
            },
        )

        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode())
        except urllib.error.HTTPError as e:
            body = e.read().decode(errors="replace")[:200]
            _log.error("Brave search HTTP %d: %s", e.code, body)
            return []
        except Exception as e:
            _log.error("Brave search failed: %s", e)
            return []

        results: list[SearchResult] = []
        web_results = data.get("web", {}).get("results", [])
        for item in web_results:
            url = item.get("url", "")
            if not url:
                continue
            domain = ""
            try:
                domain = urllib.parse.urlparse(url).netloc
            except Exception:
                pass

            results.append(SearchResult(
                url=url,
                title=item.get("title", ""),
                snippet=item.get("description", ""),
                provider="brave",
                query=query,
                domain=domain,
                age=item.get("age", ""),
                extra={
                    "extra_snippets": item.get("extra_snippets", []),
                    "is_first": item.get("is_first", False),
                },
            ))

        _log.info("Brave search '%s' → %d results", query[:60], len(results))
        return results
