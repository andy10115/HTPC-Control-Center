"""XDG and system paths used by HTPC Control Center."""
from __future__ import annotations

import os
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class AppPaths:
    config_dir: Path
    data_dir: Path
    state_dir: Path
    runtime_dir: Path
    config_file: Path
    user_unit_dir: Path
    user_unit_file: Path

    @classmethod
    def from_environment(cls) -> "AppPaths":
        home = Path.home()
        config_home = Path(os.environ.get("XDG_CONFIG_HOME", home / ".config"))
        data_home = Path(os.environ.get("XDG_DATA_HOME", home / ".local/share"))
        state_home = Path(os.environ.get("XDG_STATE_HOME", home / ".local/state"))
        runtime_base = Path(os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}"))
        config_dir = config_home / "htpc-control-center"
        data_dir = data_home / "htpc-control-center"
        state_dir = state_home / "htpc-control-center"
        runtime_dir = runtime_base / "htpc-control-center"
        user_unit_dir = config_home / "systemd/user"
        return cls(
            config_dir=config_dir,
            data_dir=data_dir,
            state_dir=state_dir,
            runtime_dir=runtime_dir,
            config_file=config_dir / "config.toml",
            user_unit_dir=user_unit_dir,
            user_unit_file=user_unit_dir / "htpc-control-center-tv-watcher.service",
        )

    def ensure_private_directories(self) -> None:
        for path in (self.config_dir, self.data_dir, self.state_dir, self.runtime_dir):
            path.mkdir(parents=True, exist_ok=True, mode=0o700)
            with suppress(OSError):
                path.chmod(0o700)
