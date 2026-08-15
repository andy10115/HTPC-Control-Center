"""Adwaita application object."""
from __future__ import annotations

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, Gio, Gtk  # noqa: E402

from .window import MainWindow

APP_ID = "io.github.andy10115.HTPCControlCenter"

APP_CSS = b"""
.hero-heading {
  font-size: 2.15rem;
  font-weight: 800;
}

.hero-subtitle {
  font-size: 1.05rem;
  opacity: 0.9;
}

.section-heading {
  font-size: 1.45rem;
  font-weight: 750;
}

.section-subtitle {
  font-size: 0.98rem;
  opacity: 0.88;
}

.couch-row {
  padding-top: 4px;
  padding-bottom: 4px;
}

.couch-button {
  min-height: 48px;
  min-width: 220px;
  padding-left: 14px;
  padding-right: 14px;
  font-weight: 650;
}

.button-row {
  margin-top: 6px;
}

.status-chip {
  font-weight: 650;
}

.status-chip.success {
  color: @success_color;
}

.status-chip.warning {
  color: @warning_color;
}
"""


class HTPCControlCenterApplication(Adw.Application):
    def __init__(self) -> None:
        super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.DEFAULT_FLAGS)
        self.window: MainWindow | None = None

    def do_startup(self) -> None:
        Adw.Application.do_startup(self)
        display = Gdk.Display.get_default()
        if display is not None:
            provider = Gtk.CssProvider()
            provider.load_from_data(APP_CSS)
            Gtk.StyleContext.add_provider_for_display(
                display,
                provider,
                Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
            )

    def do_activate(self) -> None:
        if self.window is None:
            self.window = MainWindow(self)
        self.window.present()
        self.window.start_update_check()
