"""In-process background job manager for long-running actions.

Fetch-all and GAV calculation can take minutes (external API calls with
retry/backoff). Running them inside the request handler blocks the
worker and times out behind reverse proxies. This module runs them in a
daemon thread and lets the UI poll job status.

Limitations (by design, matching the in-memory rate limiter):
- Jobs live in process memory: a restart loses status (not the work
  already committed to the DB — fetch/calculate commit incrementally).
- With multiple uvicorn workers each worker has its own job table; the
  session-cookie'd user polls the worker that spawned the job only if
  the proxy uses sticky sessions. Single-worker deployments (default
  docker-compose) are unaffected.
"""

import logging
import threading
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime

logger = logging.getLogger(__name__)

MAX_FINISHED_JOBS = 50


@dataclass
class Job:
    id: str
    user_id: int
    name: str
    status: str = "running"  # running | done | error
    message: str = ""
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    finished_at: datetime | None = None


class JobManager:
    """Thread-based job runner with per-user single-concurrency."""

    def __init__(self) -> None:
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()

    def start(self, user_id: int, name: str, fn: Callable[[Job], str]) -> Job | None:
        """Start `fn` in a background thread.

        `fn` receives the Job (it may update `job.message` for progress)
        and returns the final success message.

        Returns None if the user already has a running job.
        """
        with self._lock:
            if any(j.user_id == user_id and j.status == "running" for j in self._jobs.values()):
                return None
            job = Job(id=uuid.uuid4().hex, user_id=user_id, name=name)
            self._jobs[job.id] = job

        thread = threading.Thread(
            target=self._run, args=(job, fn), name=f"job-{name}-{job.id[:8]}", daemon=True
        )
        thread.start()
        return job

    def get(self, job_id: str, user_id: int) -> Job | None:
        """Return a job by id, only if owned by `user_id`."""
        job = self._jobs.get(job_id)
        if job is None or job.user_id != user_id:
            return None
        return job

    def _run(self, job: Job, fn: Callable[[Job], str]) -> None:
        try:
            job.message = fn(job)
            job.status = "done"
        except Exception as e:
            logger.exception("Background job %s (%s) failed", job.id, job.name)
            job.status = "error"
            job.message = str(e)
        job.finished_at = datetime.now(UTC)
        self._prune()

    def _prune(self) -> None:
        """Keep only the most recent finished jobs."""
        with self._lock:
            finished = sorted(
                (j for j in self._jobs.values() if j.status != "running"),
                key=lambda j: j.finished_at or j.created_at,
            )
            for job in finished[:-MAX_FINISHED_JOBS]:
                self._jobs.pop(job.id, None)


# Singleton used by web routes
job_manager = JobManager()
