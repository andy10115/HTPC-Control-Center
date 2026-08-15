"""Main dashboard."""
from __future__ import annotations

import asyncio
from collections.abc import Callable

from gi.repository import Adw, Gtk

from ..config import load_config, remove_config
from ..controller import manager as controller_manager
from ..legacy import detect_legacy_projects
from ..updates import UpdateInfo
from ..tv.providers import create_controller
from ..tv.systemd import remove_user_service, service_status
from .common import (
    action_row,
    confirm,
    emphasized_link_button,
    heading,
    page_shell,
    primary_button,
    run_background,
    secondary_button,
    show_message,
    status_label,
)

README_URL = "https://github.com/andy10115/HTPC-Control-Center#readme"


def _button_grid(*buttons: Gtk.Button) -> Gtk.Grid:
    grid = Gtk.Grid()
    grid.set_column_homogeneous(True)
    grid.set_column_spacing(10)
    grid.set_row_spacing(10)
    grid.set_hexpand(True)
    for index, button in enumerate(buttons):
        button.set_hexpand(True)
        button.set_halign(Gtk.Align.FILL)
        grid.attach(button, index % 2, index // 2, 1, 1)
    return grid


def build_main_page(
    window: Gtk.Window,
    *,
    on_tv_setup: Callable[[], None],
    on_controller_setup: Callable[[], None],
    on_refresh: Callable[[], None],
    on_preferences: Callable[[], None],
    update_info: UpdateInfo | None = None,
    on_update: Callable[[UpdateInfo], None] | None = None,
) -> Gtk.Widget:
    page, content, header = page_shell("HTPC Control Center", maximum_size=1220)

    preferences = secondary_button("Preferences")
    preferences.set_tooltip_text("Preferences and update settings")

    def open_preferences(_button: Gtk.Button) -> None:
        on_preferences()

    preferences.connect("clicked", open_preferences)
    header.pack_end(preferences)

    if update_info is not None and on_update is not None:
        banner = Adw.Banner.new(f"HTPC Control Center {update_info.version} is available.")
        banner.set_button_label("Update")
        banner.set_revealed(True)
        banner.connect("button-clicked", lambda *_: on_update(update_info))
        content.append(banner)

    content.append(
        heading(
            "HTPC Control Center",
            "Set up console-like TV behavior and controller wake from one couch-friendly interface.",
            level=1,
        )
    )

    tips = Adw.PreferencesGroup()
    tips.set_title("Before you start")
    legacy = detect_legacy_projects()
    legacy_text = (
        f"Detected: {', '.join(legacy)}. Uninstall it before configuring the same feature here."
        if legacy
        else "Uninstall ATV-Couch-Wake or HTPC-Controller-Wake first if either proof-of-concept is still installed."
    )
    tips.add(action_row("Previous versions", legacy_text))
    tips.add(action_row("TV", "PC and TV should be on the same LAN. Android / Google TV needs Developer Options and network debugging."))
    tips.add(action_row("Controller", "Use a USB receiver/dongle and make sure the motherboard allows USB wake from suspend."))
    readme_row = action_row("Setup guide", "Detailed preparation and troubleshooting are in the README.")
    readme_row.add_suffix(emphasized_link_button("Read README", README_URL))
    tips.add(readme_row)
    content.append(tips)

    grid = Gtk.Grid()
    grid.set_column_homogeneous(True)
    grid.set_column_spacing(28)
    grid.set_row_spacing(0)
    grid.set_hexpand(True)

    tv_column = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
    tv_column.set_hexpand(True)
    controller_column = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
    controller_column.set_hexpand(True)
    grid.attach(tv_column, 0, 0, 1, 1)
    grid.attach(controller_column, 1, 0, 1, 1)

    config = load_config(required=False)

    # TV column
    tv_column.append(heading("TV Control", "Wake, sleep, and switch inputs automatically.", level=2))
    tv_group = Adw.PreferencesGroup()
    if config.tv_configured:
        svc = service_status()
        detail = config.tv.name or config.tv.model or "Android / Google TV"
        if config.tv.input_label:
            detail += f" • {config.tv.input_label}"
        row = action_row("Configured", detail)
        row.add_suffix(status_label("Running" if svc.active else "Service stopped", "success" if svc.active else "warning"))
        tv_group.add(row)
        tv_column.append(tv_group)

        wake = secondary_button("Wake TV")
        sleep = secondary_button("Sleep TV")
        select_input = secondary_button("Select Input")
        settings = secondary_button("TV Settings")
        remove = secondary_button("Remove TV")
        remove.add_css_class("destructive-action")
        select_input.set_sensitive(bool(config.tv.input_uri))

        def tv_work(coro_factory, success_heading: str) -> None:
            for button in (wake, sleep, select_input):
                button.set_sensitive(False)

            def work():
                return asyncio.run(coro_factory())

            def ok(result) -> None:
                for button in (wake, sleep, select_input):
                    button.set_sensitive(True)
                message = getattr(result, "message", None) or str(result or "Command completed.")
                show_message(window, success_heading, message)

            def err(exc: BaseException) -> None:
                for button in (wake, sleep, select_input):
                    button.set_sensitive(True)
                show_message(window, "TV command failed", str(exc))

            run_background(work, ok, err)

        wake.connect("clicked", lambda *_: tv_work(lambda: create_controller(config).wake_and_select_input(), "TV wake sent"))
        sleep.connect("clicked", lambda *_: tv_work(lambda: create_controller(config).set_power(False), "TV sleep sent"))
        select_input.connect("clicked", lambda *_: tv_work(lambda: create_controller(config).select_input(), "Input command sent"))
        settings.connect("clicked", lambda *_: on_tv_setup())

        def do_remove_tv() -> None:
            try:
                remove_user_service()
                remove_config()
            except Exception as exc:
                show_message(window, "Could not remove TV setup", str(exc))
                return
            on_refresh()

        remove.connect(
            "clicked",
            lambda *_: confirm(
                window,
                "Remove TV setup?",
                "This disables the TV lifecycle watcher and removes the saved TV configuration. Controller wake is unaffected.",
                "Remove",
                do_remove_tv,
                destructive=True,
            ),
        )
        tv_column.append(_button_grid(wake, sleep, select_input, settings, remove))
    else:
        tv_group.add(action_row("Not configured", "Android / Google TV is supported in the initial release."))
        tv_column.append(tv_group)
        setup_tv = primary_button("Set Up My TV", fill=True)

        def open_tv_setup(_button: Gtk.Button) -> None:
            on_tv_setup()

        setup_tv.connect("clicked", open_tv_setup)
        tv_column.append(setup_tv)

    platforms = Adw.PreferencesGroup()
    platforms.set_title("TV platform support")
    platforms.add(action_row("Android TV / Google TV", "Supported through ADB."))
    platforms.add(action_row("Other TV operating systems", "Contributors needed for additional TV providers."))
    tv_column.append(platforms)

    # Controller column
    controller_column.append(heading("Controller Wake", "Wake the PC from suspend with a USB controller receiver.", level=2))
    controller_group = Adw.PreferencesGroup()
    cstatus = controller_manager.status()
    if cstatus.configured:
        device_names = ", ".join(item.name for item in cstatus.devices) or "Configured USB wake path"
        row = action_row("Configured", device_names)
        row.add_suffix(
            status_label(
                "Wake paths armed" if cstatus.all_targets_enabled else "Check wake paths",
                "success" if cstatus.all_targets_enabled else "warning",
            )
        )
        controller_group.add(row)
        controller_column.append(controller_group)

        test = secondary_button("Suspend Test")
        settings = secondary_button("Controller Settings")
        remove = secondary_button("Remove Controller Wake")
        remove.add_css_class("destructive-action")
        settings.connect("clicked", lambda *_: on_controller_setup())

        def do_suspend() -> None:
            run_background(
                controller_manager.suspend_test,
                lambda _result: None,
                lambda exc: show_message(window, "Suspend failed", str(exc)),
            )

        test.connect(
            "clicked",
            lambda *_: confirm(
                window,
                "Suspend and test controller wake?",
                "Turn the controller off first. After the PC is fully asleep, turn it back on. Keep another wake method available.",
                "Suspend",
                do_suspend,
            ),
        )

        def do_remove_controller() -> None:
            remove.set_sensitive(False)
            run_background(
                controller_manager.remove,
                lambda _result: on_refresh(),
                lambda exc: (remove.set_sensitive(True), show_message(window, "Could not remove controller wake", str(exc))),
            )

        remove.connect(
            "clicked",
            lambda *_: confirm(
                window,
                "Remove controller wake?",
                "This removes the udev wake rule and 5-second pre-suspend guard.",
                "Remove",
                do_remove_controller,
                destructive=True,
            ),
        )
        controller_column.append(_button_grid(test, settings, remove))
    else:
        controller_group.add(action_row("Not configured", "Select one or more USB controller receivers."))
        controller_column.append(controller_group)
        setup_controller = primary_button("Set Up Controller Wake", fill=True)

        def open_controller_setup(_button: Gtk.Button) -> None:
            on_controller_setup()

        setup_controller.connect("clicked", open_controller_setup)
        controller_column.append(setup_controller)

    controller_notes = Adw.PreferencesGroup()
    controller_notes.set_title("Controller wake notes")
    controller_notes.add(action_row("USB receiver required", "Bluetooth-only wake is not configured here."))
    controller_notes.add(action_row("5-second quiet window", "Prevents controller power-off chatter from immediately waking the PC again."))
    controller_column.append(controller_notes)

    content.append(grid)
    return page
