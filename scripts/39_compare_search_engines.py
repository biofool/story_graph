#!/usr/bin/env python3
"""
Compare Brave vs Bing vs DuckDuckGo for a small set of key enrichment
queries. Tests only the most important queries for finding magazine sources.

Usage:
    python scripts/39_compare_search_engines.py "peter ralston" --context "cheng hsin"
    python scripts/39_compare_search_engines.py "robert nadeau" --context "aikido" --cities "moscow"
    python scripts/39_compare_search_engines.py "richard moon" --context "aikido"
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from urllib.parse import urlparse

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from config.settings import settings
from src.search.bing_search_client import BingSearchClient
from src.search.brave_search_client import BraveSearchClient
from src.search.duckduckgo_search_client import DuckDuckGoSearchClient

# Key domains we care about for magazine discovery
MAGAZINE_DOMAINS = {
    "books.google.com", "books.google.co.nz", "books.google.co.uk",
    "doczz.net", "archive.org", "scribd.com",
    "wikitia.com", "en-academic.com",
    "blackbeltmag.com", "aikidojournal.com", "blitzmag.com.au",
    "tqj.de", "karateillustrated.com",
}

# Russian/organizational domains for Nadeau
NADEAU_DOMAINS = {
    "aikiclub.ru", "lenkai.spb.ru", "bujutsu.ru", "aikido.ru",
    "kannagara-aikido.ru", "bigrock-aikikai.com", "aikido.org.nz",
    "cityaikido.com",
}


def is_relevant(url: str, person_name: str) -> str:
    """Categorize a URL as magazine-relevant, person-relevant, or other."""
    domain = urlparse(url).netloc.replace("www.", "")
    if domain in MAGAZINE_DOMAINS or any(d in url for d in MAGAZINE_DOMAINS):
        return "magazine"
    if "nadeau" in person_name.lower() and any(d in url for d in NADEAU_DOMAINS):
        return "organizational"
    return "other"


def run_engine(client, queries: list[str], label: str) -> dict:
    """Run queries through one search engine."""
    all_results: list[dict] = []
    seen_urls: set[str] = set()
    errors = 0

    for q in queries:
        try:
            hits = client.search(q, count=5)
            for h in hits:
                if h.url and h.url not in seen_urls:
                    seen_urls.add(h.url)
                    all_results.append({
                        "url": h.url,
                        "title": (h.title or "")[:80],
                        "query": q[:60],
                    })
        except Exception as e:
            errors += 1
            if errors <= 3:
                print(f"  [{label}] error: {e}")

    return {
        "label": label,
        "total": len(all_results),
        "errors": errors,
        "results": all_results,
    }


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Compare search engines (key queries only)")
    p.add_argument("name", help="Person name")
    p.add_argument("--dates", default="", help="Comma-separated dates")
    p.add_argument("--cities", default="", help="Comma-separated cities")
    p.add_argument("--context", default="martial arts", help="Context word")
    args = p.parse_args(argv)

    dates = [d.strip() for d in args.dates.split(",") if d.strip()]
    cities = [c.strip() for c in args.cities.split(",") if c.strip()]
    name = args.name
    style = args.context

    # Build a focused set of key queries (not all 60+)
    queries: list[str] = []
    seen: set[str] = set()

    def _add(q: str) -> None:
        q = " ".join(q.split())
        if q and q not in seen:
            seen.add(q)
            queries.append(q)

    # Standard biography queries
    _add(f'"{name}" {style} biography')
    _add(f'"{name}" interview {style}')
    _add(f'"{name}" seminar {style}')

    # Magazine-specific queries
    _add(f'"{name}" "Black Belt Magazine"')
    _add(f'"{name}" "Aikido Journal"')
    _add(f'"{name}" "Blitz Magazine"')
    _add(f'"{name}" "Karate Illustrated"')
    _add(f'"{name}" "Tai Chi Chuan Journal"')

    # Archive queries
    _add(f'"{name}" site:books.google.com')
    _add(f'"{name}" site:doczz.net')
    _add(f'"{name}" site:archive.org')

    # Wiki mirror queries
    _add(f'"{name}" site:wikitia.com')
    _add(f'"{name}" site:en-academic.com')

    # Magazine site queries
    _add(f'"{name}" site:blackbeltmag.com')
    _add(f'"{name}" site:aikidojournal.com')
    _add(f'"{name}" site:blitzmag.com.au')
    _add(f'"{name}" site:tqj.de')

    # Date-specific
    for date in dates:
        _add(f'"{name}" {date} {style}')
        _add(f'"{name}" "Black Belt Magazine" {date}')

    # City-specific
    for city in cities:
        _add(f'"{name}" "{city}" {style}')

    # Person-specific organizational queries for Nadeau
    if "nadeau" in name.lower():
        _add(f'"{name}" site:aikiclub.ru')
        _add(f'"{name}" site:lenkai.spb.ru')
        _add(f'"{name}" site:aikido.ru')
        _add(f'"{name}" Russia aikido')
        _add(f'"{name}" Soviet Union')

    print(f"Person: {name}")
    print(f"Context: {style}, Dates: {dates}, Cities: {cities}")
    print(f"Queries: {len(queries)}")
    print()

    # Initialize search clients
    brave = BraveSearchClient(api_key=settings.brave_search_api_key)
    bing = BingSearchClient()
    ddg = DuckDuckGoSearchClient()

    engines: list[tuple[str, any]] = []
    if brave.is_available():
        engines.append(("Brave", brave))
        print("Brave: available")
    else:
        print("Brave: NOT AVAILABLE")
    if bing.is_available():
        engines.append(("Bing", bing))
        print("Bing: available")
    else:
        print("Bing: NOT AVAILABLE")
    if ddg.is_available():
        engines.append(("DuckDuckGo", ddg))
        print("DuckDuckGo: available")
    else:
        print("DuckDuckGo: NOT AVAILABLE")
    print()

    if not engines:
        print("No search engines available!")
        return 1

    # Run each engine
    all_results: list[dict] = []
    for label, client in engines:
        print(f"── {label} ({len(queries)} queries) ", end="", flush=True)
        r = run_engine(client, queries, label)
        all_results.append(r)
        mag_count = sum(1 for x in r["results"] if is_relevant(x["url"], name) == "magazine")
        org_count = sum(1 for x in r["results"] if is_relevant(x["url"], name) == "organizational")
        print(f"→ {r['total']} results ({mag_count} magazine, {org_count} org) [{r['errors']} errors]")

    # Detailed comparison
    print(f"\n{'='*70}")
    print("DETAILED RESULTS")
    print(f"{'='*70}")

    for r in all_results:
        print(f"\n── {r['label']} ({r['total']} results)")
        mag_results = [x for x in r["results"] if is_relevant(x["url"], name) in ("magazine", "organizational")]
        if mag_results:
            print(f"  Magazine/org-relevant results ({len(mag_results)}):")
            for x in mag_results:
                cat = is_relevant(x["url"], name)
                print(f"    [{cat}] {x['url']}")
                print(f"          \"{x['title']}\"")
        else:
            print(f"  No magazine/org-relevant results found")

    # Venn comparison
    print(f"\n{'='*70}")
    print("COMPARISON")
    print(f"{'='*70}")

    urls_by_engine: dict[str, set[str]] = {}
    for r in all_results:
        urls_by_engine[r["label"]] = set(x["url"] for x in r["results"])

    # Unique to each engine
    for r in all_results:
        label = r["label"]
        urls = urls_by_engine[label]
        other_urls = set()
        for l in urls_by_engine:
            if l != label:
                other_urls |= urls_by_engine[l]
        unique = urls - other_urls
        mag_unique = [u for u in unique if is_relevant(u, name) in ("magazine", "organizational")]
        print(f"\n  {label} unique URLs: {len(unique)} ({len(mag_unique)} magazine/org)")
        for u in mag_unique[:10]:
            print(f"    {u}")

    # Overlap
    if len(all_results) >= 2:
        print(f"\n  Overlap:")
        for i in range(len(all_results)):
            for j in range(i + 1, len(all_results)):
                a, b = all_results[i], all_results[j]
                overlap = urls_by_engine[a["label"]] & urls_by_engine[b["label"]]
                mag_overlap = [u for u in overlap if is_relevant(u, name) in ("magazine", "organizational")]
                print(f"    {a['label']} ∩ {b['label']}: {len(overlap)} total, {len(mag_overlap)} magazine/org")

    # Check for expected URLs
    print(f"\n{'='*70}")
    print("EXPECTED URL CHECK")
    print(f"{'='*70}")

    expected_checks = []
    if "ralston" in name.lower():
        expected_checks = [
            ("Black Belt Magazine (Google Books)", "books.google.com"),
            ("Blitz Magazine (doczz.net)", "doczz.net"),
            ("Wikitia (citation source)", "wikitia.com"),
            ("en-academic (mirror)", "en-academic.com"),
            ("TQJ (German Tai Chi journal)", "tqj.de"),
        ]
    elif "nadeau" in name.lower():
        expected_checks = [
            ("Aikido Journal", "aikidojournal.com"),
            ("Moscow Aiki Club", "aikiclub.ru"),
            ("Lenkai Club", "lenkai.spb.ru"),
            ("Bujutsu Federation", "bujutsu.ru"),
            ("City Aikido", "cityaikido.com"),
            ("Riai Aikido NZ", "aikido.org.nz"),
            ("Black Belt Magazine", "blackbeltmag.com"),
        ]
    elif "moon" in name.lower():
        expected_checks = [
            ("Aikido Journal", "aikidojournal.com"),
            ("Black Belt Magazine", "blackbeltmag.com"),
            ("Simon & Schuster", "simonandschuster.com"),
        ]

    for desc, domain in expected_checks:
        found_in = []
        for r in all_results:
            if any(domain in x["url"] for x in r["results"]):
                found_in.append(r["label"])
        status = "✓" if found_in else "✗"
        print(f"  {status} {desc} ({domain}): {', '.join(found_in) if found_in else 'NOT FOUND'}")

    # Save JSON
    output_file = PROJECT_ROOT / "data" / f"search-comparison-{name.lower().replace(' ', '-')}.json"
    output_file.parent.mkdir(parents=True, exist_ok=True)
    with open(output_file, "w") as f:
        json.dump({
            "person": name,
            "context": style,
            "dates": dates,
            "cities": cities,
            "queries": len(queries),
            "results": all_results,
        }, f, indent=2, ensure_ascii=False)
    print(f"\n  Results saved to: {output_file}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
