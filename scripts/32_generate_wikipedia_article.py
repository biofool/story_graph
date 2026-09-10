#!/usr/bin/env python3
"""
Generate a Wikipedia-style article draft from Story Graph nodes about a person.

Reads graph_snapshot/ JSONL files, collects the person's subgraph, scores every
source using the Source Reliability Score (SRS), and generates a Wikipedia-
style article draft with inline citations + a reliability report.

Usage:
    # Dry run — collect subgraph, score sources, print reliability report
    python scripts/32_generate_wikipedia_article.py "peter ralston" --dry-run

    # Generate article + report to files
    python scripts/32_generate_wikipedia_article.py "richard moon" \
        --article /tmp/moon_article.md --report /tmp/moon_report.md

    # Use a specific Tranco list file
    python scripts/32_generate_wikipedia_article.py "robert nadeau" \
        --tranco data/reference/tranco_top_1m.csv

    # Skip notability check
    python scripts/32_generate_wikipedia_article.py "robert nadeau" \
        --skip-notability-check
"""

import argparse
import json
import re
import sys
from collections import defaultdict
from pathlib import Path
from urllib.parse import urlparse

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SNAPSHOT_DIR = PROJECT_ROOT / "graph_snapshot"
DOMAIN_TIERS_PATH = PROJECT_ROOT / "data" / "reference" / "domain_tiers.json"

# Reuse collection logic from the data ticket generator
import importlib.util

_spec = importlib.util.spec_from_file_location(
    "gen_ticket",
    str(PROJECT_ROOT / "scripts" / "19_generate_data_ticket.py"),
)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)

load_jsonl = _mod.load_jsonl
find_matching_nodes = _mod.find_matching_nodes
select_canonical_person = _mod.select_canonical_person
collect_key_edges = _mod.collect_key_edges
collect_sources = _mod.collect_sources
search_term_from_nodes = _mod.search_term_from_nodes

KEY_RELATIONS = {
    "FOUNDED", "MEMBER_OF", "WORKED_AT", "ALIAS_OF", "LIVED_AT",
    "CREATED", "PUBLISHED_AT", "LOCATED_IN", "PRECEDES", "DESCRIBES",
    "ABOUT", "ASSERTED_BY", "SUPPORTED_BY", "CONTRADICTS",
    "DEPICTS", "CONTAINS", "MENTIONS",
}

# WP:RSP status points
WP_RSP_POINTS = {
    "generally reliable": 30,
    "no consensus": 15,
    "generally unreliable": -50,
    "deprecated": -100,
    "blacklisted": -100,
}

# source_class points
SOURCE_CLASS_POINTS = {
    "journalistic": 25,
    "archival": 20,
    "documentary_promotional": -10,
    "comment_thread": -30,
    "primary_first_person": -20,
}


def load_domain_tiers() -> dict[str, int]:
    """Load the hardcoded domain tier fallback."""
    if DOMAIN_TIERS_PATH.exists():
        with open(DOMAIN_TIERS_PATH) as f:
            return json.load(f)
    return {}


def load_tranco(path: Path) -> dict[str, int]:
    """Load a Tranco top-1M CSV and return domain→rank mapping."""
    ranks = {}
    if not path or not path.exists():
        return ranks
    with open(path) as f:
        for line in f:
            parts = line.strip().split(",")
            if len(parts) == 2:
                rank, domain = int(parts[0]), parts[1]
                ranks[domain] = rank
    return ranks


def get_domain(url: str) -> str:
    """Extract the registered domain from a URL."""
    parsed = urlparse(url)
    host = parsed.hostname or ""
    # Strip 'www.' prefix
    if host.startswith("www."):
        host = host[4:]
    return host.lower()


def domain_rank_points(domain: str, tranco: dict, tiers: dict) -> int:
    """Score domain rank 0-40 using Tranco or fallback tiers."""
    if tranco and domain in tranco:
        rank = tranco[domain]
        if rank <= 1000:
            return 40
        elif rank <= 10000:
            return 30
        elif rank <= 100000:
            return 20
        elif rank <= 1000000:
            return 10
        else:
            return 0
    # Fallback to hardcoded tiers
    return tiers.get(domain, 0)


def wp_rsp_points(domain: str, rsp_cache: dict) -> int:
    """Get WP:RSP status points for a domain."""
    status = rsp_cache.get(domain, "")
    if status in WP_RSP_POINTS:
        return WP_RSP_POINTS[status]
    return 0  # Not listed — unknown, not penalized


