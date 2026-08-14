from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from htpc_control_center.controller.manager import parse_configured_devices
from htpc_control_center.controller import privileged_helper as helper
from htpc_control_center.controller.privileged_helper import Device, render_guard, render_rules, render_targets


class ControllerRuleTests(unittest.TestCase):
    def test_rules_are_topology_based_and_deduplicated(self) -> None:
        devices = [
            Device("8BitDo Receiver", "2dc8", "6013", "5-1.3", ("5-1", "usb5")),
            Device("Steam Receiver", "28de", "1142", "5-1.4", ("5-1", "usb5")),
        ]
        rules, targets = render_rules(devices)
        self.assertEqual(targets, ("5-1", "usb5"))
        self.assertEqual(rules.count('KERNEL=="5-1"'), 1)
        self.assertEqual(rules.count('KERNEL=="usb5"'), 1)
        self.assertNotIn('ATTR{idVendor}', rules)

        parsed = parse_configured_devices(rules)
        self.assertEqual(len(parsed), 2)
        self.assertEqual(parsed[0].path, "5-1.3")
        self.assertEqual(parsed[1].wake_targets, ("5-1", "usb5"))

    def test_guard_defaults_to_five_seconds(self) -> None:
        guard = render_guard()
        self.assertIn('HTPC_CC_QUIET_SECONDS:-5', guard)
        self.assertIn('set_targets disabled', guard)
        self.assertIn('sleep "$QUIET_SECONDS"', guard)
        self.assertIn('set_targets enabled', guard)
        self.assertIn('trap rearm EXIT', guard)

    def test_target_file_is_simple_and_comment_tolerant(self) -> None:
        text = render_targets(("5-1", "usb5"))
        self.assertTrue(text.endswith("5-1\nusb5\n"))

    def test_full_privileged_configure_against_fake_sysfs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            sysroot = root / "sys"
            usb_subsystem = sysroot / "bus/usb"
            links = usb_subsystem / "devices"
            links.mkdir(parents=True)
            leaf = sysroot / "devices/pci0000:00/usb5/5-1/5-1.3"
            leaf.mkdir(parents=True)
            for node in (leaf.parents[1], leaf.parent, leaf):
                (node / "power").mkdir(exist_ok=True)
                (node / "subsystem").symlink_to(usb_subsystem)
            (leaf.parents[1] / "power/wakeup").write_text("disabled\n")
            (leaf.parent / "power/wakeup").write_text("disabled\n")
            (leaf / "idVendor").write_text("2dc8\n")
            (leaf / "idProduct").write_text("6013\n")
            (leaf / "product").write_text("8BitDo Receiver\n")
            (links / "5-1.3").symlink_to(leaf)
            (links / "5-1").symlink_to(leaf.parent)
            (links / "usb5").symlink_to(leaf.parents[1])

            etc = root / "etc"
            libexec = root / "usr/local/libexec"
            rule_file = etc / "udev/rules.d/rules"
            config_dir = etc / "htpc-control-center"
            targets_file = config_dir / "controller-wake-targets"
            dropin_dir = etc / "systemd/system/systemd-suspend.service.d"
            dropin = dropin_dir / "controller.conf"
            guard = libexec / "guard"
            privileged = libexec / "privileged"

            with (
                patch.object(helper, "SYSFS_ROOT", sysroot),
                patch.object(helper, "USB_DEVICES_DIR", links),
                patch.object(helper, "RULE_FILE", rule_file),
                patch.object(helper, "CONFIG_DIR", config_dir),
                patch.object(helper, "WAKE_TARGETS_FILE", targets_file),
                patch.object(helper, "SUSPEND_DROPIN_DIR", dropin_dir),
                patch.object(helper, "SUSPEND_DROPIN", dropin),
                patch.object(helper, "SUSPEND_GUARD", guard),
                patch.object(helper, "PRIVILEGED_HELPER", privileged),
                patch.object(helper.os, "geteuid", return_value=0),
                patch.object(helper, "_run_quiet"),
                patch("builtins.print"),
            ):
                helper.configure(["5-1.3"])

            rules = rule_file.read_text()
            self.assertIn('KERNEL=="5-1"', rules)
            self.assertIn('KERNEL=="usb5"', rules)
            self.assertEqual(targets_file.read_text().splitlines()[-2:], ["5-1", "usb5"])
            self.assertIn("ExecStartPre=", dropin.read_text())
            self.assertTrue(guard.stat().st_mode & 0o111)
            self.assertEqual((leaf.parent / "power/wakeup").read_text(), "enabled\n")
            self.assertEqual((leaf.parents[1] / "power/wakeup").read_text(), "enabled\n")


if __name__ == "__main__":
    unittest.main()
