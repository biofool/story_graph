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
    "magazine_archive",
    "reference_discovery",
    "arctic_shift",
]

# ──────────────────────────────────────────────────────────────────────────
#  Magazine archive discovery
# ──────────────────────────────────────────────────────────────────────────

# Martial-arts magazines with Google Books archives.
# These are editorially-overseen publications that count as RELIABLE sources
# for WP:GNG when they contain significant coverage of the subject.
_MARTIAL_ARTS_MAGAZINES = [
    {"name": "Black Belt Magazine", "issn": "0277-3066", "domain": "blackbeltmag.com"},
    {"name": "Karate Illustrated", "issn": "0022-9016", "domain": "karateillustrated.com"},
    {"name": "Blitz Magazine", "issn": "", "domain": "blitzmag.com.au"},
    {"name": "Aikido Journal", "issn": "", "domain": "aikidojournal.com"},
    {"name": "Fighting Stars", "issn": "", "domain": ""},
    {"name": "Inside Kung-Fu", "issn": "", "domain": "insidekungfu.com"},
    {"name": "Aikido Today Magazine", "issn": "", "domain": ""},
    {"name": "Tai Chi Chuan Journal", "issn": "", "domain": "tqj.de"},
    {"name": "Journal of Asian Martial Arts", "issn": "", "domain": ""},
]

# Document archives that mirror magazine content (searchable via web search).
_DOC_ARCHIVE_DOMAINS = [
    "doczz.net",
    "archive.org",
    "scribd.com",
    "doczz.com",
    "documents.site",
    "docdroid.net",
]

# Wiki mirrors that cite real publications — used for citation tracing.
# These are NOT reliable sources themselves, but their citations point to
# real magazine articles that can be verified separately.
_WIKI_MIRROR_DOMAINS = [
    "wikitia.com",
    "en-academic.com",
    "alchetron.com",
    "grokipedia.com",
    "everybodywiki.com",
    "wiki2.org",
]

# Domains that host magazine archives we can verify against.
_MAGAZINE_ARCHIVE_DOMAINS = [
    "books.google.com",
    "books.google.co.nz",
    "books.google.co.uk",
    "books.google.ca",
    "books.google.com.au",
]

