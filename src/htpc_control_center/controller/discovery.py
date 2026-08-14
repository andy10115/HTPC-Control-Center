"""USB receiver discovery and topology tracing for controller wake."""
from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path


class ControllerDiscoveryError(RuntimeError):
    pass


@dataclass(frozen=True)
class USBDevice:
    bus: int
    device: int
    vid: str
    pid: str
    name: str
    sysfs_node: str
    wake_targets: tuple[str, ...]

    @property
    def selectable(self) -> bool:
        return bool(self.sysfs_node and self.wake_targets)

    @property
    def looks_like_bluetooth(self) -> bool:
        return "bluetooth" in self.name.casefold()

    @property
    def display_name(self) -> str:
        return self.name or "Unknown USB device"


LSUSB_RE = re.compile(
    r"^Bus\s+(\d+)\s+Device\s+(\d+):\s+ID\s+([0-9a-fA-F]{4}):([0-9a-fA-F]{4})(?:\s+(.*))?$"
)


def parse_lsusb(text: str) -> list[tuple[int, int, str, str, str]]:
    parsed: list[tuple[int, int, str, str, str]] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or "root hub" in line.casefold():
            continue
        match = LSUSB_RE.match(line)
        if not match:
            continue
        parsed.append(
            (
                int(match.group(1)),
                int(match.group(2)),
                match.group(3).lower(),
                match.group(4).lower(),
                (match.group(5) or "Unknown USB device").strip(),
            )
        )
    return parsed


def _read_int(path: Path) -> int | None:
    try:
        return int(path.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return None


def resolve_lsusb_sysfs(bus: int, device: int, sysfs_root: Path = Path("/sys")) -> Path | None:
    usb_dir = sysfs_root / "bus/usb/devices"
    if not usb_dir.is_dir():
        return None
    for node in usb_dir.iterdir():
        node_bus = _read_int(node / "busnum")
        node_dev = _read_int(node / "devnum")
        if node_bus == bus and node_dev == device:
            try:
                return node.resolve()
            except OSError:
                return None
    return None


def discover_wake_targets(start: Path, sysfs_root: Path = Path("/sys")) -> tuple[str, ...]:
    """Walk upward and return USB nodes that expose power/wakeup."""
    try:
        current = start.resolve()
        root = sysfs_root.resolve()
    except OSError:
        return ()

    targets: list[str] = []
    while current != root:
        try:
            current.relative_to(root)
        except ValueError:
            break
        subsystem = current / "subsystem"
        subsystem_name = ""
        try:
            if subsystem.is_symlink():
                subsystem_name = subsystem.resolve().name
        except OSError:
            pass
        if subsystem_name == "usb" and (current / "power/wakeup").exists():
            targets.append(current.name)
        parent = current.parent
        if parent == current:
            break
        current = parent
    return tuple(targets)


def list_usb_devices(
    *, sysfs_root: Path = Path("/sys"), lsusb_text: str | None = None
) -> list[USBDevice]:
    if lsusb_text is None:
        try:
            result = subprocess.run(
                ["lsusb"], check=False, capture_output=True, text=True, timeout=8
            )
        except FileNotFoundError as exc:
            raise ControllerDiscoveryError(
                "lsusb was not found. Install your distribution's usbutils package and try again."
            ) from exc
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise ControllerDiscoveryError(f"Could not scan USB devices: {exc}") from exc
        if result.returncode != 0:
            raise ControllerDiscoveryError(result.stderr.strip() or "lsusb failed.")
        lsusb_text = result.stdout

    devices: list[USBDevice] = []
    for bus, dev, vid, pid, name in parse_lsusb(lsusb_text):
        node = resolve_lsusb_sysfs(bus, dev, sysfs_root)
        devices.append(
            USBDevice(
                bus=bus,
                device=dev,
                vid=vid,
                pid=pid,
                name=name,
                sysfs_node=node.name if node else "",
                wake_targets=discover_wake_targets(node, sysfs_root) if node else (),
            )
        )
    return devices
