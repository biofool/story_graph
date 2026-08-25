"""Unit tests for scripts/_run_lock.py -- the scheduled job's overlap guard."""

from __future__ import annotations

import json
import time

from scripts._run_lock import LOCK_FILENAME, RunLock


class TestDisabled:
    """No lock_dir configured -- locking is a no-op (e.g. local/manual runs)."""

    def test_acquire_returns_true_with_no_lock_dir(self):
        lock = RunLock(None)
        assert lock.enabled is False
        assert lock.acquire() is True

    def test_release_is_a_safe_noop_with_no_lock_dir(self):
        lock = RunLock(None)
        assert lock.acquire() is True
        lock.release()  # must not raise


class TestAcquireRelease:
    def test_acquire_creates_lock_file(self, tmp_path):
        lock = RunLock(tmp_path)
        assert lock.enabled is True
        assert lock.acquire() is True
        assert (tmp_path / LOCK_FILENAME).exists()

    def test_acquire_creates_missing_lock_dir(self, tmp_path):
        lock_dir = tmp_path / "nested" / "state"
        lock = RunLock(lock_dir)
        assert lock.acquire() is True
        assert (lock_dir / LOCK_FILENAME).exists()

    def test_lock_file_contains_timestamp_and_execution_id(self, tmp_path):
        lock = RunLock(tmp_path)
        before = time.time()
        assert lock.acquire() is True
        after = time.time()

        payload = json.loads((tmp_path / LOCK_FILENAME).read_text())
        assert before <= payload["acquired_at"] <= after
        assert payload["execution_id"]

    def test_release_removes_lock_file(self, tmp_path):
        lock = RunLock(tmp_path)
        assert lock.acquire() is True
        lock.release()
        assert not (tmp_path / LOCK_FILENAME).exists()

    def test_release_before_acquire_is_a_noop(self, tmp_path):
        lock = RunLock(tmp_path)
        lock.release()  # must not raise, must not create anything
        assert not (tmp_path / LOCK_FILENAME).exists()

    def test_second_lock_can_acquire_after_first_releases(self, tmp_path):
        first = RunLock(tmp_path)
        assert first.acquire() is True
        first.release()

        second = RunLock(tmp_path)
        assert second.acquire() is True


class TestOverlapDetection:
    def test_acquire_fails_when_fresh_lock_already_held(self, tmp_path):
        holder = RunLock(tmp_path, stale_after_seconds=3600)
        assert holder.acquire() is True

        contender = RunLock(tmp_path, stale_after_seconds=3600)
        assert contender.acquire() is False
        # The contender never held it, so its release() must be a no-op --
        # the original holder's lock file must survive untouched.
        contender.release()
        assert (tmp_path / LOCK_FILENAME).exists()

    def test_acquire_reclaims_stale_lock(self, tmp_path):
        lock_path = tmp_path / LOCK_FILENAME
        stale_payload = {
            "acquired_at": time.time() - 10_000,  # long past any reasonable threshold
            "execution_id": "crashed-run",
        }
        lock_path.write_text(json.dumps(stale_payload))

        lock = RunLock(tmp_path, stale_after_seconds=60)
        assert lock.acquire() is True

        new_payload = json.loads(lock_path.read_text())
        assert new_payload["execution_id"] != "crashed-run"

    def test_acquire_treats_corrupt_lock_file_as_absent(self, tmp_path):
        lock_path = tmp_path / LOCK_FILENAME
        lock_path.write_text("not json")

        lock = RunLock(tmp_path, stale_after_seconds=3600)
        assert lock.acquire() is True


class TestFromSettings:
    def test_disabled_when_settings_job_lock_dir_is_empty(self, monkeypatch):
        monkeypatch.setattr("config.settings.settings.job_lock_dir", "")
        lock = RunLock.from_settings()
        assert lock.enabled is False
        assert lock.acquire() is True

    def test_enabled_and_uses_configured_stale_threshold(self, tmp_path, monkeypatch):
        monkeypatch.setattr("config.settings.settings.job_lock_dir", str(tmp_path))
        monkeypatch.setattr("config.settings.settings.lock_stale_after_seconds", 42)

        lock = RunLock.from_settings()
        assert lock.enabled is True
        assert lock._stale_after_seconds == 42
        assert lock.acquire() is True
        assert (tmp_path / LOCK_FILENAME).exists()


class TestFailsOpenOnWriteError:
    def test_acquire_returns_true_when_lock_dir_is_unwritable(self, tmp_path):
        # Point the lock at a path that can't be created as a directory
        # (its parent is actually a file), simulating a transient
        # mount/permission failure -- acquire() must fail open rather than
        # blocking the whole run over the overlap guard.
        blocking_file = tmp_path / "not_a_dir"
        blocking_file.write_text("occupied")

        lock = RunLock(blocking_file / "lock_subdir")
        assert lock.acquire() is True
