"""List and fetch S3 manifests through the AWS CLI used by the backup scripts."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.domain.errors import NotFoundError, ValidationError
from app.infrastructure.env_file import EnvFileStore
from app.infrastructure.process_runner import ProcessRunner


class ManifestClient:
    def __init__(
        self,
        *,
        env_store: EnvFileStore,
        runner: ProcessRunner,
        aws_cli: Path,
    ) -> None:
        self._env_store = env_store
        self._runner = runner
        self._aws_cli = aws_cli

    def _aws(self) -> str:
        if self._aws_cli.is_file():
            return str(self._aws_cli)
        return "aws"

    def _bucket(self) -> str:
        values = self._env_store.read_raw()
        bucket = values.get("S3_BUCKET")
        if not bucket:
            raise ValidationError("S3_BUCKET is not set in the backup env file")
        return bucket

    def _env(self) -> dict[str, str]:
        return self._env_store.as_process_env()

    def list_manifests(self) -> list[dict[str, Any]]:
        bucket = self._bucket()
        result = self._runner.run(
            [
                self._aws(),
                "s3api",
                "list-objects-v2",
                "--bucket",
                bucket,
                "--prefix",
                "daily/manifests/",
                "--output",
                "json",
            ],
            env=self._env(),
            timeout_seconds=60,
        )
        if result.exit_code != 0:
            raise ValidationError(
                f"Failed to list manifests: {result.stderr.strip() or result.stdout.strip()}"
            )
        payload = json.loads(result.stdout or "{}")
        contents = payload.get("Contents") or []
        items: list[dict[str, Any]] = []
        for obj in contents:
            key = obj.get("Key") or ""
            if not key.endswith(".json"):
                continue
            name = key.rsplit("/", 1)[-1]
            timestamp = name[: -len(".json")]
            items.append(
                {
                    "timestamp": timestamp,
                    "key": key,
                    "size": obj.get("Size"),
                    "lastModified": obj.get("LastModified"),
                }
            )
        items.sort(key=lambda item: item["timestamp"], reverse=True)
        return items

    def get_manifest(self, timestamp: str) -> dict[str, Any]:
        bucket = self._bucket()
        key = f"daily/manifests/{timestamp}.json"
        result = self._runner.run(
            [
                self._aws(),
                "s3",
                "cp",
                f"s3://{bucket}/{key}",
                "-",
            ],
            env=self._env(),
            timeout_seconds=60,
        )
        if result.exit_code != 0:
            message = (result.stderr or result.stdout or "manifest not found").strip()
            lowered = message.lower()
            if "404" in message or "not found" in lowered or "nosuchkey" in lowered:
                raise NotFoundError(f"Manifest not found: {timestamp}")
            raise ValidationError(f"Failed to download manifest: {message}")
        try:
            content = json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            raise ValidationError(f"Manifest JSON is invalid: {exc}") from exc
        return {"timestamp": timestamp, "key": key, "content": content}