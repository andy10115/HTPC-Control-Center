"""GitHub Releases based update checks and user-confirmed self-updates."""
from __future__ import annotations

import contextlib
import inspect
import json
import os
import re
import shutil
import subprocess
import tarfile
import tempfile
import time
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from . import __version__
from .paths import AppPaths

REPOSITORY = "andy10115/HTPC-Control-Center"
LATEST_RELEASE_API = f"https://api.github.com/repos/{REPOSITORY}/releases/latest"
CHECK_INTERVAL_SECONDS = 24 * 60 * 60
USER_AGENT = f"HTPC-Control-Center/{__version__}"


class UpdateError(RuntimeError):
    """Raised when an update check or installation cannot be completed."""


@dataclass(frozen=True)
class UpdateInfo:
    version: str
    tag_name: str
    html_url: str
    tarball_url: str


@dataclass
class UpdatePreferences:
    automatically_check: bool = True


@dataclass
class UpdateState:
    last_check_epoch: float = 0.0
    latest_version: str = ""
    latest_tag: str = ""
    latest_html_url: str = ""
    latest_tarball_url: str = ""


def _preferences_path(paths: AppPaths) -> Path:
    return paths.config_dir / "update-settings.json"


def _state_path(paths: AppPaths) -> Path:
    return paths.state_dir / "update-state.json"


def _load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}
    return value if isinstance(value, dict) else {}


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    with contextlib.suppress(OSError):
        temporary.chmod(0o600)
    temporary.replace(path)


def load_preferences(paths: AppPaths | None = None) -> UpdatePreferences:
    paths = paths or AppPaths.from_environment()
    data = _load_json(_preferences_path(paths))
    return UpdatePreferences(automatically_check=bool(data.get("automatically_check", True)))


def save_preferences(preferences: UpdatePreferences, paths: AppPaths | None = None) -> None:
    paths = paths or AppPaths.from_environment()
    paths.ensure_private_directories()
    _write_json(_preferences_path(paths), asdict(preferences))


def load_state(paths: AppPaths | None = None) -> UpdateState:
    paths = paths or AppPaths.from_environment()
    data = _load_json(_state_path(paths))
    return UpdateState(
        last_check_epoch=float(data.get("last_check_epoch", 0.0) or 0.0),
        latest_version=str(data.get("latest_version", "") or ""),
        latest_tag=str(data.get("latest_tag", "") or ""),
        latest_html_url=str(data.get("latest_html_url", "") or ""),
        latest_tarball_url=str(data.get("latest_tarball_url", "") or ""),
    )


def save_state(state: UpdateState, paths: AppPaths | None = None) -> None:
    paths = paths or AppPaths.from_environment()
    paths.ensure_private_directories()
    _write_json(_state_path(paths), asdict(state))


def _version_tuple(value: str) -> tuple[int, int, int]:
    match = re.fullmatch(r"v?(\d+)\.(\d+)\.(\d+)", value.strip())
    if not match:
        raise UpdateError(f"Unsupported release version format: {value!r}")
    return tuple(int(part) for part in match.groups())  # type: ignore[return-value]


def is_newer_version(candidate: str, current: str = __version__) -> bool:
    return _version_tuple(candidate) > _version_tuple(current)


def _info_from_state(state: UpdateState) -> UpdateInfo | None:
    if not all((state.latest_version, state.latest_tag, state.latest_html_url, state.latest_tarball_url)):
        return None
    try:
        if not is_newer_version(state.latest_version):
            return None
    except UpdateError:
        return None
    return UpdateInfo(
        version=state.latest_version,
        tag_name=state.latest_tag,
        html_url=state.latest_html_url,
        tarball_url=state.latest_tarball_url,
    )


def cached_available_update(paths: AppPaths | None = None) -> UpdateInfo | None:
    return _info_from_state(load_state(paths))


def check_due(paths: AppPaths | None = None, *, now: float | None = None) -> bool:
    paths = paths or AppPaths.from_environment()
    preferences = load_preferences(paths)
    if not preferences.automatically_check:
        return False
    state = load_state(paths)
    current_time = time.time() if now is None else now
    return current_time - state.last_check_epoch >= CHECK_INTERVAL_SECONDS


