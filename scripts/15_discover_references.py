#!/usr/bin/env python3
"""
Discover new reference URLs by fetching pages from the graph's existing
source_urls and extracting their outbound links.

This is the graph-driven counterpart to the BFS WebCrawler
(scripts/01_crawl_and_build_graph.py). Instead of crawling from seed URLs
within allowed domains, it uses the URLs already stored on graph nodes
and source records as its crawl frontier — useful for finding new
references in sources that were ingested manually (e.g. the yoga abuse
spreadsheet, the Deslippe paper, CDNC articles).

For each source URL:
1. Fetches the page (if not already visited)
2. Extracts outbound links from the HTML
3. For each link not already in the graph:
   - Creates a SourceRecord + Work node
   - Creates a MENTIONS edge from the source page to the discovered URL
4. Records the visit in a ref_discovery table (idempotent)

Usage:
    python scripts/15_discover_references.py
    python scripts/15_discover_references.py --dry-run
    python scripts/15_discover_references.py --max-urls 50
    python scripts/15_discover_references.py --delay 5 --timeout 30
    python scripts/15_discover_references.py --db data/graph.db --no-export
"""

import argparse
import logging
import sys
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from rich.console import Console
from rich.table import Table

from src.crawler.reference_discoverer import ReferenceDiscoverer
from src.storage.graph_db import GraphDB
from src.storage.json_export import export_to_json

console = Console()


def main():
    parser = argparse.ArgumentParser(
        description="Discover new references from the graph's source URLs"
    )
    parser.add_argument("--db", default="data/graph.db", help="Database path")
    parser.add_argument("--dry-run", action="store_true", help="Don't fetch or write — just report")
    parser.add_argument("--max-urls", type=int, default=None, help="Max source URLs to fetch")
    parser.add_argument("--delay", type=float, default=3.0, help="Delay between fetches (seconds)")
    parser.add_argument("--timeout", type=int, default=20, help="Request timeout (seconds)")
    parser.add_argument("--no-export", action="store_true", help="Skip snapshot export")
    parser.add_argument("-v", "--verbose", action="store_true", help="Verbose logging")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    print()
    print("╔════════════════════════════════════════════════════════════════════╗")
    print("║  REFERENCE DISCOVERY — story_graph                                  ║")
    print("║  Fetch graph source URLs → extract outbound links → store new refs  ║")
    print("╚════════════════════════════════════════════════════════════════════╝")
    print()

    if args.dry_run:
        print("[dry-run mode — no fetches, no DB writes]\n")

    db = GraphDB(Path(args.db))
    try:
        discoverer = ReferenceDiscoverer(
            db,
            delay_seconds=args.delay,
            timeout=args.timeout,
            max_source_urls=args.max_urls,
        )

        stats, results = discoverer.discover(dry_run=args.dry_run)

        # Print summary
        print()
        table = Table(title="Discovery Results")
        table.add_column("Metric", style="cyan")
        table.add_column("Count", style="magenta")
        table.add_row("Source URLs in graph", str(stats.total_source_urls))
        table.add_row("Visited", str(stats.visited))
        table.add_row("Skipped (already visited)", str(stats.skipped))
        table.add_row("Errors", str(stats.errors))
        table.add_row("Total links found", str(stats.total_links_found))
        table.add_row("New references discovered", str(stats.total_new_references))
        table.add_row("New SourceRecords", str(stats.new_source_records))
        table.add_row("New Work nodes", str(stats.new_work_nodes))
        table.add_row("New MENTIONS edges", str(stats.new_edges))
        console.print(table)

        # Print errors if any
        errors = [r for r in results if r.status == "error"]
        if errors:
            print(f"\n[red]Errors ({len(errors)}):[/red]")
            for r in errors[:20]:
                print(f"  {r.source_url[:80]} -> {r.error}")

        # Print top discoveries
        discoveries = [r for r in results if r.links_new > 0]
        if discoveries:
            print(f"\n[green]URLs with new references ({len(discoveries)}):[/green]")
            disc_table = Table(title="Top Sources by New References")
            disc_table.add_column("Source URL", style="cyan", overflow="fold")
            disc_table.add_column("Title", style="white")
            disc_table.add_column("Links", style="yellow")
            disc_table.add_column("New", style="green")
            for r in sorted(discoveries, key=lambda x: x.links_new, reverse=True)[:20]:
                disc_table.add_row(
                    r.source_url[:80],
                    r.title[:50],
                    str(r.links_found),
                    str(r.links_new),
                )
            console.print(disc_table)

        if not args.dry_run and not args.no_export:
            print("\nExporting snapshot...")
            counts = export_to_json(db, Path("graph_snapshot"))
            print(f"Exported snapshot: {counts}")

    finally:
        db.close()


if __name__ == "__main__":
    main()
