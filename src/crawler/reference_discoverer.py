"""
Reference discoverer: iterates over the graph's existing source_urls and
SourceRecord URLs, fetches each page, extracts outbound links, and records
newly discovered URLs as SourceRecords + Work nodes in the graph.

Unlike the BFS WebCrawler (which crawls from seed URLs within allowed
domains), this module is **graph-driven**: it uses the URLs already stored
on graph nodes and source records as its crawl frontier. This makes it
useful for finding new references in sources that were ingested manually
(e.g. via scripts/11_ingest_cdnc.py, scripts/13_ingest_yoga_abuse_sheet.py,
scripts/14_ingest_deslippe_paper.py) rather than via the crawl pipeline.

Design:
- Collects all unique http(s) URLs from node.source_urls and SourceRecord.url
- Skips URLs already visited (tracked in a persistent table: ref_discovery)
- Fetches each unvisited URL with a polite delay
- Extracts outbound links from the page HTML
- For each discovered link not already in the graph:
  - Creates a SourceRecord (so it shows up in the sources export)
  - Creates a Work node
  - Creates a MENTIONS edge from the source page's Work node to the
    discovered URL's Work node
- Idempotent: re-running skips already-visited URLs and already-stored
  discovered URLs

The ref_discovery table tracks:
  - url: the URL that was fetched
  - visited_at: ISO timestamp
  - status: 'ok' | 'error' | 'skipped'
  - error: error message if status='error'
  - links_found: number of outbound links extracted
  - links_new: number of links not already in the graph
"""

from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

from src.extractor.alias_resolver import work_id
from src.storage.graph_db import GraphDB
from src.storage.models import (
    BiasHint,
    GraphEdge,
    GraphNode,
    NodeType,
    RelationType,
    SourceClass,
    SourceRecord,
)
from src.utils.text_utils import get_domain, hash_url, resolve_url

_log = logging.getLogger(__name__)

# URL schemes to skip (non-fetchable)
_SKIP_SCHEMES = {"kkron", "reddit", "mailto", "javascript", "data", "ftp"}

# File extensions to skip (binary/non-HTML — we don't parse them for links)
_SKIP_EXTENSIONS = {
    ".pdf", ".jpg", ".jpeg", ".png", ".gif", ".svg", ".ico",
    ".mp3", ".mp4", ".wav", ".avi", ".mov",
    ".zip", ".tar", ".gz", ".rar",
    ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
}

# Domains to skip (social media platforms that block scraping or have
# their own dedicated collectors)
_SKIP_DOMAINS = {
    "facebook.com", "instagram.com", "twitter.com", "x.com",
    "tiktok.com", "youtube.com", "youtu.be",
}

# Default settings
DEFAULT_DELAY = 3.0  # seconds between fetches
DEFAULT_TIMEOUT = 20  # seconds per request
DEFAULT_USER_AGENT = "story-graph-bot/0.1 (+research)"


@dataclass
class DiscoveryResult:
    """Result of discovering references from a single source URL."""

    source_url: str
    status: str = "ok"  # 'ok' | 'error' | 'skipped'
    error: str = ""
    title: str = ""
    links_found: int = 0
    links_new: int = 0
    new_urls: list[str] = field(default_factory=list)


@dataclass
class DiscoveryStats:
    """Aggregate stats for a discovery run."""

    total_source_urls: int = 0
    visited: int = 0
    skipped: int = 0
    errors: int = 0
    total_links_found: int = 0
    total_new_references: int = 0
    new_source_records: int = 0
    new_work_nodes: int = 0
    new_edges: int = 0


def _is_fetchable_url(url: str) -> bool:
    """Check if a URL is worth fetching (http/https, not a binary file)."""
    if not url:
        return False
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        return False
    # Check for skipped extensions
    path = parsed.path.lower().split("?")[0]
    for ext in _SKIP_EXTENSIONS:
        if path.endswith(ext):
            return False
    # Check for skipped domains
    domain = get_domain(url)
    if domain in _SKIP_DOMAINS:
        return False
    return True


def _should_skip_url(url: str) -> bool:
    """Check if a URL should be skipped entirely (non-http schemes)."""
    if not url:
        return True
    parsed = urlparse(url)
    if parsed.scheme in _SKIP_SCHEMES:
        return True
    return False


