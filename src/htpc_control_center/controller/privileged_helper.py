#!/usr/bin/python3
"""Root-only helper for HTPC Control Center controller wake configuration.

This file is copied to /usr/local/libexec with root ownership before execution.
It intentionally uses only the Python standard library.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

RULE_FILE = Path("/etc/udev/rules.d/99-htpc-control-center-controller-wake.rules")
CONFIG_DIR = Path("/etc/htpc-control-center")
WAKE_TARGETS_FILE = CONFIG_DIR / "controller-wake-targets"
SUSPEND_DROPIN_DIR = Path("/etc/systemd/system/systemd-suspend.service.d")
SUSPEND_DROPIN = SUSPEND_DROPIN_DIR / "htpc-control-center-controller-wake.conf"
PRIVILEGED_HELPER = Path("/usr/local/libexec/htpc-control-center-privileged")
SUSPEND_GUARD = Path("/usr/local/libexec/htpc-control-center-suspend-guard")
SYSFS_ROOT = Path(os.environ.get("HTPC_CC_SYSFS_ROOT", "/sys"))
USB_DEVICES_DIR = SYSFS_ROOT / "bus/usb/devices"
SAFE_NODE = re.compile(r"^[A-Za-z0-9_.:-]+$")
QUIET_SECONDS = 5


@dataclass(frozen=True)
class Device:
    name: str
    vid: str
    pid: str
    path: str
    targets: tuple[str, ...]


def fail(message: str, code: int = 1) -> "NoReturn":
    print(message, file=sys.stderr)
    raise SystemExit(code)


def _read(path: Path, default: str = "") -> str:
    try:
        return path.read_text(encoding="utf-8").strip()
    except OSError:
        return default


def _subsystem_name(path: Path) -> str:
    subsystem = path / "subsystem"
    try:
        return subsystem.resolve().name if subsystem.is_symlink() else ""
    except OSError:
        return ""


def discover_targets(start: Path) -> tuple[str, ...]:
    try:
        current = start.resolve()
        root = SYSFS_ROOT.resolve()
    except OSError:
        return ()
    targets: list[str] = []
    while current != root:
        try:
            current.relative_to(root)
        except ValueError:
            break
        if _subsystem_name(current) == "usb" and (current / "power/wakeup").exists():
            if SAFE_NODE.fullmatch(current.name):
                targets.append(current.name)
        parent = current.parent
        if parent == current:
            break
        current = parent
    return tuple(targets)


def resolve_device(node_name: str) -> Device:
    if not SAFE_NODE.fullmatch(node_name):
        fail(f"Refusing invalid USB node name: {node_name}")
    node = USB_DEVICES_DIR / node_name
    if not node.exists():
        fail(f"USB device is no longer present: {node_name}")
    try:
        resolved = node.resolve(strict=True)
    except OSError as exc:
        fail(f"Could not resolve USB device {node_name}: {exc}")
    targets = discover_targets(resolved)
    if not targets:
        fail(f"No wake-capable USB nodes were found above {node_name}.")
    vid = _read(resolved / "idVendor", "0000").lower()
    pid = _read(resolved / "idProduct", "0000").lower()
    name = _read(resolved / "product", "Unknown USB device").replace("\n", " ").strip()
    return Device(name=name, vid=vid, pid=pid, path=node_name, targets=targets)


def _atomic_write(path: Path, content: str, mode: int = 0o644) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temp = Path(temp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temp, mode)
        os.replace(temp, path)
    finally:
        try:
            temp.unlink()
        except FileNotFoundError:
            pass


def render_rules(devices: list[Device]) -> tuple[str, tuple[str, ...]]:
    lines = [
        "# HTPC Control Center controller wake rules",
        f"# Generated {datetime.now().astimezone().isoformat(timespec='seconds')}",
        "# Wake-capable USB topology is discovered from the selected receiver(s).",
        "",
    ]
    targets: list[str] = []
    seen: set[str] = set()
    for device in devices:
        lines.extend(
            [
                f"# {device.name} ({device.vid}:{device.pid})",
                f"# Device path: {device.path}",
                f"# Wake targets: {' '.join(device.targets)}",
                "",
            ]
        )
        for target in device.targets:
            if target not in seen:
                seen.add(target)
                targets.append(target)
    for target in targets:
        lines.append(
            f'ACTION=="add", SUBSYSTEM=="usb", KERNEL=="{target}", '
            'TEST=="power/wakeup", ATTR{power/wakeup}="enabled"'
        )
    lines.append("")
    return "\n".join(lines), tuple(targets)


def render_targets(targets: tuple[str, ...]) -> str:
    return (
        "# HTPC Control Center controller wake targets\n"
        "# One USB topology node per line. Used by the pre-suspend quiet-window guard.\n"
        + "".join(f"{target}\n" for target in targets)
    )


def render_guard() -> str:
    return f'''#!/bin/bash
# Installed by HTPC Control Center.
# Temporarily disarm only configured controller-wake USB paths while receiver
# shutdown/re-enumeration traffic settles, then re-arm them before suspend.
set -u
TAG="htpc-control-center"
SYSFS_ROOT="${{HTPC_CC_SYSFS_ROOT:-/sys}}"
USB_DEVICES_DIR="$SYSFS_ROOT/bus/usb/devices"
TARGETS_FILE="${{HTPC_CC_WAKE_TARGETS_FILE:-{WAKE_TARGETS_FILE}}}"
QUIET_SECONDS="${{HTPC_CC_QUIET_SECONDS:-{QUIET_SECONDS}}}"

log() {{ command -v logger >/dev/null 2>&1 && logger -t "$TAG" -- "$*" || true; }}
read_targets() {{
    local line target
    [[ -r "$TARGETS_FILE" ]] || return 0
    while IFS= read -r line; do
        target="${{line%%#*}}"
        target="${{target%%[[:space:]]*}}"
        [[ -n "$target" ]] && printf '%s\\n' "$target"
    done < "$TARGETS_FILE"
}}
set_targets() {{
    local state="$1" target wake_file
    while IFS= read -r target; do
        [[ -n "$target" ]] || continue
        wake_file="$USB_DEVICES_DIR/$target/power/wakeup"
        [[ -e "$wake_file" ]] || continue
        printf '%s\\n' "$state" > "$wake_file" 2>/dev/null || true
    done < <(read_targets)
}}
rearm() {{ set_targets enabled; }}
trap rearm EXIT
trap 'exit 130' INT
trap 'exit 143' TERM HUP
[[ -r "$TARGETS_FILE" ]] || exit 0
[[ "$QUIET_SECONDS" =~ ^[0-9]+([.][0-9]+)?$ ]] || QUIET_SECONDS={QUIET_SECONDS}
set_targets disabled
log "Controller wake paths disarmed for ${{QUIET_SECONDS}}s pre-suspend quiet window."
sleep "$QUIET_SECONDS"
set_targets enabled
log "Controller wake paths re-armed; continuing suspend."
exit 0
'''


def _run_quiet(command: list[str]) -> None:
    try:
        subprocess.run(command, check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=20)
    except (OSError, subprocess.TimeoutExpired):
        pass


def _enable_targets(targets: tuple[str, ...]) -> tuple[int, int]:
    enabled = failed = 0
    for target in targets:
        wake_file = USB_DEVICES_DIR / target / "power/wakeup"
        if not wake_file.exists():
            continue
        try:
            wake_file.write_text("enabled\n", encoding="utf-8")
            enabled += 1
        except OSError:
            failed += 1
    return enabled, failed


def configure(node_names: list[str]) -> None:
    if os.geteuid() != 0:
        fail("This helper must run as root.")
    if not node_names:
        fail("No USB devices were supplied.")
    devices: list[Device] = []
    seen_paths: set[str] = set()
    for node_name in node_names:
        if node_name in seen_paths:
            continue
        seen_paths.add(node_name)
        devices.append(resolve_device(node_name))

    rules, targets = render_rules(devices)
    _atomic_write(RULE_FILE, rules)
    _atomic_write(WAKE_TARGETS_FILE, render_targets(targets))
    _atomic_write(SUSPEND_GUARD, render_guard(), 0o755)
    _atomic_write(
        SUSPEND_DROPIN,
        f"# Installed by HTPC Control Center.\n[Service]\nExecStartPre={SUSPEND_GUARD}\n",
    )
    enabled, failed = _enable_targets(targets)
    _run_quiet(["udevadm", "control", "--reload-rules"])
    _run_quiet(["systemctl", "daemon-reload"])
    print(f"Configured {len(devices)} controller receiver(s); enabled {enabled} wake path(s).")
    if failed:
        print(f"Warning: {failed} current wake-path write(s) failed; udev will retry on future add events.")
    print(f"Pre-suspend quiet window: {QUIET_SECONDS} seconds.")


def remove(*, purge: bool = False) -> None:
    if os.geteuid() != 0:
        fail("This helper must run as root.")
    for path in (RULE_FILE, WAKE_TARGETS_FILE, SUSPEND_DROPIN, SUSPEND_GUARD):
        try:
            path.unlink()
        except FileNotFoundError:
            pass
    try:
        CONFIG_DIR.rmdir()
    except OSError:
        pass
    try:
        SUSPEND_DROPIN_DIR.rmdir()
    except OSError:
        pass
    _run_quiet(["udevadm", "control", "--reload-rules"])
    _run_quiet(["systemctl", "daemon-reload"])
    print("Controller wake configuration removed. Existing live wake flags were left unchanged intentionally.")
    if purge:
        try:
            PRIVILEGED_HELPER.unlink()
        except FileNotFoundError:
            pass


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        fail("Usage: htpc-control-center-privileged configure <usb-node>... | remove | purge")
    command = argv[1]
    if command == "configure":
        configure(argv[2:])
        return 0
    if command == "remove":
        remove(purge=False)
        return 0
    if command == "purge":
        remove(purge=True)
        return 0
    fail(f"Unknown privileged command: {command}")


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
