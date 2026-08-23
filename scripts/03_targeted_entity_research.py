"""
Targeted entity research: corroborate a small, hand-picked list of
(subject, relation, object) leads via web search + the existing crawl / LLM
extraction / graph-storage pipeline — instead of the broad BFS crawl that
scripts/01_crawl_and_build_graph.py runs over the full seed-URL set.

This exists to chase down specific leads kkron (the project owner) reported
first-hand, rather than waiting for the general crawl to stumble onto them.
See ``DEFAULT_LEADS`` in scripts/_targeted_research_helpers.py for the
current list — as of the 2026-08-23 Slack thread: Richard Moon's early time
with Jim Baker (Father Yod), Richard Moon working at both The Source
restaurant and the Aware Inn (Jim Baker's earlier, pre-Source restaurant),
and a less-certain possible link to some Wild Mountain Cafe location(s).

For each lead this script:

  1. Stores kkron's own first-hand claim about the lead as a Claim node,
     ASSERTED_BY a dedicated "kkron (project owner, first-hand account)"
     Person node, at a confidence capped well below what an independently
     verified web source can reach (see KKRON_CONFIDENCE_CEILING in
     scripts/_targeted_research_helpers.py) — kkron's account is real
     signal, but it is not independent corroboration.
  2. Runs one or more Gemini + Google Search grounded queries
     (``SeedDiscoverer``) to find independent web pages that might
     corroborate or contradict the lead.
  3. Fetches each newly discovered URL (``WebCrawler``), extracts entities /
     claims / relations with Gemini (``GeminiExtractor`` +
     ``GeminiClaimExtractor``), and stores them via the same
     ``scripts._pipeline_helpers.process_page`` used by scripts/01 and
     scripts/02 — so independently-found claims land in the graph exactly
     like any other crawled source, standing on their own merits alongside
     kkron's claim rather than replacing it.
  4. Re-runs ``ContradictionDetector`` so any web-sourced claim that agrees
     or disagrees with kkron's account is linked in (implicit ABOUT
     inference, CONTRADICTS edges between opposite-stance claims about the
     same entity).

This script does not fabricate or guess at research results — it only
issues real search/crawl/extraction calls, which require network access and
a configured GEMINI_API_KEY. It is meant to be run from a cron job on a
machine that actually has internet access, e.g.:

    # crontab -e
    0 6 * * *  cd /path/to/story_graph && \\
        /path/to/.venv/bin/python scripts/03_targeted_entity_research.py \\
        >> data/targeted_research.log 2>&1

Results land in the same SQLite graph DB as scripts/01 and scripts/02
(default: data/graph.db, override with --db-path or the GRAPH_DB_PATH env
var — see config/settings.py). data/graph.db and *.log are already
git-ignored, so cron output stays local. The run summary is printed to
stdout/stderr — redirect it to a log file (as in the cron example above) to
keep a persistent record across runs.

JSON snapshot is the source of truth, SQLite is a local working copy
------------------------------------------------------------------------
data/graph.db is git-ignored and disposable. What actually gets committed
and reviewed in an MR is a tracked JSON/JSONL snapshot of the graph under
``graph_snapshot/`` at the repo root (override with --snapshot-dir or the
GRAPH_SNAPSHOT_DIR env var — see config/settings.py and
src/storage/json_export.py). Every run of this script:

  1. Rebuilds a fresh local SQLite working copy from that tracked snapshot
     before doing anything else (src/storage/json_export.import_from_json),
     so the graph state a run starts from is always exactly what is in git
     — not whatever a previous, possibly-stale local data/graph.db held.
  2. Does its work against that local SQLite copy, same as before.
  3. Exports the resulting graph back out to the same tracked snapshot
     directory when it finishes (src/storage/json_export.export_to_json),
     so the JSONL diff in the MR reflects this run's changes.

JSON/JSONL was chosen over committing data/graph.db directly because it
diffs cleanly in a merge request (one sorted, human-readable line per
node/edge/source) where a SQLite file would show as an opaque binary diff.
This can be revisited (e.g. back to SQLite as the tracked format) if the
graph grows large enough for JSON export/import to become a real
performance problem — see src/storage/json_export.py's module docstring.

The script is idempotent: re-running it re-upserts the same kkron-sourced
nodes/edges (safe no-ops) and skips URLs already present in the `sources`
table, so a daily cron job naturally converges rather than re-processing
the same pages every time.

Usage:
    python scripts/03_targeted_entity_research.py
    python scripts/03_targeted_entity_research.py --max-results-per-lead 3
    python scripts/03_targeted_entity_research.py --skip-kkron-claims
    python scripts/03_targeted_entity_research.py --skip-search
    python scripts/03_targeted_entity_research.py --dry-run
    python scripts/03_targeted_entity_research.py --snapshot-dir graph_snapshot
"""

