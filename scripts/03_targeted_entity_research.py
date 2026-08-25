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
a configured GEMINI_API_KEY. It needs to run on a schedule from somewhere
that actually has internet access; see infra/README.md for the deployed
version of this: a GCP Cloud Run Job (see Dockerfile at the repo root) plus
a Cloud Scheduler trigger on the same "0 6 * * *" cron this docstring used
to just describe in prose, provisioned by the Terraform under infra/ and
built/pushed/applied via ./deploy.sh. That setup has not yet been applied
against a real GCP project — see infra/README.md's "known limitations"
section before assuming it's live.

For a one-off local/manual run instead of the deployed job, invoke it the
same way cron would:

    cd /path/to/story_graph && \\
        .venv/bin/python scripts/03_targeted_entity_research.py \\
        >> data/targeted_research.log 2>&1

Results land in the same SQLite graph DB as scripts/01 and scripts/02
(default: data/graph.db, override with --db-path or the GRAPH_DB_PATH env
var — see config/settings.py). data/graph.db and *.log are already
git-ignored, so a local run's output stays local. The run summary is
printed to stdout/stderr — redirect it to a log file (as above) to keep a
persistent record across runs; the deployed Cloud Run Job's output instead
goes to Cloud Logging.

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

import logging
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
from src.llm.gemini_client import GeminiClient, TieredGeminiClient
from src.llm.cost_tracker import (
    BillingDenied,
    GeminiCostTracker,
    make_cost_tracker_from_settings,
    make_run_job_id,
)
from src.llm.seed_discoverer import SeedDiscoverer
from src.storage.graph_db import GraphDB
from src.storage.json_export import export_to_json, import_from_json, snapshot_exists
from src.utils.text_utils import get_domain
from scripts._pipeline_helpers import process_page
from scripts._run_lock import RunLock
from scripts._targeted_research_helpers import (
    DEFAULT_LEADS,
    ResearchLead,
    build_search_queries,
    filter_new_urls,
    lead_search_priority,
    sort_leads_by_priority,
    store_kkron_claim,
)

console = Console()
_log = logging.getLogger(__name__)

_VERTEXAI_REDIRECT_PREFIX = "https://vertexaisearch.cloud.google.com/grounding-api-redirect/"


def _resolve_redirect_url(url: str, timeout: int = 10) -> str:
    """Resolve a Vertex AI grounding redirect URL to its final destination.

    Vertex AI's Google Search grounding returns obfuscated redirect URLs
    (``vertexaisearch.cloud.google.com/grounding-api-redirect/...``) that
    302-redirect to the real source URL. The crawler can't fetch the
    redirect URL directly (returns 403), so we resolve it first via a
    lightweight HTTP GET with ``allow_redirects=True`` and use the final
    URL for crawling.

    For non-redirect URLs, returns the input unchanged.
    """
    if not url.startswith(_VERTEXAI_REDIRECT_PREFIX):
        return url
    try:
        import requests
        resp = requests.get(
            url,
            allow_redirects=True,
            timeout=timeout,
            headers={"User-Agent": settings.crawl_user_agent},
        )
        final = resp.url
        if final and not final.startswith(_VERTEXAI_REDIRECT_PREFIX):
            return final
        # If the final URL is still the redirect, try the Location header.
        location = resp.headers.get("Location", "")
        if location and not location.startswith(_VERTEXAI_REDIRECT_PREFIX):
            return location
        _log.warning("Could not resolve Vertex AI redirect URL: %s", url[:80])
        return url
    except Exception as e:
        _log.warning("Failed to resolve Vertex AI redirect URL: %s", e)
        return url


