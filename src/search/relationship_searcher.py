"""Relationship discovery searcher.

Generates entity-pair queries from graph nodes, executes them via
BraveSearchClient, and produces review-ready result sets. The core
innovation is searching for documentation of *relationships between*
people, not just single-entity enrichment.

Query templates are loaded from data/search_terms/relationship_templates.json.
Priority clusters are defined in the same file.
"""

from __future__ import annotations

import hashlib
import itertools
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.search.brave_search_client import BraveSearchClient, SearchResult
from src.search.quota import BudgetExceeded, QuotaTracker
from src.search.search_cache import SearchCache

_log = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
TEMPLATES_PATH = PROJECT_ROOT / "data" / "search_terms" / "relationship_templates.json"


@dataclass
class EntityInfo:
    """Info about a graph entity for query generation."""

    node_id: str
    label: str
    entity_type: str
    aliases: list[str] = field(default_factory=list)
    style: str = ""
    org: str = ""
    year: str = ""


@dataclass
class SearchPlan:
    """A plan of queries to execute, reviewable before running."""

    plan_id: str
    created_at: str
    cluster_id: str
    cluster_name: str
    entities: list[EntityInfo]
    pair_queries: list[dict]
    single_queries: list[dict]
    total_queries: int

    def to_dict(self) -> dict:
        return {
            "plan_id": self.plan_id,
            "created_at": self.created_at,
            "cluster_id": self.cluster_id,
            "cluster_name": self.cluster_name,
            "entities": [
                {
                    "node_id": e.node_id,
                    "label": e.label,
                    "entity_type": e.entity_type,
                    "aliases": e.aliases,
                    "style": e.style,
                }
                for e in self.entities
            ],
            "pair_queries": self.pair_queries,
            "single_queries": self.single_queries,
            "total_queries": self.total_queries,
        }


@dataclass
class SearchRunResult:
    """Results of a search run, for triage review."""

    run_id: str
    plan_id: str
    created_at: str
    results: list[dict]
    total_results: int
    queries_executed: int
    queries_cached: int
    budget_status: dict

    def to_dict(self) -> dict:
        return {
            "run_id": self.run_id,
            "plan_id": self.plan_id,
            "created_at": self.created_at,
            "results": self.results,
            "total_results": self.total_results,
            "queries_executed": self.queries_executed,
            "queries_cached": self.queries_cached,
            "budget_status": self.budget_status,
        }


def load_templates() -> dict:
    """Load query templates from the JSON data file."""
    with open(TEMPLATES_PATH) as f:
        return json.load(f)


def load_priority_clusters() -> list[dict]:
    """Load priority cluster definitions."""
    data = load_templates()
    return data.get("priority_clusters", [])


