#!/usr/bin/env python3
"""
Generate a structured enrichment report for a person and optionally post it
as a GitHub issue.

This complements ``scripts/34_enrich_person.py`` by producing a human-readable
report of what was found, what was tried (via the SearchCache), and what is
still missing (coverage gaps, untried methods, notability assessment).

The report has six sections:

1. Person Summary        — canonical node, aliases, metadata, subgraph counts
2. Enrichment Method Status — per-search-API tried/results (SearchCache + metadata)
3. Source Inventory       — sources grouped by class / SRS tier / independence
4. Coverage Gaps          — missing dates, cities, untried methods, blocked URLs
5. Notability Assessment  — WP:GNG status, independent RELIABLE/MARGINAL counts
6. Recommendations        — concrete next steps

Usage:
    # Dry run — print report summary to stderr, full report to stdout
    python scripts/35_generate_github_report.py "robert nadeau" --dry-run

    # Write report to the default location
    python scripts/35_generate_github_report.py "robert nadeau"

    # Write to a specific file
    python scripts/35_generate_github_report.py "robert nadeau" \
        --output /tmp/nadeau_report.md

    # Post as a GitHub issue
    python scripts/35_generate_github_report.py "robert nadeau" \
        --post --repo biofool/story_graph \
        --label enrichment-report
"""

import argparse
import json
import re
import subprocess
import sys
import tempfile
from collections import defaultdict
from datetime import date
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SNAPSHOT_DIR = PROJECT_ROOT / "graph_snapshot"
REPORTS_DIR = PROJECT_ROOT / "docs" / "enrichment-reports"

# Reuse collection logic from the data ticket generator (script 19) and the
# SRS scoring logic from the Wikipedia article generator (script 32), using
# the importlib.util pattern (same as 32 imports from 19).
import importlib.util

_spec19 = importlib.util.spec_from_file_location(
    "gen_ticket",
    str(PROJECT_ROOT / "scripts" / "19_generate_data_ticket.py"),
)
_mod19 = importlib.util.module_from_spec(_spec19)
_spec19.loader.exec_module(_mod19)

load_jsonl = _mod19.load_jsonl
find_matching_nodes = _mod19.find_matching_nodes
select_canonical_person = _mod19.select_canonical_person
collect_sources = _mod19.collect_sources
collect_key_edges = _mod19.collect_key_edges
collect_kkron_claims = _mod19.collect_kkron_claims
search_term_from_nodes = _mod19.search_term_from_nodes

_spec32 = importlib.util.spec_from_file_location(
    "gen_wiki",
    str(PROJECT_ROOT / "scripts" / "32_generate_wikipedia_article.py"),
)
_mod32 = importlib.util.module_from_spec(_spec32)
_spec32.loader.exec_module(_mod32)

compute_srs = _mod32.compute_srs
load_domain_tiers = _mod32.load_domain_tiers
load_tranco = _mod32.load_tranco
get_domain = _mod32.get_domain
independence_points = _mod32.independence_points
get_name_variants = _mod32.get_name_variants
collect_claims_for_person = _mod32.collect_claims_for_person

# SearchCache lives under src/ — add src to sys.path so we can import it.
sys.path.insert(0, str(PROJECT_ROOT / "src"))
from search.search_cache import SearchCache  # noqa: E402

# Settings for the default search cache path.
sys.path.insert(0, str(PROJECT_ROOT))
from config.settings import settings  # noqa: E402

# Search providers tracked by the enrichment pipeline. Each is checked
# against the SearchCache (by provider name) except google_kg, which is
# recorded on the canonical Person node's metadata.
SEARCH_PROVIDERS = [
    "gemini",
    "brave",
    "bing",
    "duckduckgo",
    "arctic_shift",
]

# Source classes used in the graph (mirrors SOURCE_CLASS_POINTS in script 32).
SOURCE_CLASSES = [
    "journalistic",
    "archival",
    "primary_first_person",
    "documentary_promotional",
    "comment_thread",
]

# SRS tiers in descending reliability order.
SRS_TIERS = ["RELIABLE", "MARGINAL", "WEAK", "UNRELIABLE", "BLACKLISTED"]


def slugify(name: str) -> str:
    """Convert a person name to a URL/file slug."""
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return slug or "person"


