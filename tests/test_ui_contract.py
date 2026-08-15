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


    def test_shared_page_shell_expands_inside_subpage_wrappers(self) -> None:
        source = (ROOT / "src/htpc_control_center/ui/common.py").read_text(encoding="utf-8")
        self.assertIn("toolbar.set_hexpand(True)", source)
        self.assertIn("toolbar.set_vexpand(True)", source)
        self.assertIn("scroller.set_hexpand(True)", source)
        self.assertIn("scroller.set_vexpand(True)", source)

    def test_preferences_has_update_toggle(self) -> None:
        source = (ROOT / "src/htpc_control_center/ui/preferences.py").read_text(encoding="utf-8")
        self.assertIn('Adw.SwitchRow()', source)
        self.assertIn('"Automatically check for updates"', source)

    def test_main_page_keeps_status_but_drops_extra_notes(self) -> None:
        source = (ROOT / "src/htpc_control_center/ui/main_page.py").read_text(encoding="utf-8")
        self.assertIn('status_label(', source)
        self.assertNotIn('"TV platform support"', source)
        self.assertNotIn('"Controller wake notes"', source)

    def test_preferences_is_updates_and_about_only(self) -> None:
        source = (ROOT / "src/htpc_control_center/ui/preferences.py").read_text(encoding="utf-8")
        self.assertIn('updates_group.set_title("Updates")', source)
        self.assertIn('about_group.set_title("About")', source)
        self.assertNotIn('heading("TV"', source)
        self.assertNotIn('heading("Controller Wake"', source)

    def test_setup_flows_use_header_back_arrow_only(self) -> None:
        for relative in ("ui/tv_setup.py", "ui/controller_setup.py"):
            source = (ROOT / "src/htpc_control_center" / relative).read_text(encoding="utf-8")
            self.assertIn('self._set_back(', source)
            self.assertNotIn('secondary_button("Back")', source)

    def test_tv_setup_can_recheck_bazzite_homebrew_adb(self) -> None:
        source = (ROOT / "src/htpc_control_center/ui/tv_setup.py").read_text(encoding="utf-8")
        backend = (ROOT / "src/htpc_control_center/tv/android.py").read_text(encoding="utf-8")
        self.assertIn('primary_button("Recheck ADB", fill=True)', source)
        self.assertIn('"ADB found via Homebrew"', source)
        self.assertIn('/home/linuxbrew/.linuxbrew/bin/brew', backend)
        self.assertIn('brew install android-platform-tools', backend)

    def test_application_icons_are_shipped(self) -> None:
        icons = ROOT / "data/icons"
        stem = "io.github.andy10115.HTPCControlCenter"
        self.assertTrue((icons / f"{stem}.svg").is_file())
        self.assertTrue((icons / f"{stem}.png").is_file())
        self.assertTrue((icons / f"{stem}.ico").is_file())


if __name__ == "__main__":
    unittest.main()
