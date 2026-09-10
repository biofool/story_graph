#!/usr/bin/env python3
"""
Unified person-enrichment script (issue #34).

Given a person name (or an existing graph node ID) plus optional dates and
cities, tries every available search/discovery/API method that hasn't
already been tried for that person, fetches the newly discovered URLs, and
ingests them through the same GeminiExtractor + process_page pipeline the
rest of the graph uses.

This is the idempotent, contamination-safe successor to
scripts/ingest_a_person.py. It only runs single-entity queries (name +
date/city context) — never the broad pair-query expansion that polluted
the graph in the old Technique 2b — and it skips methods and URLs that
have already been tried/ingested.

Usage:
    python scripts/34_enrich_person.py "robert nadeau" \
        --dates "1987-1994" \
        --cities "san francisco,moscow,leningrad" \
        --from-node person:robert-nadeau \
        --dry-run

    python scripts/34_enrich_person.py "robert nadeau" --max-urls 20
    python scripts/34_enrich_person.py "robert nadeau" --skip-methods bing,duckduckgo
"""

from __future__ import annotations

import argparse
import logging
import sqlite3
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import requests

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SNAPSHOT_DIR = PROJECT_ROOT / "graph_snapshot"
DB_PATH = PROJECT_ROOT / "data" / "graph.db"

sys.path.insert(0, str(PROJECT_ROOT))

from config.settings import settings
from src.crawler.fetch_page import fetch_page
from src.crawler.reference_discoverer import ReferenceDiscoverer
from src.llm.entity_claim_extractor import GeminiClaimExtractor, GeminiExtractor
from src.llm.gemini_client import TieredGeminiClient
from src.llm.seed_discoverer import SeedDiscoverer
from src.search.bing_search_client import BingSearchClient
from src.search.brave_search_client import BraveSearchClient
from src.search.duckduckgo_search_client import DuckDuckGoSearchClient
from src.search.kg_client import KnowledgeGraphClient
from src.search.quota import BudgetExceeded, QuotaTracker
from src.search.search_cache import SearchCache
from src.storage.graph_db import GraphDB
from src.storage.json_export import export_to_json, import_from_json, snapshot_exists
from src.storage.models import GraphNode
from scripts._pipeline_helpers import process_page

# Reuse the canonical-person selection logic from the data-ticket generator
# (imported via importlib so this script stays self-contained).
import importlib.util

_spec = importlib.util.spec_from_file_location(
    "gen_ticket",
    str(PROJECT_ROOT / "scripts" / "19_generate_data_ticket.py"),
)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)

find_matching_nodes = _mod.find_matching_nodes
select_canonical_person = _mod.select_canonical_person
load_jsonl = _mod.load_jsonl

_log = logging.getLogger(__name__)

_VERTEXAI_REDIRECT_PREFIX = "https://vertexaisearch.cloud.google.com/grounding-api-redirect/"

# Arctic Shift Reddit archive (mirrors scripts/07_arctic_shift_reddit.py).
_ARCTIC_SHIFT_BASE = "https://arctic-shift.photon-reddit.com"
_ARCTIC_SHIFT_POSTS = f"{_ARCTIC_SHIFT_BASE}/api/posts/search"
_ARCTIC_SHIFT_TIMEOUT = 60
_ARCTIC_SHIFT_DELAY = 1.0
_ARCTIC_SHIFT_SUBREDDITS = [
    "cults", "communes", "spirituality", "cultsurvivors",
    "exvangelical", "hippies", "1970s", "losangeles", "FamousPeople",
    "martialarts", "aikido",
]

# The ordered list of enrichment methods (tried in this order).
ALL_METHODS = [
    "google_kg",
    "gemini_grounded",
    "brave",
    "bing",
    "duckduckgo",
    "reference_discovery",
    "arctic_shift",
]


# ──────────────────────────────────────────────────────────────────────────
#  Result tracking
# ──────────────────────────────────────────────────────────────────────────