def query_cache_for_person(
    cache: SearchCache, name_variants: set[str]
) -> dict[str, list[dict]]:
    """Return {provider: [cached_rows]} for queries matching any name variant.

    Queries the SQLite cache directly (via the SearchCache connection) since
    ``SearchCache.get`` requires an exact query+params key. Matching is
    case-insensitive substring against the cached ``query`` column.
    """
    by_provider: dict[str, list[dict]] = defaultdict(list)
    conn = cache._get_conn()  # noqa: SLF001 — intentional internal access
    # Build a set of lowercase search terms (drop very short tokens).
    terms = {v.lower() for v in name_variants if len(v) > 2}
    if not terms:
        return by_provider
    rows = conn.execute(
        "SELECT query, provider, results, created_at FROM search_cache"
    ).fetchall()
    for row in rows:
        q = (row["query"] or "").lower()
        if any(t in q for t in terms):
            try:
                results = json.loads(row["results"])
            except (json.JSONDecodeError, TypeError):
                results = []
            by_provider[row["provider"]].append(
                {
                    "query": row["query"],
                    "provider": row["provider"],
                    "results": results,
                    "created_at": row["created_at"],
                }
            )
    return dict(by_provider)


def collect_subgraph_sources(
    canonical: dict,
    matches: list[dict],
    nodes: list[dict],
    edges: list[dict],
    sources: list[dict],
    claim_sources: list[dict],
) -> list[dict]:
    """Collect all sources for the person subgraph (text match + claim links)."""
    matched = collect_sources(matches, sources)
    existing_urls = {s.get("url") for s in matched}

    # Search sources using Cyrillic / alias name variants.
    name_variants = get_name_variants(canonical, matches)
    for s in sources:
        if s.get("url") in existing_urls:
            continue
        blob = json.dumps(s, ensure_ascii=False).lower()
        if any(v in blob for v in name_variants if len(v) > 3):
            matched.append(s)
            existing_urls.add(s.get("url"))

    # Add sources linked to claims about this person.
    claims = collect_claims_for_person(
        canonical, matches, nodes, edges, claim_sources,
    )
    source_map = {s["id"]: s for s in sources if "id" in s}
    for c in claims:
        for sid in c.get("_source_ids", []):
            if sid in source_map and source_map[sid].get("url") not in existing_urls:
                matched.append(source_map[sid])
                existing_urls.add(source_map[sid].get("url"))

    return matched


def score_sources(
    sources: list[dict],
    canonical: dict,
    edges: list[dict],
    nodes: list[dict],
    tranco: dict,
    tiers: dict,
) -> list[dict]:
    """Score every source with the SRS and return annotated copies."""
    rsp_cache: dict[str, str] = {}  # No WP:RSP cache yet.
    scored = []
    for s in sources:
        srs, tier, breakdown = compute_srs(
            s, canonical, edges, nodes, tranco, tiers, rsp_cache,
        )
        copy = dict(s)
        copy["_srs"] = srs
        copy["_tier"] = tier
        copy["_breakdown"] = breakdown
        scored.append(copy)
    scored.sort(key=lambda x: x["_srs"], reverse=True)
    return scored


# ---------------------------------------------------------------------------
# Report section generators
# ---------------------------------------------------------------------------