class ReferenceDiscoverer:
    """Discovers new reference URLs by fetching pages from the graph's
    existing source_urls and extracting their outbound links.

    Usage:
        db = GraphDB("data/graph.db")
        discoverer = ReferenceDiscoverer(db)
        stats = discoverer.discover(dry_run=False)
        db.close()
    """

    def __init__(
        self,
        db: GraphDB,
        delay_seconds: float = DEFAULT_DELAY,
        timeout: int = DEFAULT_TIMEOUT,
        user_agent: str = DEFAULT_USER_AGENT,
        max_source_urls: int | None = None,
    ):
        self.db = db
        self.delay_seconds = delay_seconds
        self.timeout = timeout
        self.user_agent = user_agent
        self.max_source_urls = max_source_urls
        self._init_table()

    def _init_table(self) -> None:
        """Create the ref_discovery tracking table if it doesn't exist."""
        self.db._get_conn().execute(
            """
            CREATE TABLE IF NOT EXISTS ref_discovery (
                url TEXT PRIMARY KEY,
                visited_at TEXT NOT NULL,
                status TEXT NOT NULL,
                error TEXT,
                links_found INTEGER DEFAULT 0,
                links_new INTEGER DEFAULT 0
            )
            """
        )
        self.db._get_conn().commit()

    def _is_visited(self, url: str) -> bool:
        """Check if a URL has already been visited."""
        row = self.db._get_conn().execute(
            "SELECT 1 FROM ref_discovery WHERE url = ?", (url,)
        ).fetchone()
        return row is not None

    def _record_visit(self, result: DiscoveryResult) -> None:
        """Record a visit in the ref_discovery table."""
        now = datetime.now(timezone.utc).isoformat()
        self.db._get_conn().execute(
            """
            INSERT INTO ref_discovery (url, visited_at, status, error, links_found, links_new)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(url) DO UPDATE SET
                visited_at = excluded.visited_at,
                status = excluded.status,
                error = excluded.error,
                links_found = excluded.links_found,
                links_new = excluded.links_new
            """,
            (
                result.source_url,
                now,
                result.status,
                result.error or None,
                result.links_found,
                result.links_new,
            ),
        )
        self.db._get_conn().commit()

    def _collect_source_urls(self) -> list[str]:
        """Collect all unique http(s) URLs from the graph.

        Sources:
        1. All node.source_urls fields
        2. All SourceRecord.url fields

        Returns URLs sorted for deterministic ordering.
        """
        urls: set[str] = set()

        # From nodes
        for node in self.db.get_all_nodes():
            for url in node.source_urls:
                if not _should_skip_url(url):
                    urls.add(url)

        # From source records
        for source in self.db.get_all_sources():
            if source.url and not _should_skip_url(source.url):
                urls.add(source.url)

        # Filter to fetchable URLs and sort for determinism
        fetchable = sorted(u for u in urls if _is_fetchable_url(u))
        return fetchable

    def _get_known_urls(self) -> set[str]:
        """Get the set of all URLs already known to the graph
        (in source_urls or SourceRecord.url fields)."""
        known: set[str] = set()
        for node in self.db.get_all_nodes():
            known.update(node.source_urls)
        for source in self.db.get_all_sources():
            if source.url:
                known.add(source.url)
        return known

    def _fetch_page(self, url: str) -> tuple[str, str, int]:
        """Fetch a URL and return (html, error, status_code).

        Returns (html, "", 200) on success, ("", error_msg, status_code) on failure.
        """
        headers = {
            "User-Agent": self.user_agent,
            "Accept": "text/html,application/xhtml+xml,text/plain,*/*",
        }
        try:
            resp = requests.get(url, headers=headers, timeout=self.timeout, allow_redirects=True)
            if resp.status_code != 200:
                return "", f"HTTP {resp.status_code}", resp.status_code
            # Check content type
            content_type = resp.headers.get("Content-Type", "")
            if "text" not in content_type and "html" not in content_type and "xml" not in content_type:
                return "", f"non-text content-type: {content_type}", resp.status_code
            return resp.text, "", resp.status_code
        except requests.Timeout:
            return "", "timeout", 0
        except requests.RequestException as e:
            return "", str(e), 0

    def _extract_links(self, url: str, html: str) -> tuple[list[str], str]:
        """Extract outbound links from a page.

        Returns (links, title). Links are resolved absolute URLs,
        de-duplicated, and filtered to http(s) only.
        """
        soup = BeautifulSoup(html, "lxml")

        # Title
        title = ""
        if soup.title:
            title = soup.title.string or ""
        title = title.strip()

        # Extract links from content area (prefer article/main, fallback to body)
        content_area = soup.find("article") or soup.find("main") or soup.find("body") or soup
        links: list[str] = []
        seen: set[str] = set()

        for a_tag in content_area.find_all("a", href=True):
            href = a_tag["href"]
            resolved = resolve_url(url, href)
            # Skip non-http links
            parsed = urlparse(resolved)
            if parsed.scheme not in ("http", "https"):
                continue
            # Skip anchors on the same page
            if parsed.fragment and not parsed.path:
                continue
            # Strip fragment
            clean_url = resolved.split("#")[0]
            if clean_url in seen:
                continue
            seen.add(clean_url)
            links.append(clean_url)

        return links, title

    def _store_discovered_url(
        self,
        discovered_url: str,
        source_url: str,
        source_work_id: str,
    ) -> bool:
        """Store a discovered URL as a new SourceRecord + Work node + edge.

        Returns True if a new record was created, False if it already existed.
        """
        # Check if this URL is already a source record
        existing = self.db.get_source_by_url(discovered_url)
        if existing:
            return False

        # Create Work node for the discovered URL
        disc_work_id = work_id(discovered_url)
        existing_work = self.db.get_node(disc_work_id)
        if existing_work:
            return False  # already exists

        domain = get_domain(discovered_url)

        # Create Work node
        self.db.add_node(GraphNode(
            id=disc_work_id,
            type=NodeType.WORK,
            label=discovered_url,
            canonical_name=None,
            metadata={
                "url": discovered_url,
                "platform": domain,
                "work_type": "discovered_reference",
                "discovered_from": source_url,
                "discovered_at": datetime.now(timezone.utc).isoformat(),
            },
            source_urls=[discovered_url],
        ))

        # Create SourceRecord
        self.db.add_source(SourceRecord(
            id=disc_work_id,
            url=discovered_url,
            title=None,
            author=None,
            platform=domain,
            source_class=SourceClass.JOURNALISTIC,
            bias_hint=BiasHint.NEUTRAL_ISH,
        ))

        # Create MENTIONS edge: source page mentions discovered URL
        self.db.add_edge(GraphEdge(
            src_id=source_work_id,
            rel_type=RelationType.MENTIONS,
            dst_id=disc_work_id,
            metadata={
                "evidence": f"Link found on {source_url}",
                "discovery_method": "reference_discoverer",
            },
        ))

        return True

    def discover(self, dry_run: bool = False) -> tuple[DiscoveryStats, list[DiscoveryResult]]:
        """Run the reference discovery process.

        Args:
            dry_run: If True, don't fetch pages or write to the DB — just
                report what would be done.

        Returns:
            (stats, results) — aggregate stats and per-URL results.
        """
        stats = DiscoveryStats()
        results: list[DiscoveryResult] = []

        # 1. Collect source URLs from the graph
        source_urls = self._collect_source_urls()
        stats.total_source_urls = len(source_urls)

        if self.max_source_urls:
            source_urls = source_urls[: self.max_source_urls]

        _log.info(f"Collected {len(source_urls)} fetchable source URLs from graph")

        # 2. Get known URLs (for filtering discovered links)
        known_urls = self._get_known_urls()

        # 3. Fetch each URL and extract links
        for i, url in enumerate(source_urls):
            # Skip already-visited URLs (idempotent)
            if self._is_visited(url):
                stats.skipped += 1
                results.append(DiscoveryResult(
                    source_url=url, status="skipped",
                    error="already visited",
                ))
                _log.info(f"[{i+1}/{len(source_urls)}] SKIP (visited): {url}")
                continue

            if dry_run:
                _log.info(f"[{i+1}/{len(source_urls)}] DRY-RUN: {url}")
                stats.visited += 1
                results.append(DiscoveryResult(source_url=url, status="skipped"))
                continue

            _log.info(f"[{i+1}/{len(source_urls)}] Fetching: {url}")

            result = DiscoveryResult(source_url=url)
            html, error, status_code = self._fetch_page(url)

            if error:
                result.status = "error"
                result.error = error
                stats.errors += 1
                _log.warning(f"  -> ERROR: {error}")
            else:
                links, title = self._extract_links(url, html)
                result.title = title
                result.links_found = len(links)
                stats.total_links_found += len(links)

                # Filter to links not already known to the graph
                new_links = [l for l in links if l not in known_urls]
                result.links_new = len(new_links)
                result.new_urls = new_links
                stats.total_new_references += len(new_links)

                # Store discovered URLs
                source_work_id = work_id(url)
                # Ensure the source URL has a Work node
                source_work = self.db.get_node(source_work_id)
                if not source_work:
                    domain = get_domain(url)
                    self.db.add_node(GraphNode(
                        id=source_work_id,
                        type=NodeType.WORK,
                        label=title or url,
                        canonical_name=title or None,
                        metadata={
                            "url": url,
                            "platform": domain,
                            "work_type": "web_page",
                        },
                        source_urls=[url],
                    ))
                    stats.new_work_nodes += 1

                for disc_url in new_links:
                    created = self._store_discovered_url(
                        disc_url, url, source_work_id,
                    )
                    if created:
                        stats.new_source_records += 1
                        stats.new_work_nodes += 1
                        stats.new_edges += 1
                        # Add to known set so we don't double-create
                        known_urls.add(disc_url)

                _log.info(
                    f"  -> title='{title[:60]}', "
                    f"links={len(links)}, new={len(new_links)}"
                )

            # Record the visit
            self._record_visit(result)
            stats.visited += 1

            # Polite delay
            if i < len(source_urls) - 1:
                time.sleep(self.delay_seconds)

        return stats, results
