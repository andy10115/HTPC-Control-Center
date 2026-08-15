"""Shared GTK helpers."""
from __future__ import annotations

import threading
from collections.abc import Callable
from typing import Any

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, GLib, Gtk  # noqa: E402


def run_background(
    work: Callable[[], Any],
    on_success: Callable[[Any], None],
    on_error: Callable[[BaseException], None],
) -> None:
    def runner() -> None:
        try:
            result = work()
        except BaseException as exc:  # UI boundary; surface any backend failure.
            def deliver_error() -> bool:
                on_error(exc)
                return GLib.SOURCE_REMOVE
            GLib.idle_add(deliver_error)
        else:
            def deliver_success() -> bool:
                on_success(result)
                return GLib.SOURCE_REMOVE
            GLib.idle_add(deliver_success)

    threading.Thread(target=runner, daemon=True).start()


def page_shell(
    title: str,
    on_back: Callable[..., None] | None = None,
    *,
    maximum_size: int = 1120,
) -> tuple[Gtk.Widget, Gtk.Box, Adw.HeaderBar]:
    toolbar = Adw.ToolbarView()
    header = Adw.HeaderBar()
    title_widget = Adw.WindowTitle()
    title_widget.set_title(title)
    header.set_title_widget(title_widget)
    if on_back is not None:
        back = Gtk.Button.new_from_icon_name("go-previous-symbolic")
        back.set_tooltip_text("Back")
        back.add_css_class("flat")
        back.connect("clicked", on_back)
        header.pack_start(back)
    toolbar.add_top_bar(header)

    scroller = Gtk.ScrolledWindow()
    scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
    clamp = Adw.Clamp()
    clamp.set_maximum_size(maximum_size)
    clamp.set_tightening_threshold(720)
    content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=24)
    content.set_margin_top(28)
    content.set_margin_bottom(40)
    content.set_margin_start(24)
    content.set_margin_end(24)
    clamp.set_child(content)
    scroller.set_child(clamp)
    toolbar.set_content(scroller)
    return toolbar, content, header


def heading(text: str, subtitle: str = "", *, level: int = 1) -> Gtk.Box:
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
    label = Gtk.Label(label=text, xalign=0)
    label.set_wrap(True)
    label.add_css_class("hero-heading" if level == 1 else "section-heading")
    box.append(label)
    if subtitle:
        sub = Gtk.Label(label=subtitle, xalign=0)
        sub.add_css_class("hero-subtitle" if level == 1 else "section-subtitle")
        sub.set_wrap(True)
        box.append(sub)
    return box


def action_row(title: str, subtitle: str = "") -> Adw.ActionRow:
    row = Adw.ActionRow()
    row.set_title(title)
    row.add_css_class("couch-row")
    if subtitle:
        row.set_subtitle(subtitle)
    return row


def status_label(text: str, css: str = "") -> Gtk.Label:
    label = Gtk.Label(label=text)
    label.add_css_class("status-chip")
    if css:
        label.add_css_class(css)
    return label


def button_row(*buttons: Gtk.Button) -> Gtk.Box:
    box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
    box.set_halign(Gtk.Align.END)
    box.add_css_class("button-row")
    for button in buttons:
        box.append(button)
    return box


def primary_button(label: str) -> Gtk.Button:
    button = Gtk.Button(label=label)
    button.add_css_class("suggested-action")
    button.add_css_class("couch-button")
    return button


def secondary_button(label: str) -> Gtk.Button:
    button = Gtk.Button(label=label)
    button.add_css_class("couch-button")
    return button


def emphasized_link_button(label: str, uri: str) -> Gtk.LinkButton:
    button = Gtk.LinkButton(uri=uri, label=label)
    button.add_css_class("couch-button")
    return button


def show_message(parent: Gtk.Window, heading_text: str, body: str, *, destructive: bool = False) -> None:
    dialog = Adw.MessageDialog.new(parent, heading_text, body)
    dialog.add_response("ok", "OK")
    if destructive:
        dialog.set_response_appearance("ok", Adw.ResponseAppearance.DESTRUCTIVE)
    dialog.present()


def confirm(
    parent: Gtk.Window,
    heading_text: str,
    body: str,
    confirm_label: str,
    callback: Callable[[], None],
    *,
    destructive: bool = False,
) -> None:
    dialog = Adw.MessageDialog.new(parent, heading_text, body)
    dialog.add_response("cancel", "Cancel")
    dialog.add_response("confirm", confirm_label)
    dialog.set_default_response("cancel")
    dialog.set_close_response("cancel")
    if destructive:
        dialog.set_response_appearance("confirm", Adw.ResponseAppearance.DESTRUCTIVE)

    def responded(_dialog: Adw.MessageDialog, response: str) -> None:
        if response == "confirm":
            callback()

    dialog.connect("response", responded)
    dialog.present()
