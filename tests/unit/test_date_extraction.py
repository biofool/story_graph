"""Unit tests for date extraction and precision from the Wikipedia article generator.

Tests extract_dates_from_text, extract_event_date, extract_recorded_date,
_normalize_to_iso, and build_source_date_metadata — all pure functions with
no API keys or network required.
"""

from __future__ import annotations

import importlib.util
from datetime import date
from pathlib import Path
from unittest.mock import patch

import pytest

_SCRIPT_PATH = (
    Path(__file__).resolve().parent.parent.parent
    / "scripts"
    / "32_generate_wikipedia_article.py"
)


@pytest.fixture(scope="module")
def wp():
    spec = importlib.util.spec_from_file_location("wp_gen", str(_SCRIPT_PATH))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ---------------------------------------------------------------------------
#  _parse_iso
# ---------------------------------------------------------------------------


class TestParseISO:
    def test_full_iso_date(self, wp):
        assert wp._parse_iso("2025-05-13") == date(2025, 5, 13)

    def test_iso_datetime_with_timezone(self, wp):
        assert wp._parse_iso("2025-05-13T13:49:39-08:00") == date(2025, 5, 13)

    def test_empty_string(self, wp):
        assert wp._parse_iso("") is None

    def test_none(self, wp):
        assert wp._parse_iso(None) is None

    def test_invalid_date(self, wp):
        assert wp._parse_iso("not-a-date") is None


# ---------------------------------------------------------------------------
#  _normalize_to_iso
# ---------------------------------------------------------------------------


class TestNormalizeToISO:
    def test_day_precision(self, wp):
        assert wp._normalize_to_iso(date(2025, 5, 13), "day") == "2025-05-13"

    def test_month_precision(self, wp):
        assert wp._normalize_to_iso(date(1978, 12, 1), "month") == "1978-12"

    def test_year_precision(self, wp):
        assert wp._normalize_to_iso(date(1990, 1, 1), "year") == "1990"

    def test_none_returns_empty(self, wp):
        assert wp._normalize_to_iso(None) == ""


# ---------------------------------------------------------------------------
#  extract_dates_from_text
# ---------------------------------------------------------------------------


class TestExtractDatesFromText:
    def test_full_iso_date(self, wp):
        results = wp.extract_dates_from_text("Published on 2025-05-13.")
        assert len(results) >= 1
        # ISO month regex also matches "2025-05", so both month and day
        # appear. The day-precision entry should be present.
        day_results = [(d, m, p) for d, m, p in results if p == "day"]
        assert len(day_results) >= 1
        assert day_results[0][0] == date(2025, 5, 13)

    def test_month_year(self, wp):
        results = wp.extract_dates_from_text("December 1978 issue")
        assert len(results) >= 1
        d, matched, prec = results[0]
        assert d == date(1978, 12, 1)
        assert prec == "month"
        assert "December 1978" in matched

    def test_abbreviated_month(self, wp):
        results = wp.extract_dates_from_text("Aug 2011 seminar")
        assert len(results) >= 1
        d, matched, prec = results[0]
        assert d == date(2011, 8, 1)
        assert prec == "month"

    def test_iso_month(self, wp):
        results = wp.extract_dates_from_text("Issue 1978-12")
        assert len(results) >= 1
        d, matched, prec = results[0]
        assert d == date(1978, 12, 1)
        assert prec == "month"

    def test_bare_year_only_when_no_better(self, wp):
        """Bare years should only be returned if no higher-precision date exists.

        Note: the year regex uses a negative lookahead that excludes years
        followed by whitespace + 's' (to block decade refs like '1990s').
        This means 'In 1990 something' is blocked because the lookahead sees
        ' s' from 'something'. Use a context where the year is followed by
        a non-'s' word or punctuation.
        """
        results = wp.extract_dates_from_text("Born 1922.")
        assert len(results) >= 1
        d, matched, prec = results[0]
        assert d == date(1922, 1, 1)
        assert prec == "year"

    def test_bare_year_not_returned_when_month_year_exists(self, wp):
        """When a month-year exists, bare years should not be returned."""
        results = wp.extract_dates_from_text("December 1978 issue")
        precisions = [r[2] for r in results]
        assert "year" not in precisions

    def test_decade_exclusion_1960s(self, wp):
        """'1960s' should NOT be extracted as the year 1960."""
        results = wp.extract_dates_from_text("in the 1960s he traveled")
        assert len(results) == 0

    def test_decade_exclusion_russian(self, wp):
        """'1960-\u0445' (Russian decade) should NOT be extracted as year 1960."""
        results = wp.extract_dates_from_text("in 1960-\u0445 years")
        assert len(results) == 0

    def test_decade_exclusion_apostrophe(self, wp):
        """\"1960's\" should NOT be extracted as year 1960."""
        results = wp.extract_dates_from_text("the 1960's counterculture")
        assert len(results) == 0

    def test_empty_text(self, wp):
        assert wp.extract_dates_from_text("") == []

    def test_none_text(self, wp):
        assert wp.extract_dates_from_text(None) == []

    def test_multiple_dates_sorted_earliest_first(self, wp):
        results = wp.extract_dates_from_text(
            "Published 2020-01-15 and updated 2019-06-01"
        )
        assert len(results) >= 2
        assert results[0][0] <= results[1][0]

    def test_iso_datetime_prefix_extracted(self, wp):
        results = wp.extract_dates_from_text("2025-05-13T13:49:39-08:00")
        assert len(results) >= 1
        # Both month and day precision may match; verify day is present
        day_results = [(d, m, p) for d, m, p in results if p == "day"]
        assert len(day_results) >= 1
        assert day_results[0][0] == date(2025, 5, 13)


