#!/usr/bin/env bash
set -euo pipefail

REPOSITORY="andy10115/HTPC-Control-Center"
API_URL="${HTPC_CC_RELEASE_API_URL:-https://api.github.com/repos/${REPOSITORY}/releases/latest}"
USER_AGENT="HTPC-Control-Center-Bootstrap"

fail() { printf 'Error: %s\n' "$*" >&2; exit 1; }
command -v curl >/dev/null 2>&1 || fail "curl is required."
command -v python3 >/dev/null 2>&1 || fail "python3 is required."
command -v tar >/dev/null 2>&1 || fail "tar is required."

TMP_DIR="$(mktemp -d -t htpc-control-center.XXXXXX)"
trap 'rm -rf "$TMP_DIR"' EXIT

printf 'Finding the latest stable HTPC Control Center release...\n'
RELEASE_JSON="$TMP_DIR/release.json"
curl -fsSL \
  -H 'Accept: application/vnd.github+json' \
  -H "User-Agent: ${USER_AGENT}" \
  "$API_URL" > "$RELEASE_JSON" || fail "Could not find a published GitHub release."

readarray -t RELEASE_INFO < <(python3 - "$RELEASE_JSON" <<'PY'
import json
import sys
from pathlib import Path
payload = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
tag = str(payload.get("tag_name", "")).strip()
tarball = str(payload.get("tarball_url", "")).strip()
if not tag or not tarball:
    raise SystemExit("Latest release metadata is incomplete.")
print(tag)
print(tarball)
PY
)

TAG_NAME="${RELEASE_INFO[0]:-}"
TARBALL_URL="${RELEASE_INFO[1]:-}"
[[ -n "$TAG_NAME" && -n "$TARBALL_URL" ]] || fail "Latest release metadata is incomplete."

printf 'Downloading %s...\n' "$TAG_NAME"
ARCHIVE="$TMP_DIR/release.tar.gz"
curl -fsSL --retry 2 \
  -H 'Accept: application/octet-stream' \
  -H "User-Agent: ${USER_AGENT}" \
  "$TARBALL_URL" -o "$ARCHIVE" || fail "Could not download $TAG_NAME."

SOURCE_ROOT="$TMP_DIR/source"
mkdir -p "$SOURCE_ROOT"
tar -xzf "$ARCHIVE" -C "$SOURCE_ROOT"
INSTALLER="$(find "$SOURCE_ROOT" -mindepth 2 -maxdepth 2 -type f -name install.sh -print -quit)"
[[ -n "$INSTALLER" ]] || fail "The downloaded release does not contain install.sh."

SOURCE_DIR="$(dirname "$INSTALLER")"
printf 'Installing %s...\n' "$TAG_NAME"
cd "$SOURCE_DIR"
exec bash ./install.sh