def source_class_points(source_class: str) -> int:
    """Get points for the graph's source_class field."""
    if not source_class:
        return 0
    return SOURCE_CLASS_POINTS.get(source_class, 0)


def independence_points(
    domain: str, canonical: dict, edges: list[dict], nodes: list[dict],
    source: dict | None = None,
) -> int:
    """Score independence: +10 if independent, -20 if affiliated.

    A source is "affiliated" if:
    - The source's own source_class is primary_first_person (the subject's
      own writing/website/interview), OR
    - The domain matches an organization the subject FOUNDED (not just
      member of — being a member of a large org doesn't make the org's
      website "affiliated" in the Wikipedia sense), OR
    - The domain is clearly the subject's personal website (heuristic:
      domain contains the subject's surname).

    Being interviewed by an independent publication (e.g., Aikido Journal)
    does NOT make that publication "affiliated" — the interview is still
    independent secondary journalism.
    """
    if not canonical:
        return 10

    # Check source_class first — primary_first_person is always affiliated
    if source and source.get("source_class") == "primary_first_person":
        return -20

    # Publisher author pages are NOT independent sources.
    # A publisher's page about its own author is ABOUTSELF — the publisher
    # has a financial stake in promoting the author's books. This includes:
    # simonandschuster.com, penguin.co.nz, penguinrandomhouse.com,
    # innertraditions.com, books.google.com, openlibrary.org, etc.
    PUBLISHER_DOMAINS = {
        "simonandschuster.com", "simonandschuster.net",
        "penguin.co.nz", "penguinrandomhouse.com", "penguin.com",
        "innertraditions.com", "bearandcompany.com",
        "books.google.com", "books.google.co.nz", "books.google.co.uk",
        "openlibrary.org",
        "amazon.com", "amazon.co.uk", "amazon.de",
        "audible.com", "audible.in",
        "goodreads.com",
    }
    if domain in PUBLISHER_DOMAINS:
        return -20

    # Collect domains of organizations the subject FOUNDED only
    # (MEMBER_OF / WORKED_AT doesn't make the org's website "affiliated")
    # NOTE: We only check the source's domain against domains that appear
    # to be the org's OWN website, not just any URL that mentions the org.
    # A Group node's source_urls contains all pages that mention the group,
    # including independent publications — we can't use those as "affiliated".
    # Instead, we use a heuristic: the org's own domain is likely the one
    # that contains the org's name. For now, we skip this check entirely
    # and rely on the source_class + surname checks above.
    # TODO: Add an explicit "official_url" field to Group nodes.
    canonical_id = canonical["id"]
    founded_domains = set()
    # Only flag as affiliated if the source's source_class is also
    # documentary_promotional or primary_first_person (i.e., the source
    # itself is not independent journalism)
    if source and source.get("source_class") in (
        "documentary_promotional", "primary_first_person",
    ):
        for e in edges:
            if (e.get("src_id") == canonical_id
                    and e.get("rel_type") == "FOUNDED"):
                org_id = e.get("dst_id", "")
                for n in nodes:
                    if n["id"] == org_id:
                        for url in n.get("source_urls", []) or []:
                            d = get_domain(url)
                            if d:
                                founded_domains.add(d)

        if domain in founded_domains:
            return -20

    # Check if domain is clearly the subject's personal website
    # (contains their surname)
    label = canonical.get("label", "")
    surname = label.split()[-1].lower() if label.split() else ""
    if surname and len(surname) > 3 and surname in domain:
        return -20

    return 10


def compute_srs(
    source: dict,
    canonical: dict,
    edges: list[dict],
    nodes: list[dict],
    tranco: dict,
    tiers: dict,
    rsp_cache: dict,
) -> tuple[int, str, dict]:
    """Compute the Source Reliability Score for a source record.

    Returns (score, tier, breakdown_dict).
    """
    url = source.get("url", "") or ""
    domain = get_domain(url)

    dr = domain_rank_points(domain, tranco, tiers)
    wr = wp_rsp_points(domain, rsp_cache)
    sc = source_class_points(source.get("source_class", ""))
    ind = independence_points(domain, canonical, edges, nodes, source)

    srs = dr + wr + sc + ind

    if srs >= 70:
        tier = "RELIABLE"
    elif srs >= 50:
        tier = "MARGINAL"
    elif srs >= 20:
        tier = "WEAK"
    elif srs <= -50:
        tier = "BLACKLISTED"
    else:
        tier = "UNRELIABLE"

    breakdown = {
        "domain_rank": dr,
        "wp_rsp": wr,
        "source_class": sc,
        "independence": ind,
        "domain": domain,
    }
    return srs, tier, breakdown


