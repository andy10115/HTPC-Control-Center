"""Graphical controller wake setup flow."""
from __future__ import annotations

from collections.abc import Callable

from gi.repository import Adw, Gtk

from ..controller.discovery import ControllerDiscoveryError, USBDevice, list_usb_devices
from ..controller import manager
from .common import action_row, button_row, confirm, emphasized_link_button, heading, page_shell, primary_button, run_background, secondary_button, show_message

README_URL = "https://github.com/andy10115/HTPC-Control-Center#controller-wake-setup"


class ControllerSetupView(Gtk.Box):
    def __init__(self, window: Gtk.Window, on_done: Callable[[], None]) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.window = window
        self.on_done = on_done
        self.devices: list[USBDevice] = []
        self.checks: list[tuple[USBDevice, Gtk.CheckButton]] = []
        self.selected: list[USBDevice] = []
        shell, self.content, _header = page_shell("Controller Wake Setup", lambda *_: self.on_done())
        self.append(shell)
        self.render_prereqs()

    def clear(self) -> None:
        child = self.content.get_first_child()
        while child is not None:
            nxt = child.get_next_sibling()
            self.content.remove(child)
            child = nxt

    def footer(self, back_cb=None, next_cb=None, next_label="Continue") -> None:
        buttons: list[Gtk.Button] = []
        if back_cb is not None:
            back = secondary_button("Back")
            back.connect("clicked", lambda *_: back_cb())
            buttons.append(back)
        if next_cb is not None:
            nxt = primary_button(next_label)
            nxt.connect("clicked", lambda *_: next_cb())
            buttons.append(nxt)
        self.content.append(button_row(*buttons))

    def render_prereqs(self) -> None:
        self.clear()
        self.content.append(
            heading(
                "Wake the PC with a controller",
                "This configures wake from system suspend for controller signals arriving through a USB receiver/dongle.",
            )
        )
        group = Adw.PreferencesGroup()
        group.set_title("Before you start")
        group.add(action_row("Power on and pair the controller", "Keep its USB receiver/dongle connected while setup scans the USB topology."))
        group.add(action_row("Firmware must allow USB wake", "Check USB Wake Support, PME/PCIe wake, ErP/Deep Sleep, or equivalent motherboard settings when needed."))
        group.add(action_row("Suspend only", "This does not configure controller power-on from full shutdown (S5)."))
        group.add(action_row("Bluetooth-only controllers are not supported", "A device that merely looks like a Bluetooth adapter will be warned about before setup continues."))
        group.add(action_row("5-second quiet window", "Immediately before suspend, only the configured USB wake paths are disarmed for 5 seconds so controller power-off traffic cannot bounce the PC awake."))
        if manager.legacy_installation_detected():
            legacy = action_row(
                "Older HTPC-Controller-Wake install detected",
                "Uninstall the proof-of-concept first. Running both can create duplicate udev configuration and stack multiple pre-suspend guards.",
            )
            group.add(legacy)
        docs = action_row("Need details?", "Read the controller setup and troubleshooting sections in the README.")
        docs.add_suffix(emphasized_link_button("Read Setup Guide", README_URL))
        group.add(docs)
        self.content.append(group)
        self.footer(None, self.render_scan, "Scan USB Devices")

    def render_scan(self) -> None:
        self.clear()
        self.content.append(
            heading(
                "Select controller receivers",
                "Choose one or more USB devices. HTPC Control Center resolves each current bus/device identity to sysfs and walks upward to every USB node that actually exposes power/wakeup.",
            )
        )
        self.device_group = Adw.PreferencesGroup()
        self.device_group.set_title("Connected USB devices")
        self.scan_status_row = action_row("Scanning…", "Root hubs are hidden from the choice list.")
        self.device_group.add(self.scan_status_row)
        self.content.append(self.device_group)
        self.footer(self.render_prereqs, None)
        run_background(list_usb_devices, self._show_devices, self._show_scan_error)

    def _show_devices(self, devices: list[USBDevice]) -> None:
        self.devices = devices
        self.checks = []
        if not devices:
            self.scan_status_row.set_title("No USB devices found")
            self.scan_status_row.set_subtitle("Connect the receiver/dongle and scan again.")
            retry = secondary_button("Scan Again")
            retry.connect("clicked", lambda *_: self.render_scan())
            self.content.append(button_row(retry))
            return
        self.scan_status_row.set_title(f"Found {len(devices)} USB device(s)")
        self.scan_status_row.set_subtitle("Devices without a wake-capable USB path are shown but cannot be selected.")
        existing_paths = {item.path for item in manager.status().devices}
        for device in devices:
            if device.selectable:
                subtitle = f"{device.vid}:{device.pid} • USB path {device.sysfs_node} • wake targets: {', '.join(device.wake_targets)}"
                if device.looks_like_bluetooth:
                    subtitle += " • WARNING: name looks like a Bluetooth adapter"
            elif device.sysfs_node:
                subtitle = f"{device.vid}:{device.pid} • USB path {device.sysfs_node} • no wake-capable USB ancestor found"
            else:
                subtitle = f"{device.vid}:{device.pid} • could not resolve current sysfs USB path"
            row = action_row(device.display_name, subtitle)
            check = Gtk.CheckButton()
            check.set_valign(Gtk.Align.CENTER)
            check.set_sensitive(device.selectable)
            check.set_active(device.sysfs_node in existing_paths and device.selectable)
            row.add_prefix(check)
            row.set_activatable_widget(check)
            self.device_group.add(row)
            self.checks.append((device, check))
        choose = primary_button("Continue with Selected Devices")
        choose.connect("clicked", lambda *_: self._review_selection())
        scan = secondary_button("Scan Again")
        scan.connect("clicked", lambda *_: self.render_scan())
        self.content.append(button_row(scan, choose))

    def _show_scan_error(self, exc: BaseException) -> None:
        self.scan_status_row.set_title("USB scan failed")
        self.scan_status_row.set_subtitle(str(exc))
        retry = secondary_button("Scan Again")
        retry.connect("clicked", lambda *_: self.render_scan())
        self.content.append(button_row(retry))

    def _review_selection(self) -> None:
        self.selected = [device for device, check in self.checks if check.get_active()]
        if not self.selected:
            show_message(self.window, "Select a receiver", "Choose at least one USB controller receiver/dongle with a wake-capable path.")
            return
        bluetooth = [device.display_name for device in self.selected if device.looks_like_bluetooth]
        if bluetooth:
            confirm(
                self.window,
                "Selected device looks like Bluetooth",
                "This feature is intended for a controller's USB receiver/dongle, not Bluetooth controller wake. Selected: " + ", ".join(bluetooth),
                "Use Anyway",
                self.render_review,
            )
            return
        self.render_review()

    def render_review(self) -> None:
        self.clear()
        self.content.append(
            heading(
                "Review controller wake paths",
                "Only the wake-capable USB topology nodes below will be persisted. Other USB devices are not globally enabled for wake.",
            )
        )
        group = Adw.PreferencesGroup()
        group.set_title("Selected receivers")
        for device in self.selected:
            group.add(
                action_row(
                    device.display_name,
                    f"{device.vid}:{device.pid} • selected path {device.sysfs_node} • wake nodes: {', '.join(device.wake_targets)}",
                )
            )
        group.add(
            action_row(
                "Pre-suspend guard",
                "The configured wake nodes are disabled for 5 seconds immediately before systemd-suspend, then re-enabled before the kernel enters suspend.",
            )
        )
        admin = action_row(
            "Administrator access required",
            "Apply uses the desktop Polkit prompt through pkexec. The GTK application itself never runs as root.",
        )
        group.add(admin)
        self.content.append(group)
        self.footer(self.render_scan, self.apply, "Apply Controller Wake")

    def apply(self) -> None:
        self.clear()
        self.content.append(heading("Applying controller wake…", "Approve the administrator prompt. Wake settings are applied immediately; a reboot is not required just to activate the udev rule."))
        spinner = Gtk.Spinner()
        spinner.set_spinning(True)
        spinner.set_halign(Gtk.Align.CENTER)
        self.content.append(spinner)
        run_background(lambda: manager.configure(self.selected), self._applied, self._apply_error)

    def _applied(self, result: str) -> None:
        self.clear()
        self.content.append(heading("Controller wake configured", "The selected USB paths are armed and the 5-second pre-suspend quiet-window guard is installed."))
        group = Adw.PreferencesGroup()
        group.add(action_row("Configured receivers", ", ".join(device.display_name for device in self.selected)))
        group.add(action_row("Result", result or "Controller wake configuration applied."))
        group.add(
            action_row(
                "Test safely",
                "Turn the controller off, suspend normally, wait until the PC is fully asleep, then turn the controller on. Hardware/firmware support can still prevent wake even when Linux flags are correct.",
            )
        )
        self.content.append(group)
        self.footer(None, self.on_done, "Return to Control Center")

    def _apply_error(self, exc: BaseException) -> None:
        self.clear()
        self.content.append(heading("Controller wake setup failed", str(exc)))
        self.footer(self.render_review, self.on_done, "Return to Control Center")
