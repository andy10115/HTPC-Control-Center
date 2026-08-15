"""GTK smoke test for visible dashboard navigation destinations.

Run under a display server, e.g.:
  PYTHONPATH=src xvfb-run -a python3 tests/ui_smoke.py

This test intentionally checks more than widget existence. A previous regression
created the correct destination widgets but left the shared ToolbarView at its
natural height, clipping every control below the page heading.
"""
from __future__ import annotations

import os
import tempfile
import time

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, GLib, Gtk

from htpc_control_center.window import MainWindow


def drain_events(duration: float = 0.15) -> None:
    deadline = time.monotonic() + duration
    context = GLib.MainContext.default()
    while time.monotonic() < deadline:
        while context.pending():
            context.iteration(False)
        time.sleep(0.005)


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


def assert_page_control_visible(widget: Gtk.Widget, label: str) -> None:
    """Verify a destination control received layout and is inside its scroller."""
    drain_events()
    if widget.get_allocated_width() <= 0 or widget.get_allocated_height() <= 0:
        raise AssertionError(f"{label} exists but has no GTK allocation")
    if not widget.get_mapped():
        raise AssertionError(f"{label} exists but is not mapped")

    ancestor = widget.get_parent()
    scroller = None
    while ancestor is not None:
        if isinstance(ancestor, Gtk.ScrolledWindow):
            scroller = ancestor
            break
        ancestor = ancestor.get_parent()
    if scroller is None:
        raise AssertionError(f"{label} is not inside the page scroller")
    if scroller.get_allocated_height() < 300:
        raise AssertionError(
            f"{label} page scroller is clipped to {scroller.get_allocated_height()}px; "
            "the sub-page shell is not expanding"
        )


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
        window.present()
        drain_events(0.3)

        assert window.current_view == "main"

        # Dashboard TV action must show the actual TV-provider selection UI.
        find_button(window, "Set Up My TV").emit("clicked")
        drain_events()
        assert window.current_view == "tv-setup"
        tv_button = find_button(window, "Set Up Android / Google TV")
        assert_page_control_visible(tv_button, "Set Up Android / Google TV")

        # Android provider action must continue into the graphical setup flow.
        tv_button.emit("clicked")
        drain_events()
        assert has_titled_widget(window, "Quick prerequisites")

        # Dashboard controller action must show the real controller flow.
        window.show_main()
        drain_events()
        find_button(window, "Set Up Controller Wake").emit("clicked")
        drain_events()
        assert window.current_view == "controller-setup"
        scan_button = find_button(window, "Scan USB Devices")
        assert_page_control_visible(scan_button, "Scan USB Devices")

        # Preferences must show actual settings, not just the heading.
        window.show_main()
        drain_events()
        find_button(window, "Preferences").emit("clicked")
        drain_events()
        assert window.current_view == "preferences"
        assert has_titled_widget(window, "Automatically check for updates")
        check_button = find_button(window, "Check Now")
        assert_page_control_visible(check_button, "Check Now")

        window.close()


if __name__ == "__main__":
    main()
