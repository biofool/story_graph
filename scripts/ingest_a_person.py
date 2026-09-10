#!/usr/bin/env python3
"""
Generalized person-ingestion pipeline — the two abstract techniques that
would have found every person currently in the Story Graph.

============================================================================
  THE TWO TECHNIQUES
============================================================================

Every one of the 416 Person nodes in the current graph was discovered by
one of two abstract techniques. This script generalizes both so that
ingesting a new person — or re-discovering an existing one from scratch —
is a single command instead of a hand-written one-off script.

----------------------------------------------------------------------------
  Technique 1: Name-Grounded Entity Discovery
----------------------------------------------------------------------------

  Given a person's NAME (and optional context — martial art, era, city),
  discover all web sources about that person and extract their graph data.

  This is what scripts/31_ingest_jack_wada.py did manually: someone knew
  the name "Jack Wada", searched for his dojo website, read the
  instructors page, and hand-coded the facts. It is also what
  scripts/24_kg_enrich.py does with the Google Knowledge Graph API, what
  scripts/02_gemini_search.py does with Gemini grounded search, and what
  the single-entity templates in scripts/22_relationship_search.py do
  with Brave/Bing biography and interview queries.

  The generalized form composes three search modalities, from most
  authoritative to broadest:

    1a. Knowledge Graph resolution — Google KG API returns the canonical
        entity, Wikipedia URL, and description. This establishes identity
        and notability in one call. (src/search/kg_client.py)

    1b. LLM-grounded web search — Gemini with Google Search grounding
        finds authoritative web pages about the person and returns them
        as cited sources. (src/llm/seed_discoverer.py)

    1c. Template web search — Brave/Bing/DuckDuckGo queries from
        biography, interview, obituary, and instructor templates, filling
        coverage gaps that the LLM's grounding missed.
        (src/search/relationship_searcher.py single_templates)

  Each discovered URL is then fetched, passed through the same
  GeminiExtractor + GeminiClaimExtractor + process_page pipeline that
  scripts/01 and scripts/03 use, so the person's claims, relationships,
  and source records land in the graph exactly like any crawled source.

  This technique finds persons whose names you already know — Jack Wada,
  Robert Nadeau, Dan Millman, Sig Kufferath, Richard Moon, etc.

----------------------------------------------------------------------------
  Technique 2: Graph-Neighbor Link-Following Discovery
----------------------------------------------------------------------------

  Given any entity ALREADY in the graph (a person, group, place, or work),
  discover NEW persons by following the graph's existing edges and source
  URLs outward.

  This is what scripts/15_discover_references.py does (fetch source URLs,
  extract outbound links), what scripts/01_crawl_and_build_graph.py does
  (BFS crawl from seeds, extract entities from every page), what
  scripts/22_relationship_search.py pair queries do (search for
  co-mentions of known entity pairs), and what the entity extraction in
  scripts/_pipeline_helpers.process_page does (pull every Person mentioned
  in a crawled page into the graph).

  The generalized form composes two discovery modalities:

    2a. Source-content extraction — fetch the source URLs already attached
        to the seed entity's nodes/edges, extract all Person entities and
        claims from the page text with GeminiExtractor, and store them.
        Every person mentioned in a news article, Wikipedia page, or blog
        post about the seed entity becomes a graph node.

    2b. Pair-query web search — for each known neighbor of the seed entity
        (persons connected by TEACHER_STUDENT, MEMBER_OF, WORKED_AT,
        FOUNDED edges), generate pair queries ("X Y training", "X student
        of Y", "X Y dojo") and search for web pages documenting the
        relationship. New persons mentioned in those pages are extracted
        and stored.

  This technique finds persons whose names you DON'T know yet — they
  appear as co-mentions, students, teachers, family members, or
  colleagues in sources about persons you already know. "Baba Don",
  "Isis Aquarian", "Harry Chandler", and hundreds of others entered the
  graph this way: they were extracted from pages about Father Yod / The
  Source Family, not searched for by name.

----------------------------------------------------------------------------
  How the two techniques compose
----------------------------------------------------------------------------

  Technique 1 finds a person by name → their sources enter the graph →
  Technique 2 runs on those sources → new persons are discovered →
  Technique 1 runs on each new person → their sources enter the graph →
  Technique 2 runs again → ...

  This is the BFS expansion that built the current 416-person graph from
  an initial set of seed URLs about Father Yod / The Source Family. The
  two techniques are the expand and extract steps of that BFS, abstracted
  away from the specific seed set and specific persons they happened to
  run on.

  scripts/31_ingest_jack_wada.py was a hand-coded instance of Technique 1
  (someone knew "Jack Wada", found his dojo website, extracted facts). The
  generalized version below does the same thing for any name, without
  hand-coding.

============================================================================
  Usage
============================================================================

    # Technique 1 only — discover sources for a known name
    python scripts/ingest_a_person.py "Jack Wada" --context "aikido"
    python scripts/ingest_a_person.py "Robert Nadeau" --context "aikido" --dry-run

    # Technique 2 only — discover new persons from an existing graph node
    python scripts/ingest_a_person.py --from-node "person:jack-wada"
    python scripts/ingest_a_person.py --from-node "person:robert-nadeau" --dry-run

    # Both techniques — discover the person, then expand from their neighbors
    python scripts/ingest_a_person.py "Jack Wada" --context "aikido" --expand

    # Limit how many URLs to fetch/extract per technique
    python scripts/ingest_a_person.py "Dan Millman" --context "aikido author" \
        --max-urls 10 --expand --max-pair-queries 20

    # Skip the LLM extraction step (just discover URLs, don't crawl/extract)
    python scripts/ingest_a_person.py "Sig Kufferath" --context "jujitsu danzan" \
        --discover-only

    # Use a specific snapshot dir / DB path
    python scripts/ingest_a_person.py "Richard Moon" --context "aikido" \
        --snapshot-dir graph_snapshot --db data/graph.db

============================================================================
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from dataclasses import dataclass, field
from pathlib import Path

_VERTEXAI_REDIRECT_PREFIX = "https://vertexaisearch.cloud.google.com/grounding-api-redirect/"

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from config.settings import settings
from src.crawler.web_crawler import WebCrawler
from src.llm.entity_claim_extractor import GeminiClaimExtractor, GeminiExtractor
from src.llm.gemini_client import TieredGeminiClient
from src.llm.seed_discoverer import SeedDiscoverer
from src.search.kg_client import KnowledgeGraphClient
from src.search.bing_search_client import BingSearchClient
from src.search.brave_search_client import BraveSearchClient
from src.search.quota import QuotaTracker
from src.search.search_cache import SearchCache
from src.storage.graph_db import GraphDB
from src.storage.json_export import export_to_json, import_from_json, snapshot_exists
from src.storage.models import NodeType
from src.utils.text_utils import get_domain
from scripts._pipeline_helpers import process_page

_log = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────────────────
#  Technique 1: Name-Grounded Entity Discovery
# ──────────────────────────────────────────────────────────────────────────

@dataclass
class DiscoveryResult:
    """Results from Technique 1 — URLs discovered for a person by name."""

    person_name: str
    context: str
    kg_entity: dict | None = None
    grounded_urls: list[str] = field(default_factory=list)
    template_urls: list[str] = field(default_factory=list)
    all_urls: list[str] = field(default_factory=list)

    def summary(self) -> str:
        lines = [
            f"Technique 1 results for '{self.person_name}' (context: {self.context}):",
        ]
        if self.kg_entity:
            lines.append(
                f"  KG: {self.kg_entity.get('name', '?')} — "
                f"{self.kg_entity.get('description', '?')}"
            )
            wiki = self.kg_entity.get("wikipedia_url", "")
            if wiki:
                lines.append(f"  KG Wikipedia URL: {wiki}")
        else:
            lines.append("  KG: no entity found")
        lines.append(f"  Grounded URLs (Gemini): {len(self.grounded_urls)}")
        lines.append(f"  Template URLs (Brave/Bing): {len(self.template_urls)}")
        lines.append(f"  Total unique URLs: {len(self.all_urls)}")
        return "\n".join(lines)


def technique1_discover_by_name(
    person_name: str,
    context: str = "",
    *,
    max_urls: int = 15,
    existing_urls: set[str] | None = None,
    kg_client: KnowledgeGraphClient | None = None,
    gemini_client: TieredGeminiClient | None = None,
    search_client: BraveSearchClient | BingSearchClient | None = None,
    dry_run: bool = False,
) -> DiscoveryResult:
    """Technique 1: discover web sources for a person given their name.

    Composes Knowledge Graph resolution, Gemini grounded search, and
    template web search to find authoritative pages about the person.

    Args:
        person_name: The person's name (e.g. "Jack Wada").
        context: Optional disambiguation context (e.g. "aikido", "jujitsu").
        max_urls: Maximum total URLs to collect across all modalities.
        existing_urls: URLs already in the graph — skipped.
        kg_client: Google Knowledge Graph client (or None to skip 1a).
        gemini_client: Gemini client for grounded search (or None to skip 1b).
        search_client: Brave/Bing client for template search (or None to skip 1c).
        dry_run: If True, discover URLs but don't fetch/extract.
    """
    existing = existing_urls or set()
    result = DiscoveryResult(person_name=person_name, context=context)

    if dry_run:
        # In dry-run mode, show what queries WOULD be made without calling APIs
        print("  [dry-run] Technique 1 would execute:")
        print(f"    1a. KG search: '{person_name}' (types=Person)")
        print(f"    1b. Gemini grounded: '{person_name} {context}'.strip()")
        print("    1c. Template queries:")
        for tmpl in _single_entity_templates(context):
            print(f"        {tmpl.format(a=person_name, style=context or 'martial arts')}")
        return result

    # ── 1a. Knowledge Graph resolution ────────────────────────────────
    if kg_client and kg_client.is_available():
        entities = kg_client.search(person_name, limit=1, types="Person")
        if entities:
            e = entities[0]
            result.kg_entity = {
                "name": e.name,
                "description": e.description,
                "wikipedia_url": e.wikipedia_url,
                "url": e.url,
                "kg_id": e.kg_id,
            }
            for url in (e.wikipedia_url, e.url):
                if url and url.startswith("http") and url not in existing:
                    result.all_urls.append(url)
        _log.info("KG resolution for '%s': %s", person_name,
                  "found" if result.kg_entity else "no entity")

    # ── 1b. Gemini grounded web search ────────────────────────────────
    if gemini_client and gemini_client.is_available():
        query = f"{person_name} {context}".strip()
        discoverer = SeedDiscoverer(gemini_client)
        seeds = discoverer.discover(
            query,
            exclude_urls=existing | set(result.all_urls),
            allow_paid=True,
        )
        for s in seeds:
            if s.url not in existing and s.url not in result.all_urls:
                result.grounded_urls.append(s.url)
                result.all_urls.append(s.url)
            if len(result.all_urls) >= max_urls:
                break
        _log.info("Gemini grounded search for '%s': %d URLs",
                  person_name, len(result.grounded_urls))

    # ── 1c. Template web search (Brave/Bing) ──────────────────────────
    if search_client and len(result.all_urls) < max_urls:
        templates = _single_entity_templates(context)
        for tmpl in templates:
            if len(result.all_urls) >= max_urls:
                break
            query = tmpl.format(a=person_name, style=context or "martial arts")
            try:
                results = search_client.search(query, count=5)
                for r in results:
                    if r.url not in existing and r.url not in result.all_urls:
                        result.template_urls.append(r.url)
                        result.all_urls.append(r.url)
                    if len(result.all_urls) >= max_urls:
                        break
            except Exception as e:
                _log.warning("Template search failed for '%s': %s", query, e)
        _log.info("Template search for '%s': %d URLs",
                  person_name, len(result.template_urls))

    return result


def _single_entity_templates(context: str) -> list[str]:
    """Biography/interview/obituary/instructor query templates for a person.

    Generalized from data/search_terms/relationship_templates.json
    single_templates — these are the templates that would find any person
    with a web presence, regardless of domain.
    """
    return [
        '"{a}" {style} biography',
        '"{a}" {style} instructor',
        '"{a}" interview {style}',
        '"{a}" obituary {style}',
        '"{a}" seminar {style}',
        '"{a}" {style} teacher',
    ]


# ──────────────────────────────────────────────────────────────────────────
#  Technique 2: Graph-Neighbor Link-Following Discovery
# ──────────────────────────────────────────────────────────────────────────

@dataclass
class NeighborDiscoveryResult:
    """Results from Technique 2 — new persons/sources found via neighbors."""

    seed_node_id: str
    source_urls_followed: list[str] = field(default_factory=list)
    new_urls_discovered: list[str] = field(default_factory=list)
    pair_queries_executed: list[str] = field(default_factory=list)
    persons_extracted: list[str] = field(default_factory=list)
    pages_processed: int = 0

    def summary(self) -> str:
        lines = [
            f"Technique 2 results for '{self.seed_node_id}':",
            f"  Source URLs followed: {len(self.source_urls_followed)}",
            f"  New URLs discovered: {len(self.new_urls_discovered)}",
            f"  Pair queries executed: {len(self.pair_queries_executed)}",
            f"  Pages processed: {self.pages_processed}",
            f"  Persons extracted: {len(self.persons_extracted)}",
        ]
        if self.persons_extracted:
            lines.append(f"  New persons: {', '.join(self.persons_extracted[:10])}")
            if len(self.persons_extracted) > 10:
                lines.append(f"    ... and {len(self.persons_extracted) - 10} more")
        return "\n".join(lines)


def technique2_discover_from_neighbors(
    seed_node_id: str,
    db: GraphDB,
    *,
    gemini_ext: GeminiExtractor | None = None,
    gemini_claim_ext: GeminiClaimExtractor | None = None,
    search_client: BraveSearchClient | BingSearchClient | None = None,
    max_source_urls: int = 10,
    max_pair_queries: int = 20,
    existing_urls: set[str] | None = None,
    dry_run: bool = False,
) -> NeighborDiscoveryResult:
    """Technique 2: discover new persons by following the seed entity's
    graph edges and source URLs outward.

    2a. Fetches source URLs attached to the seed entity's nodes/edges,
        extracts all Person entities and claims from the page text.
    2b. For each known neighbor person, generates pair queries and searches
        for web pages documenting the relationship.

    Args:
        seed_node_id: Graph node ID to expand from (e.g. "person:jack-wada").
        db: The graph database (read for neighbors, written for new nodes).
        gemini_ext: Gemini entity extractor (or None to skip extraction).
        gemini_claim_ext: Gemini claim extractor (or None to skip claims).
        search_client: Brave/Bing client for pair queries (or None to skip 2b).
        max_source_urls: Max source URLs to fetch in step 2a.
        max_pair_queries: Max pair queries to execute in step 2b.
        existing_urls: URLs already processed — skipped.
        dry_run: If True, report what would be done without fetching.
    """
    existing = existing_urls or set()
    result = NeighborDiscoveryResult(seed_node_id=seed_node_id)

    if dry_run:
        # In dry-run mode, the DB may be empty (in-memory). Report what
        # WOULD be done without actually fetching or querying.
        print("  [dry-run] Technique 2 would execute:")
        print(f"    2a. Fetch source URLs from '{seed_node_id}' and connected nodes")
        print(f"         (up to {max_source_urls} URLs)")
        print("    2b. Generate pair queries for each neighbor person")
        print(f"         (up to {max_pair_queries} queries)")
        return result

    seed_node = db.get_node(seed_node_id)
    if not seed_node:
        _log.warning("Seed node '%s' not found in graph", seed_node_id)
        return result

    # ── 2a. Source-content extraction ─────────────────────────────────
    # Collect source URLs from the seed node and its directly-connected nodes
    source_urls = _collect_source_urls(db, seed_node_id, max_source_urls)
    result.source_urls_followed = source_urls[:max_source_urls]

    if dry_run:
        _log.info("[dry-run] Would fetch %d source URLs for '%s'",
                  len(result.source_urls_followed), seed_node_id)
    else:
        for url in result.source_urls_followed:
            if url in existing or not url.startswith("http"):
                continue
            existing.add(url)
            try:
                pages = _fetch_single_page(url)
                if not pages or pages[0].error or not pages[0].text:
                    continue
                if gemini_ext and gemini_claim_ext:
                    before = set(n.id for n in db.get_all_nodes() if n.type == NodeType.PERSON)
                    process_page(pages[0], gemini_ext, gemini_claim_ext, db)
                    after = set(n.id for n in db.get_all_nodes() if n.type == NodeType.PERSON)
                    new_persons = after - before
                    result.persons_extracted.extend(
                        db.get_node(pid).label for pid in new_persons
                        if db.get_node(pid)
                    )
                    result.pages_processed += 1
            except Exception as e:
                _log.warning("Failed to fetch/extract '%s': %s", url, e)

    # ── 2b. Pair-query web search ─────────────────────────────────────
    neighbors = _get_neighbor_persons(db, seed_node_id)
    if search_client and neighbors and not dry_run:
        pair_templates = _pair_query_templates()
        queries_made = 0
        for neighbor in neighbors:
            if queries_made >= max_pair_queries:
                break
            for tmpl in pair_templates:
                if queries_made >= max_pair_queries:
                    break
                query = tmpl.format(
                    a=seed_node.label, b=neighbor["label"],
                    style=seed_node.metadata.get("art", "aikido"),
                )
                try:
                    results = search_client.search(query, count=5)
                    for r in results:
                        if r.url not in existing and r.url not in result.new_urls_discovered:
                            result.new_urls_discovered.append(r.url)
                    result.pair_queries_executed.append(query)
                    queries_made += 1
                except Exception as e:
                    _log.warning("Pair query failed '%s': %s", query, e)

        # Fetch and extract newly discovered URLs
        for url in result.new_urls_discovered:
            if url in existing or not url.startswith("http"):
                continue
            existing.add(url)
            # Resolve Vertex AI redirect URLs before crawling
            final_url = _resolve_redirect_url(url)
            if final_url != url:
                existing.add(final_url)
            try:
                pages = _fetch_single_page(final_url)
                if not pages or pages[0].error or not pages[0].text:
                    continue
                if gemini_ext and gemini_claim_ext:
                    before = set(n.id for n in db.get_all_nodes() if n.type == NodeType.PERSON)
                    process_page(pages[0], gemini_ext, gemini_claim_ext, db)
                    after = set(n.id for n in db.get_all_nodes() if n.type == NodeType.PERSON)
                    new_persons = after - before
                    result.persons_extracted.extend(
                        db.get_node(pid).label for pid in new_persons
                        if db.get_node(pid)
                    )
                    result.pages_processed += 1
            except Exception as e:
                _log.warning("Failed to fetch/extract '%s': %s", url, e)

    return result


def _collect_source_urls(db: GraphDB, node_id: str, max_urls: int) -> list[str]:
    """Collect source URLs from a node and its directly-connected nodes."""
    urls: list[str] = []
    seen: set[str] = set()

    seed = db.get_node(node_id)
    if seed:
        for u in seed.source_urls:
            if u.startswith("http") and u not in seen:
                urls.append(u)
                seen.add(u)

    # Follow edges to find connected nodes' source URLs
    for edge in db.get_all_edges():
        if edge.src_id != node_id and edge.dst_id != node_id:
            continue
        other_id = edge.dst_id if edge.src_id == node_id else edge.src_id
        other = db.get_node(other_id)
        if other:
            for u in other.source_urls:
                if u.startswith("http") and u not in seen:
                    urls.append(u)
                    seen.add(u)
        if len(urls) >= max_urls:
            break

    return urls[:max_urls]


def _get_neighbor_persons(db: GraphDB, node_id: str) -> list[dict]:
    """Get Person nodes directly connected to the seed node."""
    neighbors = []
    seen_ids: set[str] = set()
    for edge in db.get_all_edges():
        other_id = None
        if edge.src_id == node_id:
            other_id = edge.dst_id
        elif edge.dst_id == node_id:
            other_id = edge.src_id
        if other_id and other_id not in seen_ids:
            node = db.get_node(other_id)
            if node and node.type == NodeType.PERSON:
                neighbors.append({"id": other_id, "label": node.label})
                seen_ids.add(other_id)
    return neighbors


def _pair_query_templates() -> list[str]:
    """Pair query templates for relationship discovery.

    Generalized from data/search_terms/relationship_templates.json
    pair_templates — these find documentation of relationships between
    two known persons.
    """
    return [
        '"{a}" "{b}" {style}',
        '"{a}" student of "{b}"',
        '"{b}" student of "{a}"',
        '"{a}" "{b}" training',
        '"{a}" "{b}" dojo',
        '"{a}" "{b}" seminar',
        '"{a}" "{b}" lineage',
        '"{a}" "{b}" interview',
    ]


def _fetch_single_page(url: str):
    """Fetch a single URL with WebCrawler (depth=0, max_pages=1)."""
    crawler = WebCrawler(
        seed_urls=[url],
        allowed_domains={get_domain(url)},
        max_depth=0,
        max_pages=1,
        delay_seconds=settings.crawl_delay_seconds,
        user_agent=settings.crawl_user_agent,
        timeout=settings.crawl_timeout,
    )
    return crawler.crawl()


def _resolve_redirect_url(url: str, timeout: int = 10) -> str:
    """Resolve a Vertex AI grounding redirect URL to its final destination.

    Vertex AI's Google Search grounding returns obfuscated redirect URLs
    (vertexaisearch.cloud.google.com/grounding-api-redirect/...) that
    302-redirect to the real source URL. The crawler can't fetch the
    redirect URL directly (returns 403/timeout), so we resolve it first.

    Ported from scripts/03_targeted_entity_research.py.
    """
    if not url.startswith(_VERTEXAI_REDIRECT_PREFIX):
        return url
    try:
        import requests
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


def _dry_run_lookup_node(
    snapshot_dir: Path, node_id: str, name: str | None = None
) -> dict | None:
    """Look up a node from the JSONL snapshot directly (for dry-run mode).

    Avoids the slow SQLite import by reading nodes.jsonl line by line.
    Tries exact ID match first, then fuzzy name match if provided.
    """
    nodes_path = snapshot_dir / "nodes.jsonl"
    if not nodes_path.exists():
        return None
    fuzzy_match = None
    name_lower = name.lower() if name else ""
    with open(nodes_path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            node = json.loads(line)
            if node.get("id") == node_id:
                return node
            if name_lower and node.get("type") == "Person":
                label = (node.get("label") or "").lower()
                if name_lower in label and fuzzy_match is None:
                    fuzzy_match = node
    return fuzzy_match


# ──────────────────────────────────────────────────────────────────────────
#  CLI
# ──────────────────────────────────────────────────────────────────────────

def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Generalized person ingestion — the two abstract techniques "
            "that found every person in the Story Graph. "
            "Technique 1: discover by name. Technique 2: discover from neighbors."
        ),
    )
    parser.add_argument(
        "name",
 nargs="?",
        help="Person name for Technique 1 (e.g. 'Jack Wada')",
    )
    parser.add_argument(
        "--context",
        default="",
        help="Disambiguation context (e.g. 'aikido', 'jujitsu danzan')",
    )
    parser.add_argument(
        "--from-node",
        help="Graph node ID for Technique 2 (e.g. 'person:jack-wada')",
    )
    parser.add_argument(
        "--expand",
        action="store_true",
        help="Run Technique 2 after Technique 1 (discover, then expand from neighbors)",
    )
    parser.add_argument(
        "--max-urls",
        type=int,
        default=15,
        help="Max URLs to discover/fetch per technique (default: 15)",
    )
    parser.add_argument(
        "--max-pair-queries",
        type=int,
        default=20,
        help="Max pair queries for Technique 2b (default: 20)",
    )
    parser.add_argument(
        "--discover-only",
        action="store_true",
        help="Discover URLs but don't fetch/extract (skip crawl + Gemini extraction)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be done without network calls or DB writes",
    )
    parser.add_argument(
        "--snapshot-dir",
        type=Path,
        default=PROJECT_ROOT / "graph_snapshot",
        help="Graph snapshot directory (source of truth)",
    )
    parser.add_argument(
        "--db",
        type=Path,
        default=settings.graph_db_abs_path,
        help="Local SQLite working DB path",
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Verbose logging",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    if not args.name and not args.from_node:
        parser.error("Provide a person NAME (Technique 1) or --from-node (Technique 2)")

    # ── Load graph from snapshot ──────────────────────────────────────
    db_file = args.db
    snap_dir = args.snapshot_dir
    print(f"Snapshot (source of truth): {snap_dir}")
    print(f"Local working DB: {db_file}")

    if args.dry_run:
        # In dry-run mode, skip the slow SQLite import. Use an empty
        # in-memory DB — Technique 1 doesn't need graph data, and
        # Technique 2 reads from JSONL directly for neighbor lookup.
        print("[dry-run] Skipping SQLite import (using empty DB)")
        db = GraphDB(":memory:")
    elif snapshot_exists(snap_dir):
        db = import_from_json(snap_dir, db_file)
    else:
        print(f"No snapshot found at {snap_dir} — starting from empty DB")
        db = GraphDB(db_file)

    # Collect existing URLs to avoid re-processing
    existing_urls: set[str] = set()
    if not args.dry_run:
        for s in db.get_all_sources():
            if s.url:
                existing_urls.add(s.url)

    try:
        # ── Build shared infrastructure ────────────────────────────────
        # In dry-run mode, skip constructing API clients (they may make
        # network calls during availability checks).
        if args.dry_run:
            kg_client = None
            gemini_client = None
            search_client = None
            gemini_ext = None
            gemini_claim_ext = None
        else:
            kg_client = KnowledgeGraphClient()
            gemini_client = TieredGeminiClient(vertexai_enabled=True)

            cache = SearchCache(
                PROJECT_ROOT / settings.search_cache_path,
                ttl_days=settings.search_cache_ttl_days,
            )
            quota = QuotaTracker(
                PROJECT_ROOT / settings.search_cache_path,
                session_budget=settings.search_session_budget_queries,
                monthly_budget=settings.search_monthly_budget_queries,
            )

            # Prefer Brave, fall back to Bing (free, no API key)
            brave = BraveSearchClient(
                api_key=settings.brave_search_api_key,
                cache=cache, quota_tracker=quota,
            )
            search_client = brave if brave.is_available() else BingSearchClient(
                cache=cache, quota_tracker=quota,
            )

            gemini_ext = None
            gemini_claim_ext = None
            if not args.discover_only and gemini_client.is_available():
                gemini_ext = GeminiExtractor(gemini_client)
                gemini_claim_ext = GeminiClaimExtractor(gemini_client)

        # ── Technique 1: Name-Grounded Discovery ───────────────────────
        t1_result = None
        if args.name:
            print(f"\n{'='*70}")
            print("  TECHNIQUE 1: Name-Grounded Entity Discovery")
            print(f"  Name: {args.name}  Context: {args.context or '(none)'}")
            print(f"{'='*70}\n")

            t1_result = technique1_discover_by_name(
                args.name,
                context=args.context,
                max_urls=args.max_urls,
                existing_urls=existing_urls,
                kg_client=kg_client,
                gemini_client=gemini_client,
                search_client=search_client,
                dry_run=args.dry_run,
            )
            print(t1_result.summary())
            if t1_result.all_urls:
                print("\nDiscovered URLs:")
                for u in t1_result.all_urls:
                    print(f"  {u}")

            # Fetch + extract discovered URLs
            if not args.dry_run and not args.discover_only and gemini_ext:
                print(f"\nFetching and extracting {len(t1_result.all_urls)} URLs...")
                for url in t1_result.all_urls:
                    if url in existing_urls:
                        continue
                    existing_urls.add(url)
                    # Resolve Vertex AI redirect URLs before crawling
                    final_url = _resolve_redirect_url(url)
                    if final_url != url:
                        existing_urls.add(final_url)
                    try:
                        pages = _fetch_single_page(final_url)
                        if pages and not pages[0].error and pages[0].text:
                            process_page(pages[0], gemini_ext, gemini_claim_ext, db)
                            print(f"  ✓ {final_url}")
                        else:
                            print(f"  ✗ {final_url} (fetch failed)")
                    except Exception as e:
                        print(f"  ✗ {final_url} ({e})")

        # ── Technique 2: Graph-Neighbor Link-Following ─────────────────
        seed_node_id = args.from_node
        if not seed_node_id and args.expand and t1_result:
            # Derive the node ID from the name (matches person_id convention)
            seed_node_id = f"person:{args.name.lower().replace(' ', '-')}"

        if seed_node_id:
            if args.dry_run:
                # In dry-run, look up the seed node from JSONL directly
                # (the in-memory DB is empty)
                seed = _dry_run_lookup_node(snap_dir, seed_node_id, args.name)
                if seed:
                    seed_node_id = seed["id"]
            else:
                seed = db.get_node(seed_node_id)
                if not seed and t1_result:
                    # The person may not have a node yet — try fuzzy match
                    for n in db.get_all_nodes():
                        if n.type == NodeType.PERSON and args.name and args.name.lower() in n.label.lower():
                            seed_node_id = n.id
                            seed = n
                            break

            if seed:
                seed_label = seed.label if hasattr(seed, "label") else seed.get("label", seed_node_id)
                print(f"\n{'='*70}")
                print("  TECHNIQUE 2: Graph-Neighbor Link-Following Discovery")
                print(f"  Seed node: {seed_node_id} ({seed_label})")
                print(f"{'='*70}\n")

                t2_result = technique2_discover_from_neighbors(
                    seed_node_id,
                    db,
                    gemini_ext=gemini_ext,
                    gemini_claim_ext=gemini_claim_ext,
                    search_client=search_client,
                    max_source_urls=args.max_urls,
                    max_pair_queries=args.max_pair_queries,
                    existing_urls=existing_urls,
                    dry_run=args.dry_run,
                )
                print(t2_result.summary())
            elif args.from_node:
                print(f"\n[ERROR] Node '{seed_node_id}' not found in graph.")
                return 1

        # ── Export back to snapshot ────────────────────────────────────
        if not args.dry_run:
            counts = export_to_json(db, snap_dir)
            print(f"\nSnapshot exported: {counts}")

        if not args.dry_run:
            cache.close()
            quota.close()

    finally:
        db.close()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
