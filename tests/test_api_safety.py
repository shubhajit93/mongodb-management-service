"""Safety and command-mapping tests for the management API."""

from __future__ import annotations

import json

from fastapi.testclient import TestClient

from tests.conftest import FakeRunner


def test_rejects_missing_token(client: TestClient) -> None:
    response = client.get("/api/v1/health")
    assert response.status_code == 401
    body = response.json()
    assert body["success"] is False
    assert body["data"] is None


def test_backup_command_mapping(client: TestClient, auth_headers: dict[str, str], runner: FakeRunner) -> None:
    response = client.post(
        "/api/v1/backups",
        headers=auth_headers,
        json={"slot": "0200", "databases": ["registration", "cms"], "dryRun": True},
    )
    assert response.status_code == 202
    body = response.json()
    assert body["success"] is True
    assert body["data"]["status"] == "succeeded"
    command = runner.calls[0]
    assert command[0].endswith("mongodb-backup.sh")
    assert command[1:3] == ["--env-file", str(client.app.state.container.settings.backup_env_file)]
    assert command[3:] == ["--slot", "0200", "--databases", "registration,cms", "--dry-run"]


def test_rejects_unknown_database(client: TestClient, auth_headers: dict[str, str]) -> None:
    response = client.post(
        "/api/v1/backups",
        headers=auth_headers,
        json={"databases": ["nope"]},
    )
    assert response.status_code == 422
    assert response.json()["success"] is False


def test_rejects_bad_timestamp(client: TestClient, auth_headers: dict[str, str]) -> None:
    response = client.post(
        "/api/v1/restores",
        headers=auth_headers,
        json={"timestamp": "bad"},
    )
    assert response.status_code == 422
    assert response.json()["success"] is False


def test_production_restore_without_confirm_is_refused(
    client: TestClient,
    auth_headers: dict[str, str],
    runner: FakeRunner,
) -> None:
    response = client.post(
        "/api/v1/restores",
        headers=auth_headers,
        json={
            "timestamp": "2026-10-02T0200Z",
            "host": "127.0.0.1",
            "port": 28395,
            "databases": ["paymentModule"],
            "drop": True,
        },
    )
    assert response.status_code == 422
    assert "RESTORE_PRODUCTION" in response.json()["message"]
    assert runner.calls == []


def test_production_restore_with_confirm_runs_script(
    client: TestClient,
    auth_headers: dict[str, str],
    runner: FakeRunner,
) -> None:
    runner.result = runner.result.__class__(
        exit_code=0,
        stdout="Restore finished: 1 database(s) for 2026-10-02T0200Z into 127.0.0.1:28395\n",
        stderr="",
    )
    response = client.post(
        "/api/v1/restores",
        headers=auth_headers,
        json={
            "timestamp": "2026-10-02T0200Z",
            "host": "127.0.0.1",
            "port": 28395,
            "databases": ["paymentModule"],
            "drop": True,
            "confirmProduction": "RESTORE_PRODUCTION",
        },
    )
    assert response.status_code == 202
    command = runner.calls[0]
    assert command[0].endswith("mongodb-restore.sh")
    assert "--env-file" in command
    assert "--timestamp" in command
    assert "2026-10-02T0200Z" in command
    assert "--port" in command
    assert "28395" in command
    assert "--drop" in command
    assert "RESTORE_PRODUCTION" not in command
    assert response.json()["data"]["request"].get("confirmProduction") is None


def test_missing_backup_script_does_not_start_process(
    client: TestClient,
    auth_headers: dict[str, str],
    runner: FakeRunner,
    tmp_paths: dict,
) -> None:
    missing = tmp_paths["backup_script"].parent / "missing-backup.sh"
    client.app.state.container.backup_service._script = missing  # noqa: SLF001
    response = client.post("/api/v1/backups", headers=auth_headers, json={"dryRun": True})
    assert response.status_code == 422
    assert "not found" in response.json()["message"]
    assert runner.calls == []


def test_default_restore_port_is_scratch(
    client: TestClient,
    auth_headers: dict[str, str],
    runner: FakeRunner,
) -> None:
    response = client.post(
        "/api/v1/restores",
        headers=auth_headers,
        json={"timestamp": "2026-10-02T0200Z", "databases": ["registration"]},
    )
    assert response.status_code == 202
    command = runner.calls[0]
    assert "--port" in command
    assert "27018" in command


def test_single_flight_rejects_second_job(
    client: TestClient,
    auth_headers: dict[str, str],
    runner: FakeRunner,
) -> None:
    started = {"count": 0}

    def slow(command: list[str]):
        started["count"] += 1
        if started["count"] == 1:
            # First job stays "running" by never finishing if we used threads.
            # With ImmediateThread the first call completes before the second POST.
            # Simulate conflict by leaving an active job via a hanging second-check:
            return runner.result
        return runner.result

    runner.handler = slow
    first = client.post("/api/v1/backups", headers=auth_headers, json={"dryRun": True})
    assert first.status_code == 202

    # Insert an active job manually to prove conflict handling.
    from app.domain.constants import JobStatus, JobType
    from app.domain.models import Job

    container = client.app.state.container
    active = Job.create(job_type=JobType.BACKUP, command=["true"], request={})
    active.status = JobStatus.RUNNING
    container.job_store.create(active)

    second = client.post("/api/v1/backups", headers=auth_headers, json={"dryRun": True})
    assert second.status_code == 409
    assert second.json()["success"] is False


def test_config_get_redacts_secrets(client: TestClient, auth_headers: dict[str, str]) -> None:
    response = client.get("/api/v1/config", headers=auth_headers)
    assert response.status_code == 200
    data = response.json()["data"]
    assert "secret-backup" not in json.dumps(data)
    assert "secret-aws" not in json.dumps(data)
    assert data["values"]["S3_BUCKET"] == "asatv2-mongodb-backups-prod-636494949614"
    assert data["secretPresent"]["MONGO_BACKUP_PASSWORD"] is True
    assert data["secretPresent"]["AWS_SECRET_ACCESS_KEY"] is True
    assert "MONGO_BACKUP_PASSWORD" not in data["values"]
    assert "AWS_SECRET_ACCESS_KEY" not in data["values"]


def test_config_update_writes_secret_without_returning_it(
    client: TestClient,
    auth_headers: dict[str, str],
    tmp_paths: dict,
) -> None:
    response = client.put(
        "/api/v1/config",
        headers=auth_headers,
        json={"SIZE_RATIO_MIN": "0.6", "MONGO_BACKUP_PASSWORD": "new-secret"},
    )
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["values"]["SIZE_RATIO_MIN"] == "0.6"
    assert "new-secret" not in json.dumps(data)
    raw = tmp_paths["env_file"].read_text(encoding="utf-8")
    assert "SIZE_RATIO_MIN=0.6" in raw
    assert "new-secret" in raw


def test_manifest_timestamp_validation(client: TestClient, auth_headers: dict[str, str]) -> None:
    response = client.get("/api/v1/manifests/not-a-stamp", headers=auth_headers)
    assert response.status_code == 422
    assert response.json()["success"] is False