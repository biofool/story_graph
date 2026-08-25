"""Unit tests for the reviewer verdict overlay (src/storage/verdict_store.py)."""

import json

import pytest

from src.storage.models import Verdict, VerdictValue
from src.storage.verdict_store import (
    VERDICTS_FILENAME,
    delete_verdict,
    export_verdicts,
    gen_verdict_id,
    get_verdict,
    get_verdicts_for_claim,
    load_verdicts,
    save_verdict,
    verdicts_file,
)


@pytest.fixture
def snapshot_dir(tmp_path):
    return tmp_path / "graph_snapshot"


# --- load / empty-state ---------------------------------------------------

class TestLoadVerdicts:
    def test_empty_when_file_missing(self, snapshot_dir):
        assert load_verdicts(snapshot_dir) == []

    def test_empty_when_file_present_but_empty(self, snapshot_dir):
        snapshot_dir.mkdir()
        verdicts_file(snapshot_dir).touch()
        assert load_verdicts(snapshot_dir) == []

    def test_skips_corrupt_lines(self, snapshot_dir):
        snapshot_dir.mkdir()
        verdicts_file(snapshot_dir).write_text(
            '{"id":"verdict:bad","claim_id":"claim:x","verdict":"correct",'
            '"reviewer":"r","created_at":"t","updated_at":"t"}\n'
            "this is not json\n"
            '{"id":"verdict:other","claim_id":"claim:y","verdict":"incorrect",'
            '"reviewer":"r","created_at":"t","updated_at":"t"}\n'
        )
        verdicts = load_verdicts(snapshot_dir)
        assert len(verdicts) == 2
        claim_ids = {v.claim_id for v in verdicts}
        assert claim_ids == {"claim:x", "claim:y"}


# --- save (upsert) --------------------------------------------------------

class TestSaveVerdict:
    def test_creates_new_verdict_and_persists(self, snapshot_dir):
        v = save_verdict(
            snapshot_dir,
            claim_id="claim:abc",
            verdict="correct",
            reviewer="kkron",
            confidence=0.9,
            reasoning="Corroborated by two independent sources.",
            evidence_urls=["https://example.com/a"],
            corroborating_claim_ids=["claim:def"],
            tags=["well-sourced"],
        )
        assert v.claim_id == "claim:abc"
        assert v.verdict is VerdictValue.CORRECT
        assert v.confidence == 0.9
        assert v.reviewer == "kkron"
        assert v.created_at == v.updated_at
        assert v.evidence_urls == ["https://example.com/a"]
        assert v.corroborating_claim_ids == ["claim:def"]
        assert v.tags == ["well-sourced"]

        # persisted to disk
        on_disk = load_verdicts(snapshot_dir)
        assert len(on_disk) == 1
        assert on_disk[0].id == v.id

    def test_accepts_verdict_value_enum_directly(self, snapshot_dir):
        v = save_verdict(
            snapshot_dir, claim_id="claim:c", verdict=VerdictValue.UNCERTAIN
        )
        assert v.verdict is VerdictValue.UNCERTAIN

    def test_upsert_updates_in_place_and_bumps_updated_at(self, snapshot_dir):
        first = save_verdict(
            snapshot_dir, claim_id="claim:c", verdict="correct",
            reviewer="kkron", reasoning="first pass",
        )
        second = save_verdict(
            snapshot_dir, claim_id="claim:c", verdict="incorrect",
            reviewer="kkron", reasoning="changed my mind",
        )
        assert second.id == first.id
        assert second.created_at == first.created_at
        assert second.updated_at >= first.updated_at
        assert second.verdict is VerdictValue.INCORRECT
        assert second.reasoning == "changed my mind"

        # still exactly one verdict on disk
        on_disk = load_verdicts(snapshot_dir)
        assert len(on_disk) == 1
        assert on_disk[0].id == first.id

    def test_different_reviewers_get_separate_verdicts(self, snapshot_dir):
        save_verdict(snapshot_dir, claim_id="claim:c", verdict="correct", reviewer="a")
        save_verdict(snapshot_dir, claim_id="claim:c", verdict="incorrect", reviewer="b")
        on_disk = load_verdicts(snapshot_dir)
        assert len(on_disk) == 2
        reviewers = {v.reviewer for v in on_disk}
        assert reviewers == {"a", "b"}

    def test_defaults_for_optional_fields(self, snapshot_dir):
        v = save_verdict(snapshot_dir, claim_id="claim:c", verdict="uncertain")
        assert v.reviewer == "reviewer"
        assert v.confidence == 0.5
        assert v.reasoning == ""
        assert v.evidence_urls == []
        assert v.corroborating_claim_ids == []
        assert v.contradicting_claim_ids == []
        assert v.tags == []


# --- query helpers --------------------------------------------------------

