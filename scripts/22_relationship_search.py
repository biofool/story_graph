#!/usr/bin/env python3
"""
Relationship discovery search CLI.

Executes targeted web searches to find documentation of relationships
between people, groups, and places in the Story Graph. Uses Brave Search
API with caching, quota enforcement, and human review gates.

Workflow:
  1. plan    — Generate a reviewable query plan (no searches executed)
  2. search  — Execute an approved plan and produce results for triage
  3. triage  — Review search results and approve URLs for fetching
  4. fetch   — Fetch approved URLs and extract claims (future)

Usage:
    # Generate a plan for the Bay Area Aikido cluster
    python scripts/22_relationship_search.py plan --cluster bay_area_aikido_lineage

    # Generate a plan for specific entities
    python scripts/22_relationship_search.py plan \
        --entities person:dan-millman person:robert-nadeau person:richard-moon-aikido person:bob-noha

    # Execute a plan (requires plan file from 'plan' step)
    python scripts/22_relationship_search.py search --plan-file data/search_runs/<plan_id>_plan.json

    # Dry-run: show plan without writing files
    python scripts/22_relationship_search.py plan --cluster bay_area_aikido_lineage --dry-run
"""

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from config.settings import settings
from src.search.bing_search_client import BingSearchClient
from src.search.brave_search_client import BraveSearchClient
from src.search.duckduckgo_search_client import DuckDuckGoSearchClient
from src.search.quota import QuotaTracker
from src.search.relationship_searcher import (
    RelationshipSearcher,
    entities_from_cluster,
    enrich_entities_with_labels,
    load_entity_labels_from_snapshot,
    load_priority_clusters,
)
from src.search.search_cache import SearchCache


def cmd_plan(args):
    """Generate a reviewable search plan."""
    runs_dir = Path(settings.search_runs_dir)
    if not runs_dir.is_absolute():
        runs_dir = PROJECT_ROOT / runs_dir
    runs_dir.mkdir(parents=True, exist_ok=True)

    # Get entities
    if args.cluster:
        clusters = load_priority_clusters()
        cluster = next((c for c in clusters if c["id"] == args.cluster), None)
        if not cluster:
            print(f"[ERROR] Cluster '{args.cluster}' not found.")
            print(f"Available clusters: {[c['id'] for c in clusters]}")
            return 1
        entities = entities_from_cluster(cluster)
        cluster_id = cluster["id"]
        cluster_name = cluster.get("name", cluster_id)
    elif args.entities:
        entities = []
        for nid in args.entities:
            label = nid.split(":")[-1].replace("-", " ").title()
            entities.append(type(entities_from_cluster({}))(  # EntityInfo
                node_id=nid, label=label, entity_type="Person", style=args.style or "aikido"
            ))
        cluster_id = "custom"
        cluster_name = "Custom cluster"
    else:
        print("[ERROR] Provide --cluster or --entities")
        return 1

    # Enrich with labels from snapshot
    snapshot_dir = Path(settings.graph_snapshot_dir)
    if not snapshot_dir.is_absolute():
        snapshot_dir = PROJECT_ROOT / snapshot_dir
    labels = load_entity_labels_from_snapshot(snapshot_dir)
    entities = enrich_entities_with_labels(entities, labels)

    # Build plan
    cache = SearchCache(
        PROJECT_ROOT / settings.search_cache_path,
        ttl_days=settings.search_cache_ttl_days,
    )
    quota = QuotaTracker(
        PROJECT_ROOT / settings.search_cache_path,
        session_budget=settings.search_session_budget_queries,
        monthly_budget=settings.search_monthly_budget_queries,
    )
    searcher = RelationshipSearcher(cache=cache, quota=quota)
    plan = searcher.build_plan(
        entities=entities,
        cluster_id=cluster_id,
        cluster_name=cluster_name,
        include_pair_queries=not args.single_only,
        include_single_queries=not args.pair_only,
        max_pair_templates=args.max_pair_templates,
    )

    plan_dict = plan.to_dict()
    plan_file = runs_dir / f"{plan.plan_id}_plan.json"

    print()
    print("=" * 70)
    print(f"  SEARCH PLAN: {plan.cluster_name}")
    print(f"  Plan ID: {plan.plan_id}")
    print("=" * 70)
    print()
    print(f"Entities ({len(plan.entities)}):")
    for e in plan.entities:
        print(f"  {e.node_id:40} → \"{e.label}\"")
    print()
    print(f"Pair queries ({len(plan.pair_queries)}):")
    for q in plan.pair_queries[:20]:
        print(f"  [{q['target_edge']:12}] {q['query']}")
    if len(plan.pair_queries) > 20:
        print(f"  ... and {len(plan.pair_queries) - 20} more")
    print()
    print(f"Single-entity queries ({len(plan.single_queries)}):")
    for q in plan.single_queries[:10]:
        print(f"  {q['query']}")
    if len(plan.single_queries) > 10:
        print(f"  ... and {len(plan.single_queries) - 10} more")
    print()
    print(f"Total queries: {plan.total_queries}")
    print(f"Session budget: {settings.search_session_budget_queries}")
    print(f"Monthly budget: {settings.search_monthly_budget_queries}")
    print()

    if args.dry_run:
        print("[dry-run] Plan file not written.")
    else:
        with open(plan_file, "w") as f:
            json.dump(plan_dict, f, indent=2)
        print(f"Plan written to: {plan_file}")
        print()
        print("Review the plan, then execute with:")
        print(f"  python scripts/22_relationship_search.py search --plan-file {plan_file}")

    cache.close()
    quota.close()
    return 0


