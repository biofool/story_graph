"""Unit tests for the relationship discovery searcher.

Covers:
- Query template expansion
- Entity-pair generation (N*(N-1)/2 pairs)
- Search plan building and serialization
- Plan execution with mocked BraveSearchClient
- Budget exceeded handling

All tests use mocks — no API keys or network required.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.search.relationship_searcher import (
    EntityInfo,
    RelationshipSearcher,
    SearchPlan,
    entities_from_cluster,
    load_templates,
)


# ---------------------------------------------------------------------------
#  Template loading
# ---------------------------------------------------------------------------


class TestLoadTemplates:
    def test_templates_file_exists(self):
        from src.search.relationship_searcher import TEMPLATES_PATH
        assert TEMPLATES_PATH.exists(), f"Missing templates file: {TEMPLATES_PATH}"

    def test_templates_has_required_keys(self):
        data = load_templates()
        assert "pair_templates" in data
        assert "single_templates" in data
        assert isinstance(data["pair_templates"], list)
        assert isinstance(data["single_templates"], list)

    def test_pair_templates_have_required_fields(self):
        data = load_templates()
        for tmpl in data["pair_templates"]:
            assert "id" in tmpl
            assert "template" in tmpl
            assert "{a}" in tmpl["template"]
            assert "{b}" in tmpl["template"]

    def test_single_templates_have_required_fields(self):
        data = load_templates()
        for tmpl in data["single_templates"]:
            assert "id" in tmpl
            assert "template" in tmpl
            assert "{a}" in tmpl["template"]


# ---------------------------------------------------------------------------
#  Entity-pair generation
# ---------------------------------------------------------------------------


class TestEntityPairGeneration:
    def test_two_entities_one_pair(self):
        searcher = RelationshipSearcher()
        entities = [
            EntityInfo(node_id="person:a", label="Alice", entity_type="Person"),
            EntityInfo(node_id="person:b", label="Bob", entity_type="Person"),
        ]
        plan = searcher.build_plan(
            entities, include_single_queries=False, max_pair_templates=1,
        )
        # One pair × one template = 1 pair query
        assert len(plan.pair_queries) == 1
        assert plan.pair_queries[0]["entity_a"] == "person:a"
        assert plan.pair_queries[0]["entity_b"] == "person:b"

    def test_three_entities_three_pairs(self):
        searcher = RelationshipSearcher()
        entities = [
            EntityInfo(node_id=f"person:{c}", label=c.title(), entity_type="Person")
            for c in ["alice", "bob", "carol"]
        ]
        plan = searcher.build_plan(
            entities, include_single_queries=False, max_pair_templates=1,
        )
        # C(3,2) = 3 pairs × 1 template = 3 pair queries
        assert len(plan.pair_queries) == 3

    def test_four_entities_six_pairs(self):
        searcher = RelationshipSearcher()
        entities = [
            EntityInfo(node_id=f"person:{i}", label=f"P{i}", entity_type="Person")
            for i in range(4)
        ]
        plan = searcher.build_plan(
            entities, include_single_queries=False, max_pair_templates=1,
        )
        # C(4,2) = 6 pairs
        assert len(plan.pair_queries) == 6

    def test_single_entity_no_pairs(self):
        searcher = RelationshipSearcher()
        entities = [
            EntityInfo(node_id="person:a", label="Alice", entity_type="Person"),
        ]
        plan = searcher.build_plan(
            entities, include_single_queries=False,
        )
        assert len(plan.pair_queries) == 0


# ---------------------------------------------------------------------------
#  Query template expansion
# ---------------------------------------------------------------------------


class TestQueryExpansion:
    def test_pair_template_substitution(self):
        searcher = RelationshipSearcher()
        entities = [
            EntityInfo(node_id="person:nadeau", label="Robert Nadeau", entity_type="Person", style="aikido"),
            EntityInfo(node_id="person:moon", label="Richard Moon", entity_type="Person", style="aikido"),
        ]
        plan = searcher.build_plan(
            entities, include_single_queries=False, max_pair_templates=1,
        )
        q = plan.pair_queries[0]["query"]
        assert "Robert Nadeau" in q
        assert "Richard Moon" in q

    def test_single_template_substitution(self):
        searcher = RelationshipSearcher()
        entities = [
            EntityInfo(node_id="person:ralston", label="Peter Ralston", entity_type="Person", style="martial arts"),
        ]
        plan = searcher.build_plan(
            entities, include_pair_queries=False,
        )
        assert len(plan.single_queries) >= 1
        for q in plan.single_queries:
            assert "Peter Ralston" in q["query"]


# ---------------------------------------------------------------------------
#  Search plan structure
# ---------------------------------------------------------------------------


class TestSearchPlan:
    def test_plan_has_plan_id(self):
        searcher = RelationshipSearcher()
        entities = [
            EntityInfo(node_id="person:a", label="Alice", entity_type="Person"),
            EntityInfo(node_id="person:b", label="Bob", entity_type="Person"),
        ]
        plan = searcher.build_plan(entities)
        assert plan.plan_id
        assert len(plan.plan_id) == 12  # sha256[:12]

    def test_plan_total_queries(self):
        searcher = RelationshipSearcher()
        entities = [
            EntityInfo(node_id="person:a", label="Alice", entity_type="Person"),
            EntityInfo(node_id="person:b", label="Bob", entity_type="Person"),
        ]
        plan = searcher.build_plan(entities)
        assert plan.total_queries == len(plan.pair_queries) + len(plan.single_queries)

    def test_plan_serialization(self):
        searcher = RelationshipSearcher()
        entities = [
            EntityInfo(node_id="person:a", label="Alice", entity_type="Person"),
        ]
        plan = searcher.build_plan(entities)
        d = plan.to_dict()
        assert "plan_id" in d
        assert "created_at" in d
        assert "pair_queries" in d
        assert "single_queries" in d
        assert "total_queries" in d
        assert "entities" in d
        # Should be JSON-serializable
        json.dumps(d)


# ---------------------------------------------------------------------------
#  Plan execution
# ---------------------------------------------------------------------------


class TestPlanExecution:
    def test_execute_returns_results(self):
        mock_brave = MagicMock()
        mock_result = MagicMock()
        mock_result.url = "https://example.com/article"
        mock_result.title = "Found Article"
        mock_result.snippet = "Some snippet"
        mock_result.domain = "example.com"
        mock_result.age = "2020"
        mock_brave.search.return_value = [mock_result]

        searcher = RelationshipSearcher(brave_client=mock_brave)
        entities = [
            EntityInfo(node_id="person:a", label="Alice", entity_type="Person"),
            EntityInfo(node_id="person:b", label="Bob", entity_type="Person"),
        ]
        plan = searcher.build_plan(entities, max_pair_templates=1, include_single_queries=False)
        run_result = searcher.execute_plan(plan)

        assert run_result.total_results >= 1
        assert run_result.queries_executed >= 1
        assert run_result.results[0]["url"] == "https://example.com/article"

    def test_execute_deduplicates_urls(self):
        mock_brave = MagicMock()
        mock_result = MagicMock()
        mock_result.url = "https://example.com/same-article"
        mock_result.title = "Same"
        mock_result.snippet = ""
        mock_result.domain = "example.com"
        mock_result.age = ""
        mock_brave.search.return_value = [mock_result]

        searcher = RelationshipSearcher(brave_client=mock_brave)
        entities = [
            EntityInfo(node_id="person:a", label="A", entity_type="Person"),
            EntityInfo(node_id="person:b", label="B", entity_type="Person"),
            EntityInfo(node_id="person:c", label="C", entity_type="Person"),
        ]
        # Multiple pair queries will return the same URL
        plan = searcher.build_plan(entities, max_pair_templates=1, include_single_queries=False)
        run_result = searcher.execute_plan(plan)

        # URL should appear only once despite being returned for each query
        urls = [r["url"] for r in run_result.results]
        assert len(urls) == len(set(urls))

    def test_execute_without_brave_raises(self):
        searcher = RelationshipSearcher(brave_client=None)
        entities = [
            EntityInfo(node_id="person:a", label="A", entity_type="Person"),
        ]
        plan = searcher.build_plan(entities)
        with pytest.raises(RuntimeError, match="No BraveSearchClient"):
            searcher.execute_plan(plan)

    def test_execute_max_queries(self):
        mock_brave = MagicMock()
        mock_brave.search.return_value = []
        searcher = RelationshipSearcher(brave_client=mock_brave)
        entities = [
            EntityInfo(node_id="person:a", label="A", entity_type="Person"),
            EntityInfo(node_id="person:b", label="B", entity_type="Person"),
        ]
        plan = searcher.build_plan(entities)
        run_result = searcher.execute_plan(plan, max_queries=1)
        assert run_result.queries_executed <= 1

    def test_budget_exceeded_stops_execution(self):
        from src.search.quota import BudgetExceeded
        mock_brave = MagicMock()
        mock_brave.search.side_effect = BudgetExceeded("quota hit")
        searcher = RelationshipSearcher(brave_client=mock_brave)
        entities = [
            EntityInfo(node_id="person:a", label="A", entity_type="Person"),
            EntityInfo(node_id="person:b", label="B", entity_type="Person"),
        ]
        plan = searcher.build_plan(entities, max_pair_templates=2, include_single_queries=False)
        run_result = searcher.execute_plan(plan)
        # Should stop after first BudgetExceeded, not crash
        assert run_result.total_results == 0


# ---------------------------------------------------------------------------
#  Run result serialization
# ---------------------------------------------------------------------------


class TestSearchRunResult:
    def test_to_dict(self):
        mock_brave = MagicMock()
        mock_brave.search.return_value = []
        searcher = RelationshipSearcher(brave_client=mock_brave)
        entities = [
            EntityInfo(node_id="person:a", label="A", entity_type="Person"),
        ]
        plan = searcher.build_plan(entities, include_pair_queries=False)
        run_result = searcher.execute_plan(plan)
        d = run_result.to_dict()
        assert "run_id" in d
        assert "plan_id" in d
        assert "results" in d
        assert "total_results" in d
        json.dumps(d)


# ---------------------------------------------------------------------------
#  entities_from_cluster helper
# ---------------------------------------------------------------------------


class TestEntitiesFromCluster:
    def test_builds_entity_list(self):
        cluster = {
            "entities": ["person:nadeau", "person:moon"],
            "style": "aikido",
        }
        entities = entities_from_cluster(cluster)
        assert len(entities) == 2
        assert entities[0].node_id == "person:nadeau"
        assert entities[0].style == "aikido"

    def test_label_from_node_id(self):
        cluster = {
            "entities": ["person:robert-nadeau"],
            "style": "martial arts",
        }
        entities = entities_from_cluster(cluster)
        # Label derived from node ID: "robert-nadeau" -> "Robert Nadeau"
        assert entities[0].label == "Robert Nadeau"

    def test_empty_cluster(self):
        cluster = {"entities": []}
        entities = entities_from_cluster(cluster)
        assert entities == []