class TestQueryHelpers:
    def test_get_verdict_found(self, snapshot_dir):
        save_verdict(snapshot_dir, claim_id="claim:c", verdict="correct", reviewer="r")
        v = get_verdict(snapshot_dir, "claim:c", "r")
        assert v is not None
        assert v.verdict is VerdictValue.CORRECT

    def test_get_verdict_miss(self, snapshot_dir):
        save_verdict(snapshot_dir, claim_id="claim:c", verdict="correct", reviewer="r")
        assert get_verdict(snapshot_dir, "claim:c", "other") is None
        assert get_verdict(snapshot_dir, "claim:other", "r") is None

    def test_get_verdicts_for_claim_across_reviewers(self, snapshot_dir):
        save_verdict(snapshot_dir, claim_id="claim:c", verdict="correct", reviewer="a")
        save_verdict(snapshot_dir, claim_id="claim:c", verdict="incorrect", reviewer="b")
        save_verdict(snapshot_dir, claim_id="claim:d", verdict="correct", reviewer="a")
        verdicts = get_verdicts_for_claim(snapshot_dir, "claim:c")
        assert len(verdicts) == 2
        assert {v.reviewer for v in verdicts} == {"a", "b"}


# --- export / determinism -------------------------------------------------

class TestExportVerdicts:
    def test_writes_sorted_jsonl(self, snapshot_dir):
        save_verdict(snapshot_dir, claim_id="claim:z", verdict="correct", reviewer="r")
        save_verdict(snapshot_dir, claim_id="claim:a", verdict="incorrect", reviewer="r")
        lines = verdicts_file(snapshot_dir).read_text().splitlines()
        claim_ids = [json.loads(line)["claim_id"] for line in lines]
        assert claim_ids == sorted(claim_ids)
        assert claim_ids == ["claim:a", "claim:z"]

    def test_sorted_object_keys_per_line(self, snapshot_dir):
        save_verdict(snapshot_dir, claim_id="claim:c", verdict="correct", reviewer="r")
        line = verdicts_file(snapshot_dir).read_text().strip()
        keys = list(json.loads(line).keys())
        assert keys == sorted(keys)

    def test_export_is_deterministic_across_runs(self, snapshot_dir):
        save_verdict(snapshot_dir, claim_id="claim:a", verdict="correct", reviewer="r")
        save_verdict(snapshot_dir, claim_id="claim:b", verdict="incorrect", reviewer="r")
        first = verdicts_file(snapshot_dir).read_text()
        export_verdicts(snapshot_dir)  # re-export without changes
        second = verdicts_file(snapshot_dir).read_text()
        assert first == second

    def test_export_given_list_writes_those_verdicts(self, snapshot_dir):
        snapshot_dir.mkdir()
        custom = [
            Verdict(
                id="verdict:1", claim_id="claim:x", verdict=VerdictValue.CORRECT,
                reviewer="r", created_at="2026-01-01T00:00:00+00:00",
                updated_at="2026-01-01T00:00:00+00:00",
            ),
        ]
        count = export_verdicts(snapshot_dir, custom)
        assert count == 1
        on_disk = load_verdicts(snapshot_dir)
        assert len(on_disk) == 1
        assert on_disk[0].claim_id == "claim:x"

    def test_creates_snapshot_dir_if_missing(self, tmp_path):
        target = tmp_path / "new" / "snapshot"
        assert not target.exists()
        export_verdicts(target, [])
        assert verdicts_file(target).exists()


# --- delete ---------------------------------------------------------------

class TestDeleteVerdict:
    def test_removes_existing_verdict(self, snapshot_dir):
        save_verdict(snapshot_dir, claim_id="claim:c", verdict="correct", reviewer="r")
        assert delete_verdict(snapshot_dir, "claim:c", "r") is True
        assert load_verdicts(snapshot_dir) == []

    def test_returns_false_when_absent(self, snapshot_dir):
        save_verdict(snapshot_dir, claim_id="claim:c", verdict="correct", reviewer="r")
        assert delete_verdict(snapshot_dir, "claim:c", "other") is False
        assert delete_verdict(snapshot_dir, "claim:other", "r") is False
        assert len(load_verdicts(snapshot_dir)) == 1

    def test_only_removes_matching_reviewer(self, snapshot_dir):
        save_verdict(snapshot_dir, claim_id="claim:c", verdict="correct", reviewer="a")
        save_verdict(snapshot_dir, claim_id="claim:c", verdict="incorrect", reviewer="b")
        assert delete_verdict(snapshot_dir, "claim:c", "a") is True
        remaining = load_verdicts(snapshot_dir)
        assert len(remaining) == 1
        assert remaining[0].reviewer == "b"


# --- id generation --------------------------------------------------------

class TestGenVerdictId:
    def test_format_and_determinism(self):
        a = gen_verdict_id("claim:c", "r", "2026-01-01T00:00:00+00:00")
        b = gen_verdict_id("claim:c", "r", "2026-01-01T00:00:00+00:00")
        assert a.startswith("verdict:")
        assert a == b

    def test_differs_on_inputs(self):
        a = gen_verdict_id("claim:c", "r", "t1")
        b = gen_verdict_id("claim:c", "r", "t2")
        c = gen_verdict_id("claim:d", "r", "t1")
        d = gen_verdict_id("claim:c", "s", "t1")
        assert len({a, b, c, d}) == 4
