"""Main application window and page routing."""
from __future__ import annotations

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


class MainWindow(Adw.ApplicationWindow):
    def __init__(self, application: Adw.Application) -> None:
        super().__init__(application=application)
        self.set_title("HTPC Control Center")
        self.set_default_size(900, 760)
        self.set_size_request(650, 520)
        self.stack = Gtk.Stack()
        self.stack.set_transition_type(Gtk.StackTransitionType.SLIDE_LEFT_RIGHT)
        self.stack.set_transition_duration(180)
        self.set_content(self.stack)
        self.available_update = updates.cached_available_update()
        self._update_check_started = False
        self._update_installing = False
        self.show_main()

    def _replace(self, name: str, widget: Gtk.Widget) -> None:
        existing = self.stack.get_child_by_name(name)
        if existing is not None:
            self.stack.remove(existing)
        self.stack.add_named(widget, name)
        self.stack.set_visible_child_name(name)

    def show_main(self) -> None:
        self.available_update = updates.cached_available_update()
        page = build_main_page(
            self,
            on_tv_setup=self.show_tv_setup,
            on_controller_setup=self.show_controller_setup,
            on_refresh=self.show_main,
            on_preferences=self.show_preferences,
            update_info=self.available_update,
            on_update=self.install_update,
        )
        self._replace("main", page)

    def show_tv_setup(self) -> None:
        self._replace("tv-setup", TVSetupView(self, self.show_main))

    def show_controller_setup(self) -> None:
        self._replace("controller-setup", ControllerSetupView(self, self.show_main))

    def show_preferences(self) -> None:
        self._replace("preferences", PreferencesView(self, self.show_main, self.restart_after_update))

    def start_update_check(self) -> None:
        if self._update_check_started:
            return
        self._update_check_started = True
        if not updates.check_due():
            return

        def checked(info: updates.UpdateInfo | None) -> None:
            self.available_update = info
            if info is not None and self.stack.get_visible_child_name() == "main":
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
