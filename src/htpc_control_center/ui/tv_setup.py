"""Graphical Android/Google TV setup flow."""
from __future__ import annotations

import asyncio
from collections.abc import Callable

from gi.repository import Adw, Gtk

from ..config import AppConfig, load_config, save_config
from ..tv.android import (
    ADBController,
    ADBNotInstalled,
    TVControlError,
    TVInput,
    authorize_controller,
    discover_adb_targets,
    find_adb,
    installation_help,
    set_tv_endpoint,
)
from ..tv.systemd import install_user_service
from .common import action_row, button_row, heading, page_shell, run_background, show_message

README_URL = "https://github.com/andy10115/HTPC-Control-Center#android-tv--google-tv-setup"


class TVSetupView(Gtk.Box):
    def __init__(self, window: Gtk.Window, on_done: Callable[[], None]) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.window = window
        self.on_done = on_done
        self.config: AppConfig = load_config(required=False)
        self.config.tv.provider = "android"
        self.inputs: list[TVInput] = []
        self._busy_buttons: list[Gtk.Button] = []
        shell, self.content, _header = page_shell("TV Setup", lambda *_: self.on_done())
        self.append(shell)
        self.render_provider()

    def clear(self) -> None:
        child = self.content.get_first_child()
        while child is not None:
            nxt = child.get_next_sibling()
            self.content.remove(child)
            child = nxt

    def footer(self, back_cb=None, next_cb=None, next_label="Continue") -> None:
        buttons: list[Gtk.Button] = []
        if back_cb is not None:
            back = Gtk.Button(label="Back")
            back.connect("clicked", lambda *_: back_cb())
            buttons.append(back)
        if next_cb is not None:
            nxt = Gtk.Button(label=next_label)
            nxt.add_css_class("suggested-action")
            nxt.connect("clicked", lambda *_: next_cb())
            buttons.append(nxt)
        self.content.append(button_row(*buttons))

    def render_provider(self) -> None:
        self.clear()
        self.content.append(
            heading(
                "Set up my TV",
                "TV providers stay separate so more operating systems can be added without changing controller wake.",
            )
        )
        group = Adw.PreferencesGroup()
        group.set_title("Choose a TV operating system")
        android = action_row(
            "Android TV / Google TV",
            "Supported — uses ADB over your local network for power and physical input selection.",
        )
        use = Gtk.Button(label="Use Android / Google TV")
        use.add_css_class("suggested-action")
        use.connect("clicked", lambda *_: self.render_prereqs())
        android.add_suffix(use)
        group.add(android)
        group.add(
            action_row(
                "Other TV operating systems",
                "Contributors needed. The v1 project has no untestable placeholder backends.",
            )
        )
        self.content.append(group)
        self.footer(None, None)

    def render_prereqs(self) -> None:
        self.clear()
        self.content.append(
            heading(
                "Prepare your Android / Google TV",
                "Do these once on the TV before connecting. Labels vary a little by manufacturer.",
            )
        )
        group = Adw.PreferencesGroup()
        group.set_title("Quick prerequisites")
        group.add(
            action_row(
                "1. Enable Developer Options",
                "Settings → System → About → select Android TV OS build seven times, then enable Network, Wireless, or USB debugging under Developer Options.",
            )
        )
        group.add(
            action_row(
                "2. Keep networking alive in standby",
                "Enable Quick Start, Quick Resume, Fast TV Start, or Network Standby when available. Avoid an aggressive Eco mode that fully disables networking.",
            )
        )
        group.add(
            action_row(
                "3. Put both devices on the same trusted LAN",
                "A stable TV IP/DHCP reservation is recommended. Never expose ADB to the internet.",
            )
        )
        docs = action_row("Need detailed steps?", "Open the README setup guide before continuing.")
        docs.add_suffix(Gtk.LinkButton(uri=README_URL, label="Read Setup Guide"))
        group.add(docs)
        self.content.append(group)
        try:
            self.config.tv.adb_path = find_adb(self.config.tv.adb_path)
            adb = action_row("ADB ready", self.config.tv.adb_path)
            group.add(adb)
            self.footer(self.render_provider, self.render_connection)
        except ADBNotInstalled:
            missing = action_row("ADB is required", "Install Android platform tools, then return to this page.")
            install_help = Gtk.Button(label="Show Install Help")
            install_help.connect("clicked", lambda *_: show_message(self.window, "Install Android platform tools", installation_help()))
            missing.add_suffix(install_help)
            group.add(missing)
            self.footer(self.render_provider, None)

    def render_connection(self) -> None:
        self.clear()
        self.content.append(
            heading(
                "Find your TV",
                "HTPC Control Center checks ADB's known devices and local mDNS advertisements first. Manual IP entry is always available.",
            )
        )
        self.discovery_group = Adw.PreferencesGroup()
        self.discovery_group.set_title("Discovered TVs")
        self.discovery_status_row = action_row("Scanning…", "Looking for Android/Google TV ADB endpoints on the local network.")
        self.discovery_group.add(self.discovery_status_row)
        self.content.append(self.discovery_group)

        manual_group = Adw.PreferencesGroup()
        manual_group.set_title("Manual address")
        row = action_row("TV IP address", "Use the connection port shown by Wireless debugging when it is not 5555.")
        self.manual_entry = Gtk.Entry()
        self.manual_entry.set_placeholder_text("10.0.0.42 or 10.0.0.42:5555")
        self.manual_entry.set_text(self.config.tv.serial or self.config.tv.host)
        self.manual_entry.set_width_chars(24)
        row.add_suffix(self.manual_entry)
        use_manual = Gtk.Button(label="Use Address")
        use_manual.connect("clicked", self._use_manual_address)
        row.add_suffix(use_manual)
        manual_group.add(row)
        self.content.append(manual_group)
        self.footer(self.render_prereqs, None)

        run_background(
            lambda: discover_adb_targets(self.config.tv.adb_path),
            self._show_discovered_targets,
            lambda exc: self._show_discovery_error(exc),
        )

    def _show_discovered_targets(self, targets) -> None:
        if not targets:
            self.discovery_status_row.set_title("No TVs discovered automatically")
            self.discovery_status_row.set_subtitle("That's okay — enter the TV IP address below.")
            return
        self.discovery_status_row.set_title(f"Found {len(targets)} ADB endpoint(s)")
        self.discovery_status_row.set_subtitle("Choose the TV you want to configure, or use the manual address field below.")
        for target in targets:
            row = action_row(target.label, f"Found through {target.source}")
            use = Gtk.Button(label="Use This TV")
            use.connect("clicked", lambda _button, address=target.address: self._select_address(address))
            row.add_suffix(use)
            self.discovery_group.add(row)

    def _show_discovery_error(self, exc: BaseException) -> None:
        self.discovery_status_row.set_title("Automatic discovery unavailable")
        self.discovery_status_row.set_subtitle(str(exc))

    def _use_manual_address(self, _button: Gtk.Button) -> None:
        self._select_address(self.manual_entry.get_text())

    def _select_address(self, address: str) -> None:
        try:
            set_tv_endpoint(self.config, address)
        except TVControlError as exc:
            show_message(self.window, "Invalid TV address", str(exc))
            return
        self.render_authorization()

    def render_authorization(self) -> None:
        self.clear()
        self.content.append(
            heading(
                "Authorize this PC",
                f"Connecting to {self.config.tv.serial}. Watch the TV for an ADB authorization prompt and choose “Always allow from this computer.”",
            )
        )
        auth = Adw.PreferencesGroup()
        auth.set_title("Connection")
        auth.add(
            action_row(
                "Normal network debugging",
                "For most TVs, just click Connect & Authorize. HTPC Control Center will wait up to one minute for the TV prompt.",
            )
        )
        self.connect_button = Gtk.Button(label="Connect & Authorize")
        self.connect_button.add_css_class("suggested-action")
        self.connect_button.connect("clicked", self._authorize)
        connect_row = action_row("Authorize ADB", "The TV should display a confirmation prompt on first connection.")
        connect_row.add_suffix(self.connect_button)
        auth.add(connect_row)
        self.content.append(auth)

        pairing = Adw.PreferencesGroup()
        pairing.set_title("Pairing code — only if your TV requires it")
        pair_row = action_row("Pairing address", "Use the separate address and port shown under “Pair device with pairing code.”")
        self.pair_address = Gtk.Entry()
        self.pair_address.set_placeholder_text("10.0.0.42:37123")
        pair_row.add_suffix(self.pair_address)
        pairing.add(pair_row)
        code_row = action_row("Six-digit pairing code")
        self.pair_code = Gtk.Entry()
        self.pair_code.set_placeholder_text("123456")
        self.pair_code.set_max_length(6)
        self.pair_code.set_input_purpose(Gtk.InputPurpose.DIGITS)
        code_row.add_suffix(self.pair_code)
        pair = Gtk.Button(label="Pair")
        pair.connect("clicked", self._pair)
        code_row.add_suffix(pair)
        pairing.add(code_row)
        self.content.append(pairing)
        self.footer(self.render_connection, None)

    def _pair(self, button: Gtk.Button) -> None:
        address = self.pair_address.get_text().strip()
        code = self.pair_code.get_text().strip()
        if not address or not code:
            show_message(self.window, "Pairing information required", "Enter the pairing address and six-digit code shown by the TV.")
            return
        button.set_sensitive(False)
        run_background(
            lambda: asyncio.run(ADBController(self.config).pair(address, code)),
            lambda _result: (button.set_sensitive(True), show_message(self.window, "Pairing complete", "The PC paired successfully. Now click Connect & Authorize.")),
            lambda exc: (button.set_sensitive(True), show_message(self.window, "Wireless pairing failed", str(exc))),
        )

    def _authorize(self, _button: Gtk.Button) -> None:
        self.connect_button.set_sensitive(False)
        self.connect_button.set_label("Waiting for TV…")

        def work():
            return asyncio.run(authorize_controller(ADBController(self.config)))

        def success(model: str) -> None:
            self.config.tv.model = model
            self.render_identity()

        def error(exc: BaseException) -> None:
            self.connect_button.set_sensitive(True)
            self.connect_button.set_label("Connect & Authorize")
            show_message(self.window, "TV authorization failed", str(exc))

        run_background(work, success, error)

    def render_identity(self) -> None:
        self.clear()
        self.content.append(heading("TV connected", "ADB authorization succeeded. Give the TV a friendly name."))
        group = Adw.PreferencesGroup()
        group.set_title("Connected TV")
        group.add(action_row("Model", self.config.tv.model or "Model name unavailable"))
        group.add(action_row("ADB address", self.config.tv.serial))
        name_row = action_row("Friendly name")
        self.name_entry = Gtk.Entry()
        self.name_entry.set_text(self.config.tv.name or self.config.tv.model or "Living Room TV")
        name_row.add_suffix(self.name_entry)
        group.add(name_row)
        self.content.append(group)

        def next_step() -> None:
            self.config.tv.name = self.name_entry.get_text().strip() or self.config.tv.model or "Android TV"
            self.render_power_test()

        self.footer(self.render_authorization, next_step)

    def render_power_test(self) -> None:
        self.clear()
        self.content.append(
            heading(
                "Test TV power",
                "Keep the physical remote nearby. These tests are optional and a failed test does not discard the ADB setup.",
            )
        )
        group = Adw.PreferencesGroup()
        group.set_title("Power control")
        sleep_row = action_row("Sleep TV", "Sends Android KEYCODE_SLEEP.")
        sleep_btn = Gtk.Button(label="Test Sleep")
        sleep_row.add_suffix(sleep_btn)
        group.add(sleep_row)
        wake_row = action_row("Wake TV", "Sends Android KEYCODE_WAKEUP with retry and verification logic.")
        wake_btn = Gtk.Button(label="Test Wake")
        wake_row.add_suffix(wake_btn)
        group.add(wake_row)
        self.content.append(group)

        def run_power(target_on: bool, button: Gtk.Button) -> None:
            button.set_sensitive(False)
            run_background(
                lambda: asyncio.run(ADBController(self.config).set_power(target_on)),
                lambda result: (button.set_sensitive(True), show_message(self.window, "Power test complete", result.message)),
                lambda exc: (button.set_sensitive(True), show_message(self.window, "Power test failed", str(exc))),
            )

        sleep_btn.connect("clicked", lambda *_: run_power(False, sleep_btn))
        wake_btn.connect("clicked", lambda *_: run_power(True, wake_btn))
        self.footer(self.render_identity, self.render_inputs, "Continue to Input Setup")

    def render_inputs(self) -> None:
        self.clear()
        self.content.append(
            heading(
                "Choose the PC's TV input",
                "Android's TV Input Framework exposes vendor-specific physical inputs. Test candidates instead of assuming an HW number maps to a particular HDMI port.",
            )
        )
        self.input_group = Adw.PreferencesGroup()
        self.input_group.set_title("Physical passthrough inputs")
        self.input_status_row = action_row("Discovering inputs…", "Keep the TV on while this runs.")
        self.input_group.add(self.input_status_row)
        self.content.append(self.input_group)
        skip = Gtk.Button(label="Skip Input Switching")
        skip.connect("clicked", lambda *_: self._skip_input())
        self.content.append(button_row(skip))
        self.footer(self.render_power_test, None)
        run_background(
            lambda: asyncio.run(ADBController(self.config).discover_inputs()),
            self._show_inputs,
            lambda exc: self._show_input_error(exc),
        )

    def _show_inputs(self, inputs: list[TVInput]) -> None:
        self.inputs = inputs
        if not inputs:
            self.input_status_row.set_title("No physical inputs found")
            self.input_status_row.set_subtitle("Power automation can still be configured.")
            return
        self.input_status_row.set_title(f"Found {len(inputs)} physical input(s)")
        self.input_status_row.set_subtitle("Test candidates until the gaming PC appears, then choose Use This Input.")
        for candidate in inputs:
            row = action_row(candidate.display_name, candidate.input_id)
            test = Gtk.Button(label="Test")
            use = Gtk.Button(label="Use This Input")
            use.add_css_class("suggested-action")
            test.connect("clicked", lambda _b, item=candidate: self._test_input(item))
            use.connect("clicked", lambda _b, item=candidate: self._use_input(item))
            row.add_suffix(test)
            row.add_suffix(use)
            self.input_group.add(row)

    def _show_input_error(self, exc: BaseException) -> None:
        self.input_status_row.set_title("Input discovery failed")
        self.input_status_row.set_subtitle(str(exc))

    def _test_input(self, candidate: TVInput) -> None:
        run_background(
            lambda: asyncio.run(ADBController(self.config).select_input(candidate.uri)),
            lambda _result: show_message(self.window, "Input launched", f"If the gaming PC input is now visible, choose Use This Input for {candidate.hardware_id}."),
            lambda exc: show_message(self.window, "Input test failed", str(exc)),
        )

    def _use_input(self, candidate: TVInput) -> None:
        self.config.tv.input_id = candidate.input_id
        self.config.tv.input_uri = candidate.uri
        self.config.tv.input_label = candidate.hardware_id
        self.config.behavior.switch_input_after_wake = True
        self.render_behavior()

    def _skip_input(self) -> None:
        self.config.behavior.switch_input_after_wake = False
        self.render_behavior()

    def render_behavior(self) -> None:
        self.clear()
        self.content.append(heading("Choose automatic TV behavior", "These are the same lifecycle behaviors from ATV-Couch-Wake, now configured graphically."))
        group = Adw.PreferencesGroup()
        group.set_title("Automation")
        self.switches: dict[str, Gtk.Switch] = {}
        options = [
            ("on_startup", "Wake on session start", "Wake the TV when the user's systemd session starts."),
            ("on_resume", "Wake after resume", "Wake the TV after the PC resumes from suspend."),
            ("off_on_suspend", "Sleep before suspend", "Put the TV to sleep before the PC enters suspend."),
            ("off_on_shutdown", "Sleep before shutdown", "Put the TV to sleep before the PC powers off."),
            ("off_on_reboot", "Sleep on reboot", "Usually leave this off so a reboot does not unnecessarily blank the TV."),
        ]
        for attr, title, subtitle in options:
            row = action_row(title, subtitle)
            switch = Gtk.Switch()
            switch.set_active(bool(getattr(self.config.behavior, attr)))
            switch.set_valign(Gtk.Align.CENTER)
            row.add_suffix(switch)
            row.set_activatable_widget(switch)
            group.add(row)
            self.switches[attr] = switch
        if self.config.tv.input_uri:
            row = action_row("Select PC input after wake", f"Saved input: {self.config.tv.input_label or self.config.tv.input_id}")
            switch = Gtk.Switch()
            switch.set_active(self.config.behavior.switch_input_after_wake)
            switch.set_valign(Gtk.Align.CENTER)
            row.add_suffix(switch)
            row.set_activatable_widget(switch)
            group.add(row)
            self.switches["switch_input_after_wake"] = switch
        self.content.append(group)
        self.footer(self.render_inputs, self.finish_setup, "Finish TV Setup")

    def finish_setup(self) -> None:
        for attr, switch in self.switches.items():
            setattr(self.config.behavior, attr, switch.get_active())
        self.clear()
        self.content.append(heading("Saving TV setup…", "The lifecycle watcher runs as your user. No administrator access is required for TV control."))
        spinner = Gtk.Spinner()
        spinner.set_spinning(True)
        spinner.set_halign(Gtk.Align.CENTER)
        self.content.append(spinner)

        def work():
            save_config(self.config)
            return install_user_service()

        def success(unit) -> None:
            self.clear()
            self.content.append(heading("TV setup complete", f"{self.config.tv.name} is configured and the lifecycle watcher is running."))
            group = Adw.PreferencesGroup()
            group.add(action_row("TV", f"{self.config.tv.model or 'Android / Google TV'} • {self.config.tv.serial}"))
            group.add(action_row("Input", self.config.tv.input_label if self.config.behavior.switch_input_after_wake and self.config.tv.input_uri else "Automatic input switching disabled"))
            group.add(action_row("Lifecycle watcher", str(unit)))
            self.content.append(group)
            self.footer(None, self.on_done, "Return to Control Center")

        def error(exc: BaseException) -> None:
            self.clear()
            self.content.append(heading("TV settings saved, but automation could not start", str(exc)))
            self.footer(self.render_behavior, self.on_done, "Return to Control Center")

        run_background(work, success, error)
