"""Preferences and update controls."""
from __future__ import annotations

from collections.abc import Callable

from gi.repository import Adw, Gtk

from .. import __version__
from .. import updates
from .common import (
    action_row,
    emphasized_link_button,
    heading,
    page_shell,
    primary_button,
    run_background,
    secondary_button,
    show_message,
)

RELEASES_URL = "https://github.com/andy10115/HTPC-Control-Center/releases"


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
        page, content, _header, self.back_button = page_shell("Preferences", lambda *_: self.on_back(), maximum_size=920)
        self.append(page)
        content.append(heading("Preferences", "Updates and application information.", level=1))

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
