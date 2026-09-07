"""DuckDuckGo HTML search fallback (no API key required).

Scrapes DuckDuckGo's HTML endpoint for search results when Brave and
Gemini are unavailable. Results are normalized to the same SearchResult
format as BraveSearchClient.

This is a fallback for relationship discovery when paid API quotas are
exhausted. It is slower and less structured than the Brave API but
requires no credentials.
"""

from __future__ import annotations

import logging
import re
import time
import urllib.parse
import urllib.request
from html import unescape

from src.search.brave_search_client import SearchResult

_log = logging.getLogger(__name__)

_DDGO_ENDPOINT = "https://html.duckduckgo.com/html/"
_USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64; rv:128.0) Gecko/20100101 Firefox/128.0"
)


class DuckDuckGoSearchClient:
    """DuckDuckGo HTML search fallback with caching and quota tracking."""

    def __init__(
        self,
        cache=None,
        quota_tracker=None,
        delay_seconds: float = 3.0,
    ):
        self.cache = cache
        self.quota = quota_tracker
        self.delay = delay_seconds

    def is_available(self) -> bool:
        return True  # No API key needed

    def search(
        self,
        query: str,
        count: int = 10,
        country: str = "US",
        search_lang: str = "en",
        safesearch: str = "moderate",
    ) -> list[SearchResult]:
        """Execute a web search via DuckDuckGo HTML endpoint."""
        params = {"count": count, "country": country, "search_lang": search_lang}

        # Check cache
        if self.cache:
            cached = self.cache.get(query, "duckduckgo", params)
            if cached is not None:
                _log.debug("Cache hit for query: %s", query[:60])
                if self.quota:
                    self.quota.record_call("duckduckgo", query, result_count=len(cached), cached=True)
                return [SearchResult(**r) for r in cached]

        # Check quota
        if self.quota:
            self.quota.check_budget("duckduckgo")

        # Make the request
        results = self._fetch_html(query, count)

        # Cache results
        if self.cache and results:
            self.cache.put(query, "duckduckgo", [r.__dict__ for r in results], params)

        # Record usage
        if self.quota:
            self.quota.record_call("duckduckgo", query, result_count=len(results))

        # Rate limit
        if self.delay > 0:
            time.sleep(self.delay)

        return results

    def _fetch_html(self, query: str, count: int) -> list[SearchResult]:
        """Fetch and parse DuckDuckGo HTML results."""
        data = urllib.parse.urlencode({
            "q": query,
            "s": "0",  # start offset
            "kl": "us-en",  # region-language
        }).encode()

        req = urllib.request.Request(
            _DDGO_ENDPOINT,
            data=data,
            headers={
                "User-Agent": _USER_AGENT,
                "Accept": "text/html,application/xhtml+xml",
                "Accept-Language": "en-US,en;q=0.9",
                "Content-Type": "application/x-www-form-urlencoded",
            },
        )

        try:
            with urllib.request.urlopen(req, timeout=20) as resp:
                html = resp.read().decode("utf-8", errors="replace")
        except Exception as e:
            _log.error("DuckDuckGo search failed: %s", e)
            return []

        return self._parse_html(html, query, count)

    def _parse_html(self, html: str, query: str, count: int = 10) -> list[SearchResult]:
        """Parse DuckDuckGo HTML results into SearchResult objects."""
        results: list[SearchResult] = []

        # DuckDuckGo HTML results have result links in <a class="result__a" href="...">
        # and snippets in <a class="result__snippet" ...>
        # The href is a redirect URL like //duckduckgo.com/l/?uddg=<encoded_url>

        # Find all result blocks
        result_blocks = re.findall(
            r'<a[^>]*class="[^"]*result__a[^"]*"[^>]*href="([^"]*)"[^>]*>(.*?)</a>',
            html,
            re.DOTALL,
        )

        snippets = re.findall(
            r'<a[^>]*class="[^"]*result__snippet[^"]*"[^>]*>(.*?)</a>',
            html,
            re.DOTALL,
        )

        for i, (raw_url, title_html) in enumerate(result_blocks[:count]):
            # Decode the redirect URL
            url = self._decode_ddgo_url(raw_url)
            if not url:
                continue

            title = unescape(re.sub(r"<[^>]+>", "", title_html)).strip()
            snippet = ""
            if i < len(snippets):
                snippet = unescape(re.sub(r"<[^>]+>", "", snippets[i])).strip()

            domain = ""
            try:
                domain = urllib.parse.urlparse(url).netloc
            except Exception:
                pass

            results.append(SearchResult(
                url=url,
                title=title,
                snippet=snippet,
                provider="duckduckgo",
                query=query,
                domain=domain,
            ))

        _log.info("DuckDuckGo search '%s' → %d results", query[:60], len(results))
        return results

    @staticmethod
    def _decode_ddgo_url(raw_url: str) -> str:
        """Decode a DuckDuckGo redirect URL to get the actual target URL."""
        # URLs look like: //duckduckgo.com/l/?uddg=<encoded_url>&rut=...
        if "uddg=" in raw_url:
            parsed = urllib.parse.urlparse(raw_url)
            params = urllib.parse.parse_qs(parsed.query)
            if "uddg" in params:
                return urllib.parse.unquote(params["uddg"][0])
        # Sometimes it's a direct URL
        if raw_url.startswith("http"):
            return raw_url
        if raw_url.startswith("//"):
            return "https:" + raw_url
        return ""
