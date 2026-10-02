"""Domain models for jobs."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from app.domain.constants import JobStatus, JobType


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class Job:
    id: str
    job_type: JobType
    status: JobStatus
    created_at: datetime
    updated_at: datetime
    command: list[str]
    request: dict[str, Any] = field(default_factory=dict)
    stamp: str | None = None
    exit_code: int | None = None
    log_tail: str = ""
    error_message: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None

    @classmethod
    def create(
        cls,
        *,
        job_type: JobType,
        command: list[str],
        request: dict[str, Any],
    ) -> Job:
        now = utc_now()
        return cls(
            id=str(uuid4()),
            job_type=job_type,
            status=JobStatus.QUEUED,
            created_at=now,
            updated_at=now,
            command=command,
            request=request,
        )