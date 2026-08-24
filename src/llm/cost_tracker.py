"""Cost tracking and budget gating for Gemini API calls.

Wraps an optional :class:`CloudManagementClient` (vendored at
``src/cloud_management_client/``) to provide centralized cost tracking,
budget gating, and kill-switch integration with the CloudManagement hub.

This is the story_graph analogue of AIRichardMoon's
``backend/app/costs.py`` ``GeminiCostTracker``, adapted for the tiered
free/paid call pattern of :class:`TieredGeminiClient`.

The integration is **opt-in**: when ``CLOUDMANAGEMENT_ENABLED`` is unset
or false (the default), :meth:`GeminiCostTracker.is_available` returns
False, :meth:`declare_intent_for_run` returns None, and :meth:`report_call`
is a no-op — the pipeline runs exactly as before with zero behavior change.

When enabled, the script (not the client) declares an intent before a run
via :meth:`declare_intent_for_run`. If the hub approves, the client reports
incremental actuals after each successful API call via
:meth:`report_call`. If the hub denies the intent, :class:`BillingDenied`
is raised so the script can skip paid calls the hub said we can't afford.
If the hub is unreachable, the tracker enters degraded mode: calls proceed
without blocking (best-effort reporting), and a warning is logged.
"""

from __future__ import annotations

import logging
import time
import uuid
from typing import TYPE_CHECKING, Any

# Guarded import: cloud_management_client is vendored at
# src/cloud_management_client/ (stdlib-only). The import is guarded so a
# missing package never crashes the app — the integration is disabled by
# default and only activates when CLOUDMANAGEMENT_ENABLED is true and the
# hub is configured.
try:
    from cloud_management_client import CloudManagementClient
except ImportError:  # pragma: no cover — exercised only when package absent
    CloudManagementClient = None  # type: ignore[assignment,misc]

if TYPE_CHECKING:
    from cloud_management_client import CloudManagementClient  # noqa: F811

_log = logging.getLogger(__name__)

# Conservative per-call cost estimate for gemini-2.5-flash (search-grounded
# + extraction). Used as a fallback when the hub's suggest_expected_cost is
# unavailable. This is a list-price estimate, not a verified figure — the
# hub's own cost history is the authoritative source when available.
_DEFAULT_COST_PER_CALL_USD = 0.01

# How long to stay in degraded mode before retrying the intent declaration.
_CM_RETRY_COOLDOWN_SECONDS = 60.0


class BillingDenied(RuntimeError):
    """Raised when the CloudManagement hub denies an intent declaration.

    The script should catch this, print a clear message, and skip the
    paid-API phase rather than making calls the hub said we can't afford.
    """


