"""Unit tests for scripts/_cyprus_crtg_helpers.py — pure logic only.

``store_lead_claim``/``ensure_kkron_source`` touch the DB (no network) and
are covered instead by tests/integration/test_cyprus_crtg_pipeline.py.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from src.storage.models import ClaimStance, ClaimType, EvidenceMode, RelationType
from scripts._cyprus_crtg_helpers import (
    CRTG_GROUP_NAME,
    CRTG_WIKIPEDIA_TALK_URL,
    CYPRUS_FULBRIGHT_COMMISSION_NAME,
    DEFAULT_LEADS,
    KKRON_CONFIDENCE_CEILING,
    KKRON_SOURCE_PERSON_ID,
    ResearchLead,
    build_claim_record,
    build_search_queries,
    citation_source_url,
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

    def test_diana_lead_stays_below_more_certain_kkron_leads(self):
        diana = next(l for l in DEFAULT_LEADS if l.subject_name == "Diana")
        stone = next(
            l for l in DEFAULT_LEADS
            if l.subject_name == "Douglas Stone" and l.object_name == CRTG_GROUP_NAME
        )
        assert (
            effective_kkron_confidence(diana.kkron_confidence)
            < effective_kkron_confidence(stone.kkron_confidence)
        )


class TestLeadProvenance:
    def test_kkron_lead_detected(self):
        lead = ResearchLead(
            subject_name="A", subject_type="person",
            relation=RelationType.MEMBER_OF, object_name="B", object_type="group",
            kkron_claim_text="x", kkron_confidence=0.5,
        )
        assert lead.provenance() == "kkron"

    def test_citation_lead_detected(self):
        lead = ResearchLead(
            subject_name="A", subject_type="group",
            relation=RelationType.MENTIONS, object_name="B", object_type="event",
            source_url="https://example.com/x",
            source_claim_text="y", source_confidence=0.5,
        )
        assert lead.provenance() == "citation"

    def test_public_record_lead_detected(self):
        lead = ResearchLead(
            subject_name="A", subject_type="person",
            relation=RelationType.MEMBER_OF, object_name="B", object_type="group",
            public_record_text="y", public_record_confidence=0.85,
        )
        assert lead.provenance() == "public_record"

    def test_all_default_leads_have_exactly_one_provenance_kind(self):
        for lead in DEFAULT_LEADS:
            # "citation" covers either a known source_url or a pending
            # source_pending_label (see module docstring's 2026-08-23
            # update) — either one counts as the single "citation" kind.
            kinds_present = sum([
                lead.kkron_claim_text is not None,
                lead.source_url is not None or lead.source_pending_label is not None,
                lead.public_record_text is not None,
            ])
            assert kinds_present == 1, f"lead {lead.subject_name}->{lead.object_name} has {kinds_present} provenance kinds set"


class TestBuildSearchQueries:
    def test_includes_subject_and_object(self):
        lead = ResearchLead(
            subject_name="Douglas Stone", subject_type="person",
            relation=RelationType.MEMBER_OF,
            object_name=CRTG_GROUP_NAME, object_type="group",
            kkron_claim_text="x", kkron_confidence=0.5,
        )
        queries = build_search_queries(lead)
        assert any("Douglas Stone" in q and CRTG_GROUP_NAME in q for q in queries)

    def test_extra_queries_come_first_and_are_included(self):
        lead = ResearchLead(
            subject_name="A", subject_type="person",
            relation=RelationType.MEMBER_OF,
            object_name="B", object_type="group",
            kkron_claim_text="x", kkron_confidence=0.5,
            extra_queries=("hand tuned query",),
        )
        queries = build_search_queries(lead)
        assert queries[0] == "hand tuned query"

    def test_dedupes_case_insensitively(self):
        lead = ResearchLead(
            subject_name="A", subject_type="person",
            relation=RelationType.MEMBER_OF,
            object_name="B", object_type="group",
            kkron_claim_text="x", kkron_confidence=0.5,
            extra_queries=("A member of B",),
        )
        queries = build_search_queries(lead)
        assert sum(1 for q in queries if q.lower() == "a member of b") == 1

    def test_relation_phrase_used_for_created(self):
        lead = ResearchLead(
            subject_name="Douglas Stone", subject_type="person",
            relation=RelationType.CREATED,
            object_name="Difficult Conversations", object_type="work",
            public_record_text="x", public_record_confidence=0.85,
        )
        queries = build_search_queries(lead)
        assert any("wrote" in q for q in queries)

    def test_unmapped_relation_falls_back_to_generic_phrase(self):
        lead = ResearchLead(
            subject_name="A", subject_type="person",
            relation=RelationType.CONTRADICTS,
            object_name="B", object_type="person",
            kkron_claim_text="x", kkron_confidence=0.5,
        )
        queries = build_search_queries(lead)
        assert any("connected to" in q for q in queries)


class TestBuildClaimRecord:
    def test_kkron_confidence_is_clamped_but_raw_value_preserved(self):
        lead = next(l for l in DEFAULT_LEADS if l.provenance() == "kkron")
        record = build_claim_record(lead)
        assert record["confidence"] <= KKRON_CONFIDENCE_CEILING
        assert record["raw_kkron_confidence"] == lead.kkron_confidence

    def test_kkron_speaker_is_kkron_source(self):
        lead = next(l for l in DEFAULT_LEADS if l.provenance() == "kkron")
        record = build_claim_record(lead)
        assert record["speaker_id"] == KKRON_SOURCE_PERSON_ID

    def test_citation_lead_uses_wikipedia_talk_url_and_is_not_clamped(self):
        lead = next(l for l in DEFAULT_LEADS if l.provenance() == "citation")
        record = build_claim_record(lead)
        assert record["source_url"] == CRTG_WIKIPEDIA_TALK_URL
        assert record["speaker_id"] is None
        assert record["confidence"] == lead.source_confidence

    def test_public_record_lead_confidence_higher_than_kkron_ceiling(self):
        lead = next(l for l in DEFAULT_LEADS if l.provenance() == "public_record")
        record = build_claim_record(lead)
        assert record["confidence"] > KKRON_CONFIDENCE_CEILING
        assert record["speaker_id"] is None

    def test_stance_and_evidence_mode_are_valid_enum_values(self):
        for lead in DEFAULT_LEADS:
            record = build_claim_record(lead)
            assert record["stance"] == ClaimStance.NEUTRAL.value
            if lead.provenance() == "kkron":
                assert record["evidence_mode"] == EvidenceMode.FIRST_PERSON.value
            else:
                assert record["evidence_mode"] == EvidenceMode.SECONDARY_REPORT.value

    def test_claim_id_is_stable_and_namespaced_by_provenance(self):
        for lead in DEFAULT_LEADS:
            record1 = build_claim_record(lead)
            record2 = build_claim_record(lead)
            assert record1["id"] == record2["id"]
            assert record1["id"].startswith(f"claim:{lead.provenance().replace('_', '-')}:")

    def test_different_leads_get_different_claim_ids(self):
        ids = {build_claim_record(lead)["id"] for lead in DEFAULT_LEADS}
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
        assert {
            "Douglas Stone", "Sheila Heen", "Richard", "Louise", "Diana",
            CRTG_GROUP_NAME,
        } <= names

    def test_placeholder_people_have_unconfirmed_surname_role_notes(self):
        for name in ("Richard", "Louise", "Diana"):
            leads = [l for l in DEFAULT_LEADS if l.subject_name == name]
            assert leads, f"expected at least one lead for {name}"
            assert any(l.role_note and "surname unconfirmed" in l.role_note for l in leads)

    def test_richard_lead_does_not_resolve_to_an_unrelated_persons_id(self):
        """Regression guard: the Cyprus 'Richard' placeholder must keep its
        own bare-first-name node id and must not get aliased/merged onto a
        full name belonging to an unrelated person from a different,
        separate research topic in this project."""
        richard_leads = [l for l in DEFAULT_LEADS if l.subject_name == "Richard"]
        assert richard_leads
        for lead in richard_leads:
            assert lead.subject_name == "Richard"
            assert lead.subject_id() == "person:richard"

    def test_diana_lead_is_lowest_confidence(self):
        diana = next(l for l in DEFAULT_LEADS if l.subject_name == "Diana")
        others = [
            l.kkron_confidence for l in DEFAULT_LEADS
            if l.provenance() == "kkron" and l.subject_name != "Diana"
        ]
        assert all(diana.kkron_confidence < c for c in others)

    def test_public_record_leads_confidence_exceeds_kkron_ceiling(self):
        public_leads = [l for l in DEFAULT_LEADS if l.provenance() == "public_record"]
        assert public_leads
        assert all(l.public_record_confidence > KKRON_CONFIDENCE_CEILING for l in public_leads)

    def test_subject_and_object_ids_resolve(self):
        for lead in DEFAULT_LEADS:
            assert lead.subject_id()
            assert lead.object_id()

    def test_wikipedia_talk_url_is_the_real_public_url(self):
        # Not all "citation" leads have a known source_url — some are
        # citation-pending (see source_pending_label). Of the ones that do
        # have a real URL, it must be the real public Wikipedia Talk page.
        citation_leads_with_url = [
            l for l in DEFAULT_LEADS if l.provenance() == "citation" and l.source_url
        ]
        assert citation_leads_with_url
        assert all(l.source_url == CRTG_WIKIPEDIA_TALK_URL for l in citation_leads_with_url)

    def test_no_raw_email_addresses_anywhere_in_lead_text(self):
        for lead in DEFAULT_LEADS:
            for text in (
                lead.kkron_claim_text, lead.source_claim_text, lead.public_record_text,
                lead.role_note, lead.subject_name, lead.object_name,
                lead.subject_also_known_as, lead.object_also_known_as,
                lead.source_pending_label, lead.source_pending_author,
            ):
                if text:
                    assert "@" not in text, f"possible email address leaked in: {text!r}"


class TestCitationPendingSources:
    """Covers the 2026-08-23 'citation, pending exact identification'
    mechanism (source_pending_label/source_pending_author) added for
    kkron's Wikipedia Talk-page COI disclosure draft leads — see module
    docstring."""

    def test_pending_lead_is_citation_provenance(self):
        lead = ResearchLead(
            subject_name="A", subject_type="person",
            relation=RelationType.WORKED_AT, object_name="B", object_type="group",
            source_pending_label="some 2008 case study (citation TBD)",
            source_claim_text="x", source_confidence=0.5,
        )
        assert lead.provenance() == "citation"

    def test_pending_lead_has_no_real_source_url(self):
        lead = ResearchLead(
            subject_name="A", subject_type="person",
            relation=RelationType.WORKED_AT, object_name="B", object_type="group",
            source_pending_label="some 2008 case study (citation TBD)",
            source_claim_text="x", source_confidence=0.5,
        )
        assert lead.source_url is None

    def test_citation_source_url_prefers_real_url(self):
        lead = ResearchLead(
            subject_name="A", subject_type="group",
            relation=RelationType.MENTIONS, object_name="B", object_type="event",
            source_url="https://example.com/x", source_claim_text="y", source_confidence=0.5,
        )
        assert citation_source_url(lead) == "https://example.com/x"

    def test_citation_source_url_falls_back_to_pending_pseudo_url(self):
        lead = ResearchLead(
            subject_name="A", subject_type="person",
            relation=RelationType.WORKED_AT, object_name="B", object_type="group",
            source_pending_label="some 2008 case study (citation TBD)",
            source_claim_text="x", source_confidence=0.5,
        )
        url = citation_source_url(lead)
        assert url.startswith("pseudo://citation-needed/")

    def test_citation_source_url_is_stable(self):
        lead = ResearchLead(
            subject_name="A", subject_type="person",
            relation=RelationType.WORKED_AT, object_name="B", object_type="group",
            source_pending_label="some 2008 case study (citation TBD)",
            source_claim_text="x", source_confidence=0.5,
        )
        assert citation_source_url(lead) == citation_source_url(lead)

    def test_build_claim_record_flags_citation_needed_when_pending(self):
        lead = ResearchLead(
            subject_name="A", subject_type="person",
            relation=RelationType.WORKED_AT, object_name="B", object_type="group",
            source_pending_label="some 2008 case study (citation TBD)",
            source_claim_text="x", source_confidence=0.5,
        )
        record = build_claim_record(lead)
        assert record["citation_needed"] is True

    def test_build_claim_record_does_not_flag_citation_needed_when_url_known(self):
        lead = ResearchLead(
            subject_name="A", subject_type="group",
            relation=RelationType.MENTIONS, object_name="B", object_type="event",
            source_url="https://example.com/x", source_claim_text="y", source_confidence=0.5,
        )
        record = build_claim_record(lead)
        assert record["citation_needed"] is False


class TestClaimType:
    def test_default_claim_type_is_biographical(self):
        lead = ResearchLead(
            subject_name="A", subject_type="person",
            relation=RelationType.MEMBER_OF, object_name="B", object_type="group",
            kkron_claim_text="x", kkron_confidence=0.5,
        )
        assert lead.claim_type == ClaimType.BIOGRAPHICAL

    def test_wikipedia_talk_lead_is_historical_dispute(self):
        lead = next(
            l for l in DEFAULT_LEADS
            if l.provenance() == "citation" and l.source_url == CRTG_WIKIPEDIA_TALK_URL
        )
        assert lead.claim_type == ClaimType.HISTORICAL_DISPUTE
        assert build_claim_record(lead)["claim_type"] == ClaimType.HISTORICAL_DISPUTE.value

    def test_new_citation_pending_leads_default_to_biographical(self):
        thorsen_leads = [l for l in DEFAULT_LEADS if l.subject_name == "Christopher Thorsen"]
        assert thorsen_leads
        assert all(l.claim_type == ClaimType.BIOGRAPHICAL for l in thorsen_leads)


class TestAlsoKnownAs:
    def test_thorsen_leads_document_both_spellings(self):
        thorsen_leads = [
            l for l in DEFAULT_LEADS
            if l.subject_also_known_as and "Christopher Thorsen" == l.subject_name
        ]
        assert thorsen_leads
        for lead in thorsen_leads:
            assert "Chris Thorsen" in lead.subject_also_known_as
            assert "Thorson" in lead.subject_also_known_as

    def test_also_known_as_fields_do_not_leak_emails(self):
        for lead in DEFAULT_LEADS:
            for text in (lead.subject_also_known_as, lead.object_also_known_as):
                if text:
                    assert "@" not in text


class TestNewCyprusCrtgDraftLeads:
    """Leads added from kkron's 2026-08-23 draft Wikipedia Talk-page COI
    disclosure — see module docstring's 2026-08-23 update."""

    def test_christopher_thorsen_hired_by_cyprus_consortium_is_citation_sourced(self):
        lead = next(
            l for l in DEFAULT_LEADS
            if l.subject_name == "Christopher Thorsen" and l.relation == RelationType.WORKED_AT
        )
        assert lead.provenance() == "citation"
        assert lead.kkron_claim_text is None
        assert "1995" in lead.source_claim_text
        assert "Aikido" in lead.source_claim_text

    def test_louise_diamond_leads_are_citation_sourced_not_kkron(self):
        diamond_leads = [l for l in DEFAULT_LEADS if l.subject_name == "Louise Diamond"]
        assert diamond_leads
        assert all(l.provenance() == "citation" for l in diamond_leads)
        assert all(l.kkron_claim_text is None for l in diamond_leads)

    def test_richard_moon_fulbright_lead_does_not_use_kkron_provenance(self):
        lead = next(
            l for l in DEFAULT_LEADS
            if l.subject_name == "Richard Moon" and l.object_name == CYPRUS_FULBRIGHT_COMMISSION_NAME
        )
        assert lead.provenance() == "citation"
        assert lead.kkron_claim_text is None

    def test_richard_moon_lead_carries_open_disambiguation_flag(self):
        lead = next(
            l for l in DEFAULT_LEADS
            if l.subject_name == "Richard Moon" and l.object_name == CYPRUS_FULBRIGHT_COMMISSION_NAME
        )
        assert lead.role_note is not None
        assert "OPEN DISAMBIGUATION" in lead.role_note
        assert "MR !3" in lead.role_note
        assert "Quantum Aikido" in lead.role_note
        assert "NOT" in lead.role_note  # not resolved/asserted

    def test_moon_and_thorsen_do_not_get_a_member_of_crtg_edge_from_peterson_alone(self):
        """Peterson's account does not establish CRTG membership — make
        sure no lead asserts a positive MEMBER_OF-CRTG relation for either
        Moon or Thorsen from these citation-pending leads."""
        for name in ("Richard Moon", "Christopher Thorsen"):
            crtg_member_leads = [
                l for l in DEFAULT_LEADS
                if l.subject_name == name
                and l.object_name == CRTG_GROUP_NAME
                and l.relation == RelationType.MEMBER_OF
            ]
            assert crtg_member_leads == []

    def test_moon_and_thorsen_have_negative_scoping_claim_about_crtg(self):
        for name in ("Richard Moon", "Christopher Thorsen"):
            scoping_leads = [
                l for l in DEFAULT_LEADS
                if l.subject_name == name and l.object_name == CRTG_GROUP_NAME
            ]
            assert scoping_leads, f"expected a scoping lead for {name}"
            assert any(
                l.role_note and "NEGATIVE/SCOPING" in l.role_note for l in scoping_leads
            )

    def test_douglas_stone_cyprus_fulbright_connection_is_an_open_gap(self):
        lead = next(
            l for l in DEFAULT_LEADS
            if l.subject_name == "Douglas Stone" and l.object_name == CYPRUS_FULBRIGHT_COMMISSION_NAME
        )
        assert lead.provenance() == "citation"
        assert lead.role_note is not None
        assert "OPEN RESEARCH GAP" in lead.role_note
        # Deliberately low confidence: "no evidence found", not "unlikely".
        assert lead.source_confidence is not None and lead.source_confidence < 0.5

    def test_kkron_source_metadata_discloses_personal_acquaintances_separately(self):
        """kkron's personal-knowledge disclosure is metadata/context on the
        kkron source, never itself a citation-sourced claim about CRTG/
        Cyprus involvement."""
        import tempfile, os
        from src.storage.graph_db import GraphDB
        from scripts._cyprus_crtg_helpers import ensure_kkron_source

        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name
        db = GraphDB(db_path)
        try:
            ensure_kkron_source(db)
            node = db.get_node(KKRON_SOURCE_PERSON_ID)
            assert node is not None
            assert set(node.metadata["personally_knows"]) == {
                "Richard Moon", "Christopher Thorsen", "Douglas Stone",
            }
            assert "unpublished interview" in node.metadata["personally_knows_note"]
            assert "NOT" in node.metadata["personally_knows_note"]
        finally:
            db.close()
            os.unlink(db_path)