def cmd_search(args):
    """Execute an approved search plan."""
    plan_file = Path(args.plan_file)
    if not plan_file.exists():
        print(f"[ERROR] Plan file not found: {plan_file}")
        return 1

    with open(plan_file) as f:
        plan_dict = json.load(f)

    runs_dir = Path(settings.search_runs_dir)
    if not runs_dir.is_absolute():
        runs_dir = PROJECT_ROOT / runs_dir
    runs_dir.mkdir(parents=True, exist_ok=True)

    # Reconstruct entities
    from src.search.relationship_searcher import EntityInfo
    entities = [
        EntityInfo(
            node_id=e["node_id"],
            label=e["label"],
            entity_type=e.get("entity_type", "Person"),
            style=e.get("style", "aikido"),
        )
        for e in plan_dict["entities"]
    ]

    # Build search infrastructure
    cache = SearchCache(
        PROJECT_ROOT / settings.search_cache_path,
        ttl_days=settings.search_cache_ttl_days,
    )
    quota = QuotaTracker(
        PROJECT_ROOT / settings.search_cache_path,
        session_budget=settings.search_session_budget_queries,
        monthly_budget=settings.search_monthly_budget_queries,
    )

    # Try Brave first, fall back to DuckDuckGo
    search_client = None
    provider = "duckduckgo"

    brave = BraveSearchClient(
        api_key=settings.brave_search_api_key,
        cache=cache,
        quota_tracker=quota,
        delay_seconds=args.delay,
    )
    if brave.is_available() and not args.use_ddgo:
        # Quick quota check
        try:
            import urllib.request as _urllib
            import json as _json
            _test_url = "https://api.search.brave.com/res/v1/web/search?q=test&count=1"
            _req = _urllib.Request(_test_url, headers={
                "Accept": "application/json",
                "X-Subscription-Token": settings.brave_search_api_key,
            })
            with _urllib.urlopen(_req, timeout=10) as _resp:
                _data = _json.loads(_resp.read().decode())
                if _data.get("web", {}).get("results"):
                    search_client = brave
                    provider = "brave"
                else:
                    print("[WARNING] Brave API returned no results (quota=0?). Falling back to DuckDuckGo.")
        except Exception as e:
            print(f"[WARNING] Brave API check failed ({e}). Falling back to DuckDuckGo.")

    if search_client is None:
        print("[INFO] Using Bing HTML search (no API key required, free)")
        search_client = BingSearchClient(
            cache=cache,
            quota_tracker=quota,
            delay_seconds=args.delay,
        )

    searcher = RelationshipSearcher(brave_client=search_client, cache=cache, quota=quota)

    # Rebuild plan object
    from src.search.relationship_searcher import SearchPlan
    plan = SearchPlan(
        plan_id=plan_dict["plan_id"],
        created_at=plan_dict["created_at"],
        cluster_id=plan_dict["cluster_id"],
        cluster_name=plan_dict["cluster_name"],
        entities=entities,
        pair_queries=plan_dict["pair_queries"],
        single_queries=plan_dict["single_queries"],
        total_queries=plan_dict["total_queries"],
    )

    max_q = args.max_queries or settings.search_session_budget_queries
    print()
    print("=" * 70)
    print(f"  EXECUTING SEARCH: {plan.cluster_name}")
    print(f"  Plan ID: {plan.plan_id}")
    print(f"  Max queries: {max_q}")
    print("=" * 70)
    print()

    result = searcher.execute_plan(plan, max_queries=max_q, count_per_query=args.count)

    # Write results
    results_file = runs_dir / f"{result.run_id}_results.json"
    with open(results_file, "w") as f:
        json.dump(result.to_dict(), f, indent=2)

    print(f"Queries executed: {result.queries_executed}")
    print(f"Total unique results: {result.total_results}")
    print()
    print("Top results:")
    for r in result.results[:20]:
        print(f"  [{r['target_edge']:12}] {r['url']}")
        print(f"    title: {r['title'][:70]}")
        print(f"    snippet: {r['snippet'][:100]}")
        print()
    if len(result.results) > 20:
        print(f"  ... and {len(result.results) - 20} more")
    print()
    print(f"Budget status: {json.dumps(result.budget_status, indent=2)}")
    print()
    print(f"Results written to: {results_file}")
    print()
    print("Review results, then triage with:")
    print(f"  python scripts/22_relationship_search.py triage --results-file {results_file}")

    cache.close()
    quota.close()
    return 0


