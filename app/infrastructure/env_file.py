"""Read and write /etc/asat/mongodb-backup.env without leaking secrets in GET."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from app.domain.constants import CONFIG_WRITABLE_KEYS, SECRET_ENV_KEYS
from app.domain.errors import ValidationError

_LINE_RE = re.compile(r"^(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)=(.*)$")


def _strip_quotes(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value


def _format_value(key: str, value: str) -> str:
    if key in SECRET_ENV_KEYS or any(ch in value for ch in (" ", "$", "'", '"', "\\")):
        escaped = value.replace("'", "'\"'\"'")
        return f"'{escaped}'"
    return value


class EnvFileStore:
    def __init__(self, path: Path) -> None:
        self.path = path

    def exists(self) -> bool:
        return self.path.is_file()

    def read_raw(self) -> dict[str, str]:
        if not self.path.is_file():
            raise ValidationError(f"Backup env file not found: {self.path}")
        values: dict[str, str] = {}
        for line in self.path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            match = _LINE_RE.match(stripped)
            if not match:
                continue
            key, raw_value = match.group(1), match.group(2)
            values[key] = _strip_quotes(raw_value)
        return values

    def redacted_view(self) -> tuple[dict[str, Any], dict[str, bool]]:
        values = self.read_raw()
        public: dict[str, Any] = {}
        secret_present: dict[str, bool] = {}
        for key, value in values.items():
            if key in SECRET_ENV_KEYS:
                secret_present[key] = bool(value)
            else:
                public[key] = value
        for key in SECRET_ENV_KEYS:
            secret_present.setdefault(key, False)
        return public, secret_present

    def update(self, updates: dict[str, str | None]) -> None:
        cleaned = {key: value for key, value in updates.items() if value is not None}
        unknown = [key for key in cleaned if key not in CONFIG_WRITABLE_KEYS]
        if unknown:
            raise ValidationError(f"Unsupported config keys: {', '.join(sorted(unknown))}")
        if not cleaned:
            return
        if not self.path.is_file():
            raise ValidationError(f"Backup env file not found: {self.path}")

        current = self.read_raw()
        current.update(cleaned)

        original_lines = self.path.read_text(encoding="utf-8").splitlines()
        seen: set[str] = set()
        output: list[str] = []
        for line in original_lines:
            stripped = line.strip()
            match = _LINE_RE.match(stripped) if stripped and not stripped.startswith("#") else None
            if match is None:
                output.append(line)
                continue
            key = match.group(1)
            if key in cleaned:
                output.append(f"{key}={_format_value(key, cleaned[key])}")
                seen.add(key)
            else:
                output.append(line)
        for key, value in cleaned.items():
            if key not in seen:
                output.append(f"{key}={_format_value(key, value)}")

        self.path.write_text("\n".join(output) + "\n", encoding="utf-8")
        try:
            self.path.chmod(0o600)
        except OSError:
            # Windows local tests may not support Unix modes.
            pass

    def as_process_env(self, base: dict[str, str] | None = None) -> dict[str, str]:
        env = dict(base or {})
        env.update(self.read_raw())
        path = env.get("PATH", "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin")
        if "/usr/local/bin" not in path.split(":"):
            path = f"/usr/local/bin:{path}"
        env["PATH"] = path
        return env