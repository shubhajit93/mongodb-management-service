"""FastAPI dependencies and application container."""

from __future__ import annotations

import secrets
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated

from fastapi import Header, HTTPException, Request

from app.config import Settings, get_settings
from app.infrastructure.aws_cli import ManifestClient
from app.infrastructure.env_file import EnvFileStore
from app.infrastructure.job_store import JobStore
from app.infrastructure.process_runner import ProcessRunner
from app.infrastructure.systemctl import ScheduleReader
from app.services.backup_restore import BackupService, RestoreService
from app.services.config_health import ConfigService, HealthService
from app.services.job_service import JobService


@dataclass
class AppContainer:
    settings: Settings
    runner: ProcessRunner
    env_store: EnvFileStore
    job_store: JobStore
    job_service: JobService
    backup_service: BackupService
    restore_service: RestoreService
    config_service: ConfigService
    health_service: HealthService
    manifest_client: ManifestClient
    schedule_reader: ScheduleReader


def build_container(settings: Settings | None = None, runner: ProcessRunner | None = None) -> AppContainer:
    settings = settings or get_settings()
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    runner = runner or ProcessRunner()
    env_store = EnvFileStore(settings.backup_env_file)
    job_store = JobStore(settings.sqlite_path)
    job_service = JobService(
        store=job_store,
        runner=runner,
        env_store=env_store,
        log_max_chars=settings.job_log_max_chars,
        timeout_seconds=settings.job_timeout_seconds,
    )
    return AppContainer(
        settings=settings,
        runner=runner,
        env_store=env_store,
        job_store=job_store,
        job_service=job_service,
        backup_service=BackupService(
            job_service=job_service,
            backup_script=settings.backup_script,
            backup_env_file=settings.backup_env_file,
        ),
        restore_service=RestoreService(
            job_service=job_service,
            restore_script=settings.restore_script,
            backup_env_file=settings.backup_env_file,
            production_port=settings.production_mongo_port,
            default_restore_port=settings.default_restore_port,
            confirm_phrase=settings.production_confirm_phrase,
        ),
        config_service=ConfigService(env_store=env_store, job_service=job_service),
        health_service=HealthService(
            backup_script=settings.backup_script,
            restore_script=settings.restore_script,
            backup_env_file=settings.backup_env_file,
            timer_unit_path=Path(f"/etc/systemd/system/{settings.timer_unit}"),
            mongo_port=settings.production_mongo_port,
        ),
        manifest_client=ManifestClient(
            env_store=env_store,
            runner=runner,
            aws_cli=settings.aws_cli,
        ),
        schedule_reader=ScheduleReader(runner=runner, timer_unit=settings.timer_unit),
    )


def get_container(request: Request) -> AppContainer:
    return request.app.state.container


def require_token(
    request: Request,
    authorization: Annotated[str | None, Header()] = None,
) -> None:
    if authorization is None or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing bearer token")
    provided = authorization.removeprefix("Bearer ").strip()
    container: AppContainer = request.app.state.container
    expected = container.settings.api_token
    if not provided or not secrets.compare_digest(provided, expected):
        raise HTTPException(status_code=401, detail="Invalid bearer token")