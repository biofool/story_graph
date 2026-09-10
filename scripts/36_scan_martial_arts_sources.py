#!/usr/bin/env python3
"""
Scan all graph sources and rate them for reliability in movement arts
and martial arts contexts.

Produces a comprehensive report classifying every source domain in the
graph by:
- SRS tier (RELIABLE / MARGINAL / WEAK / UNRELIABLE / BLACKLISTED)
- Martial arts reliability category (per SKILL.md guidance)
- Source class (journalistic / archival / primary / promotional / comment)
- Independence (independent vs affiliated vs publisher)
- Recommended usage for Wikipedia martial arts biographies

Usage:
    python scripts/36_scan_martial_arts_sources.py
    python scripts/36_scan_martial_arts_sources.py -o docs/martial-arts-source-scan.md
"""

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path
from urllib.parse import urlparse

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SNAPSHOT_DIR = PROJECT_ROOT / "graph_snapshot"
DOMAIN_TIERS_PATH = PROJECT_ROOT / "data" / "reference" / "domain_tiers.json"

# Martial arts source categories per SKILL.md
MA_HIGH_AUTHORITY = {
    # Long-running edited publications with in-depth coverage
    "aikidojournal.com": "Aikido Journal — long-running edited publication, authoritative on aikido history",
    "blackbeltmag.com": "Black Belt Magazine — legacy martial arts magazine with editorial oversight",
    "karateillustrated.com": "Karate Illustrated — legacy martial arts magazine",
    "taichiunion.com": "Tai Chi Union for Great Britain — union journal with editorial oversight",
    "tqj.de": "Tai Chi Chuan Journal (TQJ) — German tai chi magazine with editorial oversight",
    # National/regional association publications
    "chenghsin.nl": "Cheng Hsin Netherlands — Dutch branch org (affiliated, not independent)",
}

MA_MID_TIER = {
    "usadojo.com": "USAdojo — independent dojo directory and article site",
    "budovideos.com": "Budovideos — martial arts retailer with some editorial content",
    "aikido-health.com": "Aikido Health — aikido information site, commentary",
    "thetaichinotebook.com": "Tai Chi Notebook — commentary blog on internal arts",
    "whistlekickmartialartsradio.com": "Whistlekick Martial Arts Radio — podcast, commentary",
}

MA_AFFILIATED = {
    "chenghsin.com": "Peter Ralston's own website (ABOUTSELF)",
    "nadeaushihan.com": "Robert Nadeau's own website (ABOUTSELF)",
    "moonsic.com": "Richard Moon's own website (ABOUTSELF)",
    "moonsensei.com": "Richard Moon's own website (ABOUTSELF)",
    "openmindadventures.com": "Richard Moon's business website (ABOUTSELF)",
    "quantumaikido.com": "Richard Moon's business website (ABOUTSELF)",
    "quantumedge.org": "Richard Moon's business website (ABOUTSELF)",
    "ai-ki-do.org": "California Aikido Association — organizational",
    "cityaikido.com": "City Aikido SF — dojo organizational",
    "aikidoofpetaluma.com": "Aikido of Petaluma — dojo organizational",
    "aikido.org.nz": "Aikido NZ — organizational",
    "aikiclub.ru": "Moscow Aiki Club — organizational",
    "bujutsu.ru": "Bujutsu.ru — Russian martial arts org",
    "rebenok-na-aikido.ru": "Children's Aikido school Kazan — organizational",
}

# Publisher / bookseller domains — NOT independent for author biographies
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

# Wiki mirrors / encyclopedic aggregators — generally unreliable
WIKI_MIRRORS = {
    "wikitia.com", "alchetron.com", "grokipedia.com",
    "wikidata.org",
}

# Self-published / blog platforms
SELF_PUBLISHED = {
    "blogspot.com", "blogspot.in", "blogger.com",
    "wixsite.com", "wordpress.com", "wordpress.org",
    "medium.com", "substack.com",
    "kitothecity.substack.com",
}


def get_domain(url: str) -> str:
    parsed = urlparse(url)
    host = parsed.hostname or ""
    if host.startswith("www."):
        host = host[4:]
    return host.lower()


