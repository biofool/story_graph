"""Unit tests for entity extraction."""

import pytest
from src.extractor.entity_extractor import EntityExtractor, _is_valid_person_name


@pytest.fixture
def extractor():
    """Create extractor without spaCy (rule-based only)."""
    return EntityExtractor(spacy_model_name="nonexistent_model")


class TestPersonNameFilter:
    """Tests for the spaCy NER false-positive filter (_is_valid_person_name)."""

    def test_rejects_common_adverb(self):
        assert not _is_valid_person_name("Although")

    def test_rejects_also(self):
        assert not _is_valid_person_name("Also")

    def test_rejects_day_of_week(self):
        assert not _is_valid_person_name("Tuesday")
        assert not _is_valid_person_name("Monday")

    def test_rejects_month(self):
        assert not _is_valid_person_name("January")

    def test_rejects_ambiguous_single_token(self):
        # 'Robin' is a real word/bird; not in known persons -> rejected
        assert not _is_valid_person_name("Robin")

    def test_accepts_known_single_token(self):
        # 'Octavius' is in KNOWN_PERSONS -> accepted
        assert _is_valid_person_name("Octavius")

    def test_accepts_aquarian_single_token(self):
        assert _is_valid_person_name("Aquarian")

    def test_accepts_multi_token_name(self):
        assert _is_valid_person_name("Jim Baker")
        assert _is_valid_person_name("Laura Garon")

    def test_rejects_all_stopword_tokens(self):
        assert not _is_valid_person_name("Also Although")

    def test_rejects_short(self):
        assert not _is_valid_person_name("Al")


class TestPersonExtraction:
    def test_father_yod(self, extractor):
        result = extractor.extract("Father Yod was the leader of The Source Family.")
        persons = result["persons"]
        assert any("james edward baker" in p["name"] for p in persons)

    def test_jim_baker(self, extractor):
        result = extractor.extract("Jim Baker opened The Source Restaurant.")
        persons = result["persons"]
        assert any("james edward baker" in p["name"] for p in persons)

    def test_aquarian_pattern(self, extractor):
        result = extractor.extract("Isis Aquarian wrote about her experiences.")
        persons = result["persons"]
        assert any("isis aquarian" in p["name"] for p in persons)

    def test_laura_garon(self, extractor):
        result = extractor.extract("Laura Garon described the Kauai years.")
        persons = result["persons"]
        assert any("laura garon" in p["name"] for p in persons)


class TestGroupExtraction:
    def test_source_family(self, extractor):
        result = extractor.extract("The Source Family lived in Nichols Canyon.")
        groups = result["groups"]
        assert any("source family" in g["name"].lower() for g in groups)

    def test_source_restaurant(self, extractor):
        result = extractor.extract("The Source Restaurant was on the Sunset Strip.")
        groups = result["groups"]
        assert any("source" in g["name"].lower() for g in groups)


class TestPlaceExtraction:
    def test_sunset_strip(self, extractor):
        result = extractor.extract("The restaurant was located on Sunset Strip.")
        places = result["places"]
        assert any("sunset strip" in p["name"].lower() for p in places)

    def test_kauai(self, extractor):
        result = extractor.extract("The family moved to Kauai in 1974.")
        places = result["places"]
        assert any("kauai" in p["name"].lower() for p in places)


class TestClaimExtraction:
    def test_claim_with_said(self, extractor):
        result = extractor.extract("Laura Garon said that Baker withheld support from wives.")
        claims = result["claims"]
        assert len(claims) >= 1
        assert any("withheld" in c["text"] for c in claims)

    def test_claim_stance_critical(self, extractor):
        result = extractor.extract("She described the abuse at the Kauai compound.")
        claims = result["claims"]
        assert any(c["stance"] == "critical" for c in claims)

    def test_claim_stance_supportive(self, extractor):
        result = extractor.extract("He said it was a beautiful and loving community.")
        claims = result["claims"]
        assert any(c["stance"] == "supportive" for c in claims)

    def test_claim_type_abuse(self, extractor):
        result = extractor.extract("She claimed the abuse was systemic.")
        claims = result["claims"]
        assert any(c["claim_type"] == "abuse_allegation" for c in claims)

    def test_claim_type_financial(self, extractor):
        result = extractor.extract("He claimed Baker withheld money from the family.")
        claims = result["claims"]
        assert any(c["claim_type"] == "financial_control" for c in claims)

    def test_speaker_extraction(self, extractor):
        result = extractor.extract("Laura Garon said the experience was traumatic.")
        claims = result["claims"]
        assert any(c.get("speaker") == "Laura Garon" for c in claims)


class TestEventExtraction:
    def test_event_with_trigger(self, extractor):
        result = extractor.extract("Baker opened The Source Restaurant in 1969.")
        events = result["events"]
        assert len(events) >= 1
        assert any("opened" in e["description"].lower() for e in events)

    def test_event_with_date(self, extractor):
        result = extractor.extract("The family moved to Kauai on 1974-06-01.")
        events = result["events"]
        assert any(e.get("start_date") == "1974-06-01" for e in events)


class TestRelationExtraction:
    def test_extract_returns_relations_key(self, extractor):
        result = extractor.extract("Jim Baker opened The Source Restaurant in 1969.")
        assert "relations" in result
        assert isinstance(result["relations"], list)

    def test_founded_edge(self, extractor):
        result = extractor.extract("Jim Baker opened The Source Restaurant in 1969.")
        rels = result["relations"]
        assert any(
            r["rel_type"] == "FOUNDED"
            and r["src"]["type"] == "person"
            and r["dst"]["type"] == "group"
            for r in rels
        )

    def test_member_of_edge(self, extractor):
        result = extractor.extract("Isis Aquarian joined The Source Family in 1970.")
        rels = result["relations"]
        assert any(r["rel_type"] == "MEMBER_OF" for r in rels)

    def test_lived_at_edge(self, extractor):
        result = extractor.extract("The Source Family moved to Kauai on 1974-06-01.")
        rels = result["relations"]
        assert any(
            r["rel_type"] == "LIVED_AT"
            and r["dst"]["type"] == "place"
            for r in rels
        )

    def test_located_in_edge(self, extractor):
        result = extractor.extract("The Source Restaurant was located on Sunset Strip.")
        rels = result["relations"]
        assert any(
            r["rel_type"] == "LOCATED_IN"
            and r["src"]["type"] == "group"
            and r["dst"]["type"] == "place"
            for r in rels
        )

    def test_no_relation_without_trigger(self, extractor):
        result = extractor.extract("Father Yod was the leader of The Source Family.")
        rels = result["relations"]
        # No founded/member/worked/lived/located trigger words -> no relations
        assert rels == []

    def test_group_dedup_collapses_source_family_variants(self, extractor):
        """Both 'The Source Family' and 'Source Family' in one text should
        collapse to a single group entry (canonical dedup)."""
        result = extractor.extract("The Source Family was a group. Source Family lived in Nichols Canyon.")
        groups = result["groups"]
        # Only one canonical Source Family entry, not two.
        canonicals = {g.get("canonical") for g in groups}
        assert "the source family" in canonicals
        assert sum(1 for g in groups if g.get("canonical") == "the source family") == 1