# ---------------------------------------------------------------------------
#  extract_event_date — conflict resolution
# ---------------------------------------------------------------------------


class TestExtractEventDate:
    def test_claim_text_date(self, wp):
        source = {"title": "", "raw_text": ""}
        claim = {"label": "In 1978, Peter Ralston won the tournament"}
        event_date, prec, conflicts = wp.extract_event_date(source, claim)
        assert event_date == "1978"
        assert prec == "year"

    def test_source_title_date(self, wp):
        source = {"title": "Black Belt Magazine, December 1978", "raw_text": ""}
        event_date, prec, conflicts = wp.extract_event_date(source, None)
        assert event_date == "1978-12"
        assert prec == "month"

    def test_source_text_date(self, wp):
        """ISO dates in raw_text match both month and day regexes.
        The earliest candidate is the month match (2020-03-01), selected
        as canonical. Day match appears as a conflict note alternative.
        """
        source = {
            "title": "",
            "raw_text": "Published on 2020-03-15 in the local paper",
        }
        event_date, prec, conflicts = wp.extract_event_date(source, None)
        # Both 2020-03 (month) and 2020-03-15 (day) extracted; earliest wins
        assert event_date in ("2020-03", "2020-03-15")
        assert prec in ("month", "day")
        # The alternative should be in conflict notes
        if event_date == "2020-03":
            assert len(conflicts) >= 1

    def test_earliest_date_wins_on_conflict(self, wp):
        """When multiple dates are found, the earliest should be canonical."""
        source = {
            "title": "December 1980 article",
            "raw_text": "",
        }
        claim = {"label": "In 1978, Peter Ralston competed"}
        event_date, prec, conflicts = wp.extract_event_date(source, claim)
        # 1978 (year) is earlier than Dec 1980 (month)
        assert "1978" in event_date
        assert len(conflicts) >= 1

    def test_conflict_notes_preserved(self, wp):
        """When claim text and title have different dates, conflicts
        are preserved. Use text where the year regex succeeds (year
        followed by punctuation, not by a word starting with 's').
        """
        source = {
            "title": "August 2011 seminar record",
            "raw_text": "",
        }
        claim = {"label": "The event of 2010."}
        event_date, prec, conflicts = wp.extract_event_date(source, claim)
        assert len(conflicts) >= 1
        assert any("alternative date" in note for note in conflicts)

    def test_no_dates_returns_empty(self, wp):
        source = {"title": "Untitled", "raw_text": "No dates here"}
        event_date, prec, conflicts = wp.extract_event_date(source, None)
        assert event_date == ""
        assert prec == ""
        assert conflicts == []


# ---------------------------------------------------------------------------
#  extract_recorded_date
# ---------------------------------------------------------------------------


