"""Bing HTML search client (no API key required).

Scrapes Bing's HTML search results as a fallback when Brave and Gemini
are unavailable. Bing tends to be more lenient with automated requests
than Google or DuckDuckGo.

Result URLs are base64-encoded in Bing's redirect links
(https://www.bing.com/ck/a?...&u=a1<base64_url>&...) and must be decoded.
"""

from __future__ import annotations

import base64
import logging
import re
import time
import urllib.parse
import urllib.request
from html import unescape

from src.search.brave_search_client import SearchResult

_log = logging.getLogger(__name__)

_BING_ENDPOINT = "https://www.bing.com/search"
_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)


class BingSearchClient:
    """Bing HTML search fallback with caching and quota tracking."""

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

    def health_check(self) -> bool:
        """Verify Bing HTML scraping is working.

        Makes a single test query and checks that results are returned.
        Caches the result so repeated health checks don't waste requests.
        """
        if hasattr(self, "_health_checked"):
            return self._health_checked
        try:
            results = self._fetch_html("test", 1)
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
        """Execute a web search via Bing HTML and return normalized results."""
        params = {"count": count, "country": country, "search_lang": search_lang}

        # Check cache
        if self.cache:
            cached = self.cache.get(query, "bing", params)
            if cached is not None:
                _log.debug("Cache hit for query: %s", query[:60])
                if self.quota:
                    self.quota.record_call("bing", query, result_count=len(cached), cached=True)
                return [SearchResult(**r) for r in cached]

        # Check quota
        if self.quota:
            self.quota.check_budget("bing")

        # Make the request
        results = self._fetch_html(query, count)

        # Cache results
        if self.cache and results:
            self.cache.put(query, "bing", [r.__dict__ for r in results], params)

        # Record usage
        if self.quota:
            self.quota.record_call("bing", query, result_count=len(results))

        # Rate limit
        if self.delay > 0:
            time.sleep(self.delay)

        return results

    def _fetch_html(self, query: str, count: int) -> list[SearchResult]:
        """Fetch and parse Bing HTML results."""
        url = _BING_ENDPOINT + "?" + urllib.parse.urlencode({
            "q": query,
            "setlang": "en-US",
            "cc": "US",
            "count": str(count),
        })

        req = urllib.request.Request(url, headers={
            "User-Agent": _USER_AGENT,
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Language": "en-US,en;q=0.9",
            "Accept-Encoding": "identity",  # Avoid compression for simpler parsing
        })

        try:
            with urllib.request.urlopen(req, timeout=20) as resp:
                html = resp.read().decode("utf-8", errors="replace")
        except Exception as e:
            _log.error("Bing search failed: %s", e)
            return []

        return self._parse_html(html, query, count)

    def _parse_html(self, html: str, query: str, count: int = 10) -> list[SearchResult]:
        """Parse Bing HTML results into SearchResult objects."""
        results: list[SearchResult] = []

        # Find all b_algo sections
        algo_sections = re.findall(
            r'class="b_algo"[^>]*>(.*?)</li>', html, re.DOTALL
        )

        for section in algo_sections[:count]:
            # Find the redirect URL in the h2 > a tag
            link_match = re.search(
                r'<h2[^>]*><a[^>]*href="([^"]+)"[^>]*>(.*?)</a>',
                section,
                re.DOTALL,
            )
            if not link_match:
                continue

            raw_url = link_match.group(1)
            title_html = link_match.group(2)
            url = self._decode_bing_url(raw_url)
            if not url:
                continue

            title = unescape(re.sub(r"<[^>]+>", "", title_html)).strip()

            # Extract snippet from <p> tag or b_caption
            snippet = ""
            snippet_match = re.search(
                r'<div class="b_caption"[^>]*>.*?<p[^>]*>(.*?)</p>',
                section,
                re.DOTALL,
            )
            if snippet_match:
                snippet = unescape(re.sub(r"<[^>]+>", "", snippet_match.group(1))).strip()
            else:
                # Try any <p> in the section
                p_match = re.search(r'<p[^>]*>(.*?)</p>', section, re.DOTALL)
                if p_match:
                    snippet = unescape(re.sub(r"<[^>]+>", "", p_match.group(1))).strip()

            domain = ""
            try:
                domain = urllib.parse.urlparse(url).netloc
            except Exception:
                pass

            results.append(SearchResult(
                url=url,
                title=title,
                snippet=snippet,
                provider="bing",
                query=query,
                domain=domain,
            ))

        _log.info("Bing search '%s' → %d results", query[:60], len(results))
        return results

    @staticmethod
    def _decode_bing_url(raw_url: str) -> str:
        """Decode a Bing redirect URL to get the actual target URL.

        Bing wraps URLs in: https://www.bing.com/ck/a?...&u=a1<base64>&...
        The 'a1' prefix is stripped before base64 decoding.
        """
        if "bing.com/ck/a" not in raw_url:
            # Direct URL
            if raw_url.startswith("http"):
                return unescape(raw_url)
            return ""

        # Extract the 'u' parameter
        parsed = urllib.parse.urlparse(raw_url)
        # The URL might be HTML-encoded
        raw_url = unescape(raw_url)
        params = urllib.parse.parse_qs(parsed.query)

        # The 'u' parameter might be in the fragment or query
        u_param = params.get("u", [None])[0]
        if not u_param:
            # Try finding it with regex
            u_match = re.search(r'[&?]u=a1([A-Za-z0-9+/=]+)', raw_url)
            if u_match:
                u_param = "a1" + u_match.group(1)

        if not u_param:
            return ""

        # Strip the 'a1' prefix and base64-decode
        if u_param.startswith("a1"):
            u_param = u_param[2:]

        try:
            # Add padding if needed
            padding = 4 - len(u_param) % 4
            if padding != 4:
                u_param += "=" * padding
            decoded = base64.b64decode(u_param).decode("utf-8")
            return decoded
        except Exception as e:
            _log.debug("Failed to decode Bing URL: %s", e)
            return ""