def classify_ma_reliability(domain: str, source_class: str) -> tuple[str, str]:
    """Classify a domain for martial arts reliability.

    Returns (category, explanation).
    """
    if domain in MA_HIGH_AUTHORITY:
        if "affiliated" in MA_HIGH_AUTHORITY[domain].lower():
            return "AFFILIATED_AUTHORITY", MA_HIGH_AUTHORITY[domain]
        return "HIGH_AUTHORITY", MA_HIGH_AUTHORITY[domain]

    if domain in MA_MID_TIER:
        return "MID_TIER", MA_MID_TIER[domain]

    if domain in MA_AFFILIATED:
        return "AFFILIATED", MA_AFFILIATED[domain]

    if domain in PUBLISHER_DOMAINS:
        return "PUBLISHER", "Publisher/bookseller page — not independent for author biographies"

    if domain in WIKI_MIRRORS:
        return "WIKI_MIRROR", "Wiki mirror/aggregator — generally unreliable"

    if domain in SELF_PUBLISHED:
        return "SELF_PUBLISHED", "Self-published platform — no editorial oversight"

    if domain in ("en.wikipedia.org", "wikipedia.org"):
        return "ENCYCLOPEDIA", "Wikipedia — tertiary source, use for verification not citation"

    if domain in ("reddit.com",):
        return "COMMENT_THREAD", "Reddit — comment thread, no editorial oversight"

    if domain in ("youtube.com",):
        return "VIDEO_PLATFORM", "YouTube — user-generated content, no editorial oversight"

    if domain in ("facebook.com", "twitter.com", "instagram.com"):
        return "SOCIAL_MEDIA", "Social media — user-generated, no editorial oversight"

    if source_class == "primary_first_person":
        return "PRIMARY", "First-person account — not independent secondary"

    if source_class == "comment_thread":
        return "COMMENT_THREAD", "Comment thread — no editorial oversight"

    if source_class == "documentary_promotional":
        return "PROMOTIONAL", "Promotional material — not independent"

    if source_class == "archival":
        return "ARCHIVAL", "Archival/historical record"

    # Default: unknown
    return "UNKNOWN", "Unclassified — needs manual review"


def load_domain_tiers() -> dict[str, int]:
    if DOMAIN_TIERS_PATH.exists():
        with open(DOMAIN_TIERS_PATH) as f:
            return json.load(f)
    return {}


