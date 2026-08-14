from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from htpc_control_center.config import AppConfig, load_config, save_config
from htpc_control_center.paths import AppPaths


class ConfigTests(unittest.TestCase):
    def test_round_trip_preserves_tv_and_behavior(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config_dir = root / "config"
            user_unit_dir = root / "systemd/user"
            paths = AppPaths(
                config_dir=config_dir,
                data_dir=root / "data",
                state_dir=root / "state",
                runtime_dir=root / "runtime",
                config_file=config_dir / "config.toml",
                user_unit_dir=user_unit_dir,
                user_unit_file=user_unit_dir / "htpc-control-center-tv-watcher.service",
            )
            config = AppConfig()
            config.tv.host = "10.0.0.42"
            config.tv.port = 5555
            config.tv.name = 'Living Room "TV"'
            config.tv.model = "QM6K"
            config.tv.input_id = "com.vendor/.InputService/HW6"
            config.tv.input_uri = "content://android.media.tv/passthrough/test"
            config.tv.input_label = "HW6"
            config.behavior.off_on_reboot = True
            config.behavior.switch_input_after_wake = True
            config.behavior.adb_ready_timeout_seconds = 30.0

            path = save_config(config, paths)
            loaded = load_config(paths)

            self.assertEqual(path, paths.config_file)
            self.assertEqual(loaded.tv.host, "10.0.0.42")
            self.assertEqual(loaded.tv.name, 'Living Room "TV"')
            self.assertEqual(loaded.tv.input_label, "HW6")
            self.assertTrue(loaded.behavior.off_on_reboot)
            self.assertEqual(loaded.behavior.adb_ready_timeout_seconds, 30.0)
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)


if __name__ == "__main__":
    unittest.main()
