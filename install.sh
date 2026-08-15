#!/usr/bin/env bash
set -euo pipefail

APP_NAME="HTPC Control Center"
PACKAGE_NAME="htpc-control-center"
APP_ID="io.github.andy10115.HTPCControlCenter"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON="${PYTHON:-python3}"
DATA_HOME="${XDG_DATA_HOME:-$HOME/.local/share}"
APP_HOME="$DATA_HOME/$PACKAGE_NAME"
VENV="$APP_HOME/venv"
BIN_DIR="$HOME/.local/bin"
DESKTOP_DIR="$DATA_HOME/applications"
METAINFO_DIR="$DATA_HOME/metainfo"

fail() { printf 'Error: %s\n' "$*" >&2; exit 1; }

command -v "$PYTHON" >/dev/null 2>&1 || fail "python3 is required."
"$PYTHON" - <<'PY' || fail "Python 3.10 or newer is required."
import sys
raise SystemExit(0 if sys.version_info >= (3, 10) else 1)
PY

if ! "$PYTHON" - <<'PY' >/dev/null 2>&1
import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk, Adw
if not hasattr(Adw, "ToolbarView"):
    raise SystemExit(1)
PY
then
    cat >&2 <<'MSG'
GTK4/libadwaita Python bindings were not found, or libadwaita is older than 1.4.

Install your distribution's native GTK4 + libadwaita + PyGObject packages, then run this installer again.
Typical package names include:
  Fedora/Bazzite: python3-gobject gtk4 libadwaita
  Arch/CachyOS:   python-gobject gtk4 libadwaita
  Debian/Ubuntu:  python3-gi gir1.2-gtk-4.0 gir1.2-adw-1

HTPC Control Center deliberately does not install or layer system packages itself.
MSG
    exit 1
fi

mkdir -p "$APP_HOME" "$BIN_DIR" "$DESKTOP_DIR" "$METAINFO_DIR"

if [[ ! -x "$VENV/bin/python" ]]; then
    "$PYTHON" -m venv --system-site-packages "$VENV"
fi

"$VENV/bin/python" -m pip install --disable-pip-version-check --upgrade "$SCRIPT_DIR"
ln -sfn "$VENV/bin/htpc-control-center" "$BIN_DIR/htpc-control-center"
install -m 0755 "$SCRIPT_DIR/uninstall.sh" "$APP_HOME/uninstall.sh"
ln -sfn "$APP_HOME/uninstall.sh" "$BIN_DIR/htpc-control-center-uninstall"

"$PYTHON" - "$SCRIPT_DIR/data/$APP_ID.desktop.in" "$DESKTOP_DIR/$APP_ID.desktop" "$BIN_DIR/htpc-control-center" <<'PY'
from pathlib import Path
import sys
source, destination, executable = map(Path, sys.argv[1:])
text = source.read_text(encoding="utf-8").replace("@EXEC@", str(executable))
destination.write_text(text, encoding="utf-8")
PY
cp "$SCRIPT_DIR/data/$APP_ID.metainfo.xml" "$METAINFO_DIR/$APP_ID.metainfo.xml"

command -v update-desktop-database >/dev/null 2>&1 && update-desktop-database "$DESKTOP_DIR" >/dev/null 2>&1 || true

echo
echo "$APP_NAME installed."
echo "Launch it from your application menu or run: htpc-control-center"
echo "Uninstall anytime with: htpc-control-center-uninstall"
echo
echo "TV setup requires adb/android-tools, but it does not need to be installed just to launch the app."
echo "Controller setup will request administrator authorization through Polkit only when applying privileged wake configuration."
echo "Application update checks use stable GitHub Releases and can be controlled under Preferences."
