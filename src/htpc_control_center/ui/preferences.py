"""Preferences and update controls."""
from __future__ import annotations

from collections.abc import Callable

from gi.repository import Adw, Gtk

from .. import __version__
from .. import updates
from ..config import load_config
from ..controller import manager
from ..tv.systemd import service_status
from .common import (
    action_row,
    emphasized_link_button,
    heading,
    page_shell,
    primary_button,
    run_background,
    secondary_button,
    show_message,
    status_label,
)

RELEASES_URL = "https://github.com/andy10115/HTPC-Control-Center/releases"
README_URL = "https://github.com/andy10115/HTPC-Control-Center#readme"


class PreferencesView(Gtk.Box):
    def __init__(
        self,
        window: Gtk.Window,
        on_back: Callable[[], None],
        on_update_installed: Callable[[], None],
    ) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.window = window
        self.on_back = on_back
        self.on_update_installed = on_update_installed
        self._build()

    def _build(self) -> None:
        page, content, _header = page_shell("Preferences", lambda *_: self.on_back(), maximum_size=1220)
        self.append(page)
        content.append(heading("Preferences", "Updates and current configuration at a glance.", level=1))

        preferences = updates.load_preferences()
        updates_group = Adw.PreferencesGroup()
        updates_group.set_title("Updates")
        updates_group.add(action_row("Installed version", __version__))

        automatic = Adw.SwitchRow()
        automatic.set_title("Automatically check for updates")
        automatic.set_subtitle("Check stable GitHub Releases at most once every 24 hours. Updates are never installed silently.")
        automatic.set_active(preferences.automatically_check)

        def changed(row: Adw.SwitchRow, _param) -> None:
            updates.save_preferences(updates.UpdatePreferences(automatically_check=row.get_active()))

        automatic.connect("notify::active", changed)
        updates_group.add(automatic)

        self.status_row = action_row("Release status", self._status_text(updates.cached_available_update()))
        self.check_button = secondary_button("Check Now")
        self.check_button.connect("clicked", self._check_now)
        self.status_row.add_suffix(self.check_button)
        updates_group.add(self.status_row)

        self.update_row = action_row("Available update", "")
        self.update_button = primary_button("Install Update")
        self.update_button.connect("clicked", self._install_update)
        self.update_row.add_suffix(self.update_button)
        updates_group.add(self.update_row)
        self._refresh_update_row(updates.cached_available_update())

        releases = action_row("GitHub Releases", "Stable releases are the only update channel used by the app.")
        releases.add_suffix(emphasized_link_button("Open Releases", RELEASES_URL))
        updates_group.add(releases)
        content.append(updates_group)

        columns = Gtk.Grid()
        columns.set_column_homogeneous(True)
        columns.set_column_spacing(28)
        columns.set_hexpand(True)

        left = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
        right = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
        left.set_hexpand(True)
        right.set_hexpand(True)
        columns.attach(left, 0, 0, 1, 1)
        columns.attach(right, 1, 0, 1, 1)

        config = load_config(required=False)
        left.append(heading("TV", "Current TV automation state.", level=2))
        tv_group = Adw.PreferencesGroup()
        if config.tv_configured:
            svc = service_status()
            name = config.tv.name or config.tv.model or "Android / Google TV"
            row = action_row("Configured TV", name)
            row.add_suffix(status_label("Watcher running" if svc.active else "Watcher stopped", "success" if svc.active else "warning"))
            tv_group.add(row)
            enabled = []
            if config.behavior.on_startup:
                enabled.append("wake on start")
            if config.behavior.on_resume:
                enabled.append("wake on resume")
            if config.behavior.off_on_suspend:
                enabled.append("sleep on suspend")
            if config.behavior.off_on_shutdown:
                enabled.append("sleep on shutdown")
            if config.behavior.off_on_reboot:
                enabled.append("sleep on reboot")
            if config.behavior.switch_input_after_wake and config.tv.input_uri:
                enabled.append("select input")
            tv_group.add(action_row("Enabled actions", ", ".join(enabled) if enabled else "No lifecycle actions enabled."))
        else:
            tv_group.add(action_row("Not configured", "Android / Google TV is the supported v1 backend."))
        docs = action_row("TV setup guide", "Preparation and troubleshooting.")
        docs.add_suffix(emphasized_link_button("Open Guide", README_URL))
        tv_group.add(docs)
        left.append(tv_group)

        right.append(heading("Controller Wake", "Current USB wake state.", level=2))
        controller_group = Adw.PreferencesGroup()
        cstatus = manager.status()
        if cstatus.configured:
            devices = ", ".join(item.name for item in cstatus.devices) or "Configured USB wake path"
            row = action_row("Configured receivers", devices)
            row.add_suffix(status_label("Wake paths armed" if cstatus.all_targets_enabled else "Check wake paths", "success" if cstatus.all_targets_enabled else "warning"))
            controller_group.add(row)
            controller_group.add(action_row("Quiet window", "5 seconds immediately before suspend."))
        else:
            controller_group.add(action_row("Not configured", "No USB controller wake paths are configured."))
        controller_group.add(action_row("Hardware requirement", "Motherboard firmware must allow USB wake from suspend."))
        right.append(controller_group)

        content.append(columns)

        about_group = Adw.PreferencesGroup()
        about_group.set_title("About")
        about_group.add(action_row("HTPC Control Center", "GTK4/libadwaita TV automation and controller wake for Linux HTPCs."))
        content.append(about_group)

    @staticmethod
    def _status_text(info: updates.UpdateInfo | None) -> str:
        if info:
            return f"Version {info.version} is available."
        return "No newer cached release is known."

    def _refresh_update_row(self, info: updates.UpdateInfo | None) -> None:
        self.available_update = info
        self.update_row.set_visible(info is not None)
        if info:
            self.update_row.set_subtitle(f"Version {info.version} ({info.tag_name})")

    def _check_now(self, *_args) -> None:
        self.check_button.set_sensitive(False)
        self.status_row.set_subtitle("Checking GitHub Releases…")

        def ok(info: updates.UpdateInfo | None) -> None:
            self.check_button.set_sensitive(True)
            self._refresh_update_row(info)
            if info:
                self.status_row.set_subtitle(f"Version {info.version} is available.")
            else:
                self.status_row.set_subtitle(f"Version {__version__} is the latest stable release.")

        def error(exc: BaseException) -> None:
            self.check_button.set_sensitive(True)
            self.status_row.set_subtitle("Update check failed.")
            show_message(self.window, "Could not check for updates", str(exc))

        run_background(lambda: updates.check_for_updates(force=True), ok, error)

    def _install_update(self, *_args) -> None:
        info = self.available_update
        if info is None:
            return
        self.update_button.set_sensitive(False)
        self.update_button.set_label("Installing…")

        def ok(_output: str) -> None:
            self.update_button.set_label("Installed")
            self.on_update_installed()

        def error(exc: BaseException) -> None:
            self.update_button.set_sensitive(True)
            self.update_button.set_label("Install Update")
            show_message(self.window, "Update failed", str(exc))

        run_background(lambda: updates.install_update(info), ok, error)