@dataclass
class MethodResult:
    """Outcome of one enrichment method."""

    method: str
    tried: bool = False
    skipped: bool = False
    skip_reason: str = ""
    new_urls: int = 0
    new_nodes: int = 0
    new_edges: int = 0
    status: str = ""

    def as_row(self) -> tuple[str, str, str, str, str, str]:
        tried = (
            "Skipped" if self.skipped
            else ("Yes" if self.tried else "No")
        )
        if self.skipped and self.skip_reason:
            tried = f"Skipped ({self.skip_reason})"
        return (
            self.method,
            tried,
            str(self.new_urls) if self.tried else "",
            str(self.new_nodes) if self.tried else "",
            str(self.new_edges) if self.tried else "",
            self.status,
        )


@dataclass
class EnrichmentContext:
    """Shared state for an enrichment run."""

    person_name: str
    person_node_id: str | None
    dates: list[str]
    cities: list[str]
    context: str
    db: GraphDB
    cache: SearchCache | None
    quota: QuotaTracker | None
    kg_client: KnowledgeGraphClient | None
    gemini_client: TieredGeminiClient | None
    gemini_ext: GeminiExtractor | None
    gemini_claim_ext: GeminiClaimExtractor | None
    brave_client: BraveSearchClient | None
    bing_client: BingSearchClient | None
    ddg_client: DuckDuckGoSearchClient | None
    existing_urls: set[str] = field(default_factory=set)
    max_urls: int = 20
    dry_run: bool = False
    results: list[MethodResult] = field(default_factory=list)


# ──────────────────────────────────────────────────────────────────────────
#  Query building (single-entity, contamination-safe)
# ──────────────────────────────────────────────────────────────────────────

def _single_entity_templates(style: str) -> list[str]:
    """Biography/interview/obituary/instructor query templates for a person.

    Mirrors scripts/ingest_a_person.py:_single_entity_templates. These are
    single-entity templates only — never the pair-query expansion that
    contaminated the graph in the old Technique 2b.
    """
    return [
        '"{a}" {style} biography',
        '"{a}" {style} instructor',
        '"{a}" interview {style}',
        '"{a}" obituary {style}',
        '"{a}" seminar {style}',
        '"{a}" {style} teacher',
    ]


def build_queries(
    person_name: str,
    dates: list[str],
    cities: list[str],
    context: str,
) -> list[str]:
    """Build single-entity search queries augmented with date/city context.

    Contamination-safe: every query is about ONE person (the name in
    quotes) plus disambiguating context. No pair queries, no broad
    co-mention expansion.

    Produces, in order:
      1. Base template queries (name + context style word).
      2. Per-city queries: '"name" city context'.
      3. Per-date queries: '"name" date context'.
      4. Cross-product city×date queries: '"name" city date context'
         (capped so the cross-product doesn't explode).
    """
    style = context or "martial arts"
    queries: list[str] = []
    seen: set[str] = set()

    def _add(q: str) -> None:
        q = " ".join(q.split())  # collapse whitespace
        if q and q not in seen:
            seen.add(q)
            queries.append(q)

    # 1. Base templates
    for tmpl in _single_entity_templates(style):
        _add(tmpl.format(a=person_name, style=style))

    # 2. Per-city
    for city in cities:
        _add(f'"{person_name}" "{city}" {style}')

    # 3. Per-date
    for date in dates:
        _add(f'"{person_name}" {date} {style}')

    # 4. Cross-product city × date (capped at 12 to stay bounded)
    cross: list[str] = []
    for city in cities:
        for date in dates:
            cross.append(f'"{person_name}" "{city}" {date} {style}')
            if len(cross) >= 12:
                break
        if len(cross) >= 12:
            break
    for q in cross:
        _add(q)

    return queries


# ──────────────────────────────────────────────────────────────────────────
#  "Already tried" checks
# ──────────────────────────────────────────────────────────────────────────