def main():
    parser = argparse.ArgumentParser(
        description="Scan all graph sources for martial arts reliability."
    )
    parser.add_argument(
        "-o", "--output",
        type=Path,
        default=Path(PROJECT_ROOT / "docs" / "martial-arts-source-scan.md"),
        help="Write report to this file",
    )
    args = parser.parse_args()

    # Load sources
    sources = []
    with open(SNAPSHOT_DIR / "sources.jsonl") as f:
        for line in f:
            sources.append(json.loads(line))

    tiers = load_domain_tiers()

    # Group by domain
    domain_sources = defaultdict(list)
    for s in sources:
        url = s.get("url", "") or ""
        domain = get_domain(url)
        domain_sources[domain].append(s)

    # Classify each domain
    domain_ratings = []
    for domain, srcs in sorted(domain_sources.items(), key=lambda x: -len(x[1])):
        source_class = srcs[0].get("source_class", "")
        category, explanation = classify_ma_reliability(domain, source_class)
        domain_tier = tiers.get(domain, 0)
        domain_ratings.append({
            "domain": domain,
            "count": len(srcs),
            "source_class": source_class,
            "category": category,
            "explanation": explanation,
            "domain_tier": domain_tier,
        })

    # Build report
    lines = []
    lines.append("# Martial Arts Source Reliability Scan")
    lines.append("")
    lines.append(f"Scanned **{len(sources)}** sources across **{len(domain_sources)}** unique domains.")
    lines.append("")
    lines.append("Classification follows the Wikipedia Article Generator SKILL.md guidance")
    lines.append("for martial arts / movement arts biographies.")
    lines.append("")

    # Summary by category
    lines.append("## Summary by category")
    lines.append("")
    lines.append("| Category | Domains | Sources | Citable for MA bio? |")
    lines.append("|----------|---------|---------|---------------------|")
    cat_counts = defaultdict(lambda: {"domains": 0, "sources": 0})
    for r in domain_ratings:
        cat_counts[r["category"]]["domains"] += 1
        cat_counts[r["category"]]["sources"] += r["count"]

    citable_map = {
        "HIGH_AUTHORITY": "Yes — primary driver of notability",
        "MID_TIER": "Yes — supporting evidence only",
        "AFFILIATED_AUTHORITY": "No — affiliated, use cautiously",
        "AFFILIATED": "No — primary/ABOUTSELF",
        "PUBLISHER": "No — not independent for author bios",
        "WIKI_MIRROR": "No — unreliable",
        "SELF_PUBLISHED": "No — no editorial oversight",
        "PRIMARY": "No — first-person",
        "COMMENT_THREAD": "No — no editorial oversight",
        "VIDEO_PLATFORM": "No — user-generated",
        "SOCIAL_MEDIA": "No — user-generated",
        "ENCYCLOPEDIA": "No — tertiary source",
        "ARCHIVAL": "Yes — historical record",
        "PROMOTIONAL": "No — promotional",
        "UNKNOWN": "Needs review",
    }

    for cat in sorted(cat_counts.keys()):
        counts = cat_counts[cat]
        citable = citable_map.get(cat, "Needs review")
        lines.append(f"| {cat} | {counts['domains']} | {counts['sources']} | {citable} |")
    lines.append("")

    # Detailed domain table
    lines.append("## Domain ratings (sorted by source count)")
    lines.append("")
    lines.append("| Domain | Count | Source Class | MA Category | Domain Tier | Citable? | Explanation |")
    lines.append("|--------|-------|-------------|-------------|-------------|----------|-------------|")

    for r in domain_ratings:
        citable = citable_map.get(r["category"], "Needs review")
        lines.append(
            f"| {r['domain']} | {r['count']} | {r['source_class'] or '(null)'} | "
            f"{r['category']} | {r['domain_tier']} | {citable} | {r['explanation']} |"
        )
    lines.append("")

    # High-authority sources found in graph
    lines.append("## High-authority martial arts sources in graph")
    lines.append("")
    high_auth = [r for r in domain_ratings if r["category"] == "HIGH_AUTHORITY"]
    if high_auth:
        for r in high_auth:
            lines.append(f"- **{r['domain']}** ({r['count']} sources) — {r['explanation']}")
    else:
        lines.append("*No high-authority martial arts sources found.*")
    lines.append("")

    # Mid-tier sources
    lines.append("## Mid-tier martial arts sources in graph")
    lines.append("")
    mid_tier = [r for r in domain_ratings if r["category"] == "MID_TIER"]
    if mid_tier:
        for r in mid_tier:
            lines.append(f"- **{r['domain']}** ({r['count']} sources) — {r['explanation']}")
    else:
        lines.append("*No mid-tier martial arts sources found.*")
    lines.append("")

    # Affiliated sources
    lines.append("## Affiliated / primary sources (NOT independent)")
    lines.append("")
    affiliated = [r for r in domain_ratings if r["category"] in ("AFFILIATED", "AFFILIATED_AUTHORITY", "PRIMARY", "PUBLISHER")]
    if affiliated:
        for r in affiliated:
            lines.append(f"- **{r['domain']}** ({r['count']} sources) — {r['explanation']}")
    lines.append("")

    # Unreliable sources
    lines.append("## Unreliable sources (wiki mirrors, self-published, social media)")
    lines.append("")
    unreliable = [r for r in domain_ratings if r["category"] in ("WIKI_MIRROR", "SELF_PUBLISHED", "COMMENT_THREAD", "VIDEO_PLATFORM", "SOCIAL_MEDIA")]
    if unreliable:
        for r in unreliable:
            lines.append(f"- **{r['domain']}** ({r['count']} sources) — {r['explanation']}")
    lines.append("")

    # Recommendations
    lines.append("## Recommendations")
    lines.append("")
    lines.append("1. **Publisher pages must NOT be treated as independent sources** — "
                 "simonandschuster.com, penguin.co.nz, innertraditions.com, etc. are "
                 "ABOUTSELF. A publisher has a financial stake in promoting its authors.")
    lines.append("")
    lines.append("2. **Aikido Journal** (aikidojournal.com) is the strongest independent "
                 "secondary source for aikido biographies — treat as RELIABLE.")
    lines.append("")
    lines.append("3. **Taijivizier / STN** (Dutch Tai Chi Association) and **TQJ** "
                 "(Tai Chi Chuan Journal, Germany) are independent editorially-overseen "
                 "martial arts publications — treat as RELIABLE for tai chi / internal arts.")
    lines.append("")
    lines.append("4. **Black Belt Magazine** and other legacy martial arts magazines "
                 "should be sought as sources — they are not yet in the graph but would "
                 "strengthen notability for tournament results (e.g., Ralston's 1978 "
                 "world championship).")
    lines.append("")
    lines.append("5. **USAdojo** is mid-tier — useful for corroborating biographical "
                 "facts and tournament results, but should not by itself establish "
                 "notability.")
    lines.append("")
    lines.append("6. **Dojo/organizational websites** (cityaikido.com, ai-ki-do.org, "
                 "aikidoofpetaluma.com, etc.) are affiliated — treat as primary, not "
                 "independent secondary.")
    lines.append("")
    lines.append("7. **Wiki mirrors** (wikitia.com, alchetron.com, grokipedia.com) are "
                 "unreliable — never cite.")
    lines.append("")

    # Write report
    report = "\n".join(lines)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(report)
    print(f"Report written to {args.output}", file=sys.stderr)
    print(f"  {len(sources)} sources, {len(domain_sources)} domains", file=sys.stderr)
    print(f"  {len(high_auth)} high-authority, {len(mid_tier)} mid-tier, {len(affiliated)} affiliated, {len(unreliable)} unreliable", file=sys.stderr)


if __name__ == "__main__":
    main()