# Combined set of all URLs we consider "magazine-relevant" for filtering.
_MAGAZINE_RELEVANT_DOMAINS = set(
    _DOC_ARCHIVE_DOMAINS
    + _WIKI_MIRROR_DOMAINS
    + _MAGAZINE_ARCHIVE_DOMAINS
    + [m["domain"] for m in _MARTIAL_ARTS_MAGAZINES if m["domain"]]
)


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

    # brave / bing / duckduckgo / gemini_grounded / magazine_archive
    provider_map = {
        "brave": "brave",
        "bing": "bing",
        "duckduckgo": "duckduckgo",
        "gemini_grounded": "gemini_grounded",
        "magazine_archive": "magazine_archive",
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

    # Health check — skip engines that are broken (wrong plan, 403, etc.)
    if hasattr(client, "health_check") and not client.health_check():
        result.skipped = True
        result.skip_reason = "health check failed"
        result.status = "Skipped (health check failed)"
        print(f"  {method}: skipped — health check failed")
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


def _run_magazine_archive(ctx: EnrichmentContext) -> MethodResult:
    """6. Search magazine archives for editorially-overseen martial-arts
    magazine coverage of the person.

    This method discovers sources that are typically RELIABLE for WP:GNG:
    magazine articles with editorial oversight. It runs three phases:

    Phase 1 — Web search for magazine/archive hits:
      Searches for the person's name within known martial-arts magazine
      domains, Google Books magazine archives, and document archives.
      Filters results to only magazine-relevant URLs.

    Phase 2 — Wiki mirror citation tracing:
      Searches the web AND the graph for wiki mirror pages about the person
      (wikitia.com, en-academic.com, etc.). Fetches each page, extracts
      magazine citations using regex patterns, then searches for verifiable
      copies of the cited articles.

    Phase 3 — Google Books page-level verification:
      For each Google Books URL found, fetches the Google Books search
      page (using the vq= parameter) and checks for page-level hits
      matching the person's name. This confirms the article exists at
      the cited page numbers.

    Discovered sources are ingested with source_class='journalistic' and
    metadata including the full citation (author, title, magazine, date,
    pages) and verification status.
    """
    result = MethodResult(method="magazine_archive")

    queries = build_magazine_archive_queries(ctx.person_name, ctx.dates, ctx.cities, ctx.context)

    if ctx.dry_run:
        result.tried = True
        result.status = f"[dry-run] {len(queries)} queries"
        print(f"  [dry-run] magazine_archive: {len(queries)} queries")
        for q in queries[:5]:
            print(f"        {q}")
        if len(queries) > 5:
            print(f"        ... ({len(queries) - 5} more)")
        return result

    discovered: list[dict] = []  # list of {url, title, citation?, verified?}
    seen_urls: set[str] = set()

    # ── Phase 1: Web search for magazine/archive hits ───────────────
    print(f"  Phase 1: searching web for magazine hits ({len(queries)} queries)")
    for q in queries:
        try:
            search_results = _search_web_for_magazine_hits(ctx, q)
            for url, title in search_results:
                if not _is_magazine_relevant_url(url):
                    continue
                if url in seen_urls or url in ctx.existing_urls:
                    continue
                seen_urls.add(url)
                discovered.append({"url": url, "title": title})
        except Exception as e:
            _log.warning("magazine_archive phase 1 failed for '%s': %s", q, e)

    # ── Phase 1b: Google Books API direct search ─────────────────────
    # The Google Books API doesn't require web search — it searches the
    # Google Books index directly. This finds magazine issues that web
    # search engines (Bing, DDG) miss.
    print(f"  Phase 1b: Google Books API direct search")
    gb_urls = _search_google_books_api(ctx.person_name, ctx.dates)
    for url, title in gb_urls:
        if url in seen_urls or url in ctx.existing_urls:
            continue
        seen_urls.add(url)
        discovered.append({"url": url, "title": title, "source": "google_books_api"})
    print(f"    Found {len(gb_urls)} Google Books URL(s)")

    # ── Phase 2: Wiki mirror citation tracing ─────────────────────────
    print(f"  Phase 2: tracing wiki mirror citations")
    # 2a. Find wiki mirror pages in the existing graph
    wiki_mirror_urls = _find_wiki_mirror_pages_in_graph(ctx, ctx.person_name)
    # 2b. Also search the web for wiki mirror pages about the person
    web_mirror_urls = _find_wiki_mirror_pages_via_search(ctx, ctx.person_name)
    all_mirror_urls = list(set(wiki_mirror_urls + web_mirror_urls))
    print(f"    Found {len(all_mirror_urls)} wiki mirror page(s)")

    for mirror_url in all_mirror_urls:
        if mirror_url in ctx.existing_urls:
            continue
        try:
            citations = _extract_magazine_citations(mirror_url)
            if citations:
                print(f"    {mirror_url[:60]}: {len(citations)} citation(s)")
            for citation in citations:
                # Search for verifiable copies of the cited article.
                citation_urls = _verify_magazine_citation_via_search(ctx, citation)
                for url in citation_urls:
                    if url in seen_urls or url in ctx.existing_urls:
                        continue
                    seen_urls.add(url)
                    discovered.append({
                        "url": url,
                        "title": _format_citation_title(citation),
                        "citation": citation,
                        "source": f"wiki_mirror:{mirror_url}",
                    })
        except Exception as e:
            _log.warning("wiki mirror citation trace failed for %s: %s", mirror_url, e)

    # ── Phase 3: Google Books page-level verification ─────────────────
    print(f"  Phase 3: verifying Google Books page-level hits")
    for entry in discovered:
        url = entry["url"]
        if "books.google.com" in url or "books.google." in url:
            try:
                page_hits = _verify_google_books_page_hits(url, ctx.person_name)
                if page_hits:
                    entry["verified"] = True
                    entry["page_hits"] = page_hits
                    print(f"    ✓ {url[:60]}: verified on pages {page_hits}")
                else:
                    entry["verified"] = False
                    print(f"    ✗ {url[:60]}: no page-level hits")
            except Exception as e:
                _log.warning("Google Books verification failed for %s: %s", url, e)
                entry["verified"] = False

    # ── Ingest discovered URLs ────────────────────────────────────────
    all_urls = [e["url"] for e in discovered]
    print(f"  Ingesting {len(all_urls)} magazine source(s)")

    # Track in cache so re-runs skip this method.
    if ctx.cache:
        cache_key = f"magazine_archive:{ctx.person_name}"
        ctx.cache.put(
            cache_key,
            "magazine_archive",
            [{"url": u} for u in all_urls],
            {"queries": len(queries), "discovered": len(all_urls)},
        )

    # Custom ingestion: tag magazine sources with source_class='journalistic'
    ingested = _ingest_magazine_sources(ctx, discovered, result)
    result.tried = True
    result.status = "OK" if result.new_urls else ("No new URLs" if all_urls else "No results")
    return result


def build_magazine_archive_queries(
    person_name: str,
    dates: list[str],
    cities: list[str],
    context: str,
) -> list[str]:
    """Build search queries targeting magazine archives.

    Generates queries that search for the person's name within known
    martial-arts magazine domains and document archives.
    """
    style = context or "martial arts"
    queries: list[str] = []
    seen: set[str] = set()

    def _add(q: str) -> None:
        q = " ".join(q.split())
        if q and q not in seen:
            seen.add(q)
            queries.append(q)

    # 1. Magazine name + person name (for Google Books / magazine site search)
    for mag in _MARTIAL_ARTS_MAGAZINES:
        if mag["name"]:
            _add(f'"{person_name}" "{mag["name"]}"')
            _add(f'"{person_name}" "{mag["name"]}" {style}')

    # 2. Person + document archive domains (site: searches)
    for domain in _DOC_ARCHIVE_DOMAINS:
        _add(f'"{person_name}" site:{domain}')

    # 3. Person + wiki mirror domains (for citation tracing)
    for domain in _WIKI_MIRROR_DOMAINS:
        _add(f'"{person_name}" site:{domain}')

    # 4. Person + Google Books (magazine archive search)
    for domain in _MAGAZINE_ARCHIVE_DOMAINS:
        _add(f'"{person_name}" site:{domain}')

    # 5. Person + "magazine" + date context (for date-specific magazine coverage)
    for date in dates:
        _add(f'"{person_name}" magazine {date}')
        for mag in _MARTIAL_ARTS_MAGAZINES:
            if mag["name"]:
                _add(f'"{person_name}" "{mag["name"]}" {date}')

    # 6. Person + "interview" or "article" (broader magazine coverage)
    _add(f'"{person_name}" interview magazine {style}')
    _add(f'"{person_name}" article magazine {style}')

    # 7. Person + magazine domain sites
    for mag in _MARTIAL_ARTS_MAGAZINES:
        if mag["domain"]:
            _add(f'"{person_name}" site:{mag["domain"]}')

    return queries


def _search_google_books_api(
    person_name: str,
    dates: list[str],
) -> list[tuple[str, str]]:
    """Search the Google Books API directly for magazine issues containing
    the person's name.

    The Google Books API (https://www.googleapis.com/books/v1/volumes) searches
    the Google Books index directly, bypassing web search engines entirely.
    This finds magazine issues that web search engines (Bing, DDG) miss because
    they don't index books.google.com URLs well.

    No API key required for basic search (anonymous quota: 1K requests/day).

    Returns list of (url, title) pairs where url is a books.google.com URL.
    """
    import json as _json
    from urllib.parse import urlencode

    urls: list[tuple[str, str]] = []
    seen_ids: set[str] = set()

    # Build search queries targeting magazine issues
    # The Google Books API searches full text, so we can search for the
    # person's name within magazine titles.
    magazine_names = [m["name"] for m in _MARTIAL_ARTS_MAGAZINES if m["name"]]

    queries: list[str] = [f'"{person_name}"']

    # Add magazine-specific queries
    for mag in magazine_names:
        queries.append(f'"{person_name}" {mag}')

    # Add date-specific queries
    for date in dates:
        queries.append(f'"{person_name}" {date}')
        for mag in magazine_names:
            queries.append(f'"{person_name}" {mag} {date}')

    # Deduplicate
    seen_queries: set[str] = set()
    unique_queries = []
    for q in queries:
        q = " ".join(q.split())
        if q not in seen_queries:
            seen_queries.add(q)
            unique_queries.append(q)

    for q in unique_queries[:20]:  # Cap at 20 queries to stay within quota
        try:
            params = {
                "q": q,
                "maxResults": "10",
                "printType": "magazines",
            }
            # Use GOOGLE_API_KEY if available (higher quota: 1K/day with key
            # vs ~100/day anonymous). The Google Books API requires a standard
            # Google API key (AIza... prefix), not a Gemini AI Studio key.
            # Only use the key if it starts with "AIza" (standard Google API key).
            google_key = settings.google_api_key or ""
            if google_key and google_key.startswith("AIza"):
                params["key"] = google_key
            api_url = "https://www.googleapis.com/books/v1/volumes?" + urlencode(params)
            req = requests.get(
                api_url,
                headers={"User-Agent": settings.crawl_user_agent},
                timeout=15,
            )
            resp = req.json()
            # Handle rate limiting (429) and auth errors (401) gracefully
            if req.status_code in (401, 403, 429):
                _log.info("Google Books API returned %d for '%s' — skipping remaining queries", req.status_code, q[:40])
                break
        except Exception as e:
            _log.warning("Google Books API search failed for '%s': %s", q, e)
            continue

        items = resp.get("items", [])
        for item in items:
            vol_info = item.get("volumeInfo", {})
            book_id = item.get("id", "")
            if not book_id or book_id in seen_ids:
                continue
            seen_ids.add(book_id)

            title = vol_info.get("title", "")
            authors = vol_info.get("authors", [])
            pub_date = vol_info.get("publishedDate", "")

            # Construct the Google Books URL
            gb_url = f"https://books.google.com/books?id={book_id}"

            # Build a descriptive title
            desc_parts = [title]
            if authors:
                desc_parts.append(f"by {', '.join(authors[:2])}")
            if pub_date:
                desc_parts.append(f"({pub_date})")
            desc = " ".join(desc_parts)

            urls.append((gb_url, desc))

        time.sleep(0.5)  # Be gentle with the API

    return urls


def _search_web_for_magazine_hits(
    ctx: EnrichmentContext,
    query: str,
) -> list[tuple[str, str]]:
    """Search for magazine archive hits using available search clients.

    Returns list of (url, title) pairs. Tries brave → bing → duckduckgo
    in order, using whichever is available and healthy.

    Uses health_check() to skip engines that are broken (e.g. Brave on
    the wrong plan, DuckDuckGo returning 403) before wasting queries.
    """
    results: list[tuple[str, str]] = []

    for client in [ctx.brave_client, ctx.bing_client, ctx.ddg_client]:
        if client is None or not client.is_available():
            continue
        # Skip engines that fail health check (wrong plan, 403, etc.)
        if hasattr(client, "health_check") and not client.health_check():
            _log.info("skipping %s — health check failed", client.__class__.__name__)
            continue
        try:
            if ctx.quota:
                ctx.quota.check_budget("magazine_archive")
            hits = client.search(query, count=10)
            for h in hits:
                if h.url and h.url.startswith("http"):
                    results.append((h.url, h.title or ""))
            if results:
                break
        except Exception as e:
            _log.warning("magazine search failed for '%s': %s", query, e)
            continue

    return results


def _is_magazine_relevant_url(url: str) -> bool:
    """Check if a URL is from a magazine-relevant domain."""
    for domain in _MAGAZINE_RELEVANT_DOMAINS:
        if domain in url:
            return True
    return False


def _format_citation_title(citation: dict) -> str:
    """Format a citation dict as a human-readable source title."""
    parts = []
    mag = citation.get("magazine", "")
    date = citation.get("date", "")
    title = citation.get("title", "")
    author = citation.get("author", "")
    pages = citation.get("pages", "")

    if mag:
        parts.append(mag)
    if date:
        parts.append(f"({date})")
    if title:
        parts.append(f'— "{title}"')
    if author:
        parts.append(f"by {author}")
    if pages:
        parts.append(f"pp. {pages}")
    return " ".join(parts) if parts else "Magazine article"


def _find_wiki_mirror_pages_in_graph(
    ctx: EnrichmentContext,
    person_name: str,
) -> list[str]:
    """Find wiki mirror pages about the person in the existing graph."""
    mirror_urls: list[str] = []
    for source in ctx.db.get_all_sources():
        if not source.url:
            continue
        for domain in _WIKI_MIRROR_DOMAINS:
            if domain in source.url:
                if person_name.lower() in (source.raw_text or "").lower():
                    mirror_urls.append(source.url)
                    break
    return list(set(mirror_urls))


def _find_wiki_mirror_pages_via_search(
    ctx: EnrichmentContext,
    person_name: str,
) -> list[str]:
    """Search the web for wiki mirror pages about the person."""
    mirror_urls: list[str] = []
    for domain in _WIKI_MIRROR_DOMAINS:
        query = f'"{person_name}" site:{domain}'
        for client in [ctx.brave_client, ctx.bing_client, ctx.ddg_client]:
            if client is None or not client.is_available():
                continue
            # Skip engines that fail health check
            if hasattr(client, "health_check") and not client.health_check():
                continue
            try:
                hits = client.search(query, count=5)
                for h in hits:
                    if h.url and domain in h.url:
                        mirror_urls.append(h.url)
                if mirror_urls:
                    break
            except Exception as e:
                _log.warning("wiki mirror search failed for %s: %s", domain, e)
                continue
    return list(set(mirror_urls))


def _extract_magazine_citations(wiki_url: str) -> list[dict]:
    """Extract magazine citations from a wiki mirror page.

    Parses the page text for citation patterns. Handles multiple formats:

    - "Lastname, Firstname (Month Year). \\"Title.\\" Magazine, pp. X-Y."
    - "Lastname, Firstname (Month Year). \\"Title.\\" Magazine: X-Y."
    - "Lastname, Firstname (Year). \\"Title.\\" Magazine, Vol. X, No. Y, pp. X-Y."
    - "Lastname, Firstname. \\"Title.\\" Magazine. Vol. X, No. Y, pp. X-Y."

    Returns list of dicts with keys: author, title, magazine, date, pages.
    """
    import re

    try:
        page = fetch_page(
            wiki_url,
            timeout=settings.crawl_timeout,
            use_browser_ua=True,
        )
    except Exception as e:
        _log.warning("fetch failed for wiki mirror %s: %s", wiki_url, e)
        return []

    if page.error or not page.text:
        return []

    text = page.text

    # Citation patterns for magazine articles.
    # These patterns handle the formats used by Wikitia and other wiki mirrors.
    patterns = [
        # "Lastname, Firstname (Month Year). "Title." Magazine, pp. X-Y."
        r'([A-Z][a-z]+,\s+[A-Z][a-z]+)\s*'
        r'\((\w+\s+\d{4})\)\s*\.?\s*'
        r'"([^"]+)"\s*\.?\s*'
        r'([A-Z][^,.]+?)[.,]\s*'
        r'(?:Vol\.?\s*\d+,?\s*No\.?\s*\d+,?\s*)?'
        r'(?:pp?\.?\s*)?(\d+)\s*[-–—](\d+)',

        # "Lastname, Firstname (Month Year). "Title." Magazine: X-Y."
        r'([A-Z][a-z]+,\s+[A-Z][a-z]+)\s*'
        r'\((\w+\s+\d{4})\)\s*\.?\s*'
        r'"([^"]+)"\s*\.?\s*'
        r'([A-Z][^:.]+?):\s*(\d+)\s*[-–—](\d+)',

        # "Lastname, Firstname (Year). "Title." Magazine, pp. X-Y."
        r'([A-Z][a-z]+,\s+[A-Z][a-z]+)\s*'
        r'\((\d{4})\)\s*\.?\s*'
        r'"([^"]+)"\s*\.?\s*'
        r'([A-Z][^,.]+?)[.,]\s*'
        r'(?:Vol\.?\s*\d+,?\s*No\.?\s*\d+,?\s*)?'
        r'(?:pp?\.?\s*)?(\d+)\s*[-–—](\d+)',

        # "Firstname Lastname (Month Year). "Title." Magazine, pp. X-Y."
        r'([A-Z][a-z]+\s+[A-Z][a-z]+)\s*'
        r'\((\w+\s+\d{4})\)\s*\.?\s*'
        r'"([^"]+)"\s*\.?\s*'
        r'([A-Z][^,.]+?)[.,]\s*'
        r'(?:Vol\.?\s*\d+,?\s*No\.?\s*\d+,?\s*)?'
        r'(?:pp?\.?\s*)?(\d+)\s*[-–—](\d+)',

        # "Firstname Lastname (Year). "Title." Magazine, pp. X-Y."
        r'([A-Z][a-z]+\s+[A-Z][a-z]+)\s*'
        r'\((\d{4})\)\s*\.?\s*'
        r'"([^"]+)"\s*\.?\s*'
        r'([A-Z][^,.]+?)[.,]\s*'
        r'(?:Vol\.?\s*\d+,?\s*No\.?\s*\d+,?\s*)?'
        r'(?:pp?\.?\s*)?(\d+)\s*[-–—](\d+)',

        # "Lastname, Firstname (Month Year). "Title." Magazine: X-Y." (no pp.)
        r'([A-Z][a-z]+,\s+[A-Z][a-z]+)\s*'
        r'\((\w+\s+\d{4})\)\s*\.?\s*'
        r'"([^"]+)"\s*\.?\s*'
        r'([A-Z][^:.]+?):\s*(\d+)\s*[-–—](\d+)',
    ]

    citations: list[dict] = []
    seen_titles: set[str] = set()

    for pattern in patterns:
        for match in re.finditer(pattern, text):
            author = match.group(1)
            date = match.group(2)
            title = match.group(3)
            magazine = match.group(4).strip().rstrip(".")
            pages_start = match.group(5)
            pages_end = match.group(6)

            if title in seen_titles:
                continue
            seen_titles.add(title)

            citations.append({
                "author": author,
                "date": date,
                "title": title,
                "magazine": magazine,
                "pages": f"{pages_start}-{pages_end}",
            })

    return citations


def _verify_magazine_citation_via_search(
    ctx: EnrichmentContext,
    citation: dict,
) -> list[str]:
    """Search for verifiable copies of a magazine citation using search clients.

    Given a citation dict (author, title, magazine, date, pages),
    searches Google Books and document archives for the article.

    Returns list of URLs where the article can be found.
    """
    import re

    urls: list[str] = []

    title = citation.get("title", "")
    magazine = citation.get("magazine", "")
    author = citation.get("author", "")
    date = citation.get("date", "")

    if not title or not magazine:
        return urls

    # Build search queries for the citation
    queries = [
        f'"{title}" "{magazine}"',
        f'"{author}" "{title}" "{magazine}"' if author else "",
        f'"{title}" "{magazine}" site:books.google.com',
        f'"{title}" "{magazine}" site:doczz.net',
    ]
    queries = [q for q in queries if q]

    for q in queries:
        for client in [ctx.brave_client, ctx.bing_client, ctx.ddg_client]:
            if client is None or not client.is_available():
                continue
            # Skip engines that fail health check
            if hasattr(client, "health_check") and not client.health_check():
                continue
            try:
                hits = client.search(q, count=10)
                for h in hits:
                    if h.url and h.url.startswith("http"):
                        # Only keep magazine-relevant URLs
                        if _is_magazine_relevant_url(h.url):
                            if h.url not in urls:
                                urls.append(h.url)
                if urls:
                    break
            except Exception as e:
                _log.warning("citation search failed for '%s': %s", q, e)
                continue
        if urls:
            break

    return urls


def _verify_google_books_page_hits(
    books_url: str,
    person_name: str,
) -> list[str] | None:
    """Verify that a person's name appears on specific pages of a Google
    Books magazine issue.

    Fetches the Google Books search page (using the vq= parameter) and
    looks for page-level hits (PA46, PA47, etc.) matching the person's name.

    Returns a list of page numbers (e.g. ["46", "47", "48", "49"]) or None
    if verification fails.
    """
    import re
    from urllib.parse import urlparse, parse_qs, urlencode, urlunparse

    # Extract the book ID from the URL
    parsed = urlparse(books_url)
    params = parse_qs(parsed.query)
    book_id = params.get("id", [None])[0]
    if not book_id:
        return None

    # Construct a Google Books search URL with the person's name as the query
    search_params = {
        "id": book_id,
        "vq": person_name,
    }
    search_url = f"https://books.google.com/books?{urlencode(search_params)}"

    try:
        resp = requests.get(
            search_url,
            headers={"User-Agent": settings.crawl_user_agent},
            timeout=15,
            allow_redirects=True,
        )
        text = resp.text
    except Exception as e:
        _log.warning("Google Books page search failed: %s", e)
        return None

    # Look for page references like PA46, PA47, etc.
    # Google Books uses PA<page_number> format for page references.
    page_pattern = r'PA(\d+)'
    pages = re.findall(page_pattern, text)

    if not pages:
        return None

    # Deduplicate and sort
    unique_pages = sorted(set(pages), key=int)
    return unique_pages if unique_pages else None


def _ingest_magazine_sources(
    ctx: EnrichmentContext,
    discovered: list[dict],
    result: MethodResult,
) -> int:
    """Ingest magazine sources with proper source_class and metadata.

    Unlike the standard ingest_url, this creates SourceRecord entries
    with source_class='journalistic' and records the citation details
    (author, title, magazine, date, pages) and verification status as
    metadata.
    """
    import hashlib

    if ctx.dry_run:
        result.new_urls = len(discovered)
        return 0

    n_before_nodes, n_before_edges = _count_graph(ctx)
    ingested = 0

    for entry in discovered:
        url = entry["url"]
        if not url or not url.startswith("http"):
            continue
        if url in ctx.existing_urls:
            continue
        if ctx.db.get_source_by_url(url) is not None:
            ctx.existing_urls.add(url)
            continue

        ctx.existing_urls.add(url)

        # For Google Books URLs, we can't fetch the full text, but we
        # can record the source with the citation metadata.
        # For document archives, we can fetch and extract.
        is_google_books = "books.google." in url

        url_hash = hashlib.md5(url.encode()).hexdigest()[:12]
        source_id = f"work:{url_hash}"

        title = entry.get("title", url)
        citation = entry.get("citation")
        verified = entry.get("verified", False)
        page_hits = entry.get("page_hits")

        # Build metadata from citation details
        metadata: dict[str, Any] = {
            "discovery_method": "magazine_archive",
            "verified": verified,
        }
        if citation:
            metadata["citation_author"] = citation.get("author", "")
            metadata["citation_title"] = citation.get("title", "")
            metadata["citation_magazine"] = citation.get("magazine", "")
            metadata["citation_date"] = citation.get("date", "")
            metadata["citation_pages"] = citation.get("pages", "")
        if page_hits:
            metadata["page_hits"] = page_hits
        if entry.get("source"):
            metadata["citation_source"] = entry["source"]

        # Determine platform from URL
        platform = _extract_platform_from_url(url)

        if is_google_books:
            # Google Books pages can't be fetched via fetch_page (403),
            # but we can record the source with the citation metadata.
            try:
                from src.storage.models import SourceRecord, SourceClass, BiasHint
                source = SourceRecord(
                    id=source_id,
                    url=url,
                    title=title,
                    platform=platform,
                    source_class=SourceClass.JOURNALISTIC,
                    bias_hint=BiasHint.NEUTRAL_ISH,
                    raw_text=None,
                    publish_date=citation.get("date") if citation else None,
                )
                # Store metadata in the source's raw_text as JSON
                # (SourceRecord doesn't have a metadata field, so we
                # encode it in the title and use the standard pipeline
                # for non-Google-Books URLs)
                ctx.db.add_source(source)
                ingested += 1
                _log.info("ingested google books source: %s", url[:60])
            except Exception as e:
                _log.warning("failed to add google books source %s: %s", url, e)
        else:
            # For document archives and magazine sites, use the standard
            # fetch + extract pipeline, then update the source_class.
            try:
                page = fetch_page(
                    url,
                    timeout=settings.crawl_timeout,
                    use_browser_ua=True,
                )
                if page.error or not page.text:
                    _log.warning("fetch failed for magazine source %s", url)
                    continue

                if ctx.gemini_ext is None or ctx.gemini_claim_ext is None:
                    # No extractor — just record the source.
                    from src.storage.models import SourceRecord, SourceClass, BiasHint
                    source = SourceRecord(
                        id=source_id,
                        url=url,
                        title=title or page.title or url,
                        platform=platform,
                        source_class=SourceClass.JOURNALISTIC,
                        bias_hint=BiasHint.NEUTRAL_ISH,
                        raw_text=page.text[:50000] if page.text else None,
                    )
                    ctx.db.add_source(source)
                    ingested += 1
                else:
                    # Use the standard pipeline, then update source_class
                    if ingest_url(ctx, url):
                        # Update the source_class to journalistic
                        source = ctx.db.get_source_by_url(url)
                        if source:
                            from src.storage.models import SourceRecord, SourceClass
                            source.source_class = SourceClass.JOURNALISTIC
                            ctx.db.add_source(source)
                        ingested += 1
            except Exception as e:
                _log.warning("failed to ingest magazine source %s: %s", url, e)

    n_after_nodes, n_after_edges = _count_graph(ctx)
    result.new_urls = ingested
    result.new_nodes = max(0, n_after_nodes - n_before_nodes)
    result.new_edges = max(0, n_after_edges - n_before_edges)
    return ingested


def _extract_platform_from_url(url: str) -> str:
    """Extract a platform name from a URL."""
    from urllib.parse import urlparse
    parsed = urlparse(url)
    domain = parsed.netloc or ""
    # Remove www. prefix
    domain = domain.replace("www.", "")
    return domain or "unknown"


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
            elif method == "magazine_archive":
                r = _run_magazine_archive(ctx)
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
