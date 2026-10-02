"""Read systemd timer state without enabling or disabling units."""

from __future__ import annotations

from pathlib import Path

from app.infrastructure.process_runner import ProcessRunner


class ScheduleReader:
    def __init__(self, *, runner: ProcessRunner, timer_unit: str) -> None:
        self._runner = runner
        self._timer_unit = timer_unit

    def read(self) -> dict[str, object]:
        unit_path = Path(f"/etc/systemd/system/{self._timer_unit}")
        timezone_line = None
        timezone_present = False
        if unit_path.is_file():
            for line in unit_path.read_text(encoding="utf-8").splitlines():
                if line.startswith("Timezone="):
                    timezone_line = line.strip()
                    timezone_present = timezone_line == "Timezone=UTC"
                    break

        show = self._runner.run(
            [
                "systemctl",
                "show",
                self._timer_unit,
                "-p",
                "UnitFileState",
                "-p",
                "ActiveState",
                "-p",
                "NextElapseUSecRealtime",
                "-p",
                "LastTriggerUSec",
            ],
            timeout_seconds=15,
        )
        props: dict[str, str] = {}
        if show.exit_code == 0:
            for line in show.stdout.splitlines():
                if "=" in line:
                    key, value = line.split("=", 1)
                    props[key] = value

        enabled_raw = props.get("UnitFileState")
        enabled: bool | None
        if enabled_raw in {"enabled", "enabled-runtime"}:
            enabled = True
        elif enabled_raw in {"disabled", "masked", "static"}:
            enabled = False
        else:
            enabled = None

        active_raw = props.get("ActiveState")
        active = active_raw == "active" if active_raw else None

        return {
            "timerUnit": self._timer_unit,
            "enabled": enabled,
            "active": active,
            "nextElapse": props.get("NextElapseUSecRealtime") or None,
            "lastTrigger": props.get("LastTriggerUSec") or None,
            "timezoneLinePresent": timezone_present,
            "timezoneLine": timezone_line,
            "note": "Enable or disable the timer with systemctl on the database host. This API only reports state.",
        }