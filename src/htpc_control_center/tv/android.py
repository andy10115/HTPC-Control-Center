"""ADB-backed Android TV / Google TV control."""

from __future__ import annotations

import asyncio
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote

from ..config import AppConfig


class TVControlError(RuntimeError):
    """A user-facing ADB or TV control failure."""


class ADBNotInstalled(TVControlError):
    """Raised when the Android platform tools are unavailable."""


class ADBUnauthorized(TVControlError):
    """Raised when the TV has not authorized this computer."""


@dataclass(frozen=True)
class CommandResult:
    args: tuple[str, ...]
    returncode: int
    stdout: str
    stderr: str


@dataclass(frozen=True)
class PowerResult:
    target_on: bool
    success: bool
    verified: bool
    attempts: int
    message: str


@dataclass(frozen=True)
class TVStatus:
    serial: str
    connected: bool
    authorized: bool
    is_on: bool | None
    model: str
    current_input_id: str


@dataclass(frozen=True)
class TVInput:
    input_id: str
    uri: str
    hardware_id: str

    @property
    def display_name(self) -> str:
        service = self.input_id.split("/", 1)[0]
        return f"{self.hardware_id} — {service}"


def find_adb(configured: str = "") -> str:
    """Resolve adb without modifying the system."""
    if configured:
        path = Path(configured).expanduser()
        if path.is_file() and path.stat().st_mode & 0o111:
            return str(path.resolve())
    discovered = shutil.which("adb")
    if discovered:
        return str(Path(discovered).resolve())
    raise ADBNotInstalled(
        "Android platform tools were not found. Install your distribution's adb/android-tools "
        "package, then run setup again."
    )


def installation_help() -> str:
    return """ADB (Android platform tools) is required but was not found.

Install it with your distribution's supported package method, then rerun this command:

  Arch Linux / CachyOS:  sudo pacman -S android-tools
  Fedora:                sudo dnf install android-tools
  Debian / Ubuntu:       sudo apt install adb
  openSUSE:              sudo zypper install android-tools
  Bazzite:               use Bazzite's supported ujust recipe for Android platform tools

HTPC Control Center deliberately does not install or layer system packages for you."""


def input_uri(input_id: str) -> str:
    return f"content://android.media.tv/passthrough/{quote(input_id, safe='')}"


def parse_power_state(text: str) -> bool | None:
    lower = text.casefold()
    wakefulness = re.search(r"mwakefulness\s*=\s*(awake|asleep|dozing|dreaming)", lower)
    if wakefulness:
        return wakefulness.group(1) in {"awake", "dreaming"}
    if re.search(r"\bstate\s*=\s*(on|doze_suspend|doze)\b", lower):
        return "state=on" in lower.replace(" ", "")
    return None


def parse_current_input(text: str) -> str:
    match = re.search(r"^\s*inputId:\s*(\S+)\s*$", text, re.MULTILINE)
    return match.group(1) if match else ""


def parse_tv_inputs(text: str) -> list[TVInput]:
    """Extract physical passthrough inputs from dumpsys tv_input."""
    ids: set[str] = set()
    for line in text.splitlines():
        if "TvInputInfo{id=" not in line or "TunerInputService" in line:
            continue
        match = re.search(r"TvInputInfo\{id=([^,}]+)", line)
        if not match:
            continue
        candidate = match.group(1).strip()
        physical_hint = any(marker in line.casefold() for marker in ("passthrough", "hdmi", "externalinput"))
        if not physical_hint and not re.search(r"/HW\d+$", candidate, re.IGNORECASE):
            continue
        ids.add(candidate)

    def sort_key(value: str) -> tuple[int, str]:
        match = re.search(r"HW(\d+)$", value)
        return (int(match.group(1)) if match else 9999, value)

    results: list[TVInput] = []
    for candidate in sorted(ids, key=sort_key):
        hardware = re.search(r"(HW\d+)$", candidate, re.IGNORECASE)
        fallback_label = candidate.rsplit("/", 1)[-1]
        results.append(
            TVInput(
                input_id=candidate,
                uri=input_uri(candidate),
                hardware_id=hardware.group(1).upper() if hardware else fallback_label,
            )
        )
    return results