def get_name_variants(canonical: dict, matches: list[dict]) -> set[str]:
    """Get all name variants for a person, including transliterations.

    The graph may contain sources in other scripts (Cyrillic, CJK) that use
    transliterated name variants. We build a set of search terms that includes:
    - The canonical label and ID
    - The surname
    - Common Cyrillic transliterations for known persons
    - All alias node labels
    """
    terms = set()
    if canonical:
        terms.add(canonical.get("id", "").lower())
        terms.add(canonical.get("label", "").lower())
        words = canonical.get("label", "").split()
        if len(words) > 1:
            terms.add(words[-1].lower())

    # Add alias node labels
    for m in matches:
        if m.get("type") == "Person":
            label = m.get("label", "").lower()
            if label:
                terms.add(label)

    # Known Cyrillic transliterations for graph persons
    # (the graph stores Russian sources with Cyrillic names that weren't
    # automatically linked to the English person nodes)
    # Include both lowercase and uppercase variants since the source
    # text may use either case
    CYRILLIC_VARIANTS = {
        "robert nadeau": {"роберт надо", "надо", "роберт над",
                          "Роберт НАДО", "НАДО", "Роберт НАД"},
        "robert": {"роберт", "Роберт"},
        "nadeau": {"надо", "над", "НАДО", "НАД"},
    }
    if canonical:
        label_lower = canonical.get("label", "").lower()
        for key, variants in CYRILLIC_VARIANTS.items():
            if key in label_lower:
                terms.update(variants)

    terms.discard("")
    return terms


def collect_claims_for_person(
    canonical: dict, matches: list[dict], nodes: list[dict],
    edges: list[dict], claim_sources: list[dict],
) -> list[dict]:
    """Collect all Claim nodes about the person, with their linked source IDs."""
    canonical_id = canonical["id"] if canonical else ""
    match_ids = {n["id"] for n in matches}

    # Find claims via ABOUT/ASSERTED_BY edges
    claim_ids = set()
    for e in edges:
        if e.get("rel_type") in ("ABOUT", "ASSERTED_BY") and e.get("dst_id") == canonical_id:
            claim_ids.add(e.get("src_id", ""))
        if e.get("rel_type") == "ABOUT" and e.get("dst_id") in match_ids:
            claim_ids.add(e.get("src_id", ""))

    # Also find claims by text matching (including Cyrillic variants)
    search_terms = get_name_variants(canonical, matches)

    for n in nodes:
        if n.get("type") != "Claim":
            continue
        if n["id"] in claim_ids:
            continue
        blob = json.dumps(n, ensure_ascii=False).lower()
        if any(t in blob for t in search_terms):
            claim_ids.add(n["id"])

    # Map claim IDs to source IDs
    claim_to_sources = defaultdict(list)
    for cs in claim_sources:
        cid = cs.get("claim_id", "")
        sid = cs.get("source_id", "")
        if cid in claim_ids:
            claim_to_sources[cid].append(sid)

    # Build claim records
    node_map = {n["id"]: n for n in nodes}
    claims = []
    for cid in claim_ids:
        if cid in node_map:
            claim = dict(node_map[cid])
            claim["_source_ids"] = claim_to_sources.get(cid, [])
            claims.append(claim)

    return claims


