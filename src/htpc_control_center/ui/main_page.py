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
    preferences.connect("clicked", lambda *_: on_preferences())
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
            "Set up console-like TV behavior and controller wake without living in the terminal.",
            level=1,
        )
    )

    tips = Adw.PreferencesGroup()
    tips.set_title("Before you start")
    legacy = detect_legacy_projects()
    legacy_text = (
        f"Detected: {', '.join(legacy)}. Uninstall the old proof-of-concept before configuring "
        "the same feature here to avoid duplicate services or suspend delays."
        if legacy
        else "If ATV-Couch-Wake or HTPC-Controller-Wake is already installed, uninstall it before configuring this app."
    )
    tips.add(action_row("Previous proof-of-concepts", legacy_text))
    tips.add(
        action_row(
            "TV setup",
            "Put the PC and TV on the same network. Android/Google TV needs Developer Options plus network or wireless debugging.",
        )
    )
    tips.add(
        action_row(
            "Controller wake",
            "Use a USB receiver/dongle and make sure firmware allows USB wake from suspend. Bluetooth-only wake is not configured here.",
        )
    )
    readme_row = action_row("Setup guide", "The README has preparation steps, dependency notes, and troubleshooting.")
    readme_row.add_suffix(emphasized_link_button("Read README", README_URL))
    tips.add(readme_row)
    content.append(tips)

    columns = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=24)
    columns.set_homogeneous(True)
    columns.set_valign(Gtk.Align.START)

    tv_column = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18)
    controller_column = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18)
    columns.append(tv_column)
    columns.append(controller_column)

    config = load_config(required=False)

    tv_column.append(
        heading(
            "TV Control",
            "Configure Android TV / Google TV wake, sleep, input selection, and lifecycle automation.",
            level=2,
        )
    )
    tv_group = Adw.PreferencesGroup()
    if config.tv_configured:
        svc = service_status()
        detail = f"{config.tv.name or config.tv.model or 'Android / Google TV'} • {config.tv.serial}"
        if config.tv.input_label:
            detail += f" • input: {config.tv.input_label}"
        row = action_row("Configured", detail)
        row.add_suffix(status_label("Running" if svc.active else "Service stopped", "success" if svc.active else "warning"))
        tv_group.add(row)

        actions = action_row("Actions", "Test commands immediately or rerun setup to change the TV, input, or automation behavior.")
        wake = secondary_button("Wake")
        sleep = secondary_button("Sleep")
        select_input = secondary_button("Select Input")
        settings = secondary_button("Settings")
        remove = secondary_button("Remove")
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
                "This disables the per-user TV lifecycle watcher and removes the saved TV configuration. Controller wake is unaffected.",
                "Remove",
                do_remove_tv,
                destructive=True,
            ),
        )
        for button in (wake, sleep, select_input, settings, remove):
            actions.add_suffix(button)
        tv_group.add(actions)
    else:
        row = action_row("Not configured", "Android TV / Google TV is the supported TV backend in the initial release.")
        setup = primary_button("Set Up My TV")
        setup.connect("clicked", lambda *_: on_tv_setup())
        row.add_suffix(setup)
        tv_group.add(row)
    tv_column.append(tv_group)

    contribution = Adw.PreferencesGroup()
    contribution.set_title("TV platform support")
    contribution.add(
        action_row(
            "Android TV / Google TV",
            "Supported in v1 through ADB for wake, sleep, and direct physical-input selection.",
        )
    )
    contribution.add(
        action_row(
            "Other TV operating systems",
            "Contributors needed. New TV providers should remain independent from the controller-wake backend.",
        )
    )
    tv_column.append(contribution)

    controller_column.append(
        heading(
            "Controller Wake",
            "Trace one or more USB controller receivers and arm only the wake-capable USB path Linux actually needs.",
            level=2,
        )
    )
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
        actions = action_row(
            "Actions",
            "The suspend test will put this PC to sleep. Make sure another wake method is available before testing.",
        )
        test = secondary_button("Suspend Test")
        settings = secondary_button("Settings")
        remove = secondary_button("Remove")
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
                "Turn the controller off first. After the PC is fully asleep, turn it back on. Keep another wake method available in case this hardware cannot wake the system.",
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
                "This removes HTPC Control Center's udev rule and 5-second pre-suspend guard. It does not touch the older proof-of-concept projects.",
                "Remove",
                do_remove_controller,
                destructive=True,
            ),
        )
        for button in (test, settings, remove):
            actions.add_suffix(button)
        controller_group.add(actions)
    else:
        row = action_row(
            "Not configured",
            "Select one or more USB controller receivers and HTPC Control Center will trace their actual wake-capable USB path.",
        )
        setup = primary_button("Set Up Controller Wake")
        setup.connect("clicked", lambda *_: on_controller_setup())
        row.add_suffix(setup)
        controller_group.add(row)
    controller_column.append(controller_group)

    controller_info = Adw.PreferencesGroup()
    controller_info.set_title("Controller wake notes")
    controller_info.add(
        action_row(
            "USB receiver / dongle required",
            "Bluetooth-only controller wake is not configured here. Firmware and motherboard wake support still matter.",
        )
    )
    controller_info.add(
        action_row(
            "5-second quiet window",
            "Immediately before suspend, only the configured wake nodes are temporarily disarmed so controller power-off chatter cannot bounce the PC awake.",
        )
    )
    controller_column.append(controller_info)

    content.append(columns)
    return page
