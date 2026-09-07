"""Quota budget enforcement and API usage tracking for search.

Tracks per-provider call counts and enforces session + monthly budget
caps. When a budget is exceeded, a BudgetExceeded exception is raised
so the caller can halt gracefully.

Ported and adapted from WorldStudioFinder's QuotaBudget pattern
(src/scrapers/google_places_api.py:86) and api_usage tracking
(src/utils/api_usage.py).
"""

from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

_log = logging.getLogger(__name__)


class BudgetExceeded(Exception):
    """Raised when a session or monthly budget is exhausted."""


class QuotaTracker:
    """Tracks API call counts per provider with session + monthly caps."""

    def __init__(
        self,
        db_path: str | Path,
        session_budget: int = 100,
        monthly_budget: int = 2000,
    ):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.session_budget = session_budget
        self.monthly_budget = monthly_budget
        self._session_counts: dict[str, int] = {}
        self._conn: sqlite3.Connection | None = None
        self._init_db()

    def _get_conn(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = sqlite3.connect(str(self.db_path))
            self._conn.row_factory = sqlite3.Row
        return self._conn

    def _init_db(self):
        conn = self._get_conn()
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS api_call_log (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                provider    TEXT NOT NULL,
                query       TEXT,
                called_at   TEXT NOT NULL,
                result_count INTEGER DEFAULT 0,
                cached      INTEGER DEFAULT 0
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_call_log_provider ON api_call_log(provider)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_call_log_date ON api_call_log(called_at)"
        )
        conn.commit()

    def _monthly_count(self, provider: str) -> int:
        conn = self._get_conn()
        now = datetime.now(timezone.utc)
        month_start = now.strftime("%Y-%m-01T00:00:00")
        row = conn.execute(
            "SELECT COUNT(*) as cnt FROM api_call_log WHERE provider = ? AND called_at >= ? AND cached = 0",
            (provider, month_start),
        ).fetchone()
        return row["cnt"] if row else 0

    def check_budget(self, provider: str) -> None:
        """Raise BudgetExceeded if session or monthly budget is exhausted."""
        session_used = self._session_counts.get(provider, 0)
        if session_used >= self.session_budget:
            raise BudgetExceeded(
                f"Session budget for {provider} reached: {session_used}/{self.session_budget}"
            )
        monthly_used = self._monthly_count(provider)
        if monthly_used >= self.monthly_budget:
            raise BudgetExceeded(
                f"Monthly budget for {provider} reached: {monthly_used}/{self.monthly_budget}"
            )

    def record_call(
        self,
        provider: str,
        query: str,
        result_count: int = 0,
        cached: bool = False,
    ) -> None:
        """Log an API call and increment session counter."""
        if not cached:
            self._session_counts[provider] = self._session_counts.get(provider, 0) + 1
        conn = self._get_conn()
        conn.execute(
            """
            INSERT INTO api_call_log (provider, query, called_at, result_count, cached)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                provider,
                query[:200],
                datetime.now(timezone.utc).isoformat(),
                result_count,
                1 if cached else 0,
            ),
        )
        conn.commit()

    def status(self) -> dict:
        """Return current budget status for all providers."""
        providers = set(self._session_counts.keys())
        # Also include providers from the log
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT DISTINCT provider FROM api_call_log"
        ).fetchall()
        providers.update(r["provider"] for r in rows)

        return {
            p: {
                "session_used": self._session_counts.get(p, 0),
                "session_budget": self.session_budget,
                "monthly_used": self._monthly_count(p),
                "monthly_budget": self.monthly_budget,
            }
            for p in sorted(providers)
        }

    def close(self):
        if self._conn:
            self._conn.close()
            self._conn = None