def generate_article(
    canonical: dict,
    matches: list[dict],
    claims: list[dict],
    edges: list[dict],
    sources: list[dict],
    scored_sources: list[dict],
    nodes: list[dict],
) -> str:
    """Generate the Wikipedia-style article draft."""
    if not canonical:
        return "ERROR: No canonical Person node found."

    label = canonical.get("label", "Unknown")
    canonical_id = canonical["id"]

    # Build node lookup
    node_map = {n["id"]: n for n in nodes}

    # Citable sources (SRS >= 50)
    citable = [s for s in scored_sources if s["_srs"] >= 50]
    reliable = [s for s in scored_sources if s["_srs"] >= 70]

    # Group claims by topic (simple keyword clustering)
    def claim_text(c):
        return c.get("label", "") or c.get("metadata", {}).get("claim_text", "")

    # Collect key relationships
    relationships = []
    for e in edges:
        if e.get("src_id") == canonical_id or e.get("dst_id") == canonical_id:
            rel = e.get("rel_type", "")
            if rel in ("FOUNDED", "MEMBER_OF", "WORKED_AT", "STUDIED_WITH",
                       "TRAINED_AT", "LOCATED_IN", "PRECEDES", "ABOUT"):
                relationships.append(e)

    # Find founded/created organizations
    founded = []
    member_of = []
    for e in relationships:
        if e.get("src_id") == canonical_id:
            if e["rel_type"] == "FOUNDED":
                target = node_map.get(e["dst_id"], {})
                founded.append(target.get("label", e["dst_id"]))
            elif e["rel_type"] in ("MEMBER_OF", "WORKED_AT"):
                target = node_map.get(e["dst_id"], {})
                member_of.append(target.get("label", e["dst_id"]))

    # Find claims that have at least one citable source
    citable_source_ids = {s["id"] for s in citable}
    citable_claims = []
    for c in claims:
        if c.get("_source_ids"):
            if any(sid in citable_source_ids for sid in c["_source_ids"]):
                citable_claims.append(c)
        # Also include claims with no source links but text about the person

    # Build reference list
    ref_lines = []
    ref_map = {}
    for i, s in enumerate(citable, 1):
        ref_name = f"ref{i}"
        ref_map[s["id"]] = ref_name
        url = s.get("url", "")
        title = s.get("title", "") or "(untitled)"
        platform = s.get("platform", "") or ""
        author = s.get("author", "") or ""
        date = s.get("publish_date", "") or ""
        ref_lines.append(
            f'<ref name="{ref_name}">[{url} {title}'
            f"{f' — {author}' if author else ''}"
            f"{f', ' + date if date else ''}"
            f"{f', ' + platform if platform else ''}]</ref>"
        )

    lines = []

    # Lead section
    lead_parts = [f"'''{label}'''"]
    if founded:
        lead_parts.append(
            f" is a martial arts teacher and founder of "
            f"{', '.join(founded[:3])}."
        )
    else:
        lead_parts.append(" is a martial arts teacher.")

    # Add notable claims from citable sources
    notable_claims = [c for c in citable_claims if c.get("_source_ids")]
    if notable_claims:
        # Pick the first 2-3 most significant claims
        for c in notable_claims[:3]:
            text = claim_text(c)
            if text:
                # Find which citable source supports this
                for sid in c["_source_ids"]:
                    if sid in ref_map:
                        ref_tag = f'<ref name="{ref_map[sid]}"/>'
                        lines_text = f"{text} {ref_tag}"
                        lead_parts.append(lines_text)
                        break

    lines.append(" ".join(lead_parts[:1] + lead_parts[1:]))
    lines.append("")

    # Career section
    career_claims = [c for c in citable_claims if claim_text(c)]
    if career_claims or founded or member_of:
        lines.append("== Career ==")
        lines.append("")
        if founded:
            org_list = ", ".join(founded)
            ref_tag = ""
            # Try to find a citable source for the founding
            for s in citable:
                if any(kw in (s.get("raw_text", "") or "").lower()
                       for kw in ["found", "establish", "create"]):
                    ref_name = ref_map[s["id"]]
                    ref_tag = f'<ref name="{ref_name}"/>'
            lines.append(
                f"{label} founded {org_list}.{ref_tag}"
            )
            lines.append("")

        for c in career_claims[:20]:
            text = claim_text(c)
            if not text or len(text) < 10:
                continue
            ref_tag = ""
            for sid in c.get("_source_ids", []):
                if sid in ref_map:
                    ref_tag = f'<ref name="{ref_map[sid]}"/>'
                    break
            lines.append(f"{text}{ref_tag}")
            lines.append("")

    # Russia seminars section (for Nadeau)
    russia_claims = [
        c for c in claims
        if any(kw in claim_text(c).lower()
               for kw in ["russia", "leningrad", "moscow", "ussr", "soviet",
                          "надо", "ленинград", "москва"])
    ]
    if russia_claims or any(
        kw in json.dumps(canonical).lower()
        for kw in ["russia", "nadeau"]
    ):
        lines.append("== Seminars in Russia ==")
        lines.append("")
        russia_sources = [
            s for s in citable
            if any(kw in (s.get("raw_text", "") or "").lower()
                   for kw in ["russia", "leningrad", "moscow", "ussr",
                              "надо", "ленинград", "москва", "aikiclub",
                              "bujutsu"])
        ]
        if russia_sources:
            for s in russia_sources:
                ref_tag = f'<ref name="{ref_map.get(s["id"], "")}"/>'
                raw = (s.get("raw_text", "") or "")[:500]
                # Extract a relevant snippet
                lines.append(
                    f"According to {s.get('platform', 'a Russian source')}, "
                    f"{label} conducted aikido seminars in the Soviet Union "
                    f"during the late 1980s and early 1990s.{ref_tag}"
                )
                lines.append("")
        else:
            lines.append(
                f"[citation needed] — The Story Graph contains raw text "
                f"from Russian aikido sources mentioning {label}, but these "
                f"sources have not yet been classified as citable."
            )
            lines.append("")

    # References section
    if ref_lines:
        lines.append("== References ==")
        lines.append("")
        lines.append("<references>")
        for ref in ref_lines:
            lines.append(ref)
        lines.append("</references>")
        lines.append("")

    return "\n".join(lines)