def section_person_summary(
    canonical: dict,
    matches: list[dict],
    nodes: list[dict],
    edges: list[dict],
    sources: list[dict],
    claims: list[dict],
    key_edges: list[dict],
    matched_sources: list[dict],
) -> list[str]:
    """Section 1: Person Summary."""
    lines = ["## 1. Person Summary", ""]
    if not canonical:
        lines.append("*No canonical Person node found.*")
        return lines

    lines.append(f"- **Canonical node ID:** `{canonical['id']}`")
    lines.append(f"- **Label:** {canonical.get('label', '')}")
    md = canonical.get("metadata", {}) or {}
    if md:
        lines.append("- **Metadata:**")
        for key in sorted(md):
            val = md[key]
            if isinstance(val, str) and len(val) > 120:
                val = val[:117] + "..."
            lines.append(f"  - `{key}`: {val}")
    urls = canonical.get("source_urls", []) or []
    lines.append(f"- **source_urls count:** {len(urls)}")
    lines.append("")

    # Alias / duplicate Person nodes
    persons = [n for n in matches if n.get("type") == "Person"]
    aliases = [p for p in persons if p["id"] != canonical["id"]]
    if aliases:
        lines.append(
            f"- **Alias / duplicate Person nodes:** {len(aliases)} (not yet merged)"
        )
        lines.append("")
        lines.append("| Node ID | Label | source_urls count |")
        lines.append("|---|---|---|")
        for p in aliases:
            purls = len(p.get("source_urls", []) or [])
            lines.append(f"| `{p['id']}` | {p.get('label', '')} | {purls} |")
        lines.append("")
    else:
        lines.append("- **Alias / duplicate Person nodes:** none")
        lines.append("")

    # Subgraph totals
    lines.append("- **Subgraph totals:**")
    lines.append(f"  - Matched nodes: {len(matches)}")
    lines.append(f"  - Claims: {len(claims)}")
    lines.append(f"  - Key edges: {len(key_edges)}")
    lines.append(f"  - Sources: {len(matched_sources)}")
    lines.append("")
    return lines


def section_enrichment_methods(
    canonical: dict,
    matches: list[dict],
    cached: dict[str, list[dict]],
    matched_sources: list[dict],
    nodes: list[dict],
    edges: list[dict],
) -> list[str]:
    """Section 2: Enrichment Method Status."""
    lines = ["## 2. Enrichment Method Status", ""]
    md = canonical.get("metadata", {}) or {}
    canonical_urls = set(canonical.get("source_urls", []) or [])

    # google_kg — recorded on the node metadata, not the SearchCache.
    kg_enriched = bool(md.get("kg_enriched"))
    has_wiki = any("wikipedia.org" in u for u in canonical_urls)
    lines.append("### google_kg")
    lines.append(f"- Tried: {'yes' if kg_enriched else 'no'} "
                 f"(`metadata.kg_enriched` = {md.get('kg_enriched')})")
    lines.append(f"- Added Wikipedia URL: {'yes' if has_wiki else 'no'}")
    if md.get("kg_id"):
        lines.append(f"- Google Knowledge Graph ID: `{md['kg_id']}`")
    if md.get("kg_description"):
        lines.append(f"- kg_description: {md['kg_description']}")
    lines.append("")

    # gemini_grounded — check SearchCache for "gemini" provider queries.
    gemini_rows = cached.get("gemini", [])
    lines.append("### gemini_grounded")
    lines.append(f"- Tried: {'yes' if gemini_rows else 'no'} "
                 f"({len(gemini_rows)} cached query/queries)")
    if gemini_rows:
        lines.append("- Queries:")
        for r in gemini_rows[:10]:
            nresults = len(r["results"])
            lines.append(f"  - `{r['query']}` — {nresults} result(s)")
    lines.append("")

    # brave
    brave_rows = cached.get("brave", [])
    lines.append("### brave")
    lines.append(f"- Tried: {'yes' if brave_rows else 'no'} "
                 f"({len(brave_rows)} cached query/queries)")
    if brave_rows:
        total = sum(len(r["results"]) for r in brave_rows)
        lines.append(f"- Total results across queries: {total}")
        lines.append("- Queries:")
        for r in brave_rows[:10]:
            nresults = len(r["results"])
            lines.append(f"  - `{r['query']}` — {nresults} result(s)")
    lines.append("")

    # bing
    bing_rows = cached.get("bing", [])
    lines.append("### bing")
    lines.append(f"- Tried: {'yes' if bing_rows else 'no'} "
                 f"({len(bing_rows)} cached query/queries)")
    if bing_rows:
        total = sum(len(r["results"]) for r in bing_rows)
        lines.append(f"- Total results across queries: {total}")
        lines.append("- Queries:")
        for r in bing_rows[:10]:
            nresults = len(r["results"])
            lines.append(f"  - `{r['query']}` — {nresults} result(s)")
        if len(bing_rows) > 10:
            lines.append(f"  - ... ({len(bing_rows) - 10} more)")
    lines.append("")

    # duckduckgo
    ddg_rows = cached.get("duckduckgo", [])
    lines.append("### duckduckgo")
    lines.append(f"- Tried: {'yes' if ddg_rows else 'no'} "
                 f"({len(ddg_rows)} cached query/queries)")
    if ddg_rows:
        total = sum(len(r["results"]) for r in ddg_rows)
        lines.append(f"- Total results across queries: {total}")
        lines.append("- Queries:")
        for r in ddg_rows[:10]:
            nresults = len(r["results"])
            lines.append(f"  - `{r['query']}` — {nresults} result(s)")
    lines.append("")

    # reference_discovery — heuristic: sources whose URLs are NOT among the
    # canonical node's direct source_urls were likely discovered by following
    # outbound links from ingested pages.
    discovered = [
        s for s in matched_sources
        if s.get("url") and s.get("url") not in canonical_urls
    ]
    lines.append("### reference_discovery")
    lines.append(
        f"- Tried: {'yes' if discovered else 'unknown'} "
        f"({len(discovered)} source(s) not in canonical node's source_urls — "
        f"likely discovered by following outbound links)"
    )
    if discovered:
        lines.append("- Discovered sources:")
        for s in discovered[:10]:
            lines.append(f"  - {s.get('url', '')}")
        if len(discovered) > 10:
            lines.append(f"  - ... ({len(discovered) - 10} more)")
    lines.append("")

    # arctic_shift — check SearchCache and source records with arcticshift IDs.
    as_rows = cached.get("arctic_shift", [])
    as_sources = [
        s for s in matched_sources
        if str(s.get("id", "")).startswith("arcticshift")
        or s.get("platform", "") == "reddit"
    ]
    lines.append("### arctic_shift")
    lines.append(
        f"- Tried: {'yes' if (as_rows or as_sources) else 'no'} "
        f"({len(as_rows)} cached query/queries, {len(as_sources)} reddit source(s))"
    )
    if as_rows:
        lines.append("- Queries:")
        for r in as_rows[:10]:
            nresults = len(r["results"])
            lines.append(f"  - `{r['query']}` — {nresults} result(s)")
    if as_sources:
        lines.append("- Reddit sources:")
        for s in as_sources[:10]:
            lines.append(f"  - {s.get('url', '')}")
    lines.append("")
    return lines