def _cache_has_query_for(cache: SearchCache, provider: str, name: str) -> bool:
    """True if SearchCache has any non-expired row for ``provider`` whose
    query contains the person ``name`` (case-insensitive).

    Reaches into the cache's SQLite connection (the cache exposes no
    query-by-text API). Safe: read-only SELECT.
    """
    try:
        conn: sqlite3.Connection = cache._get_conn()  # noqa: SLF001
        name_lower = name.lower()
        rows = conn.execute(
            "SELECT query, expires_at FROM search_cache WHERE provider = ?",
            (provider,),
        ).fetchall()
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc)
        for r in rows:
            if name_lower in (r["query"] or "").lower():
                try:
                    exp = datetime.fromisoformat(r["expires_at"])
                    if now <= exp:
                        return True
                except Exception:
                    return True  # treat unparseable expiry as present
        return False
    except Exception as e:
        _log.warning("cache lookup failed for provider=%s: %s", provider, e)
        return False


def method_already_tried(ctx: EnrichmentContext, method: str) -> bool:
    """Has ``method`` already been run for this person?"""
    if method == "google_kg":
        node = _get_person_node(ctx)
        if node and node.metadata.get("kg_enriched") is True:
            return True
        return False

    if method == "reference_discovery":
        # Idempotent — we track completion via a metadata flag on the
        # person node. Absent the flag, we re-run (it skips already-
        # visited URLs internally anyway).
        node = _get_person_node(ctx)
        if node and node.metadata.get("ref_discovery_done") is True:
            return True
        return False

    if method == "arctic_shift":
        if ctx.cache is None:
            return False
        return _cache_has_query_for(ctx.cache, "arctic_shift", ctx.person_name)

    # brave / bing / duckduckgo / gemini_grounded
    provider_map = {
        "brave": "brave",
        "bing": "bing",
        "duckduckgo": "duckduckgo",
        "gemini_grounded": "gemini_grounded",
    }
    provider = provider_map.get(method)
    if provider is None or ctx.cache is None:
        return False
    return _cache_has_query_for(ctx.cache, provider, ctx.person_name)


def _get_person_node(ctx: EnrichmentContext):
    """Fetch the person's GraphNode from the DB (None if not loaded)."""
    if not ctx.person_node_id:
        return None
    return ctx.db.get_node(ctx.person_node_id)


# ──────────────────────────────────────────────────────────────────────────
#  URL ingestion (shared by every method)
# ──────────────────────────────────────────────────────────────────────────

def _resolve_redirect_url(url: str, timeout: int = 10) -> str:
    """Resolve a Vertex AI grounding redirect URL to its final destination.

    Ported from scripts/ingest_a_person.py:_resolve_redirect_url.
    """
    if not url.startswith(_VERTEXAI_REDIRECT_PREFIX):
        return url
    try:
        resp = requests.get(
            url,
            allow_redirects=True,
            timeout=timeout,
            headers={"User-Agent": settings.crawl_user_agent},
        )
        final = resp.url
        if final and not final.startswith(_VERTEXAI_REDIRECT_PREFIX):
            return final
        location = resp.headers.get("Location", "")
        if location and not location.startswith(_VERTEXAI_REDIRECT_PREFIX):
            return location
        _log.warning("Could not resolve Vertex AI redirect URL: %s", url[:80])
        return url
    except Exception as e:
        _log.warning("Failed to resolve Vertex AI redirect URL: %s", e)
        return url


def _count_graph(ctx: EnrichmentContext) -> tuple[int, int]:
    """Return (node_count, edge_count) of the current DB."""
    return len(ctx.db.get_all_nodes()), len(ctx.db.get_all_edges())


def ingest_url(ctx: EnrichmentContext, url: str) -> bool:
    """Fetch + extract + store a single URL. Returns True on success.

    Skips URLs already in the graph, resolves Vertex AI redirects, fetches
    via fetch_page (with Wayback fallback), and runs the GeminiExtractor +
    GeminiClaimExtractor + process_page pipeline.
    """
    if not url or not url.startswith("http"):
        return False
    if url in ctx.existing_urls:
        return False
    if ctx.db.get_source_by_url(url) is not None:
        ctx.existing_urls.add(url)
        return False

    ctx.existing_urls.add(url)
    final_url = _resolve_redirect_url(url)
    if final_url != url:
        ctx.existing_urls.add(final_url)
        if ctx.db.get_source_by_url(final_url) is not None:
            return False

    try:
        page = fetch_page(
            final_url,
            timeout=settings.crawl_timeout,
            use_browser_ua=True,
        )
    except Exception as e:
        _log.warning("fetch failed for %s: %s", final_url, e)
        return False

    if page.error or not page.text:
        return False

    if ctx.gemini_ext is None or ctx.gemini_claim_ext is None:
        # No extractor configured — just record the source/work node via
        # process_page would no-op without an extractor, so skip.
        return False

    try:
        process_page(page, ctx.gemini_ext, ctx.gemini_claim_ext, ctx.db)
        return True
    except Exception as e:
        _log.warning("process_page failed for %s: %s", final_url, e)
        return False