class RelationshipSearcher:
    """Generates and executes relationship discovery searches."""

    def __init__(
        self,
        brave_client: BraveSearchClient | None = None,
        cache: SearchCache | None = None,
        quota: QuotaTracker | None = None,
    ):
        self.brave = brave_client
        self.cache = cache
        self.quota = quota
        self._templates = load_templates()

    def build_plan(
        self,
        entities: list[EntityInfo],
        cluster_id: str = "custom",
        cluster_name: str = "Custom cluster",
        include_pair_queries: bool = True,
        include_single_queries: bool = True,
        max_pair_templates: int | None = None,
    ) -> SearchPlan:
        """Build a reviewable search plan from entities and templates.

        Generates all pair combinations and applies each pair template,
        plus single-entity enrichment queries.
        """
        pair_queries: list[dict] = []
        single_queries: list[dict] = []

        pair_templates = self._templates.get("pair_templates", [])
        single_templates = self._templates.get("single_templates", [])

        if max_pair_templates:
            pair_templates = pair_templates[:max_pair_templates]

        if include_pair_queries and len(entities) >= 2:
            for i, j in itertools.combinations(range(len(entities)), 2):
                a = entities[i]
                b = entities[j]
                for tmpl in pair_templates:
                    query_text = tmpl["template"].format(
                        a=a.label, b=b.label, style=a.style or "aikido"
                    )
                    pair_queries.append({
                        "query": query_text,
                        "template_id": tmpl["id"],
                        "target_edge": tmpl.get("target_edge", "MENTIONS"),
                        "entity_a": a.node_id,
                        "entity_b": b.node_id,
                        "description": tmpl.get("description", ""),
                    })

        if include_single_queries:
            for entity in entities:
                for tmpl in single_templates:
                    try:
                        query_text = tmpl["template"].format(
                            a=entity.label,
                            style=entity.style or "aikido",
                            org=entity.org or "",
                            year=entity.year or "",
                        )
                    except KeyError:
                        query_text = tmpl["template"].format(
                            a=entity.label, style=entity.style or "aikido"
                        )
                    single_queries.append({
                        "query": query_text,
                        "template_id": tmpl["id"],
                        "entity": entity.node_id,
                        "description": tmpl.get("description", ""),
                    })

        plan_id = hashlib.sha256(
            f"{cluster_id}:{datetime.now(timezone.utc).isoformat()}".encode()
        ).hexdigest()[:12]

        return SearchPlan(
            plan_id=plan_id,
            created_at=datetime.now(timezone.utc).isoformat(),
            cluster_id=cluster_id,
            cluster_name=cluster_name,
            entities=entities,
            pair_queries=pair_queries,
            single_queries=single_queries,
            total_queries=len(pair_queries) + len(single_queries),
        )

    def execute_plan(
        self,
        plan: SearchPlan,
        max_queries: int | None = None,
        count_per_query: int = 10,
    ) -> SearchRunResult:
        """Execute a search plan and return results for triage.

        Each query is sent to BraveSearchClient (with cache + quota).
        Results are deduplicated by URL across all queries.
        """
        if not self.brave:
            raise RuntimeError("No BraveSearchClient configured")

        all_queries = plan.pair_queries + plan.single_queries
        if max_queries:
            all_queries = all_queries[:max_queries]

        all_results: list[dict] = []
        seen_urls: set[str] = set()
        queries_executed = 0
        queries_cached = 0

        for q in all_queries:
            query_text = q["query"]
            try:
                results = self.brave.search(query_text, count=count_per_query)
            except BudgetExceeded as e:
                _log.warning("Budget exceeded, stopping: %s", e)
                break

            queries_executed += 1

            for r in results:
                if r.url in seen_urls:
                    continue
                seen_urls.add(r.url)
                all_results.append({
                    "url": r.url,
                    "title": r.title,
                    "snippet": r.snippet,
                    "domain": r.domain,
                    "age": r.age,
                    "query": query_text,
                    "template_id": q.get("template_id", ""),
                    "target_edge": q.get("target_edge", "MENTIONS"),
                    "entity_a": q.get("entity_a", ""),
                    "entity_b": q.get("entity_b", ""),
                    "provider": "brave",
                })

        budget_status = self.quota.status() if self.quota else {}

        run_id = hashlib.sha256(
            f"{plan.plan_id}:{datetime.now(timezone.utc).isoformat()}".encode()
        ).hexdigest()[:12]

        return SearchRunResult(
            run_id=run_id,
            plan_id=plan.plan_id,
            created_at=datetime.now(timezone.utc).isoformat(),
            results=all_results,
            total_results=len(all_results),
            queries_executed=queries_executed,
            queries_cached=queries_cached,
            budget_status=budget_status,
        )


def entities_from_cluster(cluster: dict) -> list[EntityInfo]:
    """Build EntityInfo list from a priority cluster definition.

    Looks up node labels from the graph snapshot.
    """
    entities = []
    for node_id in cluster.get("entities", []):
        # Try to find the node in the snapshot
        label = node_id.split(":")[-1].replace("-", " ").title()
        entity = EntityInfo(
            node_id=node_id,
            label=label,
            entity_type="Person",
            style=cluster.get("style", "aikido"),
        )
        entities.append(entity)
    return entities


def load_entity_labels_from_snapshot(snapshot_dir: Path) -> dict[str, str]:
    """Load node_id → label mapping from graph snapshot."""
    labels = {}
    nodes_file = snapshot_dir / "nodes.jsonl"
    if nodes_file.exists():
        with open(nodes_file) as f:
            for line in f:
                node = json.loads(line)
                labels[node["id"]] = node.get("label", node["id"])
    return labels


def enrich_entities_with_labels(
    entities: list[EntityInfo], labels: dict[str, str]
) -> list[EntityInfo]:
    """Update entity labels from the graph snapshot."""
    for e in entities:
        if e.node_id in labels:
            e.label = labels[e.node_id]
    return entities