class GeminiCostTracker:
    """Tracks Gemini API costs and gates paid calls via the CloudManagement hub.

    Wraps an optional :class:`CloudManagementClient` instance. When the hub
    is not configured or not reachable, cost tracking is disabled and API
    calls proceed without blocking (degraded mode logs a warning).

    Local counters (``total_cost_usd``, ``free_calls``, ``paid_calls``)
    mirror :class:`TieredGeminiClient`'s counters but add dollar amounts.
    """

    def __init__(
        self,
        cloud_management: CloudManagementClient | None = None,
        *,
        enabled: bool = False,
        source_repo: str = "",
        application: str = "",
    ):
        self._cm = cloud_management
        self._enabled_flag = enabled
        self._source_repo = source_repo
        self._application = application

        # Local counters (mirror TieredGeminiClient but with $ amounts).
        self.total_cost_usd: float = 0.0
        self.free_calls: int = 0
        self.paid_calls: int = 0

        # Intent state for the current run.
        self._intent_id: str = ""
        self._job_id: str = ""
        self._provider: str = "google"
        self._api: str = ""

        # Degraded mode: hub unreachable (not a denial). Calls proceed but
        # the declaration is retried at most once per cooldown.
        self._degraded: bool = False
        self._retry_at: float = 0.0

    # ------------------------------------------------------------------
    # Availability
    # ------------------------------------------------------------------

    def is_available(self) -> bool:
        """True when CloudManagement is configured and the client is enabled.

        Returns False when the integration is opt-out (``enabled=False``),
        the client is missing, or the client's ``.enabled`` property is
        False (no project_id + report_token).
        """
        if not self._enabled_flag or self._cm is None:
            return False
        try:
            return bool(self._cm.enabled)
        except Exception as e:
            _log.warning("cost_tracker: CloudManagementClient.enabled check failed: %s", e)
            return False

    # ------------------------------------------------------------------
    # Intent declaration (before a run)
    # ------------------------------------------------------------------

    def declare_intent_for_run(
        self,
        job_id: str,
        expected_calls: int,
        expected_cost_usd: float,
        model: str,
        rate_limit_rpm: int = 0,
    ) -> str | None:
        """Declare intent with the CloudManagement hub before a pipeline run.

        Args:
            job_id: Unique identifier for this run.
            expected_calls: Estimated number of API calls for this run.
            expected_cost_usd: Estimated total cost in USD.
            model: Model name (e.g. "gemini-2.5-flash").
            rate_limit_rpm: Rate limit in requests per minute (0 = unlimited).

        Returns:
            The intent_id if approved, or None if the tracker is disabled
            (opt-out or hub not configured).

        Raises:
            BillingDenied: If the hub explicitly denies the intent.
        """
        if not self.is_available():
            return None

        cb = self._cm
        assert cb is not None  # for type checkers; is_available() checked

        self._job_id = job_id
        self._provider = "google"
        self._api = model

        try:
            intent = cb.declare_intent(
                job_id=job_id,
                job_name="story-graph-targeted-research",
                provider=self._provider,
                api=model,
                expected_calls=expected_calls,
                expected_cost_usd=expected_cost_usd,
                rate_limit_rpm=rate_limit_rpm,
                source_repo=self._source_repo,
                application=self._application,
            )
        except Exception as e:
            # Unexpected client exception — degrade rather than crash.
            _log.warning("cost_tracker: declare_intent raised %s: %s — entering degraded mode", type(e).__name__, e)
            self._enter_degraded("declare_intent exception")
            return None

        # Detect an unreachable hub: the client returns an empty
        # IntentResponse (all defaults) when the transport fails. A genuine
        # denial returns approved=False with a reason and/or intent_id.
        # Also honor an explicit .unreachable attribute if present (newer
        # client versions).
        is_unreachable = getattr(intent, "unreachable", False) or (
            not intent.intent_id and not intent.approved and not intent.reason
        )
        if is_unreachable:
            self._enter_degraded("hub unreachable")
            return None

        if not intent.approved:
            _log.warning(
                "cost_tracker: intent denied — reason=%s budget_remaining=%.2f",
                intent.reason, intent.budget_remaining_usd,
            )
            raise BillingDenied(
                f"CloudManagement intent denied: {intent.reason or 'unknown'}"
            )

        # Approved — clear degraded mode if we were in it.
        if self._degraded:
            _log.warning("cost_tracker: degraded mode recovered — hub reachable again")
            self._degraded = False
            self._retry_at = 0.0

        self._intent_id = intent.intent_id
        _log.info(
            "cost_tracker: intent approved — intent_id=%s budget_remaining=%.2f",
            self._intent_id, intent.budget_remaining_usd,
        )
        return self._intent_id

    def _enter_degraded(self, reason: str) -> None:
        """Enter (or extend) degraded mode after a failed declaration."""
        first = not self._degraded
        self._degraded = True
        self._retry_at = time.monotonic() + _CM_RETRY_COOLDOWN_SECONDS
        if first:
            _log.warning(
                "cost_tracker: degraded mode — reason=%s, calls proceed without "
                "hub gating, retry in %ds",
                reason, int(_CM_RETRY_COOLDOWN_SECONDS),
            )

    @property
    def degraded(self) -> bool:
        """True when the hub is unreachable and degraded mode is in force."""
        return self._degraded

    # ------------------------------------------------------------------
    # Per-call actual reporting (best-effort, never raises)
    # ------------------------------------------------------------------

    def report_call(
        self,
        tier: str,
        model: str,
        cost_usd: float,
        calls: int = 1,
    ) -> None:
        """Report an incremental actual API call to the hub (best-effort).

        Args:
            tier: "free" or "paid" — which Gemini tier the call used.
            model: Model name for this call.
            cost_usd: Estimated cost of this call in USD.
            calls: Number of calls (default 1).

        Never raises — all errors are logged at WARNING. Updates local
        counters regardless of hub reporting success.
        """
        # Update local counters always (even if hub is down).
        if tier == "free":
            self.free_calls += calls
        elif tier == "paid":
            self.paid_calls += calls
        else:
            _log.warning("cost_tracker: unknown tier %r — counters not updated", tier)
            return
        self.total_cost_usd += cost_usd * calls

        # Report to hub (best-effort).
        if not self.is_available() or not self._intent_id:
            return

        cb = self._cm
        assert cb is not None
        try:
            cb.report_actual(
                intent_id=self._intent_id,
                job_id=self._job_id,
                provider=self._provider,
                api=model,
                actual_calls=self.free_calls + self.paid_calls,
                actual_cost_usd=self.total_cost_usd,
                status="running",
                free_tier=(tier == "free"),
            )
        except Exception as e:
            _log.warning("cost_tracker: report_actual failed (best-effort): %s", e)

    # ------------------------------------------------------------------
    # Kill-switch polling
    # ------------------------------------------------------------------

    def check_killed(self) -> list[Any]:
        """Poll the hub for kill orders targeting this project.

        Returns a list of kill-order objects. An empty list means no kill
        orders (the job should continue). Returns an empty list when the
        tracker is disabled.
        """
        if not self.is_available():
            return []
        cb = self._cm
        assert cb is not None
        try:
            return cb.check_kill_orders()
        except Exception as e:
            _log.warning("cost_tracker: check_kill_orders failed (best-effort): %s", e)
            return []

    # ------------------------------------------------------------------
    # Finalization
    # ------------------------------------------------------------------

    def finalize(self, status: str = "completed") -> None:
        """Send a synchronous final report, flush, and close the hub client.

        Args:
            status: "completed" or "failed".

        Best-effort — never raises. When the tracker is disabled, this is
        a no-op. Idempotent — a second call is a no-op (the intent_id is
        cleared after the first finalize).
        """
        if not self.is_available() or not self._intent_id:
            return
        cb = self._cm
        assert cb is not None
        intent_id = self._intent_id
        # Clear intent_id first so a concurrent/recursive call is a no-op.
        self._intent_id = ""
        try:
            cb.report_actual(
                intent_id=intent_id,
                job_id=self._job_id,
                provider=self._provider,
                api=self._api,
                actual_calls=self.free_calls + self.paid_calls,
                actual_cost_usd=self.total_cost_usd,
                status=status,
                sync=True,
            )
        except Exception as e:
            _log.warning("cost_tracker: final report_actual failed: %s", e)
        try:
            cb.flush()
        except Exception as e:
            _log.warning("cost_tracker: flush failed: %s", e)
        try:
            cb.close()
        except Exception as e:
            _log.warning("cost_tracker: close failed: %s", e)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def suggest_expected_cost(self, provider: str, api: str, expected_calls: int) -> float | None:
        """Ask the hub for a suggested expected cost, or fall back to a default.

        Returns None when the tracker is disabled.
        """
        if not self.is_available():
            return None
        cb = self._cm
        assert cb is not None
        try:
            suggested = cb.suggest_expected_cost(provider, api, expected_calls)
            if suggested is not None and suggested > 0:
                return suggested
        except Exception as e:
            _log.warning("cost_tracker: suggest_expected_cost failed: %s", e)
        # Fallback: conservative per-call estimate.
        return round(expected_calls * _DEFAULT_COST_PER_CALL_USD, 4)

    @property
    def job_id(self) -> str:
        """The CloudManagement job_id for the current run (empty if not declared)."""
        return self._job_id

    @property
    def intent_id(self) -> str:
        """The CloudManagement intent_id for the current run (empty if not declared)."""
        return self._intent_id