def cmd_triage(args):
    """Review search results and produce an approved URL list for fetching."""
    results_file = Path(args.results_file)
    if not results_file.exists():
        print(f"[ERROR] Results file not found: {results_file}")
        return 1

    with open(results_file) as f:
        data = json.load(f)

    runs_dir = Path(settings.search_runs_dir)
    if not runs_dir.is_absolute():
        runs_dir = PROJECT_ROOT / runs_dir

    results = data["results"]
    print()
    print("=" * 70)
    print(f"  TRIAGE: {len(results)} search results")
    print("=" * 70)
    print()

    # Auto-classify by domain quality
    trusted_domains = {
        "en.wikipedia.org", "aikidojournal.com", "danzan.com", "kodenkan.com",
        "thetaichinotebook.com", "openmindadventures.com", "usagym.org",
        "usghof.org", "whistlekickmartialartsradio.com",
    }
    skip_domains = {"youtube.com", "facebook.com", "instagram.com", "twitter.com", "x.com"}

    approved = []
    rejected = []
    manual = []

    for r in results:
        domain = r.get("domain", "")
        if domain in skip_domains:
            r["triage"] = "auto_reject"
            r["triage_reason"] = f"social media domain ({domain})"
            rejected.append(r)
        elif domain in trusted_domains:
            r["triage"] = "auto_approve"
            r["triage_reason"] = f"trusted domain ({domain})"
            approved.append(r)
        else:
            r["triage"] = "manual"
            r["triage_reason"] = "unclassified domain"
            manual.append(r)

    print(f"Auto-approved (trusted domains): {len(approved)}")
    for r in approved:
        print(f"  ✓ {r['url']}")
    print()
    print(f"Auto-rejected (social media): {len(rejected)}")
    for r in rejected:
        print(f"  ✗ {r['url']}")
    print()
    print(f"Manual review needed: {len(manual)}")
    for r in manual:
        print(f"  ? {r['url']}")
        print(f"    title: {r['title'][:70]}")
        print(f"    snippet: {r['snippet'][:100]}")
        print()

    # Write triage file
    triage_file = runs_dir / f"{data['run_id']}_triage.json"
    triage_data = {
        "run_id": data["run_id"],
        "triaged_at": __import__("datetime").datetime.now(
            __import__("datetime").timezone.utc
        ).isoformat(),
        "approved": approved,
        "rejected": rejected,
        "manual": manual,
    }
    with open(triage_file, "w") as f:
        json.dump(triage_data, f, indent=2)

    print(f"Triage file written to: {triage_file}")
    print()
    print("Next step: fetch approved URLs and extract claims (future feature)")
    return 0


def cmd_list_clusters(args):
    """List available priority clusters."""
    clusters = load_priority_clusters()
    print()
    print("Available priority clusters:")
    print()
    for c in clusters:
        print(f"  {c['id']:40} {c.get('name', c['id'])}")
        print(f"    entities: {', '.join(c.get('entities', []))}")
        print(f"    rationale: {c.get('rationale', '')[:80]}")
        print()
    return 0


def main():
    parser = argparse.ArgumentParser(
        description="Relationship discovery search for Story Graph"
    )
    sub = parser.add_subparsers(dest="command")

    # plan
    p_plan = sub.add_parser("plan", help="Generate a reviewable search plan")
    p_plan.add_argument("--cluster", help="Priority cluster ID")
    p_plan.add_argument("--entities", nargs="+", help="Entity node IDs")
    p_plan.add_argument("--style", default="aikido", help="Martial art / domain keyword")
    p_plan.add_argument("--pair-only", action="store_true", help="Only pair queries")
    p_plan.add_argument("--single-only", action="store_true", help="Only single-entity queries")
    p_plan.add_argument("--max-pair-templates", type=int, default=None, help="Limit pair templates")
    p_plan.add_argument("--dry-run", action="store_true", help="Show plan without writing")
    p_plan.set_defaults(func=cmd_plan)

    # search
    p_search = sub.add_parser("search", help="Execute an approved plan")
    p_search.add_argument("--plan-file", required=True, help="Plan JSON file from 'plan' step")
    p_search.add_argument("--max-queries", type=int, default=None, help="Override max queries")
    p_search.add_argument("--count", type=int, default=10, help="Results per query")
    p_search.add_argument("--delay", type=float, default=2.0, help="Delay between queries (seconds)")
    p_search.add_argument("--use-ddgo", action="store_true", help="Force DuckDuckGo instead of Brave")
    p_search.set_defaults(func=cmd_search)

    # triage
    p_triage = sub.add_parser("triage", help="Review and classify search results")
    p_triage.add_argument("--results-file", required=True, help="Results JSON file from 'search' step")
    p_triage.set_defaults(func=cmd_triage)

    # list-clusters
    p_list = sub.add_parser("list-clusters", help="List available priority clusters")
    p_list.set_defaults(func=cmd_list_clusters)

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        return 1

    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