def section_source_inventory(scored: list[dict]) -> list[str]:
    """Section 3: Source Inventory — grouped by class, SRS tier, independence."""
    lines = ["## 3. Source Inventory", ""]
    lines.append(f"Total sources in subgraph: **{len(scored)}**")
    lines.append("")

    # By source class
    lines.append("### By source class")
    lines.append("")
    by_class: dict[str, list[dict]] = defaultdict(list)
    for s in scored:
        by_class[s.get("source_class", "") or "(unclassified)"].append(s)
    lines.append("| Source class | Count |")
    lines.append("|---|---|")
    for cls in SOURCE_CLASSES + ["(unclassified)"]:
        rows = by_class.get(cls, [])
        if rows:
            lines.append(f"| {cls} | {len(rows)} |")
    lines.append("")

    # By SRS tier
    lines.append("### By SRS tier")
    lines.append("")
    by_tier: dict[str, list[dict]] = defaultdict(list)
    for s in scored:
        by_tier[s["_tier"]].append(s)
    lines.append("| SRS tier | Count |")
    lines.append("|---|---|")
    for tier in SRS_TIERS:
        rows = by_tier.get(tier, [])
        if rows:
            lines.append(f"| {tier} | {len(rows)} |")
    lines.append("")

    # By independence
    lines.append("### By independence")
    lines.append("")
    independent = [s for s in scored if s["_breakdown"]["independence"] > 0]
    affiliated = [s for s in scored if s["_breakdown"]["independence"] <= 0]
    lines.append(f"- Independent: {len(independent)}")
    lines.append(f"- Affiliated: {len(affiliated)}")
    lines.append("")

    # Full source table
    lines.append("### All sources (scored)")
    lines.append("")
    lines.append("| # | Title | Domain | Class | SRS | Tier | Independent? |")
    lines.append("|---|---|---|---|---|---|---|")
    for i, s in enumerate(scored, 1):
        title = (s.get("title", "") or s.get("url", "") or "(untitled)")[:50]
        domain = s["_breakdown"]["domain"]
        cls = s.get("source_class", "") or ""
        indep = "yes" if s["_breakdown"]["independence"] > 0 else "no"
        lines.append(
            f"| {i} | {title} | {domain} | {cls} | {s['_srs']} | "
            f"{s['_tier']} | {indep} |"
        )
    lines.append("")
    return lines