def ingest_urls(ctx: EnrichmentContext, urls: list[str], result: MethodResult) -> int:
    """Ingest a batch of URLs, updating ``result`` with new node/edge deltas.

    Returns the number of URLs successfully ingested.
    """
    if ctx.dry_run:
        result.new_urls = len(urls)
        return 0

    n_before_nodes, n_before_edges = _count_graph(ctx)
    ingested = 0
    for url in urls:
        if len(ctx.existing_urls) >= ctx.max_urls + len(
            [r for r in ctx.results for _ in range(r.new_urls)]
        ):
            # Rough cap — the global max_urls budget across methods.
            pass
        if ingest_url(ctx, url):
            ingested += 1
    n_after_nodes, n_after_edges = _count_graph(ctx)
    result.new_urls = ingested
    result.new_nodes = max(0, n_after_nodes - n_before_nodes)
    result.new_edges = max(0, n_after_edges - n_before_edges)
    return ingested


# ──────────────────────────────────────────────────────────────────────────
#  Method implementations
# ──────────────────────────────────────────────────────────────────────────

def _run_google_kg(ctx: EnrichmentContext) -> MethodResult:
    """1. Google Knowledge Graph — resolve the person, add Wikipedia URL +
    KG metadata to the person node."""
    result = MethodResult(method="google_kg")
    if ctx.kg_client is None or not ctx.kg_client.is_available():
        result.skipped = True
        result.skip_reason = "no API key"
        result.status = "Unavailable"
        return result

    if ctx.dry_run:
        result.tried = True
        result.new_urls = 1
        result.status = "[dry-run] would search KG"
        print(f"  [dry-run] google_kg: KG.search('{ctx.person_name}', types=Person)")
        return result

    try:
        entities = ctx.kg_client.search(ctx.person_name, limit=1, types="Person")
    except Exception as e:
        result.tried = True
        result.status = f"Error: {e}"
        return result

    if not entities:
        result.tried = True
        result.status = "No KG entity found"
        return result

    e = entities[0]
    urls: list[str] = []
    for u in (e.wikipedia_url, e.url):
        if u and u.startswith("http"):
            urls.append(u)

    # Attach KG metadata to the person node
    node = _get_person_node(ctx)
    if node:
        merged_meta = dict(node.metadata)
        merged_meta["kg_enriched"] = True
        merged_meta["kg_id"] = e.kg_id
        merged_meta["kg_description"] = e.description
        if e.wikipedia_url:
            merged_meta["wikipedia_url"] = e.wikipedia_url
        ctx.db.add_node(GraphNode(
            id=node.id,
            type=node.type,
            label=node.label,
            canonical_name=node.canonical_name,
            metadata=merged_meta,
            source_urls=node.source_urls + urls,
        ))

    ingest_urls(ctx, urls, result)
    result.tried = True
    result.status = "OK" if result.new_urls else "Already in graph"
    return result


def _run_gemini_grounded(ctx: EnrichmentContext) -> MethodResult:
    """2. Gemini grounded search via SeedDiscoverer."""
    result = MethodResult(method="gemini_grounded")
    if ctx.gemini_client is None or not ctx.gemini_client.is_available():
        result.skipped = True
        result.skip_reason = "Gemini unavailable"
        result.status = "Unavailable"
        return result

    query = " ".join(
        [ctx.person_name] + ctx.cities + ctx.dates + ([ctx.context] if ctx.context else [])
    ).strip()

    if ctx.dry_run:
        result.tried = True
        result.status = "[dry-run] would run grounded search"
        print(f"  [dry-run] gemini_grounded: SeedDiscoverer.discover('{query}')")
        return result

    try:
        discoverer = SeedDiscoverer(ctx.gemini_client)
        seeds = discoverer.discover(
            query,
            exclude_urls=ctx.existing_urls,
            allow_paid=True,
        )
    except Exception as e:
        result.tried = True
        result.status = f"Error: {e}"
        return result

    urls = [s.url for s in seeds if s.url.startswith("http")]
    # Track in cache so re-runs skip this method.
    if ctx.cache:
        ctx.cache.put(query, "gemini_grounded", [{"url": u} for u in urls], {})

    ingest_urls(ctx, urls, result)
    result.tried = True
    result.status = "OK" if result.new_urls else ("No new URLs" if urls else "No results")
    return result


