from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, patch

from htpc_control_center.config import AppConfig
from htpc_control_center.paths import AppPaths
from htpc_control_center.tv.lifecycle import EventResult, LogindWatcher


class LifecycleSeparationTests(unittest.IsolatedAsyncioTestCase):
    async def test_suspend_deadline_has_no_controller_config_dependency(self) -> None:
        config = AppConfig()
        paths = AppPaths.from_environment()
        watcher = LogindWatcher(config, paths)
        watcher.effective_delay_seconds = 1.0

        fake = AsyncMock(return_value=EventResult("suspend", True, True, "ok"))
        with patch("htpc_control_center.tv.lifecycle.handle_event", fake):
            await watcher._run_event_with_deadline("suspend")

        fake.assert_awaited_once_with("suspend", config, paths)


if __name__ == "__main__":
    unittest.main()