from __future__ import annotations

import sys
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import click
from rich.console import Console
from rich.table import Table

from config.settings import settings
from src.crawler.web_crawler import WebCrawler
from src.extractor.contradiction_detector import ContradictionDetector
from src.llm.entity_claim_extractor import GeminiClaimExtractor, GeminiExtractor
from src.llm.gemini_client import GeminiClient
from src.llm.seed_discoverer import SeedDiscoverer
from src.storage.graph_db import GraphDB
from src.storage.json_export import export_to_json, import_from_json, snapshot_exists
from src.utils.text_utils import get_domain
from scripts._pipeline_helpers import process_page
from scripts._targeted_research_helpers import (
    DEFAULT_LEADS,
    ResearchLead,
    build_search_queries,
    filter_new_urls,
    store_kkron_claim,
)

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


def _research_lead(
    lead: ResearchLead,
    db: GraphDB,
    discoverer: SeedDiscoverer,
    gemini_ext: GeminiExtractor,
    gemini_claim_ext: GeminiClaimExtractor,
    max_results: int,
    already_seen_urls: set[str],
) -> dict:
    """Run search + crawl + extraction for one lead. Returns a summary dict."""
    queries = build_search_queries(lead)
    discovered: list[str] = []
    for query in queries:
        seeds = discoverer.discover(query, exclude_urls=already_seen_urls)
        for s in seeds:
            if s.url not in discovered:
                discovered.append(s.url)
        if len(discovered) >= max_results:
            break
    discovered = discovered[:max_results]

    new_urls = filter_new_urls(discovered, already_seen_urls)
    processed = 0
    errors: list[str] = []
    for url in new_urls:
        already_seen_urls.add(url)
        try:
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
                errors.append(f"{url}: fetch failed")
                continue
            process_page(pages[0], gemini_ext, gemini_claim_ext, db)
            processed += 1
        except Exception as e:  # keep going on a per-URL failure
            errors.append(f"{url}: {e}")

    return {
        "lead": lead,
        "queries": queries,
        "discovered": discovered,
        "processed": processed,
        "errors": errors,
    }


