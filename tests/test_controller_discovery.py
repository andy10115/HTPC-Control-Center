from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from htpc_control_center.controller.discovery import list_usb_devices, parse_lsusb


def build_fake_sysfs(root: Path) -> None:
    usb_subsystem = root / "bus/usb"
    devices_links = usb_subsystem / "devices"
    devices_links.mkdir(parents=True)

    physical = root / "devices/pci0000:00/0000:00:08.1/usb5/5-1/5-1.3"
    physical.mkdir(parents=True)

    for node in [physical.parents[1], physical.parent, physical]:
        (node / "power").mkdir(exist_ok=True)
        subsystem = node / "subsystem"
        subsystem.symlink_to(usb_subsystem)

    # Root controller and parent hub expose wake; selected receiver itself does not.
    (physical.parents[1] / "power/wakeup").write_text("enabled\n")
    (physical.parent / "power/wakeup").write_text("disabled\n")

    (physical / "busnum").write_text("5\n")
    (physical / "devnum").write_text("7\n")
    (physical / "idVendor").write_text("2dc8\n")
    (physical / "idProduct").write_text("6013\n")
    (physical / "product").write_text("8BitDo Receiver\n")

    (devices_links / "5-1.3").symlink_to(physical)


class ControllerDiscoveryTests(unittest.TestCase):
    def test_parse_lsusb_hides_root_hubs(self) -> None:
        text = """Bus 005 Device 001: ID 1d6b:0003 Linux Foundation 3.0 root hub
Bus 005 Device 007: ID 2dc8:6013 8BitDo Receiver
"""
        self.assertEqual(parse_lsusb(text), [(5, 7, "2dc8", "6013", "8BitDo Receiver")])

    def test_discovery_uses_physical_path_and_wake_capable_ancestors(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            build_fake_sysfs(root)
            devices = list_usb_devices(
                sysfs_root=root,
                lsusb_text="Bus 005 Device 007: ID 2dc8:6013 8BitDo Receiver\n",
            )
            self.assertEqual(len(devices), 1)
            device = devices[0]
            self.assertEqual(device.sysfs_node, "5-1.3")
            self.assertEqual(device.wake_targets, ("5-1", "usb5"))
            self.assertTrue(device.selectable)


if __name__ == "__main__":
    unittest.main()
