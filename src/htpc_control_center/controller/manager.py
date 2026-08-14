"""Unprivileged controller-wake management used by the GTK application."""
from __future__ import annotations

import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from .discovery import USBDevice

RULE_FILE = Path("/etc/udev/rules.d/99-htpc-control-center-controller-wake.rules")
CONFIG_DIR = Path("/etc/htpc-control-center")
WAKE_TARGETS_FILE = CONFIG_DIR / "controller-wake-targets"
SUSPEND_DROPIN = Path(
    "/etc/systemd/system/systemd-suspend.service.d/htpc-control-center-controller-wake.conf"
)
PRIVILEGED_HELPER = Path("/usr/local/libexec/htpc-control-center-privileged")
SUSPEND_GUARD = Path("/usr/local/libexec/htpc-control-center-suspend-guard")
LEGACY_CONTROLLER_RULE = Path("/etc/udev/rules.d/99-controller-wakeup.rules")
LEGACY_CONTROLLER_DIR = Path("/etc/htpc-controller-wake")


class ControllerWakeError(RuntimeError):
    pass


@dataclass(frozen=True)
class ConfiguredController:
    name: str
    vid: str
    pid: str
    path: str
    wake_targets: tuple[str, ...]


@dataclass(frozen=True)
class ControllerWakeStatus:
    configured: bool
    devices: tuple[ConfiguredController, ...]
    target_states: tuple[tuple[str, str], ...]
    suspend_mode: str

    @property
    def all_targets_enabled(self) -> bool:
        return bool(self.target_states) and all(state == "enabled" for _, state in self.target_states)


_CONTROLLER_RE = re.compile(r"^#\s+(.+)\s+\(([0-9a-fA-F]{4}):([0-9a-fA-F]{4})\)$")
_PATH_RE = re.compile(r"^#\s+Device path:\s+(\S+)$")
_TARGETS_RE = re.compile(r"^#\s+Wake targets:\s+(.+)$")


def parse_configured_devices(text: str) -> tuple[ConfiguredController, ...]:
    devices: list[ConfiguredController] = []
    name = vid = pid = path = ""
    targets: tuple[str, ...] = ()

    def flush() -> None:
        nonlocal name, vid, pid, path, targets
        if name and vid and pid and path and targets:
            devices.append(ConfiguredController(name, vid.lower(), pid.lower(), path, targets))
        name = vid = pid = path = ""
        targets = ()

    for raw in text.splitlines():
        line = raw.strip()
        match = _CONTROLLER_RE.match(line)
        if match:
            flush()
            name, vid, pid = match.group(1), match.group(2), match.group(3)
            continue
        match = _PATH_RE.match(line)
        if match:
            path = match.group(1)
            continue
        match = _TARGETS_RE.match(line)
        if match:
            targets = tuple(item for item in match.group(1).split() if item)
    flush()
    return tuple(devices)


def status() -> ControllerWakeStatus:
    devices: tuple[ConfiguredController, ...] = ()
    if RULE_FILE.is_file():
        try:
            devices = parse_configured_devices(RULE_FILE.read_text(encoding="utf-8"))
        except OSError:
            devices = ()

    targets: list[str] = []
    if WAKE_TARGETS_FILE.is_file():
        try:
            for raw in WAKE_TARGETS_FILE.read_text(encoding="utf-8").splitlines():
                target = raw.partition("#")[0].strip().split()
                if target:
                    targets.append(target[0])
        except OSError:
            pass

    target_states: list[tuple[str, str]] = []
    for target in dict.fromkeys(targets):
        wake_file = Path("/sys/bus/usb/devices") / target / "power/wakeup"
        if not wake_file.exists():
            state = "missing"
        else:
            try:
                state = wake_file.read_text(encoding="utf-8").strip()
            except OSError:
                state = "unreadable"
        target_states.append((target, state))

    suspend_mode = "unknown"
    try:
        suspend_mode = Path("/sys/power/mem_sleep").read_text(encoding="utf-8").strip()
    except OSError:
        pass

    configured = (
        RULE_FILE.is_file()
        and WAKE_TARGETS_FILE.is_file()
        and SUSPEND_DROPIN.is_file()
        and SUSPEND_GUARD.is_file()
    )
    return ControllerWakeStatus(configured, devices, tuple(target_states), suspend_mode)


def legacy_installation_detected() -> bool:
    return LEGACY_CONTROLLER_RULE.exists() or LEGACY_CONTROLLER_DIR.exists()


def _source_helper() -> Path:
    return Path(__file__).with_name("privileged_helper.py").resolve()


def _run_pkexec_helper(command: str, args: Iterable[str] = ()) -> subprocess.CompletedProcess[str]:
    pkexec = shutil.which("pkexec")
    if not pkexec:
        raise ControllerWakeError("pkexec was not found. Install/configure Polkit and try again.")
    source = _source_helper()
    if not source.is_file():
        raise ControllerWakeError(f"Privileged helper source is missing: {source}")

    # Install/refresh the helper and execute it in the same authorization window.
    # The destination becomes root-owned before it is executed.
    shell = (
        'install -D -m 0755 "$1" "$2" && shift 2 && exec "$@"'
    )
    argv = [
        pkexec,
        "/bin/sh",
        "-c",
        shell,
        "htpc-control-center",
        str(source),
        str(PRIVILEGED_HELPER),
        str(PRIVILEGED_HELPER),
        command,
        *list(args),
    ]
    try:
        result = subprocess.run(argv, check=False, capture_output=True, text=True, timeout=90)
    except subprocess.TimeoutExpired as exc:
        raise ControllerWakeError("Administrator operation timed out.") from exc
    except OSError as exc:
        raise ControllerWakeError(f"Could not start administrator operation: {exc}") from exc
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip()
        if result.returncode in {126, 127} and not detail:
            detail = "Administrator authorization was cancelled or unavailable."
        raise ControllerWakeError(detail or f"Administrator operation failed ({result.returncode}).")
    return result


def configure(devices: Iterable[USBDevice]) -> str:
    paths: list[str] = []
    for device in devices:
        if not device.selectable:
            raise ControllerWakeError(f"{device.display_name} has no wake-capable USB path.")
        if not re.fullmatch(r"[A-Za-z0-9_.:-]+", device.sysfs_node):
            raise ControllerWakeError(f"Invalid USB sysfs node: {device.sysfs_node}")
        if device.sysfs_node not in paths:
            paths.append(device.sysfs_node)
    if not paths:
        raise ControllerWakeError("Select at least one controller receiver/dongle.")
    return _run_pkexec_helper("configure", paths).stdout.strip()


def remove() -> str:
    return _run_pkexec_helper("remove").stdout.strip()


def purge_privileged_components() -> str:
    return _run_pkexec_helper("purge").stdout.strip()


def suspend_test() -> None:
    try:
        result = subprocess.run(["systemctl", "suspend"], check=False, timeout=20)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ControllerWakeError(f"Could not request suspend: {exc}") from exc
    if result.returncode != 0:
        raise ControllerWakeError("systemctl suspend failed.")