class ADBController:
    def __init__(self, config: AppConfig) -> None:
        self.config = config
        self.adb = find_adb(config.tv.adb_path)

    @property
    def serial(self) -> str:
        serial = self.config.tv.serial
        if not serial:
            raise TVControlError("No TV address is configured. Open HTPC Control Center and configure TV Control.")
        return serial

    async def _run(
        self,
        *args: str,
        timeout: float | None = None,
        check: bool = False,
    ) -> CommandResult:
        command = [self.adb, *args]
        effective_timeout = timeout or self.config.behavior.command_timeout_seconds

        def invoke() -> subprocess.CompletedProcess[str]:
            return subprocess.run(
                command,
                check=False,
                capture_output=True,
                text=True,
                timeout=effective_timeout,
            )

        try:
            result = await asyncio.to_thread(invoke)
        except subprocess.TimeoutExpired as exc:
            message = f"ADB command timed out after {effective_timeout:g} seconds: {' '.join(command)}"
            raise TVControlError(message) from exc
        except OSError as exc:
            raise TVControlError(f"Could not run adb: {exc}") from exc

        wrapped = CommandResult(
            tuple(command),
            result.returncode,
            result.stdout.strip(),
            result.stderr.strip(),
        )
        if check and result.returncode != 0:
            detail = wrapped.stderr or wrapped.stdout or f"exit status {wrapped.returncode}"
            if "unauthorized" in detail.casefold():
                raise ADBUnauthorized(
                    "The TV has not authorized this computer. Accept the debugging prompt on the TV "
                    "and choose 'Always allow from this computer'."
                )
            raise TVControlError(f"ADB command failed: {detail}")
        return wrapped

    async def connect(self) -> CommandResult:
        result = await self._run(
            "connect",
            self.serial,
            timeout=self.config.behavior.connect_timeout_seconds,
        )
        combined = f"{result.stdout}\n{result.stderr}".casefold()
        authentication_pending = "authenticate" in combined or "unauthorized" in combined
        if authentication_pending:
            # First contact commonly reports an authentication failure while the TV
            # is displaying the authorization dialog. Let the onboarding poll continue.
            return result
        if result.returncode != 0 or "failed" in combined or "unable" in combined:
            raise TVControlError(result.stderr or result.stdout or f"Could not connect to {self.serial}")
        return result

    async def device_state(self) -> str:
        result = await self._run("devices")
        for line in result.stdout.splitlines()[1:]:
            fields = line.split()
            if fields and fields[0] == self.serial:
                return fields[1] if len(fields) > 1 else "unknown"
        return "missing"

    async def ensure_authorized(self) -> None:
        await self.connect()
        state = await self.device_state()
        if state == "unauthorized":
            raise ADBUnauthorized(
                "The TV is waiting for authorization. Accept the debugging prompt on the TV and "
                "choose 'Always allow from this computer'."
            )
        if state != "device":
            raise TVControlError(f"ADB device state is '{state}', expected 'device'.")

    async def ensure_ready(self) -> None:
        """Provider-neutral readiness hook used by the lifecycle watcher."""
        await self.ensure_authorized()

    async def pair(self, address: str, code: str) -> CommandResult:
        result = await self._run("pair", address, code, timeout=30.0)
        if result.returncode != 0 or "successfully paired" not in result.stdout.casefold():
            raise TVControlError(result.stderr or result.stdout or "ADB wireless pairing failed.")
        return result

    async def shell(self, *args: str, check: bool = True) -> CommandResult:
        await self.ensure_authorized()
        return await self._run("-s", self.serial, "shell", *args, check=check)

    async def model(self) -> str:
        result = await self.shell("getprop", "ro.product.model")
        return result.stdout.strip()

    async def power_state(self) -> bool | None:
        result = await self.shell("dumpsys", "power")
        return parse_power_state(result.stdout)

    async def current_input(self) -> str:
        result = await self.shell("dumpsys", "tv_input")
        return parse_current_input(result.stdout)

    async def status(self) -> TVStatus:
        await self.ensure_authorized()
        model_result, power_result, input_result = await asyncio.gather(
            self._run("-s", self.serial, "shell", "getprop", "ro.product.model", check=True),
            self._run("-s", self.serial, "shell", "dumpsys", "power", check=True),
            self._run("-s", self.serial, "shell", "dumpsys", "tv_input", check=True),
        )
        return TVStatus(
            serial=self.serial,
            connected=True,
            authorized=True,
            is_on=parse_power_state(power_result.stdout),
            model=model_result.stdout.strip(),
            current_input_id=parse_current_input(input_result.stdout),
        )

    async def discover_inputs(self) -> list[TVInput]:
        result = await self.shell("dumpsys", "tv_input")
        return parse_tv_inputs(result.stdout)

    async def set_power(self, target_on: bool) -> PowerResult:
        key = "KEYCODE_WAKEUP" if target_on else "KEYCODE_SLEEP"
        attempts = max(1, self.config.behavior.wake_attempts if target_on else 1)
        last_error = ""

        for attempt in range(1, attempts + 1):
            try:
                # WAKEUP and SLEEP are discrete, idempotent keyevents. Send first so
                # suspend/shutdown does not waste logind's delay-inhibitor window on
                # an unnecessary preliminary state query.
                await self.ensure_authorized()
                result = await self._run(
                    "-s",
                    self.serial,
                    "shell",
                    "input",
                    "keyevent",
                    key,
                    check=True,
                )
                if result.returncode != 0:
                    raise TVControlError(result.stderr or result.stdout or f"Could not send {key}")
                await asyncio.sleep(self.config.behavior.wake_settle_seconds if target_on else 0.35)

                try:
                    verification = await self._run(
                        "-s",
                        self.serial,
                        "shell",
                        "dumpsys",
                        "power",
                        check=True,
                    )
                    verified_state = parse_power_state(verification.stdout)
                except TVControlError:
                    verified_state = None

                if verified_state is target_on:
                    state = "on" if target_on else "off"
                    return PowerResult(target_on, True, True, attempt, f"TV turned {state} via ADB.")
                if not target_on:
                    return PowerResult(
                        target_on,
                        True,
                        False,
                        attempt,
                        "Sent KEYCODE_SLEEP; the command completed but the final state was not verified.",
                    )
                last_error = f"TV did not report the requested state after {key}."
            except TVControlError as exc:
                last_error = str(exc)

            if attempt < attempts:
                await asyncio.sleep(max(0.1, self.config.behavior.wake_retry_seconds))

        return PowerResult(target_on, False, False, attempts, last_error or f"Could not send {key}.")

    async def select_input(self, uri: str | None = None) -> None:
        selected = uri or self.config.tv.input_uri
        if not selected:
            raise TVControlError("No TV input is configured. Configure a TV input in HTPC Control Center.")
        result = await self.shell(
            "am",
            "start",
            "-a",
            "android.intent.action.VIEW",
            "-d",
            selected,
        )
        combined = f"{result.stdout}\n{result.stderr}".casefold()
        if result.returncode != 0 or "error" in combined or "exception" in combined:
            raise TVControlError(result.stderr or result.stdout or "TV input launch failed.")
        await asyncio.sleep(max(0.0, self.config.behavior.input_settle_seconds))

    async def wake_and_select_input(self) -> PowerResult:
        power = await self.set_power(True)
        if not power.success:
            return power
        if self.config.behavior.switch_input_after_wake and self.config.tv.input_uri:
            await self.select_input()
            return PowerResult(
                True,
                True,
                power.verified,
                power.attempts,
                f"{power.message} Selected {self.config.tv.input_label or self.config.tv.input_id}.",
            )
        return power