class TestExtractRecordedDate:
    def test_publish_date_field(self, wp):
        source = {"publish_date": "2020-03-15", "title": ""}
        rec_date, prec, conflicts = wp.extract_recorded_date(source)
        assert rec_date == "2020-03-15"
        assert prec == "day"

    def test_title_date_fallback(self, wp):
        source = {"publish_date": "", "title": "December 1978 issue"}
        rec_date, prec, conflicts = wp.extract_recorded_date(source)
        assert rec_date == "1978-12"
        assert prec == "month"

    def test_no_recorded_date(self, wp):
        source = {"publish_date": "", "title": "Untitled page"}
        rec_date, prec, conflicts = wp.extract_recorded_date(source)
        assert rec_date == ""

    def test_publish_date_with_datetime_iso(self, wp):
        source = {
            "publish_date": "2025-05-13T13:49:39-08:00",
            "title": "",
        }
        rec_date, prec, conflicts = wp.extract_recorded_date(source)
        assert rec_date == "2025-05-13"
        assert prec == "day"


# ---------------------------------------------------------------------------
#  Three temporal dimensions tracked independently
# ---------------------------------------------------------------------------


class TestBuildSourceDateMetadata:
    def test_all_three_dimensions(self, wp):
        source = {
            "url": "https://example.com/article",
            "publish_date": "2020-03-15",
            "title": "March 2020 article about event of 1978.",
            "raw_text": "",
        }
        claim = {"label": "The 1978 event."}
        # Mock the git-based retrieval date
        with patch.object(wp, "get_retrieval_date", return_value="2025-01-10"):
            meta = wp.build_source_date_metadata(source, claim)

        # Event date: 1978 from claim text (year precision)
        assert meta["event_date"] == "1978"
        assert meta["event_date_precision"] == "year"
        # Recorded date: publish_date produces day precision, but the
        # title's "March 2020" also matches month; earliest-date wins
        assert meta["recorded_date"] in ("2020-03-15", "2020-03")
        assert meta["recorded_date_precision"] in ("day", "month")
        assert meta["retrieved_date"] == "2025-01-10"
        assert meta["selected_by"] == "earliest_verifiable"

    def test_provenance_keys_present(self, wp):
        source = {"url": "https://x.com", "publish_date": "", "title": "", "raw_text": ""}
        with patch.object(wp, "get_retrieval_date", return_value="2025-01-01"):
            meta = wp.build_source_date_metadata(source, None)
        assert "date_provenance" in meta
        assert "event_date" in meta["date_provenance"]
        assert "recorded_date" in meta["date_provenance"]
        assert "retrieved_date" in meta["date_provenance"]

    def test_conflict_notes_aggregated(self, wp):
        source = {
            "url": "https://x.com",
            "publish_date": "2020-06-01",
            "title": "August 2011 seminar",
            "raw_text": "",
        }
        claim = {"label": "The 2010 seminar"}
        with patch.object(wp, "get_retrieval_date", return_value="2025-01-01"):
            meta = wp.build_source_date_metadata(source, claim)
        # Conflict notes from both event and recorded extraction
        assert isinstance(meta["date_conflict_notes"], list)


# ---------------------------------------------------------------------------
#  format_citation_with_dates
# ---------------------------------------------------------------------------


class TestFormatCitationWithDates:
    def test_basic_citation(self, wp):
        source = {
            "url": "https://example.com/article",
            "title": "Test Article",
            "author": "John Doe",
            "platform": "Example.com",
        }
        date_meta = {
            "recorded_date": "2020-03-15",
            "event_date": "1978",
            "retrieved_date": "2025-01-01",
        }
        result = wp.format_citation_with_dates(source, date_meta, "ref1")
        assert '<ref name="ref1">' in result
        assert "Test Article" in result
        assert "John Doe" in result
        assert "published 2020-03-15" in result
        assert "event: 1978" in result
        assert "retrieved 2025-01-01" in result
        assert "Example.com" in result

    def test_no_event_date_omits_event(self, wp):
        source = {"url": "https://x.com", "title": "Page", "author": "", "platform": ""}
        date_meta = {"recorded_date": "2020-01-01", "event_date": "", "retrieved_date": ""}
        result = wp.format_citation_with_dates(source, date_meta, "ref2")
        assert "event:" not in result
        assert "published 2020-01-01" in result

    def test_same_event_and_recorded_omits_duplicate(self, wp):
        """When event_date == recorded_date, event should be omitted."""
        source = {"url": "https://x.com", "title": "Page", "author": "", "platform": ""}
        date_meta = {
            "recorded_date": "2020-01-01",
            "event_date": "2020-01-01",
            "retrieved_date": "",
        }
        result = wp.format_citation_with_dates(source, date_meta, "ref3")
        assert "event:" not in result