def section_coverage_gaps(
    canonical: dict,
    matches: list[dict],
    scored: list[dict],
    cached: dict[str, list[dict]],
    nodes: list[dict],
    edges: list[dict],
) -> list[str]:
    """Section 4: Coverage Gaps."""
    lines = ["## 4. Coverage Gaps", ""]

    # Date ranges with no sources — examine publish_date on sources.
    dates = []
    for s in scored:
        pd = s.get("publish_date", "")
        if pd:
            # Normalize to a year string.
            m = re.match(r"(\d{4})", str(pd))
            if m:
                dates.append(int(m.group(1)))
    lines.append("### Date coverage")
    lines.append("")
    if dates:
        lines.append(
            f"- Sources with publish_date: {len(dates)} of {len(scored)}"
        )
        lines.append(
            f"- Date range present: {min(dates)}–{max(dates)}"
        )
        # Find gaps in year coverage.
        year_set = set(dates)
        if max(dates) - min(dates) > 1:
            gaps = [
                y for y in range(min(dates), max(dates) + 1) if y not in year_set
            ]
            if gaps:
                lines.append(
                    f"- Years with no sources: {', '.join(map(str, gaps))}"
                )
            else:
                lines.append("- No year gaps within the date range.")
    else:
        lines.append(
            f"- No sources have a publish_date ({len(scored)} sources total). "
            f"Date coverage cannot be assessed."
        )
    lines.append("")

    # Cities with no sources — best-effort: scan source raw_text/platform for
    # city mentions. The enrichment --cities input is not persisted, so we
    # report which cities appear in the source text vs. known biographical
    # cities derived from LIVED_AT / LOCATED_IN edges.
    lines.append("### City coverage")
    lines.append("")
    canonical_id = canonical["id"] if canonical else ""
    bio_cities = set()
    node_map = {n["id"]: n for n in nodes}
    for e in edges:
        if e.get("src_id") == canonical_id and e.get("rel_type") in (
            "LIVED_AT", "LOCATED_IN",
        ):
            target = node_map.get(e.get("dst_id", ""), {})
            label = target.get("label", "")
            if label:
                bio_cities.add(label)
    if bio_cities:
        lines.append(
            f"- Biographical locations (from LIVED_AT/LOCATED_IN edges): "
            f"{', '.join(sorted(bio_cities))}"
        )
        # Check which cities appear in source text.
        text_blob = " ".join(
            (s.get("raw_text", "") or "") + " " + (s.get("title", "") or "")
            for s in scored
        ).lower()
        covered = {c for c in bio_cities if c.lower() in text_blob}
        missing = bio_cities - covered
        if covered:
            lines.append(
                f"- Locations with source mentions: "
                f"{', '.join(sorted(covered))}"
            )
        if missing:
            lines.append(
                f"- Locations with NO source mentions: "
                f"{', '.join(sorted(missing))}"
            )
    else:
        lines.append(
            "- No LIVED_AT/LOCATED_IN edges found for this person. "
            "City coverage cannot be assessed from the graph. "
            "(Enrichment --cities input is not persisted.)"
        )
    lines.append("")

    # Untried search methods
    lines.append("### Untried search methods")
    lines.append("")
    md = canonical.get("metadata", {}) or {}
    tried = set()
    if md.get("kg_enriched"):
        tried.add("google_kg")
    tried.update(cached.keys())  # provider names from the cache
    # reference_discovery is heuristic — count as tried if discovered sources.
    all_methods = [
        "google_kg", "gemini_grounded", "brave", "bing",
        "duckduckgo", "reference_discovery", "arctic_shift",
    ]
    untried = [m for m in all_methods if m not in tried]
    if untried:
        lines.append(f"- Untried: {', '.join(untried)}")
    else:
        lines.append("- All known search methods have been tried.")
    lines.append("")

    # Failed / blocked URLs — check source records for error/status fields.
    lines.append("### Failed / blocked URLs")
    lines.append("")
    failed = []
    error_keys = set()
    for s in scored:
        for k, v in s.items():
            if k.startswith("_"):
                continue
            if (
                "error" in k.lower()
                or "status" in k.lower()
                or "fetch" in k.lower()
            ) and v not in (None, "", 0, "200", "ok"):
                error_keys.add(k)
                failed.append((s.get("url", ""), k, v))
    if failed:
        lines.append(f"- {len(failed)} source(s) with error/fetch status:")
        for url, key, val in failed[:20]:
            lines.append(f"  - {url} — `{key}`={val}")
    else:
        lines.append(
            "- No error/fetch-status fields found on source records "
            f"(checked keys: {sorted(error_keys) or 'none matched'}. "
            "Source records currently have no error/status schema; "
            "blocked URLs (403/404/timeout) are not recorded in the graph.)"
        )
    lines.append("")
    return lines


