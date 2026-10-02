"""Domain constants for ASAT MongoDB backups."""

from __future__ import annotations

import re
from enum import Enum

ALLOWED_DATABASES: tuple[str, ...] = (
    "registration",
    "cms",
    "paymentModule",
    "universal",
    "phishing",
    "notification",
    "breach",
)

MANIFEST_TIMESTAMP_RE = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{4}Z$")
SLOT_RE = re.compile(r"^[0-9]{4}$")

SECRET_ENV_KEYS: frozenset[str] = frozenset(
    {
        "MONGO_BACKUP_PASSWORD",
        "MONGO_RESTORE_PASSWORD",
        "MONGO_ROOT_PASSWORD",
        "AWS_SECRET_ACCESS_KEY",
        "AWS_ACCESS_KEY_ID",
    }
)

CONFIG_WRITABLE_KEYS: frozenset[str] = frozenset(
    {
        "MONGO_HOST",
        "MONGO_PORT",
        "MONGO_AUTH_DB",
        "MONGO_PUBLIC_HOST",
        "MONGO_BACKUP_USER",
        "MONGO_BACKUP_PASSWORD",
        "MONGO_RESTORE_USER",
        "MONGO_RESTORE_PASSWORD",
        "MONGO_ROOT_USER",
        "MONGO_ROOT_PASSWORD",
        "AWS_REGION",
        "AWS_ACCESS_KEY_ID",
        "AWS_SECRET_ACCESS_KEY",
        "S3_BUCKET",
        "S3_KMS_KEY_ID",
        "LOCAL_WORKDIR",
        "SIZE_RATIO_MIN",
    }
)


class JobType(str, Enum):
    BACKUP = "backup"
    RESTORE = "restore"


class JobStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"