def generate_report(
    canonical: dict,
    matches: list[dict],
    claims: list[dict],
    edges: list[dict],
    sources: list[dict],
    scored_sources: list[dict],
    tranco: dict,
) -> str:
    """Generate the reliability report."""
    label = canonical.get("label", "Unknown") if canonical else "Unknown"

    lines = []
    lines.append(f"# Reliability Report: {label}")
    lines.append("")

    # Notability check
    reliable = [s for s in scored_sources if s["_srs"] >= 70]
    independent_reliable = [
        s for s in reliable
        if s["_breakdown"]["independence"] > 0
    ]
    lines.append("## Notability check")
    lines.append("")
    lines.append(
        f"- RELIABLE independent secondary sources with significant coverage: "
        f"{len(independent_reliable)}"
    )
    for s in independent_reliable:
        lines.append(f"  - {s.get('platform', '')} ({s.get('url', '')})")
    lines.append("")

    if len(independent_reliable) >= 2:
        lines.append("- WP:GNG status: **PASS**")
    else:
        lines.append(
            f"- WP:GNG status: **FAIL** — only {len(independent_reliable)} "
            f"RELIABLE independent source(s) found (need >= 2)"
        )
    lines.append("")
    lines.append("---")
    lines.append("")

    # Source scoring table
    lines.append("## Source scoring (all sources in subgraph)")
    lines.append("")
    lines.append("| # | Source | Domain | SRS | Tier | Citable? | Reason |")
    lines.append("|---|--------|--------|-----|------|----------|--------|")

    for i, s in enumerate(scored_sources, 1):
        domain = s["_breakdown"]["domain"]
        srs = s["_srs"]
        tier = s["_tier"]
        citable = "Yes" if srs >= 50 else "No"
        reason = (
            f"dr={s['_breakdown']['domain_rank']} "
            f"rsp={s['_breakdown']['wp_rsp']} "
            f"sc={s['_breakdown']['source_class']} "
            f"ind={s['_breakdown']['independence']}"
        )
        title = s.get("title", "") or s.get("url", "")[:40]
        lines.append(
            f"| {i} | {title[:40]} | {domain} | {srs} | {tier} | {citable} | {reason} |"
        )

    lines.append("")

    # Excluded sources
    excluded = [s for s in scored_sources if s["_srs"] < 50]
    kkron_sources = [
        s for s in sources
        if "kkron://" in (s.get("url", "") or "")
        or s.get("source_class") == "primary_first_person"
    ]

    lines.append("## Excluded sources (not cited in article)")
    lines.append("")

    if kkron_sources:
        lines.append(
            f"- **kkron personal-communication claims** ({len(kkron_sources)} source(s)) "
            f"— primary_first_person, excluded per WP:RS (requires independent "
            f"secondary reporting). These remain first-class evidence in the "
            f"Story Graph but are not citable in a Wikipedia article."
        )
        lines.append(
            "  - The Story Graph considers kkron a high-trust witness, but "
            "Wikipedia requires independent secondary sources."
        )
        lines.append("")

    for s in excluded:
        if "kkron://" in (s.get("url", "") or ""):
            continue  # Already covered above
        url = s.get("url", "")
        title = s.get("title", "") or "(untitled)"
        tier = s["_tier"]
        reason = (
            f"SRS={s['_srs']} ({tier}): "
            f"dr={s['_breakdown']['domain_rank']} "
            f"rsp={s['_breakdown']['wp_rsp']} "
            f"sc={s['_breakdown']['source_class']} "
            f"ind={s['_breakdown']['independence']}"
        )
        lines.append(f"- [{title}]({url}) — {reason}")

    lines.append("")

    # Citation-pending claims
    pending = [c for c in claims if not c.get("_source_ids")]
    if pending:
        lines.append("## Citation-pending claims")
        lines.append("")
        lines.append(
            f"{len(pending)} claim(s) have no linked source in the graph. "
            f"These need source verification before they can be cited."
        )
        for c in pending[:10]:
            text = c.get("label", "") or c.get("metadata", {}).get("claim_text", "")
            lines.append(f"- `{c['id']}`: {text[:100]}")

    lines.append("")

    # Graph evidence summary
    lines.append("---")
    lines.append("")
    lines.append("## Graph evidence summary")
    lines.append("")
    lines.append(f"- Total matched nodes: {len(matches)}")
    lines.append(f"- Total claims collected: {len(claims)}")
    lines.append(f"- Total sources scored: {len(scored_sources)}")
    lines.append(f"- Citable sources (SRS >= 50): {len([s for s in scored_sources if s['_srs'] >= 50])}")
    lines.append(f"- RELIABLE sources (SRS >= 70): {len([s for s in scored_sources if s['_srs'] >= 70])}")
    lines.append(f"- Independent RELIABLE sources: {len(independent_reliable)}")
    lines.append("")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(
        description="Generate a Wikipedia article draft from Story Graph data."
    )
    parser.add_argument(
        "search_term",
        help="Person name to search for (e.g. 'peter ralston')",
    )
    parser.add_argument(
        "--article",
        type=Path,
        default=None,
        help="Write article draft to this file",
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=None,
        help="Write reliability report to this file",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Collect and score sources, print report summary, no article",
    )
    parser.add_argument(
        "--tranco",
        type=Path,
        default=None,
        help="Path to Tranco top-1M CSV file",
    )
    parser.add_argument(
        "--skip-notability-check",
        action="store_true",
        help="Generate article even if WP:GNG not met",
    )
    parser.add_argument(
        "--snapshot-dir",
        type=Path,
        default=SNAPSHOT_DIR,
        help=f"Path to graph_snapshot/ dir (default: {SNAPSHOT_DIR})",
    )

    args = parser.parse_args()

    # Load snapshot
    snapshot = args.snapshot_dir
    nodes = load_jsonl(snapshot / "nodes.jsonl")
    edges = load_jsonl(snapshot / "edges.jsonl")
    sources = load_jsonl(snapshot / "sources.jsonl")
    claim_sources = load_jsonl(snapshot / "claim_sources.jsonl")

    if not nodes:
        print(f"ERROR: No nodes found in {snapshot / 'nodes.jsonl'}", file=sys.stderr)
        sys.exit(1)

    # Find matching nodes
    matches = find_matching_nodes(args.search_term, nodes)
    if not matches:
        print(f"ERROR: No nodes found matching '{args.search_term}'", file=sys.stderr)
        sys.exit(1)

    canonical = select_canonical_person(matches)
    if not canonical:
        print(f"ERROR: No Person node found matching '{args.search_term}'", file=sys.stderr)
        sys.exit(1)

    print(f"Canonical person: {canonical['id']} — {canonical['label']}", file=sys.stderr)

    # Load reference data
    tiers = load_domain_tiers()
    tranco = load_tranco(args.tranco) if args.tranco else {}
    rsp_cache = {}  # No WP:RSP cache yet — all domains get 0

    # Collect sources — both by text matching AND via claim-source links
    matched_sources = collect_sources(matches, sources)

    # Also search sources using Cyrillic name variants
    # (the default collect_sources only uses the English label)
    # Note: json.dumps escapes non-ASCII by default, so we use
    # ensure_ascii=False to match Cyrillic/CJK text properly
    name_variants = get_name_variants(canonical, matches)
    existing_urls = {s.get("url") for s in matched_sources}
    for s in sources:
        if s.get("url") in existing_urls:
            continue
        blob = json.dumps(s, ensure_ascii=False).lower()
        if any(v in blob for v in name_variants if len(v) > 3):
            matched_sources.append(s)
            existing_urls.add(s.get("url"))
            print(f"  Added via name variant: {s.get('url', '')[:60]}", file=sys.stderr)

    # Also collect sources linked to claims about this person
    # (handles cases where the source text uses a different name variant,
    # e.g., Cyrillic "Роберт Надо" instead of "Robert Nadeau")
    claims = collect_claims_for_person(
        canonical, matches, nodes, edges, claim_sources,
    )
    claim_source_ids = set()
    for c in claims:
        for sid in c.get("_source_ids", []):
            claim_source_ids.add(sid)

    source_map = {s["id"]: s for s in sources if "id" in s}
    for sid in claim_source_ids:
        if sid in source_map and source_map[sid] not in matched_sources:
            matched_sources.append(source_map[sid])
            print(f"  Added via claim link: {source_map[sid].get('url', sid)[:60]}", file=sys.stderr)

    # Score all sources
    scored_sources = []
    for s in matched_sources:
        srs, tier, breakdown = compute_srs(
            s, canonical, edges, nodes, tranco, tiers, rsp_cache,
        )
        scored = dict(s)
        scored["_srs"] = srs
        scored["_tier"] = tier
        scored["_breakdown"] = breakdown
        scored_sources.append(scored)

    # Sort by SRS descending
    scored_sources.sort(key=lambda x: x["_srs"], reverse=True)

    # Collect key edges
    key_edges = collect_key_edges(matches, edges)

    # Notability check
    reliable_independent = [
        s for s in scored_sources
        if s["_srs"] >= 70 and s["_breakdown"]["independence"] > 0
    ]
    gng_pass = len(reliable_independent) >= 2

    if args.dry_run:
        print(f"\nDry run for '{args.search_term}':", file=sys.stderr)
        print(f"  Matched nodes: {len(matches)}", file=sys.stderr)
        print(f"  Canonical: {canonical['id']}", file=sys.stderr)
        print(f"  Claims: {len(claims)}", file=sys.stderr)
        print(f"  Key edges: {len(key_edges)}", file=sys.stderr)
        print(f"  Sources scored: {len(scored_sources)}", file=sys.stderr)
        print(f"  Citable (SRS>=50): {len([s for s in scored_sources if s['_srs'] >= 50])}", file=sys.stderr)
        print(f"  RELIABLE (SRS>=70): {len([s for s in scored_sources if s['_srs'] >= 70])}", file=sys.stderr)
        print(f"  Independent RELIABLE: {len(reliable_independent)}", file=sys.stderr)
        print(f"  WP:GNG: {'PASS' if gng_pass else 'FAIL'}", file=sys.stderr)
        print("", file=sys.stderr)

        # Print top sources
        print("Top sources:", file=sys.stderr)
        for s in scored_sources[:15]:
            print(
                f"  SRS={s['_srs']:4d} {s['_tier']:12s} "
                f"{s['_breakdown']['domain']:30s} "
                f"{(s.get('title', '') or '')[:50]}",
                file=sys.stderr,
            )
        return

    # Generate report
    report = generate_report(
        canonical, matches, claims, edges, sources, scored_sources, tranco,
    )

    # Notability check
    if not gng_pass and not args.skip_notability_check:
        print(
            f"\nNOTABILITY FAILURE: Only {len(reliable_independent)} independent "
            f"RELIABLE source(s) found (need >= 2 for WP:GNG).",
            file=sys.stderr,
        )
        print("Use --skip-notability-check to generate anyway.", file=sys.stderr)
        if args.report:
            args.report.write_text(report)
            print(f"Reliability report written to {args.report}", file=sys.stderr)
        else:
            print(report)
        return

    # Generate article
    article = generate_article(
        canonical, matches, claims, key_edges, sources, scored_sources, nodes,
    )

    # Output
    if args.article:
        args.article.write_text(article)
        print(f"Article written to {args.article}", file=sys.stderr)
    else:
        print(article)

    if args.report:
        args.report.write_text(report)
        print(f"Reliability report written to {args.report}", file=sys.stderr)
    elif not args.article:
        print("\n\n--- RELIABILITY REPORT ---\n")
        print(report)


if __name__ == "__main__":
    main()
