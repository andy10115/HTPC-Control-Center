from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class UIContractSourceTests(unittest.TestCase):
    def test_main_navigation_buttons_are_connected(self) -> None:
        source = (ROOT / "src/htpc_control_center/ui/main_page.py").read_text(encoding="utf-8")
        self.assertIn('primary_button("Set Up My TV", fill=True)', source)
        self.assertIn('setup_tv.connect("clicked", open_tv_setup)', source)
        self.assertIn('primary_button("Set Up Controller Wake", fill=True)', source)
        self.assertIn('setup_controller.connect("clicked", open_controller_setup)', source)
        self.assertIn('preferences.connect("clicked", open_preferences)', source)

    def test_router_uses_direct_content_replacement(self) -> None:
        source = (ROOT / "src/htpc_control_center/window.py").read_text(encoding="utf-8")
        self.assertIn('self.set_content(widget)', source)
        self.assertIn('self._show("tv-setup", page)', source)
        self.assertIn('self._show("controller-setup", page)', source)
        self.assertIn('self._show("preferences", page)', source)
        self.assertNotIn('self.stack = Gtk.Stack()', source)

    def test_tv_setup_starts_with_provider_choice(self) -> None:
        source = (ROOT / "src/htpc_control_center/ui/tv_setup.py").read_text(encoding="utf-8")
        self.assertIn('"Choose a TV operating system"', source)
        self.assertIn('primary_button("Set Up Android / Google TV", fill=True)', source)

    def test_preferences_has_update_toggle(self) -> None:
        source = (ROOT / "src/htpc_control_center/ui/preferences.py").read_text(encoding="utf-8")
        self.assertIn('Adw.SwitchRow()', source)
        self.assertIn('"Automatically check for updates"', source)


if __name__ == "__main__":
    unittest.main()
