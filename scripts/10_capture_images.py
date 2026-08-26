"""
Rescan every source already in the graph and backfill any images found on
its page — this is the "capture images we missed before image capture
existed" script (see scripts/_pipeline_helpers.py's capture_page_images,
which now runs automatically during normal crawling).

Sources are re-fetched by URL because SourceRecord.raw_text is cleaned
text, not HTML — the original <img>/og:image markup only exists on the
live page. Resumable: sources that already have at least one DEPICTS edge
are skipped by default, so re-running after an interruption or a --limit
cutoff only processes what's left.

Usage:
    python scripts/10_capture_images.py --limit 50
    python scripts/10_capture_images.py --domain blogspot.com
    python scripts/10_capture_images.py --force   # re-check sources that already have images
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import click
import requests
from rich.console import Console

from config.settings import settings
from scripts._pipeline_helpers import capture_page_images
from src.crawler.web_crawler import CrawledPage, WebCrawler
from src.storage.graph_db import GraphDB
from src.storage.json_export import export_to_json, import_from_json
from src.storage.models import RelationType

console = Console()


def _sources_with_images(db: GraphDB) -> set[str]:
    return {e.src_id for e in db.get_all_edges() if e.rel_type == RelationType.DEPICTS}


def _refetch_and_extract_images(url: str, crawler: WebCrawler, timeout: int) -> CrawledPage:
    """Re-fetch a single URL (single attempt, no retry) and reuse WebCrawler's
    own <img>/og:image extraction (crawler._parse_page).

    Deliberately bypasses WebCrawler._fetch's retry/backoff: this is a bulk
    best-effort backfill over hundreds of sources, many of which (Reddit,
    Facebook, YouTube, dead links) simply won't yield a fetchable page, and
    retrying each of those three times with exponential backoff would blow
    up the run's wall-clock time for no benefit.
    """
    response = requests.get(
        url, headers={"User-Agent": crawler.user_agent}, timeout=timeout
    )
    response.raise_for_status()
    return crawler._parse_page(url, response.text)


@click.command()
@click.option("--db-path", default=None, help="Override SQLite DB path")
@click.option("--snapshot", default=None, help="Override snapshot dir")
@click.option("--limit", default=None, type=int, help="Max sources to process this run")
@click.option("--domain", default=None, help="Only rescan sources whose URL contains this substring")
@click.option("--force", is_flag=True, help="Re-check sources that already have image edges")
@click.option("--delay", default=1.0, type=float, help="Seconds between fetches (politeness)")
@click.option("--timeout", default=10, type=int, help="Per-request fetch timeout, seconds")
@click.option("--no-export", is_flag=True, help="Skip writing graph_snapshot/ at the end")
def main(db_path, snapshot, limit, domain, force, delay, timeout, no_export):
    db_file = db_path or str(settings.graph_db_abs_path)
    snapshot_dir = Path(snapshot) if snapshot else Path("graph_snapshot")

    console.print(f"[dim]Rebuilding working DB from snapshot: {snapshot_dir}[/dim]")
    db = import_from_json(snapshot_dir, db_file)

    all_sources = db.get_all_sources()
    already_captured = _sources_with_images(db)

    candidates = [s for s in all_sources if force or s.id not in already_captured]
    candidates = [s for s in candidates if s.url.startswith(("http://", "https://"))]
    if domain:
        candidates = [s for s in candidates if domain in s.url]
    if limit:
        candidates = candidates[:limit]

    console.print(
        f"[bold]{len(all_sources)}[/bold] sources total, "
        f"[bold]{len(already_captured)}[/bold] already have images, "
        f"[bold]{len(candidates)}[/bold] to process this run"
    )

    crawler = WebCrawler(seed_urls=[], allowed_domains=set(), delay_seconds=0)

    processed = 0
    captured_pages = 0
    skipped_unfetchable = 0
    failed = 0

    for source in candidates:
        console.print(f"[dim]Fetching {source.url}[/dim]")
        try:
            page = _refetch_and_extract_images(source.url, crawler, timeout)
        except Exception as e:
            console.print(f"  [yellow]skip (unfetchable): {e}[/yellow]")
            skipped_unfetchable += 1
            time.sleep(delay)
            continue

        if not page.images:
            processed += 1
            time.sleep(delay)
            continue

        try:
            capture_page_images(page, source.id, db)
        except Exception as e:
            console.print(f"  [red]failed to capture images: {e}[/red]")
            failed += 1
            time.sleep(delay)
            continue
        console.print(f"  [green]found {len(page.images)} candidate image(s)[/green]")
        captured_pages += 1
        processed += 1
        time.sleep(delay)

    console.print()
    console.print(
        f"Done: processed={processed}, pages_with_images={captured_pages}, "
        f"unfetchable={skipped_unfetchable}, failed={failed}"
    )

    if not no_export:
        counts = export_to_json(db, snapshot_dir)
        console.print(f"[bold]Exported snapshot:[/bold] {counts}")

    db.close()


if __name__ == "__main__":
    main()
