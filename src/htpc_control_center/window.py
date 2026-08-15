"""Main application window and page routing."""
from __future__ import annotations

import logging
import subprocess
from pathlib import Path

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk  # noqa: E402

from . import updates
from .ui.common import run_background, show_message
from .ui.controller_setup import ControllerSetupView
from .ui.main_page import build_main_page
from .ui.preferences import PreferencesView
from .ui.tv_setup import TVSetupView

LOGGER = logging.getLogger(__name__)


class MainWindow(Adw.ApplicationWindow):
    """Single-window router.

    Pages replace the current window content directly. This intentionally avoids
    hidden/stacked navigation state: every dashboard action constructs and shows
    its destination immediately, and each sub-page owns an explicit Back action.
    """

    def __init__(self, application: Adw.Application) -> None:
        super().__init__(application=application)
        self.set_title("HTPC Control Center")
        self.set_default_size(1220, 840)
        self.set_size_request(820, 620)
        self.available_update = updates.cached_available_update()
        self._update_check_started = False
        self._update_installing = False
        self.current_view = ""
        self.show_main()

    def _show(self, name: str, widget: Gtk.Widget) -> None:
        self.current_view = name
        self.set_content(widget)

    def _show_navigation_error(self, destination: str, exc: BaseException) -> None:
        LOGGER.exception("Could not open %s", destination, exc_info=exc)
        show_message(
            self,
            f"Could not open {destination}",
            f"HTPC Control Center could not build that page.\n\n{exc}",
        )

    def show_main(self) -> None:
        self.available_update = updates.cached_available_update()
        try:
            page = build_main_page(
                self,
                on_tv_setup=self.show_tv_setup,
                on_controller_setup=self.show_controller_setup,
                on_refresh=self.show_main,
                on_preferences=self.show_preferences,
                update_info=self.available_update,
                on_update=self.install_update,
            )
        except Exception as exc:
            self._show_navigation_error("Control Center", exc)
            return
        self._show("main", page)

    def show_tv_setup(self) -> None:
        try:
            page = TVSetupView(self, self.show_main)
        except Exception as exc:
            self._show_navigation_error("TV Setup", exc)
            return
        self._show("tv-setup", page)

    def show_controller_setup(self) -> None:
        try:
            page = ControllerSetupView(self, self.show_main)
        except Exception as exc:
            self._show_navigation_error("Controller Wake Setup", exc)
            return
        self._show("controller-setup", page)

    def show_preferences(self) -> None:
        try:
            page = PreferencesView(self, self.show_main, self.restart_after_update)
        except Exception as exc:
            self._show_navigation_error("Preferences", exc)
            return
        self._show("preferences", page)

    def start_update_check(self) -> None:
        if self._update_check_started:
            return
        self._update_check_started = True
        if not updates.check_due():
            return

        def checked(info: updates.UpdateInfo | None) -> None:
            self.available_update = info
            if info is not None and self.current_view == "main":
                self.show_main()

        # Automatic checks intentionally fail silently. A network outage should
        # never turn application launch into an error dialog.
        run_background(lambda: updates.check_for_updates(force=False), checked, lambda _exc: None)

    def install_update(self, info: updates.UpdateInfo) -> None:
        if self._update_installing:
            return
        self._update_installing = True

        def installed(_output: str) -> None:
            self._update_installing = False
            self.restart_after_update()

        def failed(exc: BaseException) -> None:
            self._update_installing = False
            show_message(self, "Update failed", str(exc))

        run_background(lambda: updates.install_update(info), installed, failed)

    def restart_after_update(self) -> None:
        launcher = Path.home() / ".local/bin/htpc-control-center"
        if not launcher.exists():
            show_message(self, "Update installed", "Restart HTPC Control Center to load the new version.")
            return
        try:
            subprocess.Popen(
                ["bash", "-c", 'sleep 1; exec "$1"', "htpc-control-center-relaunch", str(launcher)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
        except OSError as exc:
            show_message(self, "Update installed", f"Restart HTPC Control Center manually to load it.\n\n{exc}")
            return
        application = self.get_application()
        if application is not None:
            application.quit()