@dataclass(frozen=True)
class DiscoveredADBTarget:
    address: str
    source: str
    label: str


def _endpoint_from_text(text: str) -> str:
    """Return the first IPv4:port-looking endpoint from a line of adb output."""
    match = re.search(r"\b((?:\d{1,3}\.){3}\d{1,3}:\d{2,5})\b", text)
    return match.group(1) if match else ""


def discover_adb_targets(adb_path: str = "") -> list[DiscoveredADBTarget]:
    """Discover already-known and mDNS-advertised Android TV ADB endpoints."""
    adb = find_adb(adb_path)
    found: dict[str, DiscoveredADBTarget] = {}

    def run(*args: str, timeout: float = 4.0) -> str:
        try:
            result = subprocess.run(
                [adb, *args], check=False, capture_output=True, text=True, timeout=timeout
            )
        except (OSError, subprocess.TimeoutExpired):
            return ""
        return result.stdout

    devices = run("devices")
    for line in devices.splitlines()[1:]:
        fields = line.split()
        if not fields or fields[0].startswith("emulator-"):
            continue
        address = fields[0]
        if re.fullmatch(r"(?:\d{1,3}\.){3}\d{1,3}:\d{2,5}", address):
            state = fields[1] if len(fields) > 1 else "known"
            found[address] = DiscoveredADBTarget(address, "adb devices", f"{address} — {state}")

    mdns = run("mdns", "services", timeout=5.0)
    for line in mdns.splitlines():
        if "_adb-tls-connect._tcp" not in line and "_adb._tcp" not in line:
            continue
        address = _endpoint_from_text(line)
        if not address:
            continue
        service = line.split()[0] if line.split() else "Android TV"
        found[address] = DiscoveredADBTarget(address, "adb mDNS", f"{service} — {address}")

    return sorted(found.values(), key=lambda item: item.address)


def set_tv_endpoint(config: AppConfig, endpoint: str) -> None:
    """Validate and store an IPv4 ADB endpoint."""
    import ipaddress

    value = endpoint.strip()
    if not value:
        raise TVControlError("Enter the TV's IP address.")
    if ":" in value:
        host, _, port_text = value.rpartition(":")
        try:
            ipaddress.IPv4Address(host)
            port = int(port_text)
        except ValueError as exc:
            raise TVControlError("Enter an address such as 10.0.0.42 or 10.0.0.42:5555.") from exc
        if not 1 <= port <= 65535:
            raise TVControlError("ADB port must be between 1 and 65535.")
        config.tv.host = host
        config.tv.port = port
        return
    try:
        ipaddress.IPv4Address(value)
    except ValueError as exc:
        raise TVControlError("Enter an IPv4 address such as 10.0.0.42.") from exc
    config.tv.host = value
    config.tv.port = 5555


async def authorize_controller(controller: ADBController, timeout: float = 60.0) -> str:
    """Connect and wait for the TV to authorize this computer."""
    await controller.connect()
    elapsed = 0.0
    while elapsed <= timeout:
        state = await controller.device_state()
        if state == "device":
            return await controller.model()
        if state not in {"unauthorized", "offline", "missing", "unknown"}:
            raise TVControlError(f"ADB device state is '{state}'.")
        await asyncio.sleep(2.0)
        elapsed += 2.0
    raise ADBUnauthorized(
        "The TV did not authorize this computer. Accept the debugging prompt on the TV and choose "
        "Always allow from this computer, then try again."
    )
