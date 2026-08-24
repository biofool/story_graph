"""Unit tests for scripts/_targeted_research_helpers.py — pure logic only.

``store_kkron_claim``/``ensure_kkron_source`` touch the DB (no network) and
are covered instead by
tests/integration/test_targeted_research_pipeline.py.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from src.storage.models import ClaimStance, ClaimType, EvidenceMode, RelationType
from scripts._targeted_research_helpers import (
    DEFAULT_LEADS,
    KKRON_CONFIDENCE_CEILING,
    KKRON_SOURCE_PERSON_ID,
    ResearchLead,
    build_kkron_claim_record,
    build_search_queries,
    effective_kkron_confidence,
    filter_new_urls,
)


class TestEffectiveKkronConfidence:
    def test_clamps_high_confidence_to_ceiling(self):
        assert effective_kkron_confidence(0.95) == KKRON_CONFIDENCE_CEILING

    def test_leaves_low_confidence_untouched(self):
        assert effective_kkron_confidence(0.2) == 0.2

    def test_clamps_negative_to_zero(self):
        assert effective_kkron_confidence(-0.5) == 0.0

    def test_wild_mountain_cafe_lead_stays_below_more_certain_leads(self):
        by_object = {lead.object_name: lead for lead in DEFAULT_LEADS if lead.subject_name == "Richard Moon"}
        wild_mountain = effective_kkron_confidence(by_object["Wild Mountain Cafe"].kkron_confidence)
        the_source = effective_kkron_confidence(by_object["The Source"].kkron_confidence)
        assert wild_mountain < the_source


class TestBuildSearchQueries:
    def test_includes_subject_and_object(self):
        lead = ResearchLead(
            subject_name="Richard Moon", subject_type="person",
            relation=RelationType.WORKED_AT,
            object_name="The Source", object_type="group",
            kkron_claim_text="x", kkron_confidence=0.5,
        )
        queries = build_search_queries(lead)
        assert any("Richard Moon" in q and "The Source" in q for q in queries)

    def test_extra_queries_come_first_and_are_included(self):
        lead = ResearchLead(
            subject_name="A", subject_type="person",
            relation=RelationType.WORKED_AT,
            object_name="B", object_type="group",
            kkron_claim_text="x", kkron_confidence=0.5,
            extra_queries=("hand tuned query",),
        )
        queries = build_search_queries(lead)
        assert queries[0] == "hand tuned query"

    def test_dedupes_case_insensitively(self):
        lead = ResearchLead(
            subject_name="A", subject_type="person",
            relation=RelationType.WORKED_AT,
            object_name="B", object_type="group",
            kkron_claim_text="x", kkron_confidence=0.5,
            extra_queries=("A worked at B",),
        )
        queries = build_search_queries(lead)
        assert sum(1 for q in queries if q.lower() == "a worked at b") == 1

    def test_relation_phrase_used_for_founded(self):
        lead = ResearchLead(
            subject_name="Jim Baker", subject_type="person",
            relation=RelationType.FOUNDED,
            object_name="Aware Inn", object_type="group",
            kkron_claim_text="x", kkron_confidence=0.5,
        )
        queries = build_search_queries(lead)
        assert any("founded" in q for q in queries)

    def test_unmapped_relation_falls_back_to_generic_phrase(self):
        lead = ResearchLead(
            subject_name="A", subject_type="person",
            relation=RelationType.CONTRADICTS,
            object_name="B", object_type="person",
            kkron_claim_text="x", kkron_confidence=0.5,
        )
        queries = build_search_queries(lead)
        assert any("connected to" in q for q in queries)


class TestBuildKkronClaimRecord:
    def test_confidence_is_clamped_but_raw_value_preserved(self):
        lead = DEFAULT_LEADS[0]
        record = build_kkron_claim_record(lead)
        assert record["confidence"] <= KKRON_CONFIDENCE_CEILING
        assert record["raw_kkron_confidence"] == lead.kkron_confidence

    def test_speaker_is_kkron_source(self):
        record = build_kkron_claim_record(DEFAULT_LEADS[0])
        assert record["speaker_id"] == KKRON_SOURCE_PERSON_ID

    def test_claim_type_stance_and_evidence_mode_are_valid_enum_values(self):
        record = build_kkron_claim_record(DEFAULT_LEADS[0])
        assert record["claim_type"] == ClaimType.BIOGRAPHICAL.value
        assert record["stance"] == ClaimStance.NEUTRAL.value
        assert record["evidence_mode"] == EvidenceMode.FIRST_PERSON.value

    def test_claim_id_is_stable_and_namespaced(self):
        record1 = build_kkron_claim_record(DEFAULT_LEADS[0])
        record2 = build_kkron_claim_record(DEFAULT_LEADS[0])
        assert record1["id"] == record2["id"]
        assert record1["id"].startswith("claim:kkron:")

    def test_different_leads_get_different_claim_ids(self):
        ids = {build_kkron_claim_record(lead)["id"] for lead in DEFAULT_LEADS}
        assert len(ids) == len(DEFAULT_LEADS)


class TestFilterNewUrls:
    def test_drops_already_known(self):
        result = filter_new_urls(["https://a.com", "https://b.com"], {"https://a.com"})
        assert result == ["https://b.com"]

    def test_dedupes_within_input(self):
        result = filter_new_urls(["https://a.com", "https://a.com"], set())
        assert result == ["https://a.com"]

    def test_preserves_order(self):
        result = filter_new_urls(["https://b.com", "https://a.com"], set())
        assert result == ["https://b.com", "https://a.com"]

    def test_skips_falsy_entries(self):
        result = filter_new_urls(["", "https://a.com", None], set())  # type: ignore[list-item]
        assert result == ["https://a.com"]


class TestDefaultLeads:
    def test_all_leads_cover_expected_entities(self):
        names = {lead.subject_name for lead in DEFAULT_LEADS} | {lead.object_name for lead in DEFAULT_LEADS}
        assert {"Richard Moon", "Jim Baker", "The Source", "Aware Inn", "Wild Mountain Cafe"} <= names

    def test_wild_mountain_cafe_lead_is_marked_lower_confidence(self):
        """kkron flagged the Wild Mountain Cafe lead as his least certain of
        the original Source Family leads, and its stored confidence has to
        reflect that.

        The comparison is against the other *kkron-sourced Source Family*
        leads only. Citation leads carry a ``source_confidence`` on a
        different scale entirely, and the Doug Stone lead is deliberately
        lower still (0.2) — research actively failed to support it, which is
        covered by :meth:`test_doug_stone_lead_is_the_least_supported`.
        """
        lead = next(l for l in DEFAULT_LEADS if l.object_name == "Wild Mountain Cafe")
        source_family_leads = {"The Source", "Aware Inn"}
        others = [
            l.kkron_confidence
            for l in DEFAULT_LEADS
            if l.source_url is None and l.object_name in source_family_leads
        ]
        assert others, "expected other kkron-sourced Source Family leads to compare against"
        assert all(lead.kkron_confidence < c for c in others)

    def test_doug_stone_lead_is_the_least_supported(self):
        """The Doug Stone / Cyprus Fulbright lead is stored at the lowest
        confidence of any kkron lead: it is the one hypothesis the research
        actively contradicted rather than merely failed to corroborate."""
        stone = next(
            lead for lead in DEFAULT_LEADS
            if lead.subject_name == "Doug Stone" and lead.source_url is None
        )
        others = [
            lead.kkron_confidence for lead in DEFAULT_LEADS
            if lead.source_url is None and lead is not stone
        ]
        assert all(stone.kkron_confidence < c for c in others)

    def test_subject_and_object_ids_resolve(self):
        for lead in DEFAULT_LEADS:
            assert lead.subject_id()
            assert lead.object_id()
