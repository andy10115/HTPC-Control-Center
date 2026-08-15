#!/usr/bin/env bash
set -u

PACKAGE_NAME="htpc-control-center"
APP_ID="io.github.andy10115.HTPCControlCenter"
DATA_HOME="${XDG_DATA_HOME:-$HOME/.local/share}"
CONFIG_HOME="${XDG_CONFIG_HOME:-$HOME/.config}"
APP_HOME="$DATA_HOME/$PACKAGE_NAME"
VENV="$APP_HOME/venv"
KEEP_CONFIG=0

[[ "${1:-}" == "--keep-config" ]] && KEEP_CONFIG=1

systemctl --user disable --now htpc-control-center-tv-watcher.service >/dev/null 2>&1 || true
rm -f "$CONFIG_HOME/systemd/user/htpc-control-center-tv-watcher.service"
systemctl --user daemon-reload >/dev/null 2>&1 || true

HELPER="/usr/local/libexec/htpc-control-center-privileged"
if [[ -x "$HELPER" ]] && command -v pkexec >/dev/null 2>&1; then
    echo "Removing privileged controller-wake components (administrator authorization may appear)..."
    pkexec "$HELPER" purge || echo "Warning: privileged controller-wake components were not removed."
elif [[ -e /etc/udev/rules.d/99-htpc-control-center-controller-wake.rules ]]; then
    echo "Warning: controller-wake system files remain installed because the privileged helper was unavailable."
fi

rm -f "$HOME/.local/bin/htpc-control-center"
rm -f "$HOME/.local/bin/htpc-control-center-uninstall"
rm -f "$DATA_HOME/applications/$APP_ID.desktop"
rm -f "$DATA_HOME/metainfo/$APP_ID.metainfo.xml"
rm -f "$DATA_HOME/icons/hicolor/scalable/apps/$APP_ID.svg"
rm -f "$DATA_HOME/icons/hicolor/256x256/apps/$APP_ID.png"
rm -rf "$APP_HOME"

if (( KEEP_CONFIG == 0 )); then
    rm -rf "$CONFIG_HOME/htpc-control-center" "${XDG_STATE_HOME:-$HOME/.local/state}/htpc-control-center"
else
    echo "Saved TV configuration kept under $CONFIG_HOME/htpc-control-center."
fi

command -v update-desktop-database >/dev/null 2>&1 && update-desktop-database "$DATA_HOME/applications" >/dev/null 2>&1 || true
command -v gtk-update-icon-cache >/dev/null 2>&1 && gtk-update-icon-cache -q -t "$DATA_HOME/icons/hicolor" >/dev/null 2>&1 || true

echo "HTPC Control Center removed."
