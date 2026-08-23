"""Unit tests for alias resolution."""

import pytest
from src.extractor.alias_resolver import (
    canonical_person,
    canonical_group,
    canonical_place,
    person_id,
    group_id,
    place_id,
    event_id,
    work_id,
    claim_id,
    get_aliases_for_canonical,
    is_aquarian_name,
    resolve_target_id,
)


class TestCanonicalPerson:
    def test_jim_baker(self):
        assert canonical_person("Jim Baker") == "james edward baker"

    def test_father_yod(self):
        assert canonical_person("Father Yod") == "james edward baker"

    def test_ya_ho_wa(self):
        assert canonical_person("Ya Ho Wa") == "james edward baker"

    def test_unknown(self):
        assert canonical_person("Laura Garon") == "laura garon"

    def test_chris_thorsen_and_thorson_collapse_to_christopher_thorsen(self):
        """Cyprus CRTG topic: 'Chris Thorsen' (2008 case study) and
        'Thorson' (Peterson's book) are two spellings for the same person —
        see scripts/_cyprus_crtg_helpers.py DEFAULT_LEADS."""
        assert canonical_person("Chris Thorsen") == "christopher thorsen"
        assert canonical_person("Thorson") == "christopher thorsen"
        assert canonical_person("Chris Thorsen") == canonical_person("Thorson")

    def test_richard_moon_has_no_alias_entry(self):
        """Regression guard: 'Richard Moon' must canonicalize to itself
        (plain normalize, no ALIAS_MAP entry) — this project deliberately
        does not assert an identity between the Cyprus CRTG topic's
        'Richard Moon' and any other same-named person found elsewhere; see
        the OPEN DISAMBIGUATION note in scripts/_cyprus_crtg_helpers.py."""
        assert canonical_person("Richard Moon") == "richard moon"


class TestCanonicalGroup:
    def test_source_family_variants_collapse(self):
        assert canonical_group("The Source Family") == canonical_group("Source Family")
        assert canonical_group("Source Family") == "the source family"

    def test_source_restaurant_variants_collapse(self):
        assert canonical_group("The Source Restaurant") == canonical_group("The Source")
        assert canonical_group("The Source") == "the source restaurant"

    def test_yahowha_variants_collapse(self):
        assert canonical_group("Yahowha 13") == canonical_group("Ya Ho Wa 13")
        assert canonical_group("Yahowha") == "ya ho wa 13"

    def test_unknown_passes_through(self):
        assert canonical_group("Some Other Group") == "some other group"


class TestCanonicalPlace:
    def test_la_collapses_to_los_angeles(self):
        assert canonical_place("LA") == canonical_place("Los Angeles")
        assert canonical_place("LA") == "los angeles"

    def test_kauai_compound_collapses(self):
        assert canonical_place("Kauai compound") == canonical_place("Kauai")
        assert canonical_place("Kauai compound") == "kauai"

    def test_fairmont_variants_collapse(self):
        assert canonical_place("Fairmont Hotel") == canonical_place("Fairmont Hotel San Francisco")
        assert canonical_place("The Fairmont Hotel") == "fairmont hotel san francisco"

    def test_unknown_passes_through(self):
        assert canonical_place("Detroit") == "detroit"


class TestPersonId:
    def test_stable(self):
        assert person_id("Jim Baker") == person_id("Father Yod")

    def test_format(self):
        pid = person_id("Laura Garon")
        assert pid.startswith("person:")
        assert "laura-garon" in pid


class TestGroupId:
    def test_basic(self):
        gid = group_id("The Source Family")
        assert gid.startswith("group:")
        assert "source-family" in gid

    def test_aliases_collapse_to_same_id(self):
        assert group_id("The Source Family") == group_id("Source Family")
        assert group_id("The Source Restaurant") == group_id("The Source")
        assert group_id("Yahowha 13") == group_id("Ya Ho Wa 13")


class TestPlaceId:
    def test_basic(self):
        plid = place_id("Sunset Strip")
        assert plid.startswith("place:")
        assert "sunset-strip" in plid

    def test_aliases_collapse_to_same_id(self):
        assert place_id("LA") == place_id("Los Angeles")
        assert place_id("Kauai compound") == place_id("Kauai")
        assert place_id("Fairmont Hotel") == place_id("Fairmont Hotel San Francisco")


class TestEventId:
    def test_basic(self):
        eid = event_id("Opened The Source Restaurant")
        assert eid.startswith("event:")


class TestWorkId:
    def test_stable(self):
        w1 = work_id("https://example.com/page")
        w2 = work_id("https://example.com/page")
        assert w1 == w2

    def test_different(self):
        w1 = work_id("https://example.com/a")
        w2 = work_id("https://example.com/b")
        assert w1 != w2


class TestClaimId:
    def test_stable(self):
        c1 = claim_id("Baker was abusive", "https://example.com")
        c2 = claim_id("Baker was abusive", "https://example.com")
        assert c1 == c2

    def test_different_source(self):
        c1 = claim_id("Baker was abusive", "https://a.com")
        c2 = claim_id("Baker was abusive", "https://b.com")
        assert c1 != c2


class TestGetAliases:
    def test_baker(self):
        aliases = get_aliases_for_canonical("james edward baker")
        assert "Jim Baker" in aliases
        assert "Father Yod" in aliases

    def test_unknown(self):
        assert get_aliases_for_canonical("unknown person") == []


class TestIsAquarian:
    def test_true(self):
        assert is_aquarian_name("Isis Aquarian")
        assert is_aquarian_name("Djin Aquarian")

    def test_false(self):
        assert not is_aquarian_name("Jim Baker")


class TestResolveTargetId:
    def test_person(self):
        tid = resolve_target_id({"type": "person", "name": "Jim Baker"})
        assert tid == person_id("Jim Baker")

    def test_group(self):
        tid = resolve_target_id({"type": "group", "name": "The Source Family"})
        assert tid == group_id("The Source Family")

    def test_place(self):
        tid = resolve_target_id({"type": "place", "name": "Kauai"})
        assert tid == place_id("Kauai")