def make_cost_tracker_from_settings() -> GeminiCostTracker:
    """Construct a GeminiCostTracker from the story_graph settings.

    Returns a disabled tracker (``is_available() == False``) when
    ``CLOUDMANAGEMENT_ENABLED`` is false/unset — the default opt-out state.
    The CloudManagementClient is only constructed when enabled, so the
    vendored package is never imported unless the integration is opted in.
    """
    # Late import to avoid a circular dependency at module load.
    from config.settings import settings

    if not settings.cloudmanagement_enabled:
        return GeminiCostTracker(enabled=False)

    if CloudManagementClient is None:
        _log.warning(
            "cost_tracker: CLOUDMANAGEMENT_ENABLED=true but cloud_management_client "
            "package is not importable — cost tracking disabled"
        )
        return GeminiCostTracker(enabled=False)

    cm = CloudManagementClient(
        project_id=settings.cloudmanagement_project_id,
        report_token=settings.cloudmanagement_report_token,
        base_url=settings.cloudmanagement_url,
        source_repo=settings.cloudmanagement_source_repo,
        application=settings.cloudmanagement_application,
        timeout=settings.cloudmanagement_timeout,
        intent_timeout=settings.cloudmanagement_intent_timeout,
        strict=settings.cloudmanagement_strict,
    )
    return GeminiCostTracker(
        cloud_management=cm,
        enabled=True,
        source_repo=settings.cloudmanagement_source_repo,
        application=settings.cloudmanagement_application,
    )


def make_run_job_id() -> str:
    """Generate a unique job_id for a pipeline run."""
    return f"story-graph-{uuid.uuid4().hex[:12]}"
