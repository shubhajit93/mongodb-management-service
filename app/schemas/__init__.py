"""Pydantic request and response schemas."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, field_validator

from app.domain.constants import ALLOWED_DATABASES, MANIFEST_TIMESTAMP_RE, SLOT_RE, JobStatus, JobType


class PaginationParams(BaseModel):
    page: int = Field(default=1, ge=1)
    size: int = Field(default=20, ge=1, le=100)


class BackupCreateRequest(BaseModel):
    slot: str | None = None
    databases: list[str] | None = None
    dryRun: bool = False

    @field_validator("slot")
    @classmethod
    def validate_slot(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if not SLOT_RE.match(value):
            raise ValueError("slot must be HHMM, for example 0200, 1000, or 1800")
        return value

    @field_validator("databases")
    @classmethod
    def validate_databases(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        if not value:
            raise ValueError("databases must not be empty when provided")
        unknown = [name for name in value if name not in ALLOWED_DATABASES]
        if unknown:
            raise ValueError(f"unknown database(s): {', '.join(unknown)}")
        if len(set(value)) != len(value):
            raise ValueError("databases must not contain duplicates")
        return value


class RestoreCreateRequest(BaseModel):
    timestamp: str
    host: str = "127.0.0.1"
    port: int | None = None
    databases: list[str] | None = None
    drop: bool = False
    dryRun: bool = False
    confirmProduction: str | None = None

    @field_validator("timestamp")
    @classmethod
    def validate_timestamp(cls, value: str) -> str:
        if not MANIFEST_TIMESTAMP_RE.match(value):
            raise ValueError("timestamp must match YYYY-MM-DDTHHMMZ")
        return value

    @field_validator("databases")
    @classmethod
    def validate_databases(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        if not value:
            raise ValueError("databases must not be empty when provided")
        unknown = [name for name in value if name not in ALLOWED_DATABASES]
        if unknown:
            raise ValueError(f"unknown database(s): {', '.join(unknown)}")
        if len(set(value)) != len(value):
            raise ValueError("databases must not contain duplicates")
        return value


class JobResponse(BaseModel):
    id: str
    jobType: JobType
    status: JobStatus
    createdAt: datetime
    updatedAt: datetime
    startedAt: datetime | None = None
    finishedAt: datetime | None = None
    stamp: str | None = None
    exitCode: int | None = None
    request: dict[str, Any]
    command: list[str]
    logTail: str = ""
    errorMessage: str | None = None


class JobListResponse(BaseModel):
    items: list[JobResponse]
    page: int
    size: int
    total: int


class ManifestSummary(BaseModel):
    timestamp: str
    key: str
    size: int | None = None
    lastModified: str | None = None


class ManifestListResponse(BaseModel):
    items: list[ManifestSummary]
    page: int
    size: int
    total: int


class ManifestDetailResponse(BaseModel):
    timestamp: str
    key: str
    content: dict[str, Any]


class ConfigViewResponse(BaseModel):
    allowedDatabases: list[str]
    values: dict[str, Any]
    secretPresent: dict[str, bool]


class ConfigUpdateRequest(BaseModel):
    MONGO_HOST: str | None = None
    MONGO_PORT: str | None = None
    MONGO_AUTH_DB: str | None = None
    MONGO_PUBLIC_HOST: str | None = None
    MONGO_BACKUP_USER: str | None = None
    MONGO_BACKUP_PASSWORD: str | None = None
    MONGO_RESTORE_USER: str | None = None
    MONGO_RESTORE_PASSWORD: str | None = None
    MONGO_ROOT_USER: str | None = None
    MONGO_ROOT_PASSWORD: str | None = None
    AWS_REGION: str | None = None
    AWS_ACCESS_KEY_ID: str | None = None
    AWS_SECRET_ACCESS_KEY: str | None = None
    S3_BUCKET: str | None = None
    S3_KMS_KEY_ID: str | None = None
    LOCAL_WORKDIR: str | None = None
    SIZE_RATIO_MIN: str | None = None


class HealthCheckItem(BaseModel):
    name: str
    ok: bool
    detail: str


class HealthResponse(BaseModel):
    healthy: bool
    checks: list[HealthCheckItem]


class ScheduleResponse(BaseModel):
    timerUnit: str
    enabled: bool | None
    active: bool | None
    nextElapse: str | None
    lastTrigger: str | None
    timezoneLinePresent: bool
    timezoneLine: str | None
    note: str


class HealthResponseEnvelope(BaseModel):
    success: bool
    message: str
    data: HealthResponse | None = None