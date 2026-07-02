"""Tests for the in-process background job manager."""

import threading
import time

from kryptoskatt.services.jobs import JobManager


def _wait_for(predicate, timeout: float = 5.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return False


class TestJobManager:
    def test_job_runs_and_completes(self):
        manager = JobManager()
        job = manager.start(1, "test", lambda j: "klart!")

        assert job is not None
        assert _wait_for(lambda: job.status == "done")
        assert job.message == "klart!"
        assert job.finished_at is not None

    def test_job_failure_sets_error_status(self):
        manager = JobManager()

        def boom(job):
            raise RuntimeError("något gick fel")

        job = manager.start(1, "test", boom)
        assert _wait_for(lambda: job.status == "error")
        assert "något gick fel" in job.message

    def test_only_one_running_job_per_user(self):
        manager = JobManager()
        release = threading.Event()

        def slow(job):
            release.wait(timeout=5)
            return "ok"

        first = manager.start(1, "slow", slow)
        assert first is not None
        second = manager.start(1, "slow", slow)
        assert second is None, "second concurrent job for same user must be refused"

        # A different user is not blocked
        other = manager.start(2, "slow", lambda j: "ok")
        assert other is not None

        release.set()
        assert _wait_for(lambda: first.status == "done")

        # After completion the user can start a new job
        third = manager.start(1, "again", lambda j: "ok")
        assert third is not None
        assert _wait_for(lambda: third.status == "done")

    def test_get_enforces_ownership(self):
        manager = JobManager()
        job = manager.start(1, "test", lambda j: "ok")
        assert _wait_for(lambda: job.status == "done")

        assert manager.get(job.id, 1) is job
        assert manager.get(job.id, 2) is None
        assert manager.get("nonexistent", 1) is None

    def test_progress_message_visible_while_running(self):
        manager = JobManager()
        release = threading.Event()

        def with_progress(job):
            job.message = "steg 1/2"
            release.wait(timeout=5)
            return "färdigt"

        job = manager.start(1, "progress", with_progress)
        assert _wait_for(lambda: job.message == "steg 1/2")
        assert job.status == "running"
        release.set()
        assert _wait_for(lambda: job.status == "done")
        assert job.message == "färdigt"
