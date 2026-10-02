"""Unit tests for env file redaction and command builders."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.infrastructure.env_file import EnvFileStore
from app.schemas import BackupCreateRequest, RestoreCreateRequest
from app.services.backup_restore import BackupService, RestoreService
from app.services.job_service import JobService
from app.infrastructure.job_store import JobStore
from app.infrastructure.process_runner import ProcessResult
from tests.conftest import FakeRunner, ImmediateThread


def test_env_file_redaction(tmp_path: Path) -> None:
    path = tmp_path / "env"
    path.write_text(
        "S3_BUCKET=bucket\nAWS_SECRET_ACCESS_KEY='topsecret'\nMONGO_BACKUP_PASSWORD='pw'\n",
        encoding="utf-8",
    )
    store = EnvFileStore(path)
    values, secrets = store.redacted_view()
    assert values == {"S3_BUCKET": "bucket"}
    assert secrets["AWS_SECRET_ACCESS_KEY"] is True
    assert secrets["MONGO_BACKUP_PASSWORD"] is True


def test_backup_service_builds_args(tmp_path: Path) -> None:
    script = tmp_path / "mongodb-backup.sh"
    script.write_text("#!/bin/bash\n", encoding="utf-8")
    env = tmp_path / "env"
    env.write_text("S3_BUCKET=bucket\n", encoding="utf-8")
    runner = FakeRunner()
    store = JobStore(tmp_path / "jobs.db")
    jobs = JobService(
        store=store,
        runner=runner,
        env_store=EnvFileStore(env),
        log_max_chars=1000,
        timeout_seconds=30,
        thread_factory=ImmediateThread,
    )
    service = BackupService(
        job_service=jobs,
        backup_script=script,
        backup_env_file=env,
    )
    job = service.start(BackupCreateRequest(slot="1800", dryRun=False))
    assert job.status.value == "succeeded"
    assert runner.calls[0] == [str(script), "--env-file", str(env), "--slot", "1800"]


def test_backup_service_missing_script_never_runs(tmp_path: Path) -> None:
    env = tmp_path / "env"
    env.write_text("S3_BUCKET=bucket\n", encoding="utf-8")
    runner = FakeRunner()
    store = JobStore(tmp_path / "jobs.db")
    jobs = JobService(
        store=store,
        runner=runner,
        env_store=EnvFileStore(env),
        log_max_chars=1000,
        timeout_seconds=30,
        thread_factory=ImmediateThread,
    )
    service = BackupService(
        job_service=jobs,
        backup_script=tmp_path / "missing.sh",
        backup_env_file=env,
    )
    with pytest.raises(Exception) as exc:
        service.start(BackupCreateRequest(dryRun=True))
    assert "not found" in str(exc.value)
    assert runner.calls == []


def test_restore_service_requires_production_phrase(tmp_path: Path) -> None:
    script = tmp_path / "mongodb-restore.sh"
    script.write_text("#!/bin/bash\n", encoding="utf-8")
    env = tmp_path / "env"
    env.write_text("S3_BUCKET=bucket\n", encoding="utf-8")
    runner = FakeRunner()
    store = JobStore(tmp_path / "jobs.db")
    jobs = JobService(
        store=store,
        runner=runner,
        env_store=EnvFileStore(env),
        log_max_chars=1000,
        timeout_seconds=30,
        thread_factory=ImmediateThread,
    )
    service = RestoreService(
        job_service=jobs,
        restore_script=script,
        backup_env_file=env,
        production_port=28395,
        default_restore_port=27018,
        confirm_phrase="RESTORE_PRODUCTION",
    )
    with pytest.raises(Exception) as exc:
        service.start(
            RestoreCreateRequest(
                timestamp="2026-10-02T0200Z",
                port=28395,
                drop=True,
            )
        )
    assert "RESTORE_PRODUCTION" in str(exc.value)
    assert runner.calls == []


def test_job_service_captures_failure(tmp_path: Path) -> None:
    env = tmp_path / "env"
    env.write_text("S3_BUCKET=bucket\n", encoding="utf-8")
    runner = FakeRunner()
    runner.result = ProcessResult(exit_code=2, stdout="", stderr="boom")
    store = JobStore(tmp_path / "jobs.db")
    jobs = JobService(
        store=store,
        runner=runner,
        env_store=EnvFileStore(env),
        log_max_chars=1000,
        timeout_seconds=30,
        thread_factory=ImmediateThread,
    )
    from app.domain.constants import JobType

    job = jobs.start(job_type=JobType.BACKUP, command=["false"], request={})
    loaded = jobs.get(job.id)
    assert loaded.status.value == "failed"
    assert loaded.exit_code == 2
    assert "boom" in loaded.log_tail