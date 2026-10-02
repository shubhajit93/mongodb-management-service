"""Single-flight job orchestration over the shell scripts."""

from __future__ import annotations

import logging
import re
import threading
from typing import Callable

from app.domain.constants import JobStatus, JobType
from app.domain.errors import ConflictError, NotFoundError
from app.domain.models import Job, utc_now
from app.infrastructure.env_file import EnvFileStore
from app.infrastructure.job_store import JobStore
from app.infrastructure.process_runner import ProcessRunner

logger = logging.getLogger(__name__)

_STAMP_RE = re.compile(r"(?:stamp=|Backup completed successfully for |timestamp )([0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{4}Z)")


class JobService:
    def __init__(
        self,
        *,
        store: JobStore,
        runner: ProcessRunner,
        env_store: EnvFileStore,
        log_max_chars: int,
        timeout_seconds: int,
        thread_factory: Callable[..., threading.Thread] | None = None,
    ) -> None:
        self._store = store
        self._runner = runner
        self._env_store = env_store
        self._log_max_chars = log_max_chars
        self._timeout_seconds = timeout_seconds
        self._thread_factory = thread_factory or threading.Thread
        self._lock = threading.Lock()

    def start(self, *, job_type: JobType, command: list[str], request: dict) -> Job:
        with self._lock:
            if self._store.has_active_job():
                raise ConflictError("A backup or restore job is already running")
            job = Job.create(job_type=job_type, command=command, request=request)
            self._store.create(job)

        worker = self._thread_factory(
            target=self._run_job,
            args=(job.id,),
            name=f"asat-job-{job.id}",
            daemon=True,
        )
        worker.start()
        # Reload so synchronous test workers and fast completions return current status.
        return self._store.get(job.id) or job

    def get(self, job_id: str) -> Job:
        job = self._store.get(job_id)
        if job is None:
            raise NotFoundError(f"Job not found: {job_id}")
        return job

    def list(self, job_type: JobType, *, page: int, size: int) -> tuple[list[Job], int]:
        return self._store.list_by_type(job_type, page=page, size=size)

    def has_active_job(self) -> bool:
        return self._store.has_active_job()

    def _run_job(self, job_id: str) -> None:
        job = self._store.get(job_id)
        if job is None:
            return
        job.status = JobStatus.RUNNING
        job.started_at = utc_now()
        job.updated_at = job.started_at
        self._store.update(job)

        try:
            env = self._env_store.as_process_env()
            result = self._runner.run(
                job.command,
                env=env,
                timeout_seconds=self._timeout_seconds,
            )
            log_tail = result.combined_output
            if len(log_tail) > self._log_max_chars:
                log_tail = log_tail[-self._log_max_chars :]
            job.log_tail = log_tail
            job.exit_code = result.exit_code
            job.stamp = self._extract_stamp(log_tail, job.request)
            job.finished_at = utc_now()
            job.updated_at = job.finished_at
            if result.exit_code == 0:
                job.status = JobStatus.SUCCEEDED
                job.error_message = None
            else:
                job.status = JobStatus.FAILED
                job.error_message = f"Script exited with code {result.exit_code}"
            self._store.update(job)
            logger.info(
                "job_finished",
                extra={
                    "job_id": job.id,
                    "job_type": job.job_type.value,
                    "status": job.status.value,
                    "exit_code": job.exit_code,
                },
            )
        except Exception as exc:  # noqa: BLE001 - background worker must never crash the process
            job.status = JobStatus.FAILED
            job.error_message = str(exc)
            job.finished_at = utc_now()
            job.updated_at = job.finished_at
            job.log_tail = (job.log_tail + f"\nERROR: {exc}").strip()
            if len(job.log_tail) > self._log_max_chars:
                job.log_tail = job.log_tail[-self._log_max_chars :]
            self._store.update(job)
            logger.exception("job_failed", extra={"job_id": job_id})

    @staticmethod
    def _extract_stamp(log_tail: str, request: dict) -> str | None:
        if request.get("timestamp"):
            return str(request["timestamp"])
        match = _STAMP_RE.search(log_tail)
        if match:
            return match.group(1)
        return None