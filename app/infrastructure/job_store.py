"""SQLite job history store."""

from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime
from pathlib import Path
from typing import Any

from app.domain.constants import JobStatus, JobType
from app.domain.models import Job


def _dt_to_str(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.isoformat()


def _dt_from_str(value: str | None) -> datetime | None:
    if value is None:
        return None
    return datetime.fromisoformat(value)


class JobStore:
    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path
        self._lock = threading.Lock()
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_schema(self) -> None:
        with self._lock:
            conn = self._connect()
            try:
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS jobs (
                        id TEXT PRIMARY KEY,
                        job_type TEXT NOT NULL,
                        status TEXT NOT NULL,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL,
                        started_at TEXT,
                        finished_at TEXT,
                        stamp TEXT,
                        exit_code INTEGER,
                        request_json TEXT NOT NULL,
                        command_json TEXT NOT NULL,
                        log_tail TEXT NOT NULL DEFAULT '',
                        error_message TEXT
                    )
                    """
                )
                conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_jobs_type_created ON jobs(job_type, created_at DESC)"
                )
                conn.commit()
            finally:
                conn.close()

    def create(self, job: Job) -> Job:
        with self._lock:
            conn = self._connect()
            try:
                conn.execute(
                    """
                    INSERT INTO jobs (
                        id, job_type, status, created_at, updated_at, started_at, finished_at,
                        stamp, exit_code, request_json, command_json, log_tail, error_message
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        job.id,
                        job.job_type.value,
                        job.status.value,
                        _dt_to_str(job.created_at),
                        _dt_to_str(job.updated_at),
                        _dt_to_str(job.started_at),
                        _dt_to_str(job.finished_at),
                        job.stamp,
                        job.exit_code,
                        json.dumps(job.request),
                        json.dumps(job.command),
                        job.log_tail,
                        job.error_message,
                    ),
                )
                conn.commit()
            finally:
                conn.close()
        return job

    def update(self, job: Job) -> Job:
        with self._lock:
            conn = self._connect()
            try:
                conn.execute(
                    """
                    UPDATE jobs SET
                        status = ?,
                        updated_at = ?,
                        started_at = ?,
                        finished_at = ?,
                        stamp = ?,
                        exit_code = ?,
                        request_json = ?,
                        command_json = ?,
                        log_tail = ?,
                        error_message = ?
                    WHERE id = ?
                    """,
                    (
                        job.status.value,
                        _dt_to_str(job.updated_at),
                        _dt_to_str(job.started_at),
                        _dt_to_str(job.finished_at),
                        job.stamp,
                        job.exit_code,
                        json.dumps(job.request),
                        json.dumps(job.command),
                        job.log_tail,
                        job.error_message,
                        job.id,
                    ),
                )
                conn.commit()
            finally:
                conn.close()
        return job

    def get(self, job_id: str) -> Job | None:
        with self._lock:
            conn = self._connect()
            try:
                row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
            finally:
                conn.close()
        if row is None:
            return None
        return self._row_to_job(row)

    def list_by_type(
        self,
        job_type: JobType,
        *,
        page: int,
        size: int,
    ) -> tuple[list[Job], int]:
        offset = (page - 1) * size
        with self._lock:
            conn = self._connect()
            try:
                total_row = conn.execute(
                    "SELECT COUNT(*) AS c FROM jobs WHERE job_type = ?",
                    (job_type.value,),
                ).fetchone()
                total = int(total_row["c"])
                rows = conn.execute(
                    """
                    SELECT * FROM jobs
                    WHERE job_type = ?
                    ORDER BY created_at DESC
                    LIMIT ? OFFSET ?
                    """,
                    (job_type.value, size, offset),
                ).fetchall()
            finally:
                conn.close()
        return [self._row_to_job(row) for row in rows], total

    def has_active_job(self) -> bool:
        with self._lock:
            conn = self._connect()
            try:
                row = conn.execute(
                    """
                    SELECT 1 FROM jobs
                    WHERE status IN (?, ?)
                    LIMIT 1
                    """,
                    (JobStatus.QUEUED.value, JobStatus.RUNNING.value),
                ).fetchone()
            finally:
                conn.close()
        return row is not None

    @staticmethod
    def _row_to_job(row: sqlite3.Row) -> Job:
        return Job(
            id=row["id"],
            job_type=JobType(row["job_type"]),
            status=JobStatus(row["status"]),
            created_at=_dt_from_str(row["created_at"]),  # type: ignore[arg-type]
            updated_at=_dt_from_str(row["updated_at"]),  # type: ignore[arg-type]
            started_at=_dt_from_str(row["started_at"]),
            finished_at=_dt_from_str(row["finished_at"]),
            stamp=row["stamp"],
            exit_code=row["exit_code"],
            request=json.loads(row["request_json"]),
            command=json.loads(row["command_json"]),
            log_tail=row["log_tail"] or "",
            error_message=row["error_message"],
        )