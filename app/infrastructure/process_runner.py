"""Subprocess runner for backup and restore scripts."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping


@dataclass(frozen=True)
class ProcessResult:
    exit_code: int
    stdout: str
    stderr: str

    @property
    def combined_output(self) -> str:
        parts = [part for part in (self.stdout, self.stderr) if part]
        return "\n".join(parts)


class ProcessRunner:
    """Runs external commands. Tests inject a fake implementation."""

    def run(
        self,
        command: list[str],
        *,
        env: Mapping[str, str] | None = None,
        cwd: Path | None = None,
        timeout_seconds: int | None = None,
    ) -> ProcessResult:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            env=dict(env) if env is not None else None,
            cwd=str(cwd) if cwd is not None else None,
            timeout=timeout_seconds,
            check=False,
        )
        return ProcessResult(
            exit_code=completed.returncode,
            stdout=completed.stdout or "",
            stderr=completed.stderr or "",
        )