def section_notability(scored: list[dict]) -> list[str]:
    """Section 5: Notability Assessment."""
    lines = ["## 5. Notability Assessment", ""]

    reliable = [s for s in scored if s["_srs"] >= 70]
    marginal = [s for s in scored if 50 <= s["_srs"] < 70]
    independent_reliable = [
        s for s in reliable if s["_breakdown"]["independence"] > 0
    ]
    independent_marginal = [
        s for s in marginal if s["_breakdown"]["independence"] > 0
    ]

    gng_pass = len(independent_reliable) >= 2
    lines.append(f"- **WP:GNG status:** {'PASS' if gng_pass else 'FAIL'}")
    lines.append(
        f"- Independent RELIABLE sources: {len(independent_reliable)} "
        f"(need >= 2 for WP:GNG)"
    )
    lines.append(f"- Independent MARGINAL sources: {len(independent_marginal)}")
    lines.append("")

    lines.append("### Top RELIABLE sources")
    lines.append("")
    if independent_reliable:
        lines.append("| # | Title | Domain | SRS | URL |")
        lines.append("|---|---|---|---|---|")
        for i, s in enumerate(independent_reliable, 1):
            title = (s.get("title", "") or "(untitled)")[:50]
            lines.append(
                f"| {i} | {title} | {s['_breakdown']['domain']} | "
                f"{s['_srs']} | {s.get('url', '')} |"
            )
    else:
        lines.append("*No independent RELIABLE sources found.*")
    lines.append("")
    return lines


def section_recommendations(
    canonical: dict,
    matches: list[dict],
    scored: list[dict],
    cached: dict[str, list[dict]],
    untried: list[str],
) -> list[str]:
    """Section 6: Recommendations."""
    lines = ["## 6. Recommendations", ""]
    label = canonical.get("label", "") if canonical else ""
    recs = []

    # Recommend untried search methods with example queries.
    if "duckduckgo" in untried:
        recs.append(
            f'Try DuckDuckGo search for "{label.lower()} aikido biography"'
        )
    if "brave" in untried:
        recs.append(
            f'Try Brave search for "{label.lower()} seminar interview"'
        )
    if "gemini_grounded" in untried:
        recs.append(
            f'Try Gemini grounded search for "{label.lower()} martial arts"'
        )
    if "arctic_shift" in untried:
        recs.append(
            f'Try Arctic Shift / Reddit search for "{label.lower()}"'
        )
    if "google_kg" in untried:
        recs.append(
            f'Run Google Knowledge Graph enrichment for "{label}" '
            "(34_enrich_person.py --google-kg)"
        )

    # Recommend fetching Wayback for blocked URLs (none recorded, but note it).
    recs.append(
        "Fetch Wayback Machine snapshots for any blocked URLs (403/404) — "
        "source records do not currently track fetch errors, so review the "
        "ingest logs manually."
    )

    # Sources needing source_class reclassification.
    unclassified = [s for s in scored if not s.get("source_class")]
    if unclassified:
        recs.append(
            f"{len(unclassified)} source(s) need source_class reclassification "
            f"(currently unclassified)."
        )

    # Notability gap.
    independent_reliable = [
        s for s in scored
        if s["_srs"] >= 70 and s["_breakdown"]["independence"] > 0
    ]
    if len(independent_reliable) < 2:
        recs.append(
            f"WP:GNG not met — only {len(independent_reliable)} independent "
            f"RELIABLE source(s). Seek additional independent secondary "
            f"journalistic coverage."
        )

    # Recommend running enrichment with dates/cities if gaps exist.
    no_dates = not any(s.get("publish_date") for s in scored)
    if no_dates:
        recs.append(
            "No sources have publish_date metadata. Consider running "
            "34_enrich_person.py with --dates to add date coverage."
        )
    recs.append(
        "Consider running 34_enrich_person.py with --dates and --cities "
        "to fill temporal and geographic coverage gaps."
    )

    for r in recs:
        lines.append(f"- {r}")
    lines.append("")
    return lines