def _request_latest_release(timeout: float) -> dict[str, Any]:
    request = urllib.request.Request(
        LATEST_RELEASE_API,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": USER_AGENT,
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.load(response)
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            raise UpdateError("No published GitHub release exists yet.") from exc
        raise UpdateError(f"GitHub returned HTTP {exc.code} while checking for updates.") from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise UpdateError(f"Could not reach GitHub: {exc}") from exc
    if not isinstance(payload, dict):
        raise UpdateError("GitHub returned an unexpected release response.")
    return payload


def check_for_updates(
    paths: AppPaths | None = None,
    *,
    force: bool = False,
    timeout: float = 7.0,
    now: float | None = None,
) -> UpdateInfo | None:
    """Check the latest stable GitHub Release.

    Automatic checks run no more than once per 24 hours. Manual checks pass
    ``force=True`` and bypass the interval and preference toggle.
    """
    paths = paths or AppPaths.from_environment()
    current_time = time.time() if now is None else now
    state = load_state(paths)

    if not force:
        preferences = load_preferences(paths)
        if not preferences.automatically_check:
            return _info_from_state(state)
        if current_time - state.last_check_epoch < CHECK_INTERVAL_SECONDS:
            return _info_from_state(state)

    # Record the attempt before network I/O so repeated application launches do
    # not hammer GitHub while the network is unavailable.
    state.last_check_epoch = current_time
    save_state(state, paths)

    payload = _request_latest_release(timeout)
    tag_name = str(payload.get("tag_name", "")).strip()
    html_url = str(payload.get("html_url", "")).strip()
    tarball_url = str(payload.get("tarball_url", "")).strip()
    if not tag_name or not html_url or not tarball_url:
        raise UpdateError("The latest GitHub release is missing required metadata.")

    version = tag_name[1:] if tag_name.startswith("v") else tag_name
    _version_tuple(version)
    state.latest_version = version
    state.latest_tag = tag_name
    state.latest_html_url = html_url
    state.latest_tarball_url = tarball_url
    save_state(state, paths)
    return _info_from_state(state)


def _download(url: str, destination: Path, timeout: float = 30.0) -> None:
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/octet-stream",
            "User-Agent": USER_AGENT,
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response, destination.open("wb") as handle:
            shutil.copyfileobj(response, handle)
    except urllib.error.HTTPError as exc:
        raise UpdateError(f"GitHub returned HTTP {exc.code} while downloading the update.") from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise UpdateError(f"Could not download the update: {exc}") from exc


def _safe_extract(archive: Path, destination: Path) -> Path:
    destination.mkdir(parents=True, exist_ok=True)
    root = destination.resolve()
    try:
        with tarfile.open(archive, "r:gz") as tar:
            members = tar.getmembers()
            if not members:
                raise UpdateError("The downloaded release archive is empty.")
            for member in members:
                target = (root / member.name).resolve()
                if target != root and root not in target.parents:
                    raise UpdateError("The downloaded release archive contains an unsafe path.")
                if member.issym() or member.islnk():
                    raise UpdateError("The downloaded release archive contains unsupported links.")
            if "filter" in inspect.signature(tar.extractall).parameters:
                tar.extractall(root, filter="fully_trusted")
            else:  # Python builds predating tarfile extraction filters.
                tar.extractall(root)
    except (tarfile.TarError, OSError) as exc:
        raise UpdateError(f"Could not unpack the downloaded release: {exc}") from exc

    candidates = [path for path in destination.iterdir() if path.is_dir() and (path / "install.sh").is_file()]
    if len(candidates) != 1:
        raise UpdateError("Could not locate install.sh inside the downloaded release.")
    return candidates[0]


def install_update(info: UpdateInfo) -> str:
    """Download a release source archive and run its normal unprivileged installer."""
    with tempfile.TemporaryDirectory(prefix="htpc-control-center-update-") as temporary:
        temp = Path(temporary)
        archive = temp / f"{info.tag_name}.tar.gz"
        _download(info.tarball_url, archive)
        source = _safe_extract(archive, temp / "source")
        try:
            result = subprocess.run(
                ["bash", str(source / "install.sh")],
                cwd=source,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                check=False,
                timeout=180,
                env=os.environ.copy(),
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise UpdateError(f"Could not run the update installer: {exc}") from exc
        if result.returncode != 0:
            output = (result.stdout or "").strip()
            raise UpdateError(output or f"Update installer exited with status {result.returncode}.")
        return (result.stdout or "").strip()
