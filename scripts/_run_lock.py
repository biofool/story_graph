"""
Overlap guard for the scheduled targeted-research Cloud Run Job.

infra/main.tf's `parallelism = 1` / `task_count = 1` on the Cloud Run Job
only prevents fan-out *within one execution* -- it does not stop two
separate *executions* from running at once (e.g. the daily 06:00 UTC Cloud
Scheduler trigger overlapping someone's manual
`gcloud run jobs execute`). Both would then race for the same shared
Gemini free-tier daily quota, which is the exact failure mode this whole
deployment exists to manage. Cloud Run Jobs have no native "reject if
already running" switch, so this is handled at the application layer
instead.

RunLock is a minimal, deliberately simple marker-file lock, not a
distributed-systems-grade mutex:

  - It is staleness-based: a lock older than ``stale_after_seconds`` is
    treated as abandoned (the execution that held it crashed, was killed,
    or hit the Cloud Run task timeout) and is silently reclaimed, so a bad
    run can never permanently deadlock every future scheduled run.
  - There is a narrow TOCTOU race between checking whether a lock exists
    and creating one -- for this job's actual traffic pattern (one daily
    cron trigger, plus rare/manual executions) that race is not worth
    building a real distributed lock (e.g. GCS conditional writes) to
    close.

Locking only happens when a lock directory is configured -- pass the
directory explicitly, or use ``RunLock.from_settings()`` to read it from
``config.settings.settings.job_lock_dir`` (set by infra/main.tf to the
mounted GCS state bucket's mount path when ``create_state_bucket = true``;
left empty for local/manual runs, which have no shared storage to lock
against and skip locking entirely -- not an error).
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from pathlib import Path

_log = logging.getLogger(__name__)

LOCK_FILENAME = ".targeted_research_job.lock"

# 2 hours: comfortably above the Cloud Run Job's default task_timeout_seconds
# (1800s / 30 minutes, see infra/variables.tf) so a slow-but-healthy run is
# never mistaken for stale, while still reclaiming a crashed run's lock well
# before the next day's scheduled trigger.
DEFAULT_STALE_AFTER_SECONDS = 2 * 60 * 60


class RunLock:
    """A simple staleness-checked marker-file lock.

    Usage::

        lock = RunLock.from_settings()
        if not lock.acquire():
            log.warning("another execution is already running -- exiting")
            sys.exit(0)
        try:
            ... do work ...
        finally:
            lock.release()
    """

    def __init__(
        self,
        lock_dir: str | Path | None,
        stale_after_seconds: int = DEFAULT_STALE_AFTER_SECONDS,
    ) -> None:
        self._path = Path(lock_dir) / LOCK_FILENAME if lock_dir else None
        self._stale_after_seconds = stale_after_seconds
        self._held = False

    @classmethod
    def from_settings(cls) -> RunLock:
        from config.settings import settings

        return cls(
            settings.job_lock_dir or None,
            stale_after_seconds=settings.lock_stale_after_seconds,
        )

    @property
    def enabled(self) -> bool:
        """Whether this lock actually guards anything (a lock_dir was configured)."""
        return self._path is not None

    def acquire(self) -> bool:
        """Attempt to acquire the lock.

        Returns True if acquired -- including when locking is disabled
        (no lock_dir configured), since there is nothing to guard against.
        Returns False if another execution already holds a non-stale lock;
        the caller should log and exit early rather than proceeding.
        """
        if self._path is None:
            return True

        existing = self._read()
        if existing is not None:
            age = time.time() - existing.get("acquired_at", 0)
            if age < self._stale_after_seconds:
                _log.warning(
                    "Lock %s is held by execution %s (age %.0fs, stale threshold "
                    "%ds) -- another run appears to be in progress. Exiting early "
                    "rather than racing it for the same Gemini quota.",
                    self._path,
                    existing.get("execution_id", "?"),
                    age,
                    self._stale_after_seconds,
                )
                return False
            _log.warning(
                "Lock %s is stale (age %.0fs >= %ds threshold, execution_id=%s) "
                "-- treating it as abandoned by a crashed/killed run and "
                "reclaiming it.",
                self._path,
                age,
                self._stale_after_seconds,
                existing.get("execution_id", "?"),
            )

        payload = {"acquired_at": time.time(), "execution_id": str(uuid.uuid4())}
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._path.write_text(json.dumps(payload))
        except OSError as e:
            # Can't write the lock (e.g. transient GCS FUSE hiccup, mount
            # not yet ready) -- fail open rather than blocking the whole run
            # over an overlap guard; log loudly so it's visible in Cloud
            # Logging even though this deliberately does not raise.
            _log.warning(
                "Could not write lock file %s (%s) -- proceeding without "
                "overlap protection for this run.",
                self._path,
                e,
            )
            return True
        self._held = True
        return True

    def release(self) -> None:
        """Release the lock, if this instance holds it. Safe to call
        unconditionally (no-op when locking is disabled or acquire()
        returned False)."""
        if self._path is None or not self._held:
            return
        try:
            self._path.unlink(missing_ok=True)
        except OSError as e:
            _log.warning("Could not remove lock file %s (%s)", self._path, e)
        self._held = False

    def _read(self) -> dict | None:
        if self._path is None or not self._path.exists():
            return None
        try:
            return json.loads(self._path.read_text())
        except (OSError, ValueError):
            # Corrupt/unreadable lock file -- treat as no lock rather than
            # erroring, matching the "fail open" bias of this guard.
            return None
