"""
Domain-filtered BFS web crawler.
Fetches pages, extracts text + outbound links, and respects allowed domains + depth cap.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Optional
from collections import deque

import requests
from bs4 import BeautifulSoup
from tenacity import retry, stop_after_attempt, wait_exponential

from src.utils.text_utils import (
    get_domain,
    is_allowed_domain,
    resolve_url,
    clean_text,
    hash_url,
)

_log = logging.getLogger(__name__)


@dataclass
class CrawledPage:
    """Result of crawling a single page."""
    url: str
    title: str = ""
    text: str = ""
    links: list[str] = field(default_factory=list)
    author: Optional[str] = None
    publish_date: Optional[str] = None
    status_code: int = 0
    error: Optional[str] = None


class WebCrawler:
    """BFS crawler with domain filtering and depth cap."""

    def __init__(
        self,
        seed_urls: list[str],
        allowed_domains: set[str],
        max_depth: int = 2,
        max_pages: int = 200,
        delay_seconds: float = 3.0,
        user_agent: str = "story-graph-bot/0.1 (+research)",
        timeout: int = 30,
    ):
        self.seed_urls = seed_urls
        self.allowed_domains = allowed_domains
        self.max_depth = max_depth
        self.max_pages = max_pages
        self.delay_seconds = delay_seconds
        self.user_agent = user_agent
        self.timeout = timeout
        self.visited: set[str] = set()
        self.pages: list[CrawledPage] = []

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
    def _fetch(self, url: str) -> requests.Response:
        headers = {"User-Agent": self.user_agent}
        return requests.get(url, headers=headers, timeout=self.timeout)

    def _parse_page(self, url: str, html: str) -> CrawledPage:
        soup = BeautifulSoup(html, "lxml")

        # Title
        title_tag = soup.find("title")
        title = title_tag.get_text(strip=True) if title_tag else ""

        # Author (common meta tags)
        author = None
        for selector in [
            ("meta", {"name": "author"}),
            ("meta", {"property": "article:author"}),
            ("meta", {"name": "twitter:creator"}),
        ]:
            tag = soup.find(*selector)
            if tag and tag.get("content"):
                author = tag["content"]
                break

        # Publish date
        publish_date = None
        for selector in [
            ("meta", {"property": "article:published_time"}),
            ("meta", {"name": "date"}),
            ("meta", {"name": "DC.date"}),
            ("time", {}),
        ]:
            tag = soup.find(*selector)
            if tag:
                val = tag.get("content") or tag.get("datetime") or ""
                if val:
                    publish_date = val
                    break

        # Extract text — prefer article/main, fallback to body
        content_area = soup.find("article") or soup.find("main") or soup.find("body") or soup
        text = clean_text(str(content_area))

        # Extract outbound links, filtered by allowed domains
        links = []
        for a_tag in content_area.find_all("a", href=True):
            href = a_tag["href"]
            resolved = resolve_url(url, href)
            # Skip anchors, javascript, mailto
            if resolved.startswith(("javascript:", "mailto:", "#")):
                continue
            if is_allowed_domain(resolved, self.allowed_domains):
                links.append(resolved)

        # Deduplicate links
        links = list(dict.fromkeys(links))

        return CrawledPage(
            url=url,
            title=title,
            text=text,
            links=links,
            author=author,
            publish_date=publish_date,
            status_code=200,
        )

    def crawl(self) -> list[CrawledPage]:
        """Run the BFS crawl from seed URLs up to max_depth."""
        queue: deque[tuple[str, int]] = deque(
            (url, 0) for url in self.seed_urls
        )
        pages_crawled = 0

        while queue and pages_crawled < self.max_pages:
            url, depth = queue.popleft()

            # Normalize URL (strip fragment)
            url = url.split("#")[0]

            if url in self.visited:
                continue
            self.visited.add(url)

            _log.info(f"[depth={depth}] Crawling: {url}")

            try:
                response = self._fetch(url)
            except Exception as e:
                _log.warning(f"Failed to fetch {url}: {e}")
                self.pages.append(CrawledPage(url=url, error=str(e)))
                continue

            if response.status_code != 200:
                _log.warning(f"HTTP {response.status_code} for {url}")
                self.pages.append(
                    CrawledPage(url=url, status_code=response.status_code, error=f"HTTP {response.status_code}")
                )
                continue

            page = self._parse_page(url, response.text)
            self.pages.append(page)
            pages_crawled += 1

            _log.info(
                f"  -> title='{page.title[:60]}', "
                f"links={len(page.links)}, "
                f"text_len={len(page.text)}"
            )

            # Enqueue child links if within depth
            if depth < self.max_depth:
                for link in page.links:
                    if link not in self.visited:
                        queue.append((link, depth + 1))

            # Rate limit
            time.sleep(self.delay_seconds)

        _log.info(
            f"Crawl complete: {pages_crawled} pages fetched, "
            f"{len(self.visited)} URLs visited"
        )
        return self.pages
