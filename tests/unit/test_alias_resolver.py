"""Unit tests for alias resolution."""

import pytest
from src.extractor.alias_resolver import (
    canonical_person,
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


class TestPlaceId:
    def test_basic(self):
        plid = place_id("Sunset Strip")
        assert plid.startswith("place:")
        assert "sunset-strip" in plid


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