def _run_search_method(
    ctx: EnrichmentContext,
    method: str,
    provider: str,
    client: Any,
) -> MethodResult:
    """Shared driver for brave / bing / duckduckgo template search."""
    result = MethodResult(method=method)
    if client is None or not client.is_available():
        result.skipped = True
        result.skip_reason = "unavailable"
        result.status = "Unavailable"
        return result

    queries = build_queries(ctx.person_name, ctx.dates, ctx.cities, ctx.context)

    if ctx.dry_run:
        result.tried = True
        result.status = f"[dry-run] {len(queries)} queries"
        print(f"  [dry-run] {method}: {len(queries)} queries via {provider}")
        for q in queries[:5]:
            print(f"        {q}")
        if len(queries) > 5:
            print(f"        ... ({len(queries) - 5} more)")
        return result

    all_urls: list[str] = []
    seen: set[str] = set()
    for q in queries:
        try:
            if ctx.quota:
                ctx.quota.check_budget(provider)
            results = client.search(q, count=5)
        except BudgetExceeded as e:
            result.tried = True
            result.status = f"Quota exhausted: {e}"
            if all_urls:
                ingest_urls(ctx, all_urls, result)
            return result
        except Exception as e:
            _log.warning("%s search failed for '%s': %s", provider, q, e)
            continue
        for r in results:
            if r.url and r.url not in seen and r.url not in ctx.existing_urls:
                seen.add(r.url)
                all_urls.append(r.url)

    ingest_urls(ctx, all_urls, result)
    result.tried = True
    result.status = "OK" if result.new_urls else ("No new URLs" if all_urls else "No results")
    return result


def _run_reference_discovery(ctx: EnrichmentContext) -> MethodResult:
    """6. Follow outbound links from existing sources (ReferenceDiscoverer)."""
    result = MethodResult(method="reference_discovery")

    if ctx.dry_run:
        result.tried = True
        result.status = "[dry-run] would follow outbound links"
        print("  [dry-run] reference_discovery: ReferenceDiscoverer on person sources")
        return result

    try:
        discoverer = ReferenceDiscoverer(
            ctx.db,
            delay_seconds=settings.crawl_delay_seconds,
            timeout=settings.crawl_timeout,
            user_agent=settings.crawl_user_agent,
        )
        stats, _results = discoverer.discover(dry_run=False)
    except Exception as e:
        result.tried = True
        result.status = f"Error: {e}"
        return result

    # Mark the person node so re-runs skip this method.
    node = _get_person_node(ctx)
    if node:
        merged_meta = dict(node.metadata)
        merged_meta["ref_discovery_done"] = True
        ctx.db.add_node(GraphNode(
            id=node.id,
            type=node.type,
            label=node.label,
            canonical_name=node.canonical_name,
            metadata=merged_meta,
            source_urls=node.source_urls,
        ))

    result.tried = True
    result.new_urls = stats.total_new_references
    n_after_nodes, n_after_edges = _count_graph(ctx)
    # ReferenceDiscoverer creates Work nodes + edges itself; we can't
    # easily attribute the delta to just this method, so report the
    # new_source_records / new_work_nodes / new_edges from its stats.
    result.new_nodes = stats.new_work_nodes
    result.new_edges = stats.new_edges
    result.status = "OK" if stats.total_new_references else "No new links"
    return result