def _require_gemini(client) -> bool:
    if not client.is_available():
        console.print("[red]Gemini is not available.[/red]")
        console.print(
            "Set GEMINI_API_KEY in .env (see .env.example), or configure "
            "Vertex AI fallback (GEMINI_VERTEXAI_ENABLED=true + ADC). "
            "Get an AI Studio key from https://aistudio.google.com/apikey"
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
    allow_paid: bool = False,
) -> dict:
    """Run search + crawl + extraction for one lead. Returns a summary dict."""
    queries = build_search_queries(lead)
    discovered: list[str] = []
    for query in queries:
        seeds = discoverer.discover(
            query, exclude_urls=already_seen_urls, allow_paid=allow_paid,
        )
        for s in seeds:
            if s.url not in discovered:
                discovered.append(s.url)
        if len(discovered) >= max_results:
            break
    discovered = discovered[:max_results]

    new_urls = filter_new_urls(discovered, already_seen_urls)
    # Resolve Vertex AI redirect URLs to their final destinations.
    resolved_urls: list[str] = []
    for url in new_urls:
        already_seen_urls.add(url)
        final_url = _resolve_redirect_url(url)
        if final_url != url:
            already_seen_urls.add(final_url)
        resolved_urls.append(final_url)

    processed = 0
    errors: list[str] = []
    for url in resolved_urls:
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
    "--no-paid",
    is_flag=True,
    help="Only use free-tier AI Studio keys; don't fall back to Vertex AI (paid) when free quota is exhausted",
)
@click.option(
    "--free-quota-leads",
    default=None,
    type=int,
    help="Estimated number of leads searchable with remaining free-tier quota. Leads beyond this are deferred to the paid tier. If unset, all leads are tried free-first and only fall to paid on 429.",
)
@click.option(
    "--dry-run",
    is_flag=True,
    help="Print the configured leads and search queries; touch neither the DB nor the network",
)
def main(db_path, snapshot_dir, max_results_per_lead, skip_kkron_claims, skip_search, no_paid, free_quota_leads, dry_run):
    """Targeted research for a hand-picked list of leads (see DEFAULT_LEADS
    in scripts/_targeted_research_helpers.py)."""
    console.print("[bold cyan]Story Graph — Targeted Entity Research[/bold cyan]")
    console.print()

    if dry_run:
        sorted_leads = sort_leads_by_priority(DEFAULT_LEADS)
        console.print("[dim]Leads sorted by search priority (highest confidence-gain first):[/dim]")
        for i, lead in enumerate(sorted_leads):
            priority = lead_search_priority(lead)
            console.print(
                f"  [{i+1}] [yellow]{lead.subject_name}[/yellow] --{lead.relation.value}--> "
                f"[yellow]{lead.object_name}[/yellow]  "
                f"(priority: {priority:.2f}, kkron confidence: {lead.kkron_confidence})"
            )
            for q in build_search_queries(lead):
                console.print(f"      query: {q}")
        return

    db_file = db_path or str(settings.graph_db_abs_path)
    snap_dir = Path(snapshot_dir) if snapshot_dir else settings.graph_snapshot_abs_dir
    console.print(f"[dim]Snapshot (source of truth): {snap_dir}[/dim]")
    console.print(f"[dim]Local working DB: {db_file}[/dim]")

    # Overlap guard: parallelism=1/task_count=1 (infra/main.tf) only stops
    # fan-out within one execution, not two overlapping executions (e.g. a
    # manual `gcloud run jobs execute` racing the daily scheduled run) --
    # see scripts/_run_lock.py. A no-op when no shared lock directory is
    # configured (e.g. a local/manual run).
    run_lock = RunLock.from_settings()
    if not run_lock.acquire():
        msg = (
            "Another execution's lock is already held and not stale -- "
            "exiting to avoid racing it for the same Gemini free-tier quota."
        )
        _log.warning(msg)
        console.print(f"[yellow]{msg}[/yellow]")
        # Exit 0, not a failure: an overlapping trigger is an expected,
        # benign race to back off from, and this only logs at WARNING (not
        # ERROR) so it does not trip the Cloud Monitoring alert policy on
        # failed executions (infra/main.tf), which watches ERROR-severity
        # log entries.
        sys.exit(0)

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
        tiered_client = None
        cost_tracker = None
        if not skip_search:
            console.print()
            console.print("[bold]Phase 2: Searching + extracting from independent sources[/bold]")
            console.print("[dim]Tiered strategy: free-tier AI Studio keys first, "
                          "then Vertex AI (paid) for remaining high-value leads[/dim]")

            # Construct the cost tracker (opt-in via CLOUDMANAGEMENT_ENABLED).
            # When disabled, is_available() is False and all tracker methods
            # are no-ops — the pipeline runs exactly as before.
            cost_tracker = make_cost_tracker_from_settings()

            # Build the tiered client: free-tier keys first, Vertex AI paid
            # fallback (unless --no-paid). Pass the cost tracker so per-call
            # actuals are reported to the hub (best-effort).
            tiered_client = TieredGeminiClient(
                vertexai_enabled=not no_paid,
                cost_tracker=cost_tracker,
            )
            if not _require_gemini(tiered_client):
                cost_tracker.finalize(status="failed")
                return

            # Sort leads by confidence-gain priority — highest-value leads
            # searched first (while free quota is still available).
            sorted_leads = sort_leads_by_priority(DEFAULT_LEADS)
            console.print(f"[dim]Search order (by priority): {len(sorted_leads)} leads[/dim]")
            for i, lead in enumerate(sorted_leads):
                console.print(
                    f"  [dim]{i+1}. {lead.subject_name} --{lead.relation.value}--> "
                    f"{lead.object_name} (priority: {lead_search_priority(lead):.2f})[/dim]"
                )

            # Declare intent with the CloudManagement hub before making paid
            # calls (only if the tracker is enabled). If denied, skip Phase 2
            # early so we don't make calls the hub said we can't afford.
            intent_declared = False
            if cost_tracker.is_available():
                job_id = make_run_job_id()
                # Estimate calls: search + extraction per lead (×2 for both phases).
                estimated_calls = len(sorted_leads) * max_results_per_lead * 2
                estimated_cost = cost_tracker.suggest_expected_cost(
                    "google", settings.gemini_model, estimated_calls,
                )
                if estimated_cost is None:
                    estimated_cost = estimated_calls * 0.01
                console.print(
                    f"[dim]CloudManagement: declaring intent for {estimated_calls} "
                    f"calls (~${estimated_cost:.2f}) — job_id={job_id}[/dim]"
                )
                try:
                    intent_id = cost_tracker.declare_intent_for_run(
                        job_id=job_id,
                        expected_calls=estimated_calls,
                        expected_cost_usd=estimated_cost,
                        model=settings.gemini_model,
                    )
                    intent_declared = intent_id is not None
                    if intent_declared:
                        console.print(
                            f"[green]CloudManagement: intent approved "
                            f"(intent_id={intent_id})[/green]"
                        )
                    elif cost_tracker.degraded:
                        console.print(
                            "[yellow]CloudManagement: hub unreachable — degraded mode, "
                            "calls proceed without budget gating[/yellow]"
                        )
                except BillingDenied as e:
                    console.print(f"[red]CloudManagement: intent DENIED — {e}[/red]")
                    console.print(
                        "[red]Skipping Phase 2 (paid API calls not approved by hub).[/red]"
                    )
                    cost_tracker.finalize(status="failed")
                    skip_search = True
            else:
                console.print(
                    "[dim]CloudManagement cost tracking disabled (set CLOUDMANAGEMENT_ENABLED=true to enable)[/dim]"
                )

            discoverer = SeedDiscoverer(tiered_client)
            # Use the same tiered client for extraction too — when free
            # quota is exhausted, extraction falls back to Vertex AI paid
            # (allow_paid=True) so we don't lose crawled pages to 429.
            gemini_ext = GeminiExtractor(tiered_client, allow_paid=not no_paid)
            gemini_claim_ext = GeminiClaimExtractor(gemini_ext)
            already_seen = {s.url for s in db.get_all_sources()}

            # If --free-quota-leads is set, split leads into free and paid
            # batches. Otherwise, all leads are tried free-first and fall
            # to paid on 429 (allow_paid=True for all).
            allow_paid_for_all = free_quota_leads is None
            free_leads = sorted_leads if allow_paid_for_all else sorted_leads[:free_quota_leads]
            paid_leads = [] if allow_paid_for_all else sorted_leads[free_quota_leads:]

            for lead in (free_leads if not skip_search else []):
                # Poll kill-switch before each lead (best-effort).
                if cost_tracker.is_available():
                    kills = cost_tracker.check_killed()
                    if kills:
                        console.print(
                            f"[red]CloudManagement: kill order received — stopping Phase 2[/red]"
                        )
                        skip_search = True
                        break
                console.print(f"  [{lead.subject_name} --{lead.relation.value}--> {lead.object_name}]")
                result = _research_lead(
                    lead, db, discoverer, gemini_ext, gemini_claim_ext,
                    max_results_per_lead, already_seen,
                    allow_paid=allow_paid_for_all and not no_paid,
                )
                results.append(result)
                console.print(
                    f"    discovered={len(result['discovered'])} "
                    f"processed={result['processed']} errors={len(result['errors'])}"
                )
                for err in result["errors"]:
                    console.print(f"    [red]error:[/red] {err}")

            # Paid-tier batch: only if free quota was insufficient and
            # paid is allowed.
            if paid_leads and not no_paid and not skip_search:
                console.print()
                console.print(f"[bold yellow]Paid-tier batch: {len(paid_leads)} leads via Vertex AI[/bold yellow]")
                for lead in paid_leads:
                    if cost_tracker.is_available():
                        kills = cost_tracker.check_killed()
                        if kills:
                            console.print(
                                f"[red]CloudManagement: kill order received — stopping Phase 2[/red]"
                            )
                            skip_search = True
                            break
                    console.print(f"  [{lead.subject_name} --{lead.relation.value}--> {lead.object_name}]")
                    result = _research_lead(
                        lead, db, discoverer, gemini_ext, gemini_claim_ext,
                        max_results_per_lead, already_seen,
                        allow_paid=True,
                    )
                    results.append(result)
                    console.print(
                        f"    discovered={len(result['discovered'])} "
                        f"processed={result['processed']} errors={len(result['errors'])}"
                    )
                    for err in result["errors"]:
                        console.print(f"    [red]error:[/red] {err}")
            elif paid_leads and no_paid:
                console.print()
                console.print(f"[yellow]Skipping {len(paid_leads)} leads (--no-paid, free quota exhausted)[/yellow]")
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

        # Tiered search cost summary
        if tiered_client is not None:
            stats = tiered_client.stats
            console.print()
            console.print("[bold]Gemini API cost summary:[/bold]")
            console.print(f"  [green]Free-tier calls: {stats['free_calls']}[/green]")
            console.print(f"  [yellow]Paid-tier calls: {stats['paid_calls']}[/yellow]")
            console.print(
                f"  [dim]Free keys: {stats['free_keys_exhausted']}/"
                f"{stats['free_keys_total']} exhausted[/dim]"
            )
            if "total_cost_usd" in stats:
                console.print(f"  [cyan]Total estimated cost: ${stats['total_cost_usd']:.4f}[/cyan]")
                console.print(
                    f"  [dim]Cost tracker: {'enabled' if stats['cost_tracker_enabled'] else 'disabled'}[/dim]"
                )

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
        # Finalize cost tracking (sync final report + flush + close).
        # Best-effort — no-op when the tracker is disabled.
        if cost_tracker is not None:
            try:
                cost_tracker.finalize(status="completed")
            except Exception as e:
                _log.warning("cost_tracker finalize failed: %s", e)
        db.close()
        run_lock.release()


if __name__ == "__main__":
    main()
