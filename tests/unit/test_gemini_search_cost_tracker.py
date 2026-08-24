"""Unit tests for the CloudManagement cost-tracker wiring in
``scripts/02_gemini_search.py``.

Exercises the ``_setup_cost_tracker`` helper in three modes — disabled
(the default opt-out), enabled + hub approves, and enabled + hub denies —
without hitting the real CloudManagement hub or the Gemini SDK.

The script module filename starts with a digit, so it is loaded via
``importlib.util`` (same pattern as ``tests/integration/test_cli_smoke.py``).
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from unittest.mock import MagicMock

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
SCRIPT_PATH = PROJECT_ROOT / "scripts" / "02_gemini_search.py"


def _load_gemini_search_module():
    """Load scripts/02_gemini_search.py as a module and return it."""
    spec = importlib.util.spec_from_file_location(
        "_gemini_search_cost_tracker_module", SCRIPT_PATH
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _make_fake_tracker(*, available: bool, intent_id: str | None = None,
                       denied: bool = False, degraded: bool = False,
                       suggested_cost: float | None = 0.5) -> MagicMock:
    """Build a fake GeminiCostTracker for _setup_cost_tracker.

    ``available`` controls is_available(). When the intent is denied,
    declare_intent_for_run raises BillingDenied (imported from the script
    module). Otherwise it returns intent_id (or None for degraded).
    """
    tracker = MagicMock()
    tracker.is_available.return_value = available
    tracker.degraded = degraded
    tracker.suggest_expected_cost.return_value = suggested_cost

    if denied:
        from src.llm.cost_tracker import BillingDenied

        def _raise(*a, **kw):
            raise BillingDenied("budget exceeded")
        tracker.declare_intent_for_run.side_effect = _raise
    else:
        tracker.declare_intent_for_run.return_value = intent_id
    return tracker


class TestSetupCostTrackerDisabled:
    """When CloudManagement is disabled (the default), _setup_cost_tracker
    returns a plain GeminiClient with no tracker attached."""

    def test_returns_plain_client_and_disabled_tracker(self, monkeypatch):
        module = _load_gemini_search_module()
        tracker = _make_fake_tracker(available=False)
        monkeypatch.setattr(module, "make_cost_tracker_from_settings", lambda: tracker)

        client, returned_tracker = module._setup_cost_tracker("ask", 1)
        assert returned_tracker is tracker
        assert client is not None
        # No intent declared, no finalize called.
        tracker.declare_intent_for_run.assert_not_called()
        tracker.finalize.assert_not_called()
        # The client has no cost tracker attached (per-call reporting off).
        assert client._cost_tracker is None


class TestSetupCostTrackerApproved:
    """When the hub approves the intent, a tracker-attached client is returned."""

    def test_returns_tracker_attached_client(self, monkeypatch):
        module = _load_gemini_search_module()
        tracker = _make_fake_tracker(
            available=True, intent_id="intent-abc", suggested_cost=0.03,
        )
        monkeypatch.setattr(module, "make_cost_tracker_from_settings", lambda: tracker)

        client, returned_tracker = module._setup_cost_tracker("discover", 3)
        assert returned_tracker is tracker
        assert client is not None
        # Intent was declared with the estimated call count.
        tracker.declare_intent_for_run.assert_called_once()
        kwargs = tracker.declare_intent_for_run.call_args.kwargs
        assert kwargs["expected_calls"] == 3
        assert kwargs["model"] == module.settings.gemini_model
        # The client carries the tracker so per-call reporting is on.
        assert client._cost_tracker is tracker
        # finalize not called yet (the subcommand's finally block does that).
        tracker.finalize.assert_not_called()

    def test_uses_suggested_cost_from_hub(self, monkeypatch):
        module = _load_gemini_search_module()
        tracker = _make_fake_tracker(
            available=True, intent_id="i1", suggested_cost=1.23,
        )
        monkeypatch.setattr(module, "make_cost_tracker_from_settings", lambda: tracker)

        module._setup_cost_tracker("extract", 2)
        kwargs = tracker.declare_intent_for_run.call_args.kwargs
        assert kwargs["expected_cost_usd"] == pytest.approx(1.23)

    def test_falls_back_to_default_when_suggestion_none(self, monkeypatch):
        module = _load_gemini_search_module()
        tracker = _make_fake_tracker(
            available=True, intent_id="i1", suggested_cost=None,
        )
        monkeypatch.setattr(module, "make_cost_tracker_from_settings", lambda: tracker)

        module._setup_cost_tracker("ask", 1)
        kwargs = tracker.declare_intent_for_run.call_args.kwargs
        # 1 call * $0.01 default.
        assert kwargs["expected_cost_usd"] == pytest.approx(0.01)


class TestSetupCostTrackerDenied:
    """When the hub denies the intent, _setup_cost_tracker returns None for
    the client (so the subcommand aborts) and finalizes the tracker as failed."""

    def test_returns_none_client_and_finalizes_failed(self, monkeypatch):
        module = _load_gemini_search_module()
        tracker = _make_fake_tracker(available=True, denied=True)
        monkeypatch.setattr(module, "make_cost_tracker_from_settings", lambda: tracker)

        client, returned_tracker = module._setup_cost_tracker("ask", 1)
        assert client is None
        assert returned_tracker is tracker
        # finalize called with status="failed" so the hub records the abort.
        tracker.finalize.assert_called_once_with(status="failed")


class TestSetupCostTrackerDegraded:
    """When the hub is unreachable, declare_intent_for_run returns None and
    degraded mode is entered — a tracker-attached client is still returned
    so calls proceed without budget gating."""

    def test_returns_client_and_marks_degraded(self, monkeypatch):
        module = _load_gemini_search_module()
        tracker = _make_fake_tracker(
            available=True, intent_id=None, degraded=True,
        )
        monkeypatch.setattr(module, "make_cost_tracker_from_settings", lambda: tracker)

        client, returned_tracker = module._setup_cost_tracker("ask", 1)
        assert client is not None
        assert returned_tracker is tracker
        # Intent was attempted (returned None = degraded).
        tracker.declare_intent_for_run.assert_called_once()
        # Client still carries the tracker for best-effort per-call reporting.
        assert client._cost_tracker is tracker
