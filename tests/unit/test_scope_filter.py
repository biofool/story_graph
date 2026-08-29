"""Unit tests for src/extractor/scope_filter.py — scope filtering logic.

Tests the ScopeFilter's ability to detect pages primarily about out-of-scope
entities (namesakes) and let through pages that mention in-scope entities.
No DB or network access — pure logic tests.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import pytest

from src.extractor.scope_filter import OutOfScopeEntity, ScopeFilter


def _make_filter(entities: list[OutOfScopeEntity]) -> ScopeFilter:
    """Build a ScopeFilter directly from a list of entities (bypasses JSON loading)."""
    from src.extractor.alias_resolver import KNOWN_GROUPS, KNOWN_PERSONS
    from src.utils.text_utils import normalize

    in_scope_forms: set[str] = set()
    for aliases in KNOWN_PERSONS.values():
        for alias in aliases:
            in_scope_forms.add(normalize(alias))
    for aliases in KNOWN_GROUPS.values():
        for alias in aliases:
            in_scope_forms.add(normalize(alias))

    return ScopeFilter(
        entities=entities,
        _in_scope_forms=frozenset(in_scope_forms),
    )


# A page about the law professor Richard Moon (out-of-scope namesake)
_PROFESSOR_PAGE = (
    "Professor Richard Moon of the University of Windsor "
    "published a new paper on freedom of expression. "
    "Richard Moon argues that hate speech laws should be "
    "narrowly tailored. Richard Moon is a leading scholar "
    "in Canadian constitutional law."
)

_PROFESSOR_TITLE = "Richard Moon on Freedom of Expression"

# A page about the aikido Richard Moon (in-scope)
_AIKIDO_PAGE = (
    "Richard Moon teaches aikido at Quantum Aikido. "
    "He worked at The Source restaurant with Father Yod. "
    "His book on conflict resolution is published by "
    "Inner Traditions."
)

_AIKIDO_TITLE = "Richard Moon — Aikido Teacher"


class TestScopeFilterEmpty:
    def test_empty_filter_passes_everything(self):
        sf = _make_filter([])
        assert sf.is_empty
        assert not sf.is_page_out_of_scope("Richard Moon", _PROFESSOR_PAGE, "https://example.com")


class TestScopeFilterProfessor:
    @pytest.fixture
    def filter_with_professor(self):
        return _make_filter([
            OutOfScopeEntity(
                canonical_name="richard moon (law professor)",
                entity_type="person",
                surface_forms=["Richard Moon", "Professor Richard Moon"],
                note="Canadian constitutional-law professor",
                normalized_forms=frozenset({"richard moon", "professor richard moon"}),
            ),
        ])

    def test_title_match_filters_page(self, filter_with_professor):
        """Page title containing the out-of-scope name → filtered."""
        assert filter_with_professor.is_page_out_of_scope(
            _PROFESSOR_TITLE, _PROFESSOR_PAGE, "https://uwindsor.ca/article"
        )

    def test_text_mention_threshold_filters_page(self, filter_with_professor):
        """3+ mentions in text without title match → filtered."""
        assert filter_with_professor.is_page_out_of_scope(
            "A Scholar's Work", _PROFESSOR_PAGE, "https://uwindsor.ca/article"
        )

    def test_in_scope_page_not_filtered(self, filter_with_professor):
        """Page about the aikido Richard Moon (mentions Father Yod) → NOT filtered."""
        assert not filter_with_professor.is_page_out_of_scope(
            _AIKIDO_TITLE, _AIKIDO_PAGE, "https://quantumaikido.com/about"
        )

    def test_page_mentioning_both_kept(self, filter_with_professor):
        """Page mentioning both out-of-scope and in-scope entities → NOT filtered."""
        mixed_page = (
            "Professor Richard Moon published a paper. "
            "Meanwhile, Father Yod and The Source Family "
            "were active in Los Angeles. Richard Moon "
            "the professor is not the same as Richard Moon "
            "the aikido teacher."
        )
        assert not filter_with_professor.is_page_out_of_scope(
            "Two Richard Moons", mixed_page, "https://example.com/article"
        )

    def test_no_url_is_fine(self, filter_with_professor):
        """Filter works without a URL (url=None)."""
        assert filter_with_professor.is_page_out_of_scope(
            _PROFESSOR_TITLE, _PROFESSOR_PAGE, None
        )


class TestScopeFilterFromConfig:
    def test_loads_from_json_file(self, tmp_path):
        """ScopeFilter.from_config loads entities from a JSON file."""
        config = {
            "persons": [
                {
                    "canonical_name": "richard moon (chef)",
                    "surface_forms": ["Richard Moon", "Rick Moon"],
                    "note": "Australian chef",
                },
            ],
            "events": [
                {
                    "canonical_name": "Some Unrelated Event",
                    "surface_forms": ["Some Unrelated Event"],
                    "note": "Not part of the story",
                },
            ],
        }
        config_path = tmp_path / "out_of_scope.json"
        config_path.write_text(json.dumps(config))

        sf = ScopeFilter.from_config(config_path)
        assert not sf.is_empty
        assert len(sf.entities) == 2
        assert sf.entities[0].canonical_name == "richard moon (chef)"
        assert sf.entities[0].entity_type == "person"
        assert sf.entities[1].canonical_name == "Some Unrelated Event"
        assert sf.entities[1].entity_type == "event"

    def test_missing_config_file_returns_empty_filter(self, tmp_path):
        """Missing config file → empty filter (no behavior change)."""
        sf = ScopeFilter.from_config(tmp_path / "nonexistent.json")
        assert sf.is_empty

    def test_malformed_json_returns_empty_filter(self, tmp_path):
        """Malformed JSON → empty filter with a warning, no crash."""
        config_path = tmp_path / "bad.json"
        config_path.write_text("{not valid json")
        sf = ScopeFilter.from_config(config_path)
        assert sf.is_empty


class TestOutOfScopeNodeIds:
    def test_person_node_id(self):
        entity = OutOfScopeEntity(
            canonical_name="richard moon (law professor)",
            entity_type="person",
            surface_forms=["Richard Moon"],
            normalized_forms=frozenset({"richard moon"}),
        )
        assert entity.node_id == "person:richard-moon-law-professor"

    def test_event_node_id(self):
        entity = OutOfScopeEntity(
            canonical_name="Some Unrelated Event",
            entity_type="event",
            surface_forms=["Some Unrelated Event"],
            normalized_forms=frozenset({"some unrelated event"}),
        )
        assert entity.node_id == "event:some-unrelated-event"
