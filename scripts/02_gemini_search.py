"""
Gemini-powered search, extraction, and Q&A for the story graph.

Three subcommands:

- ``discover``  — use Gemini + Google Search grounding to find new seed
  URLs about The Source Family / Father Yod.
- ``extract``   — re-extract entities/claims/relations from a URL or raw
  text using Gemini structured output, and store them in the graph.
- ``ask``       — ask a natural-language question over the SQLite graph,
  answered by Gemini using retrieved nodes/claims as context.

All subcommands require GEMINI_API_KEY in .env. The spaCy + rule-based
pipeline (``scripts/01_crawl_and_build_graph.py``) remains the default
and does not need Gemini.

Usage:
    python scripts/02_gemini_search.py discover [--query "..."]
    python scripts/02_gemini_search.py extract --url https://...
    python scripts/02_gemini_search.py extract --text "Father Yod opened..."
    python scripts/02_gemini_search.py ask "What did Laura Garon say about Baker?"
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import click
from rich.console import Console
from rich.table import Table

from config.settings import settings
from scripts._pipeline_helpers import process_page
from src.crawler.web_crawler import CrawledPage, WebCrawler
from src.llm.entity_claim_extractor import GeminiClaimExtractor, GeminiExtractor
from src.llm.gemini_client import GeminiClient
from src.llm.graph_qa import GraphQA
from src.llm.seed_discoverer import SeedDiscoverer
from src.storage.graph_db import GraphDB
from src.utils.text_utils import get_domain

console = Console()


def _require_gemini(client: GeminiClient) -> bool:
    if not client.is_available():
        console.print("[red]Gemini is not available.[/red]")
        console.print(
            "Set GEMINI_API_KEY in .env (see .env.example). "
            "Get a key from https://aistudio.google.com/apikey"
        )
        return False
    return True


@click.group()
def cli():
    """Gemini-powered search, extraction, and Q&A for the story graph."""


@cli.command()
@click.option("--query", default=None, help="Natural-language search query")
@click.option("--json-out", is_flag=True, help="Emit results as JSON")
def discover(query, json_out):
    """Discover new seed URLs via Gemini + Google Search grounding."""
    client = GeminiClient()
    if not _require_gemini(client):
        return

    discoverer = SeedDiscoverer(client)
    seeds = discoverer.discover(query, exclude_urls=set(settings.seed_urls))

    if json_out:
        click.echo(json.dumps([{"url": s.url, "title": s.title, "domain": s.domain} for s in seeds], indent=2))
        return

    if not seeds:
        console.print("[yellow]No new URLs discovered.[/yellow]")
        return

    table = Table(title="Discovered Seed URLs")
    table.add_column("URL", style="cyan", overflow="fold")
    table.add_column("Title", style="white")
    table.add_column("Domain", style="magenta")
    for s in seeds:
        table.add_row(s.url, s.title[:60], s.domain)
    console.print(table)
    console.print("\n[dim]Add these to settings.seed_urls or use as one-off crawl seeds.[/dim]")


@cli.command()
@click.option("--url", default=None, help="URL to fetch and extract from")
@click.option("--text", default=None, help="Raw text to extract from (instead of --url)")
@click.option("--db-path", default=None, help="Override SQLite DB path")
@click.option("--store/--no-store", default=True, help="Store results in the graph DB")
def extract(url, text, db_path, store):
    """Extract entities/claims/relations from a URL or text via Gemini."""
    client = GeminiClient()
    if not _require_gemini(client):
        return

    if not url and not text:
        console.print("[red]Provide --url or --text[/red]")
        return

    if url:
        console.print(f"[dim]Fetching {url}...[/dim]")
        crawler = WebCrawler(
            seed_urls=[url],
            allowed_domains={get_domain(url)},
            max_depth=0,
            max_pages=1,
            delay_seconds=settings.crawl_delay_seconds,
            user_agent=settings.crawl_user_agent,
            timeout=settings.crawl_timeout,
        )
        pages = crawler.crawl()
        if not pages or pages[0].error or not pages[0].text:
            console.print("[red]Failed to fetch URL[/red]")
            return
        page = pages[0]
        console.print(f"[dim]Fetched {len(page.text)} chars[/dim]")
    else:
        page = CrawledPage(
            url="gemini://inline-text",
            title="Inline text",
            text=text,
            links=[],
            author=None,
            publish_date=None,
            status_code=200,
        )

    gemini_ext = GeminiExtractor(client)
    gemini_claim_ext = GeminiClaimExtractor(gemini_ext)

    if store:
        db_file = db_path or str(settings.graph_db_abs_path)
        console.print(f"[dim]Storing in {db_file}[/dim]")
        db = GraphDB(db_file)
        try:
            process_page(page, gemini_ext, gemini_claim_ext, db)
            console.print(f"[green]Stored. Nodes: {db.get_node_count()}, Edges: {db.get_edge_count()}[/green]")
        finally:
            db.close()
    else:
        entities = gemini_ext.extract(page.text)
        console.print_json(json.dumps(entities, default=str))


@cli.command()
@click.argument("question")
@click.option("--db-path", default=None, help="Override SQLite DB path")
@click.option("--show-context", is_flag=True, help="Print retrieved context JSON")
def ask(question, db_path, show_context):
    """Ask a natural-language question over the graph, answered by Gemini."""
    client = GeminiClient()
    if not _require_gemini(client):
        return

    db_file = db_path or str(settings.graph_db_abs_path)
    db = GraphDB(db_file)
    try:
        qa = GraphQA(db, client)
        result = qa.answer(question)
        console.print()
        console.print("[bold cyan]Answer:[/bold cyan]")
        console.print(result.answer)
        if show_context:
            console.print()
            console.print("[dim]Retrieved context:[/dim]")
            console.print_json(json.dumps(result.context, default=str))
    finally:
        db.close()


if __name__ == "__main__":
    cli()
