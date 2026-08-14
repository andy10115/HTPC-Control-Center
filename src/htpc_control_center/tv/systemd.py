"""Per-user systemd service installation."""

from __future__ import annotations

import shlex
import subprocess
import sys
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path

from ..paths import AppPaths

UNIT_NAME = "htpc-control-center-tv-watcher.service"


@dataclass(frozen=True)
class ServiceStatus:
    installed: bool
    enabled: bool
    active: bool
    detail: str


def _systemd_quote(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def render_user_unit(python_executable: str | None = None) -> str:
    executable = python_executable or sys.executable
    return f"""[Unit]
Description=HTPC Control Center TV lifecycle watcher
Documentation=https://github.com/andy10115/HTPC-Control-Center
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
ExecStart={_systemd_quote(executable)} -m htpc_control_center watcher
Restart=on-failure
RestartSec=4
TimeoutStopSec=25
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=default.target
"""


def _run_systemctl(*args: str, check: bool = False) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["systemctl", "--user", *args],
        check=check,
        capture_output=True,
        text=True,
        timeout=15,
    )


def install_user_service(paths: AppPaths | None = None, *, start: bool = True) -> Path:
    paths = paths or AppPaths.from_environment()
    paths.user_unit_dir.mkdir(parents=True, exist_ok=True)
    paths.user_unit_file.write_text(render_user_unit(), encoding="utf-8")

    # Verify in a temporary path when available. User units can still be valid on systems
    # where systemd-analyze does not support --user verification.
    try:
        verify = subprocess.run(
            ["systemd-analyze", "--user", "verify", str(paths.user_unit_file)],
            check=False,
            capture_output=True,
            text=True,
            timeout=15,
        )
    except FileNotFoundError:
        verify = None
    if verify is not None and verify.returncode != 0 and "Unknown command verb" not in verify.stderr:
        paths.user_unit_file.unlink(missing_ok=True)
        raise RuntimeError(f"Generated systemd unit failed verification:\n{verify.stderr.strip()}")

    _run_systemctl("daemon-reload", check=True)
    command = ["enable"]
    if start:
        command.append("--now")
    command.append(UNIT_NAME)
    _run_systemctl(*command, check=True)
    if start:
        # enable --now does not restart an already-running watcher after an upgrade.
        _run_systemctl("restart", UNIT_NAME, check=True)
    return paths.user_unit_file


def remove_user_service(paths: AppPaths | None = None) -> None:
    paths = paths or AppPaths.from_environment()
    with suppress(FileNotFoundError, subprocess.SubprocessError):
        _run_systemctl("disable", "--now", UNIT_NAME)
    paths.user_unit_file.unlink(missing_ok=True)
    try:
        _run_systemctl("daemon-reload")
        _run_systemctl("reset-failed", UNIT_NAME)
    except (FileNotFoundError, subprocess.SubprocessError):
        pass


def service_status(paths: AppPaths | None = None) -> ServiceStatus:
    paths = paths or AppPaths.from_environment()
    installed = paths.user_unit_file.exists()
    if not installed:
        return ServiceStatus(False, False, False, "User service file is not installed.")
    try:
        enabled_result = _run_systemctl("is-enabled", UNIT_NAME)
        active_result = _run_systemctl("is-active", UNIT_NAME)
        enabled = enabled_result.returncode == 0
        active = active_result.returncode == 0
        detail = f"enabled={enabled_result.stdout.strip()} active={active_result.stdout.strip()}"
        return ServiceStatus(True, enabled, active, detail)
    except (FileNotFoundError, subprocess.SubprocessError) as exc:
        return ServiceStatus(True, False, False, str(exc))


def shell_command_for_logs() -> str:
    return shlex.join(["journalctl", "--user", "-u", UNIT_NAME, "-f"])