def generate_report(
    search_term: str,
    nodes: list[dict],
    edges: list[dict],
    sources: list[dict],
    claim_sources: list[dict],
    cache: SearchCache,
    tranco: dict,
) -> str:
    """Generate the full enrichment report markdown body."""
    matches = find_matching_nodes(search_term, nodes)
    if not matches:
        return f"No nodes found matching '{search_term}'."

    canonical = select_canonical_person(matches)
    if not canonical:
        return f"No Person node found matching '{search_term}'."

    # Collect subgraph data.
    matched_sources = collect_subgraph_sources(
        canonical, matches, nodes, edges, sources, claim_sources,
    )
    claims = collect_claims_for_person(
        canonical, matches, nodes, edges, claim_sources,
    )
    key_edges = collect_key_edges(matches, edges)

    # Score sources.
    tiers = load_domain_tiers()
    scored = score_sources(
        matched_sources, canonical, edges, nodes, tranco, tiers,
    )

    # Check SearchCache for tried queries.
    name_variants = get_name_variants(canonical, matches)
    cached = query_cache_for_person(cache, name_variants)

    # Determine untried methods for recommendations.
    md = canonical.get("metadata", {}) or {}
    tried = set(cached.keys())
    if md.get("kg_enriched"):
        tried.add("google_kg")
    all_methods = [
        "google_kg", "gemini_grounded", "brave", "bing",
        "duckduckgo", "reference_discovery", "arctic_shift",
    ]
    untried = [m for m in all_methods if m not in tried]

    lines = []
    label = canonical.get("label", search_term)
    lines.append(f"# Enrichment Report: {label}")
    lines.append("")
    lines.append(
        f"Generated by `scripts/35_generate_github_report.py` for search term "
        f"`{search_term}` on {date.today().isoformat()}."
    )
    lines.append("")
    lines.append("---")
    lines.append("")

    lines.extend(
        section_person_summary(
            canonical, matches, nodes, edges, sources, claims,
            key_edges, matched_sources,
        )
    )
    lines.append("---")
    lines.append("")
    lines.extend(
        section_enrichment_methods(
            canonical, matches, cached, matched_sources, nodes, edges,
        )
    )
    lines.append("---")
    lines.append("")
    lines.extend(section_source_inventory(scored))
    lines.append("---")
    lines.append("")
    lines.extend(
        section_coverage_gaps(
            canonical, matches, scored, cached, nodes, edges,
        )
    )
    lines.append("---")
    lines.append("")
    lines.extend(section_notability(scored))
    lines.append("---")
    lines.append("")
    lines.extend(
        section_recommendations(canonical, matches, scored, cached, untried)
    )

    lines.append("---")
    lines.append("")
    lines.append("### How this was generated")
    lines.append("")
    lines.append(
        "1. Reads `graph_snapshot/` JSONL (committed, reviewable state)."
    )
    lines.append(
        "2. Checks `data/cache/search_cache.sqlite` (SearchCache) for tried "
        "search queries per provider."
    )
    lines.append(
        "3. Scores sources using the Source Reliability Score (SRS) reused "
        "from `scripts/32_generate_wikipedia_article.py`."
    )
    lines.append(
        "4. Collection logic reused from "
        "`scripts/19_generate_data_ticket.py`."
    )
    lines.append("")

    return "\n".join(lines)


