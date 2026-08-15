"""GTK smoke test for the dashboard navigation contract.

Run under a display server, e.g.:
  PYTHONPATH=src xvfb-run -a python3 tests/ui_smoke.py
"""
from __future__ import annotations

import os
import tempfile

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk

from htpc_control_center.window import MainWindow


def walk(widget: Gtk.Widget):
    yield widget
    child = widget.get_first_child()
    while child is not None:
        yield from walk(child)
        child = child.get_next_sibling()


def find_button(root: Gtk.Widget, label: str) -> Gtk.Button:
    for widget in walk(root):
        if isinstance(widget, Gtk.Button) and widget.get_label() == label:
            return widget
    raise AssertionError(f"Button not found: {label}")


def has_titled_widget(root: Gtk.Widget, title: str) -> bool:
    for widget in walk(root):
        getter = getattr(widget, "get_title", None)
        if getter is not None:
            try:
                if getter() == title:
                    return True
            except TypeError:
                pass
    return False


def main() -> None:
    with tempfile.TemporaryDirectory() as home:
        os.environ["HOME"] = home
        os.environ["XDG_CONFIG_HOME"] = os.path.join(home, ".config")
        os.environ["XDG_DATA_HOME"] = os.path.join(home, ".local", "share")
        os.environ["XDG_CACHE_HOME"] = os.path.join(home, ".cache")

        app = Adw.Application(application_id="io.github.andy10115.HTPCControlCenter.UISmoke")
        if not app.register(None):
            raise AssertionError("Could not register GTK application")
        window = MainWindow(app)

        assert window.current_view == "main"

        # Dashboard TV action must open the TV OS/provider selection page.
        find_button(window, "Set Up My TV").emit("clicked")
        assert window.current_view == "tv-setup"
        find_button(window, "Set Up Android / Google TV")

        # Dashboard controller action must open the graphical controller flow.
        window.show_main()
        find_button(window, "Set Up Controller Wake").emit("clicked")
        assert window.current_view == "controller-setup"
        find_button(window, "Scan USB Devices")

        # Preferences must be a working destination and expose the update toggle.
        window.show_main()
        find_button(window, "Preferences").emit("clicked")
        assert window.current_view == "preferences"
        assert has_titled_widget(window, "Automatically check for updates")

        window.close()


if __name__ == "__main__":
    main()
