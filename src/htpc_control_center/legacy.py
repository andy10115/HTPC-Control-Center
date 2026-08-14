"""Detection-only helpers for earlier proof-of-concept projects."""
from __future__ import annotations

from pathlib import Path


def detect_legacy_projects() -> tuple[str, ...]:
    found: list[str] = []
    home = Path.home()
    if (home / ".config/atv-couch-wake").exists() or (
        home / ".config/systemd/user/atv-couch-wake-watcher.service"
    ).exists():
        found.append("ATV-Couch-Wake")
    if Path("/etc/udev/rules.d/99-controller-wakeup.rules").exists() or Path(
        "/etc/htpc-controller-wake"
    ).exists():
        found.append("HTPC-Controller-Wake")
    return tuple(found)
