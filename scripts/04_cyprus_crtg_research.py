"""
Targeted entity research: corroborate a small, hand-picked list of
(subject, relation, object) leads via web search + the existing crawl / LLM
extraction / graph-storage pipeline — instead of the broad BFS crawl that
scripts/01_crawl_and_build_graph.py runs over the full seed-URL set.

This exists to chase down a specific dispute kkron (the project owner)
reported first-hand: a Wikipedia editing dispute over the article "Cyprus
Conflict Resolution Trainers Group" (CRTG). See ``DEFAULT_LEADS`` in
scripts/_cyprus_crtg_helpers.py for the current list — as of a forwarded
email thread from kkron's own inbox (2026-08-14 to 2026-08-16): the article
currently credits only 4 initial trainers, but kkron says the group was
~30 Cypriot trainees plus multiple outside trainers (himself, Douglas Stone,
Sheila Heen, and others named only by first name — "Richard", "Louise",
"Diana" — whose surnames are not yet confirmed).

PRIVACY NOTE: the underlying source material is forwarded personal email,
not a public web page like the rest of this project's normal inputs. No raw
email addresses appear anywhere in this script, scripts/_cyprus_crtg_helpers.py,
or the graph data it produces — only names. See
scripts/_cyprus_crtg_helpers.py's module docstring for the three provenance
kinds this script's leads use (kkron first-hand account, citation-sourced,
and public-record).

For each lead this script:

  1. Stores the lead's claim (per its provenance — kkron's own first-hand
     account, a citation to the Wikipedia Talk page dispute itself, or a
     well-established public-record fact about Stone/Heen's Harvard
     Negotiation Project affiliation) via
     ``scripts._cyprus_crtg_helpers.store_lead_claim``. kkron-sourced claims
     are ASSERTED_BY a dedicated "kkron (project owner, first-hand account)"
     Person node, at a confidence capped well below what an independently
     verified web source can reach (see KKRON_CONFIDENCE_CEILING in
     scripts/_cyprus_crtg_helpers.py) — kkron's account is real signal, but
     it is not independent corroboration.
  2. Runs one or more Gemini + Google Search grounded queries
     (``SeedDiscoverer``) to find independent web pages that might
     corroborate or contradict the lead — e.g. confirming Sheila Heen's
     Cyprus involvement via her public bio, or searching for "Louise" and
     "Diana" by full name once/if a surname turns up.
  3. Fetches each newly discovered URL (``WebCrawler``), extracts entities /
     claims / relations with Gemini (``GeminiExtractor`` +
     ``GeminiClaimExtractor``), and stores them via the same
     ``scripts._pipeline_helpers.process_page`` used by scripts/01 and
     scripts/02 — so independently-found claims land in the graph exactly
     like any other crawled source, standing on their own merits alongside
     the curated leads rather than replacing them.
  4. Re-runs ``ContradictionDetector`` so any web-sourced claim that agrees
     or disagrees with a curated lead is linked in (implicit ABOUT
     inference, CONTRADICTS edges between opposite-stance claims about the
     same entity).

This script does not fabricate or guess at research results — it only
issues real search/crawl/extraction calls, which require network access and
a configured GEMINI_API_KEY. It is meant to be run from a cron job on a
machine that actually has internet access, e.g.:

    # crontab -e
    0 7 * * *  cd /path/to/story_graph && \\
        /path/to/.venv/bin/python scripts/04_cyprus_crtg_research.py \\
        >> data/cyprus_crtg_research.log 2>&1

Results land in the same SQLite graph DB as scripts/01 and scripts/02
(default: data/graph.db, override with --db-path or the GRAPH_DB_PATH env
var — see config/settings.py). data/graph.db and *.log are already
git-ignored, so cron output stays local.

Unlike the (currently separate, unmerged) targeted-entity-research feature,
this script writes directly to the local SQLite graph DB rather than
round-tripping through a tracked JSON snapshot directory — main does not yet
have that snapshot infrastructure (src/storage/json_export.py). If/when that
snapshot-is-source-of-truth workflow lands on main, this script should be
updated to use it too, the same way scripts/01 and scripts/02 currently do
not use it either.

The script is idempotent: re-running it re-upserts the same leads'
nodes/edges (safe no-ops) and skips URLs already present in the `sources`
table, so a daily cron job naturally converges rather than re-processing
the same pages every time.

Usage:
    python scripts/04_cyprus_crtg_research.py
    python scripts/04_cyprus_crtg_research.py --max-results-per-lead 3
    python scripts/04_cyprus_crtg_research.py --skip-curated-claims
    python scripts/04_cyprus_crtg_research.py --skip-search
    python scripts/04_cyprus_crtg_research.py --dry-run
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
from src.utils.text_utils import get_domain
from scripts._pipeline_helpers import process_page
from scripts._cyprus_crtg_helpers import (
    DEFAULT_LEADS,
    ResearchLead,
    build_search_queries,
    filter_new_urls,
    store_lead_claim,
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
@click.option("--db-path", default=None, help="Override SQLite DB path")
@click.option(
    "--max-results-per-lead",
    default=5,
    type=int,
    help="Max newly discovered URLs to fetch + extract per lead",
)
@click.option(
    "--skip-curated-claims",
    is_flag=True,
    help=(
        "Don't (re-)store the curated leads' claims (kkron first-hand, "
        "citation-sourced, and public-record); search/extract only"
    ),
)
@click.option(
    "--skip-search",
    is_flag=True,
    help="Don't run web search/crawl/extraction — store curated claims only, no network or Gemini calls",
)
@click.option(
    "--dry-run",
    is_flag=True,
    help="Print the configured leads and search queries; touch neither the DB nor the network",
)
def main(db_path, max_results_per_lead, skip_curated_claims, skip_search, dry_run):
    """Targeted research for the Cyprus Conflict Resolution Trainers Group
    (CRTG) Wikipedia dispute (see DEFAULT_LEADS in
    scripts/_cyprus_crtg_helpers.py)."""
    console.print("[bold cyan]Story Graph — Cyprus CRTG Targeted Research[/bold cyan]")
    console.print()

    if dry_run:
        for lead in DEFAULT_LEADS:
            kind = lead.provenance()
            conf = {
                "kkron": lead.kkron_confidence,
                "citation": lead.source_confidence,
                "public_record": lead.public_record_confidence,
            }[kind]
            console.print(
                f"[yellow]{lead.subject_name}[/yellow] --{lead.relation.value}--> "
                f"[yellow]{lead.object_name}[/yellow]  "
                f"(provenance: {kind}, confidence: {conf})"
            )
            for q in build_search_queries(lead):
                console.print(f"    query: {q}")
        return

    db_file = db_path or str(settings.graph_db_abs_path)
    console.print(f"[dim]Local working DB: {db_file}[/dim]")
    db = GraphDB(db_file)

    try:
        if not skip_curated_claims:
            console.print("[bold]Phase 1: Storing curated leads' claims[/bold]")
            for lead in DEFAULT_LEADS:
                cid = store_lead_claim(db, lead)
                console.print(
                    f"  stored {cid}  "
                    f"({lead.subject_name} --{lead.relation.value}--> {lead.object_name})"
                )
        else:
            console.print("[yellow]Skipping curated claims (--skip-curated-claims)[/yellow]")

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
            table = Table(title="Cyprus CRTG Research Summary")
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
        console.print("[bold green]Cyprus CRTG research run complete.[/bold green]")
        console.print(f"[dim]Local working DB: {db_file}[/dim]")
        console.print(f"[dim]Explore with: datasette {db_file}[/dim]")
    finally:
        db.close()


if __name__ == "__main__":
    main()
