"""Unit tests for the GeminiCostTracker and TieredGeminiClient cost-tracking wiring.

Uses a fake CloudManagementClient (no network) to exercise the tracker's
opt-out default, intent approval/denial, degraded mode, finalization, and
the TieredGeminiClient per-call reporting path.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from unittest.mock import MagicMock

import pytest

from src.llm.cost_tracker import (
    BillingDenied,
    GeminiCostTracker,
    make_run_job_id,
)


# --- fake CloudManagementClient response shapes ---


@dataclass
class _IntentResponse:
    intent_id: str = ""
    approved: bool = False
    deferred: bool = False
    budget_remaining_usd: float = 0.0
    reason: str = ""
    unreachable: bool = False
    warnings: list[str] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class _ActualResponse:
    actual_id: str = ""
    overrun_detected: bool = False
    status: str = ""
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class _KillOrder:
    kill_id: str = ""
    job_id: str = ""
    reason: str = ""


class _FakeCMClient:
    """Fake CloudManagementClient that records calls and returns canned responses.

    Mimics the real client's .enabled property and the methods used by
    GeminiCostTracker: declare_intent, report_actual, check_kill_orders,
    suggest_expected_cost, flush, close.
    """

    def __init__(
        self,
        *,
        enabled: bool = True,
        intent_response: _IntentResponse | None = None,
        kill_orders: list[_KillOrder] | None = None,
        suggested_cost: float | None = 0.5,
    ):
        self._enabled = enabled
        self._intent_response = intent_response or _IntentResponse(
            intent_id="intent-123", approved=True, budget_remaining_usd=10.0,
        )
        self._kill_orders = kill_orders or []
        self._suggested_cost = suggested_cost
        self.calls: dict[str, list[dict[str, Any]]] = {
            "declare_intent": [],
            "report_actual": [],
            "check_kill_orders": [],
        }
        self.flushed = False
        self.closed = False

    @property
    def enabled(self) -> bool:
        return self._enabled

    def declare_intent(self, **kwargs) -> _IntentResponse:
        self.calls["declare_intent"].append(kwargs)
        return self._intent_response

    def report_actual(self, **kwargs) -> _ActualResponse:
        self.calls["report_actual"].append(kwargs)
        return _ActualResponse()

    def check_kill_orders(self, since: str = "") -> list[_KillOrder]:
        self.calls["check_kill_orders"].append({"since": since})
        return self._kill_orders

    def suggest_expected_cost(self, provider: str, api: str, expected_calls: int) -> float | None:
        return self._suggested_cost

    def flush(self, timeout: float = 5.0) -> None:
        self.flushed = True

    def close(self) -> None:
        self.closed = True


# --- tests: disabled by default ---


class TestDisabledByDefault:
    def test_no_cm_client_is_available_false(self):
        tracker = GeminiCostTracker(enabled=False)
        assert not tracker.is_available()

    def test_declare_intent_returns_none_when_disabled(self):
        tracker = GeminiCostTracker(enabled=False)
        result = tracker.declare_intent_for_run(
            job_id="job-1", expected_calls=10, expected_cost_usd=0.1,
            model="gemini-2.5-flash",
        )
        assert result is None

    def test_report_call_is_noop_when_disabled(self):
        tracker = GeminiCostTracker(enabled=False)
        tracker.report_call(tier="free", model="gemini-2.5-flash", cost_usd=0.0)
        # Counters are still updated locally (mirrors TieredGeminiClient).
        assert tracker.free_calls == 1
        assert tracker.total_cost_usd == 0.0

    def test_report_call_paid_increments_cost(self):
        tracker = GeminiCostTracker(enabled=False)
        tracker.report_call(tier="paid", model="gemini-2.5-flash", cost_usd=0.01)
        assert tracker.paid_calls == 1
        assert tracker.total_cost_usd == pytest.approx(0.01)

    def test_check_killed_returns_empty_when_disabled(self):
        tracker = GeminiCostTracker(enabled=False)
        assert tracker.check_killed() == []

    def test_finalize_is_noop_when_disabled(self):
        tracker = GeminiCostTracker(enabled=False)
        # Should not raise.
        tracker.finalize(status="completed")

    def test_cm_none_but_enabled_flag_true_is_unavailable(self):
        tracker = GeminiCostTracker(enabled=True)
        assert not tracker.is_available()


# --- tests: enabled + hub approves ---


class TestEnabledApproved:
    def test_is_available_true_when_cm_enabled(self):
        cm = _FakeCMClient(enabled=True)
        tracker = GeminiCostTracker(cloud_management=cm, enabled=True)
        assert tracker.is_available()

    def test_declare_intent_returns_intent_id(self):
        cm = _FakeCMClient(
            enabled=True,
            intent_response=_IntentResponse(intent_id="abc-123", approved=True),
        )
        tracker = GeminiCostTracker(cloud_management=cm, enabled=True)
        result = tracker.declare_intent_for_run(
            job_id="job-1", expected_calls=10, expected_cost_usd=0.1,
            model="gemini-2.5-flash",
        )
        assert result == "abc-123"
        assert tracker.intent_id == "abc-123"
        assert tracker.job_id == "job-1"
        # declare_intent was called with the right args.
        assert len(cm.calls["declare_intent"]) == 1
        assert cm.calls["declare_intent"][0]["job_id"] == "job-1"
        assert cm.calls["declare_intent"][0]["expected_calls"] == 10

    def test_report_call_increments_and_reports_to_hub(self):
        cm = _FakeCMClient(enabled=True)
        tracker = GeminiCostTracker(cloud_management=cm, enabled=True)
        tracker.declare_intent_for_run(
            job_id="job-1", expected_calls=10, expected_cost_usd=0.1,
            model="gemini-2.5-flash",
        )
        tracker.report_call(tier="free", model="gemini-2.5-flash", cost_usd=0.0)
        tracker.report_call(tier="paid", model="gemini-2.5-flash", cost_usd=0.01)
        assert tracker.free_calls == 1
        assert tracker.paid_calls == 1
        assert tracker.total_cost_usd == pytest.approx(0.01)
        # Two incremental reports to the hub.
        assert len(cm.calls["report_actual"]) == 2
        assert cm.calls["report_actual"][0]["status"] == "running"
        assert cm.calls["report_actual"][1]["actual_calls"] == 2

    def test_check_killed_returns_orders(self):
        cm = _FakeCMClient(
            enabled=True,
            kill_orders=[_KillOrder(kill_id="k1", job_id="job-1")],
        )
        tracker = GeminiCostTracker(cloud_management=cm, enabled=True)
        kills = tracker.check_killed()
        assert len(kills) == 1
        assert kills[0].kill_id == "k1"

    def test_finalize_sends_sync_report_flush_close(self):
        cm = _FakeCMClient(enabled=True)
        tracker = GeminiCostTracker(cloud_management=cm, enabled=True)
        tracker.declare_intent_for_run(
            job_id="job-1", expected_calls=10, expected_cost_usd=0.1,
            model="gemini-2.5-flash",
        )
        tracker.report_call(tier="paid", model="gemini-2.5-flash", cost_usd=0.05)
        tracker.finalize(status="completed")
        # The final report_actual should have sync=True and status="completed".
        final_reports = [r for r in cm.calls["report_actual"] if r.get("sync")]
        assert len(final_reports) == 1
        assert final_reports[0]["status"] == "completed"
        assert cm.flushed is True
        assert cm.closed is True

    def test_finalize_is_idempotent(self):
        cm = _FakeCMClient(enabled=True)
        tracker = GeminiCostTracker(cloud_management=cm, enabled=True)
        tracker.declare_intent_for_run(
            job_id="job-1", expected_calls=10, expected_cost_usd=0.1,
            model="gemini-2.5-flash",
        )
        tracker.finalize(status="completed")
        # Second call should be a no-op (no extra sync report).
        sync_reports_before = len([r for r in cm.calls["report_actual"] if r.get("sync")])
        tracker.finalize(status="completed")
        sync_reports_after = len([r for r in cm.calls["report_actual"] if r.get("sync")])
        assert sync_reports_before == sync_reports_after == 1


# --- tests: enabled + hub denies ---


class TestEnabledDenied:
    def test_declare_intent_raises_billing_denied(self):
        cm = _FakeCMClient(
            enabled=True,
            intent_response=_IntentResponse(
                intent_id="denied-1", approved=False, reason="budget exceeded",
            ),
        )
        tracker = GeminiCostTracker(cloud_management=cm, enabled=True)
        with pytest.raises(BillingDenied, match="budget exceeded"):
            tracker.declare_intent_for_run(
                job_id="job-1", expected_calls=10, expected_cost_usd=0.1,
                model="gemini-2.5-flash",
            )


# --- tests: enabled + hub unreachable (degraded mode) ---


class TestDegradedMode:
    def test_unreachable_enters_degraded_mode(self):
        # An empty IntentResponse (all defaults) signals transport failure.
        cm = _FakeCMClient(
            enabled=True,
            intent_response=_IntentResponse(),  # intent_id="", approved=False, reason=""
        )
        tracker = GeminiCostTracker(cloud_management=cm, enabled=True)
        result = tracker.declare_intent_for_run(
            job_id="job-1", expected_calls=10, expected_cost_usd=0.1,
            model="gemini-2.5-flash",
        )
        assert result is None
        assert tracker.degraded is True

    def test_degraded_mode_calls_proceed(self):
        cm = _FakeCMClient(
            enabled=True,
            intent_response=_IntentResponse(),
        )
        tracker = GeminiCostTracker(cloud_management=cm, enabled=True)
        tracker.declare_intent_for_run(
            job_id="job-1", expected_calls=10, expected_cost_usd=0.1,
            model="gemini-2.5-flash",
        )
        # report_call should still work (local counters update).
        tracker.report_call(tier="free", model="gemini-2.5-flash", cost_usd=0.0)
        assert tracker.free_calls == 1

    def test_explicit_unreachable_attribute(self):
        cm = _FakeCMClient(
            enabled=True,
            intent_response=_IntentResponse(unreachable=True),
        )
        tracker = GeminiCostTracker(cloud_management=cm, enabled=True)
        result = tracker.declare_intent_for_run(
            job_id="job-1", expected_calls=10, expected_cost_usd=0.1,
            model="gemini-2.5-flash",
        )
        assert result is None
        assert tracker.degraded is True


# --- tests: suggest_expected_cost ---


class TestSuggestExpectedCost:
    def test_returns_suggested_from_hub(self):
        cm = _FakeCMClient(enabled=True, suggested_cost=1.23)
        tracker = GeminiCostTracker(cloud_management=cm, enabled=True)
        cost = tracker.suggest_expected_cost("google", "gemini-2.5-flash", 100)
        assert cost == 1.23

    def test_falls_back_to_default_when_none(self):
        cm = _FakeCMClient(enabled=True, suggested_cost=None)
        tracker = GeminiCostTracker(cloud_management=cm, enabled=True)
        cost = tracker.suggest_expected_cost("google", "gemini-2.5-flash", 100)
        assert cost is not None
        assert cost == pytest.approx(100 * 0.01, rel=0.01)

    def test_returns_none_when_disabled(self):
        tracker = GeminiCostTracker(enabled=False)
        assert tracker.suggest_expected_cost("google", "gemini-2.5-flash", 100) is None


# --- tests: make_run_job_id ---


class TestMakeRunJobId:
    def test_generates_unique_ids(self):
        id1 = make_run_job_id()
        id2 = make_run_job_id()
        assert id1.startswith("story-graph-")
        assert id2.startswith("story-graph-")
        assert id1 != id2


# --- tests: TieredGeminiClient with a fake tracker ---


class TestTieredGeminiClientReporting:
    """Verify TieredGeminiClient calls report_call after each successful API call."""

    def test_free_call_reports_to_tracker(self):
        from src.llm.gemini_client import GroundingResult, TieredGeminiClient

        # Build a TieredGeminiClient with a fake free-tier key and a fake tracker.
        fake_tracker = MagicMock()
        fake_tracker.is_available.return_value = False  # disabled — just records calls
        fake_tracker.total_cost_usd = 0.0

        client = TieredGeminiClient(
            free_tier_keys=["fake-key"],
            vertexai_enabled=False,
            cost_tracker=fake_tracker,
        )

        # Monkeypatch the free-tier GeminiClient.generate_content to return a
        # canned response (avoids hitting the real SDK).
        from src.llm.gemini_client import GeminiClient

        original_gen = GeminiClient.generate_content

        class _FakeResp:
            text = "hello world"
            candidates = []

        def _fake_generate_content(self, contents, *, model=None, config=None):
            return _FakeResp()

        GeminiClient.generate_content = _fake_generate_content
        try:
            result = client.generate_grounded("test prompt", allow_paid=False)
            assert isinstance(result, GroundingResult)
            assert result.text == "hello world"
            # report_call should have been called once with tier="free".
            fake_tracker.report_call.assert_called_once()
            call_kwargs = fake_tracker.report_call.call_args
            assert call_kwargs.kwargs["tier"] == "free"
        finally:
            GeminiClient.generate_content = original_gen

    def test_no_tracker_no_error(self):
        from src.llm.gemini_client import TieredGeminiClient
        from src.llm.gemini_client import GeminiClient

        client = TieredGeminiClient(
            free_tier_keys=["fake-key"],
            vertexai_enabled=False,
            cost_tracker=None,
        )

        class _FakeResp:
            text = "no tracker"
            candidates = []

        def _fake_generate_content(self, contents, *, model=None, config=None):
            return _FakeResp()

        original_gen = GeminiClient.generate_content
        GeminiClient.generate_content = _fake_generate_content
        try:
            result = client.generate_grounded("test", allow_paid=False)
            assert result.text == "no tracker"
        finally:
            GeminiClient.generate_content = original_gen

    def test_stats_include_cost_tracker_fields(self):
        from src.llm.gemini_client import TieredGeminiClient

        fake_tracker = MagicMock()
        fake_tracker.total_cost_usd = 0.42
        fake_tracker.is_available.return_value = True

        client = TieredGeminiClient(
            free_tier_keys=["fake-key"],
            vertexai_enabled=False,
            cost_tracker=fake_tracker,
        )
        stats = client.stats
        assert stats["total_cost_usd"] == 0.42
        assert stats["cost_tracker_enabled"] is True

    def test_stats_without_tracker_omit_cost_fields(self):
        from src.llm.gemini_client import TieredGeminiClient

        client = TieredGeminiClient(
            free_tier_keys=["fake-key"],
            vertexai_enabled=False,
            cost_tracker=None,
        )
        stats = client.stats
        assert "total_cost_usd" not in stats
        assert "cost_tracker_enabled" not in stats