def post_to_github(
    title: str, body: str, repo: str, labels: list[str] | None = None
) -> str:
    """Post the report body as a GitHub issue using the gh CLI."""
    cmd = ["gh", "issue", "create", "--repo", repo, "--title", title]
    for label in labels or []:
        cmd.extend(["--label", label])

    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".md", delete=False, prefix="report_"
    ) as f:
        f.write(body)
        tmp_path = f.name

    cmd.extend(["--body-file", tmp_path])
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        return result.stdout.strip()
    finally:
        Path(tmp_path).unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(
        description="Generate a structured enrichment report for a person."
    )
    parser.add_argument(
        "search_term",
        help="Person name to search for (e.g. 'robert nadeau')",
    )
    parser.add_argument(
        "--post",
        action="store_true",
        help="Post the report as a GitHub issue (requires gh CLI)",
    )
    parser.add_argument(
        "--repo",
        default="biofool/story_graph",
        help="GitHub repo to post to (default: biofool/story_graph)",
    )
    parser.add_argument(
        "--label",
        action="append",
        dest="labels",
        default=["enrichment-report"],
        help="GitHub label(s) to apply (default: enrichment-report; repeatable)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Write report to a specific file "
        "(default: docs/enrichment-reports/<slug>-<date>.md)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be posted without creating an issue",
    )
    parser.add_argument(
        "--tranco",
        type=Path,
        default=None,
        help="Path to Tranco top-1M CSV file (optional, for SRS scoring)",
    )
    parser.add_argument(
        "--snapshot-dir",
        type=Path,
        default=SNAPSHOT_DIR,
        help=f"Path to graph_snapshot/ dir (default: {SNAPSHOT_DIR})",
    )
    parser.add_argument(
        "--cache-path",
        type=Path,
        default=None,
        help="Path to search_cache.sqlite "
        "(default: from settings.search_cache_path)",
    )

    args = parser.parse_args()

    # Load snapshot.
    snapshot = args.snapshot_dir
    nodes = load_jsonl(snapshot / "nodes.jsonl")
    edges = load_jsonl(snapshot / "edges.jsonl")
    sources = load_jsonl(snapshot / "sources.jsonl")
    claim_sources = load_jsonl(snapshot / "claim_sources.jsonl")

    if not nodes:
        print(f"ERROR: No nodes found in {snapshot / 'nodes.jsonl'}", file=sys.stderr)
        sys.exit(1)

    # Open SearchCache.
    cache_path = args.cache_path
    if cache_path is None:
        cache_path = Path(settings.search_cache_path)
        if not cache_path.is_absolute():
            cache_path = PROJECT_ROOT / cache_path
    cache = SearchCache(cache_path, ttl_days=9999)  # ignore expiry for reporting

    # Load Tranco (optional).
    tranco = load_tranco(args.tranco) if args.tranco else {}

    # Generate the report body.
    body = generate_report(
        args.search_term, nodes, edges, sources, claim_sources, cache, tranco,
    )
    cache.close()

    # Determine output path.
    slug = slugify(args.search_term)
    today = date.today().isoformat()
    if args.output:
        out_path = args.output
    else:
        REPORTS_DIR.mkdir(parents=True, exist_ok=True)
        out_path = REPORTS_DIR / f"{slug}-{today}.md"

    title = f"Enrichment report: {args.search_term.title()}"

    if args.dry_run:
        # Show summary stats on stderr, full body on stdout.
        matches = find_matching_nodes(args.search_term, nodes)
        canonical = select_canonical_person(matches)
        print(f"Dry run for '{args.search_term}':", file=sys.stderr)
        print(f"  Matched nodes: {len(matches)}", file=sys.stderr)
        if canonical:
            print(f"  Canonical Person: {canonical['id']}", file=sys.stderr)
        print(f"  Body length: {len(body)} chars", file=sys.stderr)
        print(f"  Would write to: {out_path}", file=sys.stderr)
        if args.post:
            print(f"  Would post to: {args.repo} (labels: {args.labels})", file=sys.stderr)
        print("\n--- Preview (first 2000 chars) ---", file=sys.stderr)
        print(body[:2000], file=sys.stderr)
        print(body)
        return

    # Write to file.
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(body)
    print(f"Report written to {out_path}", file=sys.stderr)

    if args.post:
        print(f"Posting to GitHub: {args.repo} ...", file=sys.stderr)
        try:
            url = post_to_github(title, body, args.repo, args.labels)
            print(f"Created GitHub issue: {url}")
        except subprocess.CalledProcessError as e:
            print(f"ERROR posting to GitHub: {e.stderr}", file=sys.stderr)
            sys.exit(1)


if __name__ == "__main__":
    main()