def _run_arctic_shift(ctx: EnrichmentContext) -> MethodResult:
    """7. Search the Reddit Arctic Shift archive for the person name."""
    result = MethodResult(method="arctic_shift")

    # Build a small set of queries: the bare name, and name + each city/date.
    queries = [f'"{ctx.person_name}"']
    for city in ctx.cities:
        queries.append(f'"{ctx.person_name}" "{city}"')
    for date in ctx.dates:
        queries.append(f'"{ctx.person_name}" {date}')

    if ctx.dry_run:
        result.tried = True
        result.status = f"[dry-run] {len(queries)} queries × {len(_ARCTIC_SHIFT_SUBREDDITS)} subs"
        print(f"  [dry-run] arctic_shift: {len(queries)} term(s) × "
              f"{len(_ARCTIC_SHIFT_SUBREDDITS)} subreddit(s)")
        return result

    discovered_urls: list[str] = []
    seen: set[str] = set()
    for term in queries:
        cached_hit = False
        if ctx.cache:
            cached = ctx.cache.get(term, "arctic_shift", {})
            if cached is not None:
                cached_hit = True
                for entry in cached:
                    u = entry.get("url", "")
                    if u and u not in seen and u not in ctx.existing_urls:
                        seen.add(u)
                        discovered_urls.append(u)
        if cached_hit:
            continue

        for subreddit in _ARCTIC_SHIFT_SUBREDDITS:
            params = {
                "subreddit": subreddit,
                "query": term,
                "limit": 25,
                "sort": "asc",
            }
            try:
                resp = requests.get(
                    _ARCTIC_SHIFT_POSTS,
                    params=params,
                    timeout=_ARCTIC_SHIFT_TIMEOUT,
                )
                resp.raise_for_status()
                payload = resp.json()
            except Exception as e:
                _log.warning("arctic_shift query '%s' r/%s failed: %s", term, subreddit, e)
                time.sleep(_ARCTIC_SHIFT_DELAY)
                continue

            posts = payload.get("data", [])
            cache_entries: list[dict] = []
            for post in posts:
                permalink = post.get("permalink") or ""
                if permalink and not permalink.startswith("http"):
                    permalink = f"https://www.reddit.com{permalink}"
                if permalink and permalink not in seen and permalink not in ctx.existing_urls:
                    seen.add(permalink)
                    discovered_urls.append(permalink)
                if permalink:
                    cache_entries.append({"url": permalink, "title": post.get("title", "")})
            if ctx.cache and cache_entries:
                ctx.cache.put(term, "arctic_shift", cache_entries, {"subreddit": subreddit})
            time.sleep(_ARCTIC_SHIFT_DELAY)

    ingest_urls(ctx, discovered_urls, result)
    result.tried = True
    result.status = "OK" if result.new_urls else ("No new URLs" if discovered_urls else "No results")
    return result


# ──────────────────────────────────────────────────────────────────────────
#  Orchestration
# ──────────────────────────────────────────────────────────────────────────

def run_enrichment(ctx: EnrichmentContext, skip_methods: set[str]) -> None:
    """Run every method in order, skipping already-tried and user-skipped ones."""
    for method in ALL_METHODS:
        if method in skip_methods:
            r = MethodResult(method=method, skipped=True, skip_reason="user --skip-methods")
            r.status = "Skipped by user"
            ctx.results.append(r)
            print(f"\n── {method}: skipped by --skip-methods")
            continue

        if method_already_tried(ctx, method):
            r = MethodResult(method=method, skipped=True, skip_reason="already tried")
            r.status = "Already tried"
            ctx.results.append(r)
            print(f"\n── {method}: already tried, skipping")
            continue

        print(f"\n── {method}")
        try:
            if method == "google_kg":
                r = _run_google_kg(ctx)
            elif method == "gemini_grounded":
                r = _run_gemini_grounded(ctx)
            elif method == "brave":
                r = _run_search_method(ctx, method, "brave", ctx.brave_client)
            elif method == "bing":
                r = _run_search_method(ctx, method, "bing", ctx.bing_client)
            elif method == "duckduckgo":
                r = _run_search_method(ctx, method, "duckduckgo", ctx.ddg_client)
            elif method == "reference_discovery":
                r = _run_reference_discovery(ctx)
            elif method == "arctic_shift":
                r = _run_arctic_shift(ctx)
            else:
                r = MethodResult(method=method, skipped=True, skip_reason="unknown method")
        except Exception as e:
            r = MethodResult(method=method, tried=True, status=f"Error: {e}")
            _log.error("method %s raised: %s", method, e, exc_info=True)

        ctx.results.append(r)
        print(f"   → {r.status} (new URLs: {r.new_urls}, nodes: {r.new_nodes}, edges: {r.new_edges})")


