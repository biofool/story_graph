"""SQLite-backed search query cache.

Caches search API responses keyed by SHA-256(query + params) to avoid
re-spending API quota on identical queries. Empty result sets are not
cached (they may be transient). Default TTL: 30 days.

Ported and adapted from WorldStudioFinder's places_api_cache pattern.
"""

from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

_log = logging.getLogger(__name__)


class SearchCache:
    """Persistent SQLite cache for search query results."""

    def __init__(self, db_path: str | Path, ttl_days: int = 30):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.ttl_days = ttl_days
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
            CREATE TABLE IF NOT EXISTS search_cache (
                cache_key   TEXT PRIMARY KEY,
                query       TEXT NOT NULL,
                provider    TEXT NOT NULL,
                params_json TEXT NOT NULL,
                results     TEXT NOT NULL,
                created_at  TEXT NOT NULL,
                expires_at  TEXT NOT NULL
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_search_cache_query ON search_cache(query)"
        )
        conn.commit()

    @staticmethod
    def _make_key(query: str, provider: str, params: dict) -> str:
        """SHA-256 of query + provider + sorted params."""
        param_str = json.dumps(params, sort_keys=True)
        raw = f"{query}|{provider}|{param_str}"
        return hashlib.sha256(raw.encode()).hexdigest()

    def get(
        self, query: str, provider: str, params: dict | None = None
    ) -> list[dict] | None:
        """Return cached results if present and not expired, else None."""
        params = params or {}
        key = self._make_key(query, provider, params)
        conn = self._get_conn()
        row = conn.execute(
            "SELECT results, expires_at FROM search_cache WHERE cache_key = ?",
            (key,),
        ).fetchone()
        if row is None:
            return None
        expires = datetime.fromisoformat(row["expires_at"])
        if datetime.now(timezone.utc) > expires:
            _log.debug("Cache expired for query: %s", query[:60])
            return None
        return json.loads(row["results"])

    def put(
        self,
        query: str,
        provider: str,
        results: list[dict],
        params: dict | None = None,
    ) -> None:
        """Cache results. Empty result sets are not cached."""
        if not results:
            _log.debug("Skipping cache for empty results: %s", query[:60])
            return
        params = params or {}
        key = self._make_key(query, provider, params)
        now = datetime.now(timezone.utc)
        expires = now + timedelta(days=self.ttl_days)
        conn = self._get_conn()
        conn.execute(
            """
            INSERT OR REPLACE INTO search_cache
                (cache_key, query, provider, params_json, results, created_at, expires_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                key,
                query,
                provider,
                json.dumps(params, sort_keys=True),
                json.dumps(results),
                now.isoformat(),
                expires.isoformat(),
            ),
        )
        conn.commit()

    def close(self):
        if self._conn:
            self._conn.close()
            self._conn = None
