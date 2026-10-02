"""Service settings loaded from /etc/asat/mongodb-management.env."""

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env", "/etc/asat/mongodb-management.env"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    api_token: str = Field(..., min_length=16, description="Bearer token for all routes")
    bind_host: str = "127.0.0.1"
    bind_port: int = 8091

    backup_env_file: Path = Path("/etc/asat/mongodb-backup.env")
    backup_script: Path = Path("/opt/asat/mongodb-backup/mongodb-backup.sh")
    restore_script: Path = Path("/opt/asat/mongodb-backup/mongodb-restore.sh")
    validate_script: Path = Path("/opt/asat/mongodb-backup/validate-host.sh")
    timer_unit: str = "asat-mongo-backup.timer"
    service_unit: str = "asat-mongo-backup.service"

    data_dir: Path = Path("/var/lib/asat-mongodb-management")
    jobs_db_path: Path | None = None
    job_log_max_chars: int = 50_000
    job_timeout_seconds: int = 6 * 60 * 60

    aws_cli: Path = Path("/usr/local/bin/aws")
    production_mongo_port: int = 28395
    default_restore_port: int = 27018
    production_confirm_phrase: str = "RESTORE_PRODUCTION"

    @property
    def sqlite_path(self) -> Path:
        if self.jobs_db_path is not None:
            return self.jobs_db_path
        return self.data_dir / "jobs.db"


@lru_cache
def get_settings() -> Settings:
    return Settings()


def clear_settings_cache() -> None:
    get_settings.cache_clear()