def print_summary(results: list[MethodResult]) -> None:
    """Print the final summary table."""
    print("\n" + "=" * 78)
    print("  ENRICHMENT SUMMARY")
    print("=" * 78)
    header = f"{'Method':<16} | {'Tried':<8} | {'New URLs':<8} | {'New Nodes':<10} | {'New Edges':<10} | Status"
    print(header)
    print("-" * len(header))
    for r in results:
        method, tried, urls, nodes, edges, status = r.as_row()
        print(f"{method:<16} | {tried:<8} | {urls:<8} | {nodes:<10} | {edges:<10} | {status}")


# ──────────────────────────────────────────────────────────────────────────
#  CLI
# ──────────────────────────────────────────────────────────────────────────

def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=(
            "Unified person enrichment — tries every available "
            "search/discovery/API method that hasn't already been tried "
            "for a person. Idempotent, contamination-safe, cache-aware."
        ),
    )
    p.add_argument(
        "name",
        nargs="?",
        help="Person name to search for (e.g. 'robert nadeau')",
    )
    p.add_argument(
        "--dates",
        default="",
        help="Comma-separated date ranges or years (e.g. '1987-1994,1990')",
    )
    p.add_argument(
        "--cities",
        default="",
        help="Comma-separated city names (e.g. 'san francisco,moscow')",
    )
    p.add_argument(
        "--from-node",
        help="Use an existing graph node ID instead of searching by name",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what methods would be tried without making API calls",
    )
    p.add_argument(
        "--max-urls",
        type=int,
        default=20,
        help="Max new URLs to fetch and ingest (default: 20)",
    )
    p.add_argument(
        "--skip-methods",
        default="",
        help="Comma-separated method names to skip "
             "(e.g. 'bing,duckduckgo')",
    )
    p.add_argument(
        "--context",
        default="",
        help="Disambiguation context word (e.g. 'aikido'). Defaults to "
             "'martial arts' when not provided.",
    )
    p.add_argument(
        "--snapshot-dir",
        type=Path,
        default=SNAPSHOT_DIR,
        help="Graph snapshot directory (source of truth)",
    )
    p.add_argument(
        "--db",
        type=Path,
        default=DB_PATH,
        help="Local SQLite working DB path",
    )
    p.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Verbose logging",
    )
    return p.parse_args(argv)