@click.command()
@click.option("--db-path", default=None, help="Override SQLite (local working copy) DB path")
@click.option(
    "--snapshot-dir",
    default=None,
    help="Override tracked JSON snapshot directory (source of truth; default: graph_snapshot/)",
)
@click.option(
    "--max-results-per-lead",
    default=5,
    type=int,
    help="Max newly discovered URLs to fetch + extract per lead",
)
@click.option(
    "--skip-kkron-claims",
    is_flag=True,
    help="Don't (re-)store kkron's own first-hand claims; search/extract only",
)
@click.option(
    "--skip-search",
    is_flag=True,
    help="Don't run web search/crawl/extraction — store kkron's claims only, no network or Gemini calls",
)
@click.option(
    "--dry-run",
    is_flag=True,
    help="Print the configured leads and search queries; touch neither the DB nor the network",
)
def main(db_path, snapshot_dir, max_results_per_lead, skip_kkron_claims, skip_search, dry_run):
    """Targeted research for a hand-picked list of leads (see DEFAULT_LEADS
    in scripts/_targeted_research_helpers.py)."""
    console.print("[bold cyan]Story Graph — Targeted Entity Research[/bold cyan]")
    console.print()

    if dry_run:
        for lead in DEFAULT_LEADS:
            console.print(
                f"[yellow]{lead.subject_name}[/yellow] --{lead.relation.value}--> "
                f"[yellow]{lead.object_name}[/yellow]  "
                f"(kkron confidence: {lead.kkron_confidence})"
            )
            for q in build_search_queries(lead):
                console.print(f"    query: {q}")
        return

    db_file = db_path or str(settings.graph_db_abs_path)
    snap_dir = Path(snapshot_dir) if snapshot_dir else settings.graph_snapshot_abs_dir
    console.print(f"[dim]Snapshot (source of truth): {snap_dir}[/dim]")
    console.print(f"[dim]Local working DB: {db_file}[/dim]")

    if snapshot_exists(snap_dir):
        console.print("[dim]Loading tracked JSON snapshot into local working DB...[/dim]")
        db = import_from_json(snap_dir, db_file)
    else:
        console.print(
            "[yellow]No tracked JSON snapshot found at "
            f"{snap_dir} — starting from an empty local DB[/yellow]"
        )
        db = GraphDB(db_file)

    try:
        if not skip_kkron_claims:
            console.print("[bold]Phase 1: Storing kkron's first-hand claims[/bold]")
            for lead in DEFAULT_LEADS:
                cid = store_kkron_claim(db, lead)
                console.print(
                    f"  stored {cid}  "
                    f"({lead.subject_name} --{lead.relation.value}--> {lead.object_name})"
                )
        else:
            console.print("[yellow]Skipping kkron claims (--skip-kkron-claims)[/yellow]")

        results: list[dict] = []
        if not skip_search:
            console.print()
            console.print("[bold]Phase 2: Searching + extracting from independent sources[/bold]")
            client = GeminiClient()
            if not _require_gemini(client):
                return
            discoverer = SeedDiscoverer(client)
            gemini_ext = GeminiExtractor(client)
            gemini_claim_ext = GeminiClaimExtractor(gemini_ext)
            already_seen = {s.url for s in db.get_all_sources()}

            for lead in DEFAULT_LEADS:
                console.print(f"  [{lead.subject_name} --{lead.relation.value}--> {lead.object_name}]")
                result = _research_lead(
                    lead, db, discoverer, gemini_ext, gemini_claim_ext,
                    max_results_per_lead, already_seen,
                )
                results.append(result)
                console.print(
                    f"    discovered={len(result['discovered'])} "
                    f"processed={result['processed']} errors={len(result['errors'])}"
                )
                for err in result["errors"]:
                    console.print(f"    [red]error:[/red] {err}")
        else:
            console.print("[yellow]Skipping web search (--skip-search)[/yellow]")

        console.print()
        console.print("[bold]Phase 3: Detecting contradictions[/bold]")
        detector = ContradictionDetector(db)
        inferred = detector.infer_implicit_targets()
        contradictions = detector.detect_contradictions()
        if inferred:
            console.print(f"  [dim]Inferred {inferred} implicit ABOUT edges[/dim]")
        console.print(f"  {len(contradictions)} contradiction(s) detected")

        if results:
            console.print()
            table = Table(title="Targeted Research Summary")
            table.add_column("Lead", style="cyan", overflow="fold")
            table.add_column("Discovered", style="magenta")
            table.add_column("Processed", style="green")
            table.add_column("Errors", style="red")
            for r in results:
                lead = r["lead"]
                table.add_row(
                    f"{lead.subject_name} --{lead.relation.value}--> {lead.object_name}",
                    str(len(r["discovered"])),
                    str(r["processed"]),
                    str(len(r["errors"])),
                )
            console.print(table)

        console.print()
        console.print("[bold]Phase 4: Exporting graph to tracked JSON snapshot[/bold]")
        counts = export_to_json(db, snap_dir)
        for fname, count in counts.items():
            console.print(f"  {fname}: {count} row(s)")

        console.print()
        console.print("[bold green]Targeted research run complete.[/bold green]")
        console.print(f"[dim]Snapshot (commit this): {snap_dir}[/dim]")
        console.print(f"[dim]Local working DB: {db_file}[/dim]")
        console.print(f"[dim]Explore with: datasette {db_file}[/dim]")
    finally:
        db.close()


if __name__ == "__main__":
    main()
