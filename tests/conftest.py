"""Shared test fixtures."""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Callable

import pytest
from fastapi.testclient import TestClient

from app.api.deps import build_container
from app.config import Settings, clear_settings_cache
from app.infrastructure.process_runner import ProcessResult, ProcessRunner
from app.main import create_app
from app.services.config_health import HealthService


class FakeRunner(ProcessRunner):
    def __init__(self) -> None:
        self.calls: list[list[str]] = []
        self.result = ProcessResult(
            exit_code=0,
            stdout="Backup completed successfully for 2026-10-02T0200Z\n",
            stderr="",
        )
        self.handler: Callable[[list[str]], ProcessResult] | None = None

    def run(self, command, *, env=None, cwd=None, timeout_seconds=None):  # noqa: ANN001
        self.calls.append(list(command))
        if self.handler is not None:
            return self.handler(list(command))
        return self.result


class ImmediateThread(threading.Thread):
    """Runs the target synchronously so tests do not race background workers."""

    def start(self) -> None:
        self.run()


@pytest.fixture
def tmp_paths(tmp_path: Path) -> dict[str, Path]:
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    backup_script = scripts / "mongodb-backup.sh"
    restore_script = scripts / "mongodb-restore.sh"
    backup_script.write_text("#!/bin/bash\n", encoding="utf-8")
    restore_script.write_text("#!/bin/bash\n", encoding="utf-8")
    env_file = tmp_path / "mongodb-backup.env"
    env_file.write_text(
        "\n".join(
            [
                "MONGO_HOST=127.0.0.1",
                "MONGO_PORT=28395",
                "MONGO_BACKUP_USER=asatBackup",
                "MONGO_BACKUP_PASSWORD='secret-backup'",
                "MONGO_RESTORE_USER=admin",
                "MONGO_RESTORE_PASSWORD='secret-restore'",
                "AWS_REGION=us-east-1",
                "AWS_ACCESS_KEY_ID=AKIATEST",
                "AWS_SECRET_ACCESS_KEY='secret-aws'",
                "S3_BUCKET=asatv2-mongodb-backups-prod-636494949614",
                "S3_KMS_KEY_ID=arn:aws:kms:us-east-1:123:key/abc",
                "SIZE_RATIO_MIN=0.5",
                "",
            ]
        ),
        encoding="utf-8",
    )
    timer = tmp_path / "asat-mongo-backup.timer"
    timer.write_text("[Timer]\nTimezone=UTC\n", encoding="utf-8")
    return {
        "data_dir": data_dir,
        "backup_script": backup_script,
        "restore_script": restore_script,
        "env_file": env_file,
        "timer": timer,
        "db": data_dir / "jobs.db",
    }


@pytest.fixture
def settings(tmp_paths: dict[str, Path], monkeypatch: pytest.MonkeyPatch) -> Settings:
    clear_settings_cache()
    monkeypatch.setenv("API_TOKEN", "test-token-1234567890")
    return Settings(
        api_token="test-token-1234567890",
        bind_host="127.0.0.1",
        bind_port=8091,
        backup_env_file=tmp_paths["env_file"],
        backup_script=tmp_paths["backup_script"],
        restore_script=tmp_paths["restore_script"],
        data_dir=tmp_paths["data_dir"],
        jobs_db_path=tmp_paths["db"],
        aws_cli=Path("/usr/local/bin/aws"),
    )


@pytest.fixture
def runner() -> FakeRunner:
    return FakeRunner()


@pytest.fixture
def client(
    settings: Settings,
    runner: FakeRunner,
    tmp_paths: dict[str, Path],
) -> TestClient:
    app = create_app(settings=settings)
    container = build_container(settings=settings, runner=runner)
    container.job_service._thread_factory = ImmediateThread  # noqa: SLF001
    container.health_service = HealthService(
        backup_script=settings.backup_script,
        restore_script=settings.restore_script,
        backup_env_file=settings.backup_env_file,
        timer_unit_path=tmp_paths["timer"],
        mongo_port=1,
    )
    app.state.container = container
    return TestClient(app)


@pytest.fixture
def auth_headers() -> dict[str, str]:
    return {"Authorization": "Bearer test-token-1234567890"}