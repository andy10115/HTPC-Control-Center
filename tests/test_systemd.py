from __future__ import annotations

import unittest

from htpc_control_center.tv.systemd import render_user_unit


class UserServiceTests(unittest.TestCase):
    def test_watcher_unit_uses_new_app_and_user_target(self) -> None:
        unit = render_user_unit("/tmp/example python/bin/python")
        self.assertIn("HTPC Control Center TV lifecycle watcher", unit)
        self.assertIn('ExecStart="/tmp/example python/bin/python" -m htpc_control_center watcher', unit)
        self.assertIn("WantedBy=default.target", unit)
        self.assertNotIn("atv_couch_wake", unit)
        self.assertNotIn("controller", unit.casefold().split("execstart=", 1)[1].splitlines()[0])


if __name__ == "__main__":
    unittest.main()
