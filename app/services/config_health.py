"""Config and health services."""

from __future__ import annotations

import socket
from pathlib import Path

from app.domain.constants import ALLOWED_DATABASES
from app.domain.errors import ConflictError, ValidationError
from app.infrastructure.env_file import EnvFileStore
from app.schemas import ConfigUpdateRequest, ConfigViewResponse, HealthCheckItem, HealthResponse
from app.services.job_service import JobService


class ConfigService:
    def __init__(self, *, env_store: EnvFileStore, job_service: JobService) -> None:
        self._env_store = env_store
        self._jobs = job_service

    def get(self) -> ConfigViewResponse:
        values, secret_present = self._env_store.redacted_view()
        return ConfigViewResponse(
            allowedDatabases=list(ALLOWED_DATABASES),
            values=values,
            secretPresent=secret_present,
        )

    def update(self, request: ConfigUpdateRequest) -> ConfigViewResponse:
        if self._jobs.has_active_job():
            raise ConflictError("Cannot update config while a backup or restore job is running")
        payload = request.model_dump(exclude_none=True)
        if not payload:
            raise ValidationError("No config fields provided")
        self._env_store.update(payload)
        return self.get()


class HealthService:
    def __init__(
        self,
        *,
        backup_script: Path,
        restore_script: Path,
        backup_env_file: Path,
        timer_unit_path: Path,
        mongo_port: int,
        mongo_host: str = "127.0.0.1",
    ) -> None:
        self._backup_script = backup_script
        self._restore_script = restore_script
        self._backup_env_file = backup_env_file
        self._timer_unit_path = timer_unit_path
        self._mongo_port = mongo_port
        self._mongo_host = mongo_host

    def check(self) -> HealthResponse:
        checks = [
            self._path_check("backup_script", self._backup_script),
            self._path_check("restore_script", self._restore_script),
            self._path_check("backup_env_file", self._backup_env_file),
            self._path_check("timer_unit", self._timer_unit_path),
            self._mongo_port_check(),
        ]
        return HealthResponse(healthy=all(item.ok for item in checks), checks=checks)

    @staticmethod
    def _path_check(name: str, path: Path) -> HealthCheckItem:
        ok = path.exists()
        return HealthCheckItem(
            name=name,
            ok=ok,
            detail=str(path) if ok else f"missing: {path}",
        )

    def _mongo_port_check(self) -> HealthCheckItem:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(1.5)
        try:
            sock.connect((self._mongo_host, self._mongo_port))
            ok = True
            detail = f"{self._mongo_host}:{self._mongo_port} accepting connections"
        except OSError as exc:
            ok = False
            detail = f"{self._mongo_host}:{self._mongo_port} not reachable: {exc}"
        finally:
            sock.close()
        return HealthCheckItem(name="mongo_port", ok=ok, detail=detail)