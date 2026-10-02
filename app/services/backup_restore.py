"""Backup and restore command builders and services."""

from __future__ import annotations

from pathlib import Path

from app.domain.constants import JobType
from app.domain.errors import ValidationError
from app.domain.models import Job
from app.schemas import BackupCreateRequest, RestoreCreateRequest
from app.services.job_service import JobService


class BackupService:
    def __init__(
        self,
        *,
        job_service: JobService,
        backup_script: Path,
        backup_env_file: Path,
    ) -> None:
        self._jobs = job_service
        self._script = backup_script
        self._env_file = backup_env_file

    def start(self, request: BackupCreateRequest) -> Job:
        if not self._script.is_file():
            raise ValidationError(f"Backup script not found: {self._script}")
        if not self._env_file.is_file():
            raise ValidationError(f"Backup env file not found: {self._env_file}")
        command = [
            str(self._script),
            "--env-file",
            str(self._env_file),
        ]
        if request.slot:
            command.extend(["--slot", request.slot])
        if request.databases:
            command.extend(["--databases", ",".join(request.databases)])
        if request.dryRun:
            command.append("--dry-run")
        return self._jobs.start(
            job_type=JobType.BACKUP,
            command=command,
            request=request.model_dump(mode="json"),
        )

    def get(self, job_id: str) -> Job:
        job = self._jobs.get(job_id)
        if job.job_type != JobType.BACKUP:
            raise ValidationError("Job is not a backup job")
        return job

    def list(self, *, page: int, size: int) -> tuple[list[Job], int]:
        return self._jobs.list(JobType.BACKUP, page=page, size=size)


class RestoreService:
    def __init__(
        self,
        *,
        job_service: JobService,
        restore_script: Path,
        backup_env_file: Path,
        production_port: int,
        default_restore_port: int,
        confirm_phrase: str,
    ) -> None:
        self._jobs = job_service
        self._script = restore_script
        self._env_file = backup_env_file
        self._production_port = production_port
        self._default_restore_port = default_restore_port
        self._confirm_phrase = confirm_phrase

    def start(self, request: RestoreCreateRequest) -> Job:
        if not self._script.is_file():
            raise ValidationError(f"Restore script not found: {self._script}")
        if not self._env_file.is_file():
            raise ValidationError(f"Backup env file not found: {self._env_file}")

        port = request.port if request.port is not None else self._default_restore_port
        is_production = port == self._production_port
        if is_production and request.confirmProduction != self._confirm_phrase:
            raise ValidationError(
                f"Restoring to production port {self._production_port} requires "
                f"confirmProduction={self._confirm_phrase}"
            )
        if is_production and request.drop and request.confirmProduction != self._confirm_phrase:
            raise ValidationError(
                f"--drop on production requires confirmProduction={self._confirm_phrase}"
            )

        command = [
            str(self._script),
            "--env-file",
            str(self._env_file),
            "--timestamp",
            request.timestamp,
            "--host",
            request.host,
            "--port",
            str(port),
        ]
        if request.databases:
            command.extend(["--databases", ",".join(request.databases)])
        if request.drop:
            if is_production and request.confirmProduction != self._confirm_phrase:
                raise ValidationError(
                    f"--drop on production requires confirmProduction={self._confirm_phrase}"
                )
            command.append("--drop")
        if request.dryRun:
            command.append("--dry-run")

        payload = request.model_dump(mode="json")
        payload["port"] = port
        # Never persist the confirmation phrase beyond the request validation path.
        payload.pop("confirmProduction", None)

        return self._jobs.start(
            job_type=JobType.RESTORE,
            command=command,
            request=payload,
        )

    def get(self, job_id: str) -> Job:
        job = self._jobs.get(job_id)
        if job.job_type != JobType.RESTORE:
            raise ValidationError("Job is not a restore job")
        return job

    def list(self, *, page: int, size: int) -> tuple[list[Job], int]:
        return self._jobs.list(JobType.RESTORE, page=page, size=size)
