"""
Main pipeline: crawl seed URLs, extract entities/claims, store in SQLite graph,
detect contradictions, and build timeline edges.

Usage:
    python scripts/01_crawl_and_build_graph.py [--max-depth N] [--max-pages N]
"""

from __future__ import annotations

import json
import logging
import sys
import os
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import click
from rich.console import Console
from rich.table import Table

from config.settings import settings
from src.crawler.web_crawler import WebCrawler, CrawledPage
from src.extractor.entity_extractor import EntityExtractor
from src.extractor.claim_extractor import ClaimExtractor
from src.extractor.contradiction_detector import ContradictionDetector
from src.storage.graph_db import GraphDB
from src.storage.models import NodeType
from src.utils.text_utils import get_domain
from scripts._pipeline_helpers import process_page, classify_source


@click.command()
@click.option("--max-depth", default=None, type=int, help="Override max crawl depth")
@click.option("--max-pages", default=None, type=int, help="Override max pages to crawl")
@click.option("--skip-crawl", is_flag=True, help="Skip crawling, use cached pages")
@click.option("--db-path", default=None, help="Override SQLite DB path")
def main(max_depth, max_pages, skip_crawl, db_path):
    """Run the full story graph pipeline."""
    console.print("[bold cyan]Story Graph — Source Family / Father Yod[/bold cyan]")
    console.print()

    # Config
    crawl_depth = max_depth if max_depth is not None else settings.crawl_max_depth
    crawl_pages = max_pages if max_pages is not None else settings.crawl_max_pages
    db_file = db_path or str(settings.graph_db_abs_path)

    # Initialize components
    console.print(f"[dim]Database: {db_file}[/dim]")
    db = GraphDB(db_file)
    extractor = EntityExtractor(settings.spacy_model)
    claim_extractor = ClaimExtractor(extractor)

    # Phase 1: Crawl
    if skip_crawl:
        console.print("[yellow]Skipping crawl (--skip-crawl)[/yellow]")
        pages = []
    else:
        console.print(f"[bold]Phase 1: Crawling[/bold] (depth={crawl_depth}, max_pages={crawl_pages})")
        crawler = WebCrawler(
            seed_urls=settings.seed_urls,
            allowed_domains=settings.allowed_domains,
            max_depth=crawl_depth,
            max_pages=crawl_pages,
            delay_seconds=settings.crawl_delay_seconds,
            user_agent=settings.crawl_user_agent,
            timeout=settings.crawl_timeout,
        )
        pages = crawler.crawl()
        console.print(f"  Crawled {len(pages)} pages")

    # Phase 2: Extract + Store
    console.print("[bold]Phase 2: Extracting entities and claims[/bold]")
    for i, page in enumerate(pages):
        if page.error:
            continue
        console.print(f"  [{i+1}/{len(pages)}] {page.url[:80]}")
        process_page(page, extractor, claim_extractor, db)

    # Phase 3: Detect contradictions + timeline
    console.print("[bold]Phase 3: Detecting contradictions and building timeline[/bold]")
    detector = ContradictionDetector(db)
    contradictions = detector.detect_contradictions()
    timeline_edges = detector.build_timeline_edges()

    # Summary
    console.print()
    console.print("[bold green]Pipeline complete![/bold green]")
    table = Table(title="Graph Statistics")
    table.add_column("Metric", style="cyan")
    table.add_column("Count", style="magenta")
    table.add_row("Nodes", str(db.get_node_count()))
    table.add_row("Edges", str(db.get_edge_count()))
    table.add_row("Sources", str(db.get_source_count()))
    table.add_row("Contradictions", str(len(contradictions)))
    table.add_row("Timeline edges", str(len(timeline_edges)))
    console.print(table)

    # Node type breakdown
    for nt in NodeType:
        nodes = db.get_nodes_by_type(nt)
        if nodes:
            console.print(f"  {nt.value}: {len(nodes)} nodes")

    db.close()
    console.print(f"\n[dim]Database saved to: {db_file}[/dim]")
    console.print(f"[dim]Explore with: datasette {db_file}[/dim]")


if __name__ == "__main__":
    main()