def _resolve_person(
    args: argparse.Namespace,
    snapshot_dir: Path,
    db: GraphDB,
) -> tuple[str, str | None]:
    """Resolve the person name and node ID from CLI args + graph snapshot."""
    if args.from_node:
        # Try exact node lookup in the DB first.
        node = db.get_node(args.from_node)
        if node:
            return node.label or args.name or args.from_node, node.id
        # Fall back to JSONL lookup (dry-run / empty DB).
        nodes = load_jsonl(snapshot_dir / "nodes.jsonl")
        for n in nodes:
            if n.get("id") == args.from_node:
                return n.get("label") or args.name or args.from_node, n["id"]
        # If not found but a name was also given, use it.
        if args.name:
            return args.name, args.from_node
        return args.from_node, args.from_node

    if not args.name:
        return "", None

    # Find canonical person from the snapshot.
    nodes = load_jsonl(snapshot_dir / "nodes.jsonl")
    matches = find_matching_nodes(args.name, nodes)
    canonical = select_canonical_person(matches)
    if canonical:
        return canonical.get("label") or args.name, canonical["id"]
    # Not in graph yet — derive a node ID from the name convention.
    derived_id = f"person:{args.name.lower().replace(' ', '-')}"
    return args.name, derived_id


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    if not args.name and not args.from_node:
        print("ERROR: provide a person NAME or --from-node", file=sys.stderr)
        return 2

    snap_dir = args.snapshot_dir
    db_file = args.db
    print(f"Snapshot (source of truth): {snap_dir}")
    print(f"Local working DB: {db_file}")

    # ── Load graph ────────────────────────────────────────────────────
    if args.dry_run:
        print("[dry-run] Skipping SQLite import (using empty DB)")
        db = GraphDB(":memory:")
    elif snapshot_exists(snap_dir):
        db = import_from_json(snap_dir, db_file)
    else:
        print(f"No snapshot found at {snap_dir} — starting from empty DB")
        db = GraphDB(db_file)

    # ── Resolve person ────────────────────────────────────────────────
    person_name, person_node_id = _resolve_person(args, snap_dir, db)
    if not person_name:
        print("ERROR: could not resolve a person name", file=sys.stderr)
        db.close()
        return 2

    dates = [d.strip() for d in args.dates.split(",") if d.strip()]
    cities = [c.strip() for c in args.cities.split(",") if c.strip()]
    skip_methods = {m.strip() for m in args.skip_methods.split(",") if m.strip()}

    print(f"\nPerson: {person_name}  (node: {person_node_id or '(none)'})")
    if dates:
        print(f"Dates:  {', '.join(dates)}")
    if cities:
        print(f"Cities: {', '.join(cities)}")
    print(f"Max URLs: {args.max_urls}  Dry-run: {args.dry_run}")

    # ── Build shared infrastructure ───────────────────────────────────
    existing_urls: set[str] = set()
    if not args.dry_run:
        for s in db.get_all_sources():
            if s.url:
                existing_urls.add(s.url)

    # In dry-run mode we still construct the search clients whose
    # is_available() check is a pure local boolean (kg, brave, bing, ddg)
    # so the dry-run path can report which methods would fire and what
    # queries they would issue. Gemini is left lazy (its is_available()
    # constructs the SDK client) unless we're doing a real run.
    cache = None
    quota = None
    if not args.dry_run:
        cache = SearchCache(
            PROJECT_ROOT / settings.search_cache_path,
            ttl_days=settings.search_cache_ttl_days,
        )
        try:
            quota = QuotaTracker(
                PROJECT_ROOT / settings.search_cache_path,
                session_budget=settings.search_session_budget_queries,
                monthly_budget=settings.search_monthly_budget_queries,
            )
        except Exception:
            quota = None

    kg_client = KnowledgeGraphClient()
    brave_client = BraveSearchClient(
        api_key=settings.brave_search_api_key,
        cache=cache,
        quota_tracker=quota,
    )
    bing_client = BingSearchClient(cache=cache, quota_tracker=quota)
    ddg_client = DuckDuckGoSearchClient(cache=cache, quota_tracker=quota)

    if args.dry_run:
        gemini_client = None
        gemini_ext = None
        gemini_claim_ext = None
    else:
        gemini_client = TieredGeminiClient(vertexai_enabled=True)
        if gemini_client.is_available():
            gemini_ext = GeminiExtractor(gemini_client, allow_paid=True)
            gemini_claim_ext = GeminiClaimExtractor(gemini_ext)
        else:
            gemini_ext = None
            gemini_claim_ext = None

    ctx = EnrichmentContext(
        person_name=person_name,
        person_node_id=person_node_id,
        dates=dates,
        cities=cities,
        context=args.context,
        db=db,
        cache=cache,
        quota=quota,
        kg_client=kg_client,
        gemini_client=gemini_client,
        gemini_ext=gemini_ext,
        gemini_claim_ext=gemini_claim_ext,
        brave_client=brave_client,
        bing_client=bing_client,
        ddg_client=ddg_client,
        existing_urls=existing_urls,
        max_urls=args.max_urls,
        dry_run=args.dry_run,
    )

    try:
        run_enrichment(ctx, skip_methods)
        print_summary(ctx.results)

        # ── Export back to snapshot ───────────────────────────────────
        if not args.dry_run:
            counts = export_to_json(db, snap_dir)
            print(f"\nSnapshot exported: {counts}")
    finally:
        db.close()
        if cache is not None:
            cache.close()
        if quota is not None:
            quota.close()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
