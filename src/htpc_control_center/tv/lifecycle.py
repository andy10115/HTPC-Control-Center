"""Lifecycle event policy and logind watcher."""

from __future__ import annotations

import asyncio
import logging
import os
from contextlib import suppress
from dataclasses import dataclass
from typing import Any

from .android import PowerResult, TVControlError
from .providers import TVController, TVProviderError, create_controller
from ..config import AppConfig, load_config
from ..paths import AppPaths

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class EventResult:
    event: str
    performed: bool
    success: bool
    message: str


async def _wake_with_retries(
    event: str,
    controller: TVController,
    config: AppConfig,
) -> EventResult:
    attempts = max(1, config.behavior.wake_attempts)
    last_message = "TV wake failed."
    for attempt in range(1, attempts + 1):
        try:
            result = await controller.wake_and_select_input()
            if result.success:
                return _power_event_result(event, result)
            last_message = result.message
        except TVControlError as exc:
            last_message = str(exc)
        if attempt < attempts:
            LOGGER.warning(
                "Lifecycle event %s attempt %d/%d failed: %s; retrying",
                event,
                attempt,
                attempts,
                last_message,
            )
            await asyncio.sleep(max(0.1, config.behavior.wake_retry_seconds))
    return EventResult(event, True, False, last_message)


async def _wait_for_tv_ready(
    controller: TVController,
    config: AppConfig,
    event: str,
    grace_seconds: float,
) -> bool:
    """
    Poll until adb can actually reach and authenticate with the TV, instead
    of trusting a flat sleep. On boot in particular, the watcher can start
    before the network interface has associated/gotten a DHCP lease -
    firing `adb connect` at that point fails fast (not a slow timeout), so
    a short fixed delay can expire before the network is actually usable.
    Polling the real dependency removes that race regardless of whether
    network-online.target is meaningfully wired up on a given system.
    """
    if grace_seconds > 0:
        await asyncio.sleep(grace_seconds)

    deadline = max(0.0, config.behavior.adb_ready_timeout_seconds)
    interval = max(0.1, config.behavior.adb_ready_poll_seconds)
    elapsed = 0.0
    attempts = 0
    while True:
        attempts += 1
        try:
            await controller.ensure_ready()
            LOGGER.info(
                "Lifecycle event %s: adb ready after %.1fs grace + %.1fs poll (%d attempt(s))",
                event,
                grace_seconds,
                elapsed,
                attempts,
            )
            return True
        except TVControlError as exc:
            if elapsed >= deadline:
                LOGGER.warning(
                    "Lifecycle event %s: adb not ready after %.1fs grace + %.1fs poll (%d attempt(s)): %s",
                    event,
                    grace_seconds,
                    elapsed,
                    attempts,
                    exc,
                )
                return False
            await asyncio.sleep(interval)
            elapsed += interval


async def handle_event(
    event: str,
    config: AppConfig | None = None,
    paths: AppPaths | None = None,
) -> EventResult:
    paths = paths or AppPaths.from_environment()
    config = config or load_config(paths)
    behavior = config.behavior

    # Resolve policy before constructing the provider. A disabled lifecycle action
    # should remain disabled even if its provider dependency (for example adb) is
    # temporarily unavailable.
    if event == "startup" and not behavior.on_startup:
        return EventResult(event, False, True, "Startup automation is disabled.")
    if event == "resume" and not behavior.on_resume:
        return EventResult(event, False, True, "Resume automation is disabled.")
    if event == "suspend" and not behavior.off_on_suspend:
        return EventResult(event, False, True, "Suspend TV power-off is disabled.")
    if event == "shutdown" and not behavior.off_on_shutdown:
        return EventResult(event, False, True, "Shutdown automation is disabled.")
    if event == "reboot" and not behavior.off_on_reboot:
        return EventResult(event, False, True, "Reboot TV power-off is disabled.")
    if event not in {"startup", "resume", "suspend", "shutdown", "reboot"}:
        raise ValueError(f"Unknown lifecycle event: {event}")

    try:
        controller = create_controller(config)
        if event == "startup":
            ready = await _wait_for_tv_ready(controller, config, event, behavior.startup_delay_seconds)
            if not ready:
                total = behavior.startup_delay_seconds + behavior.adb_ready_timeout_seconds
                return EventResult(
                    event,
                    True,
                    False,
                    f"adb did not become reachable within {total:g}s; TV was not woken.",
                )
            return await _wake_with_retries(event, controller, config)
        if event == "resume":
            ready = await _wait_for_tv_ready(controller, config, event, behavior.resume_delay_seconds)
            if not ready:
                total = behavior.resume_delay_seconds + behavior.adb_ready_timeout_seconds
                return EventResult(
                    event,
                    True,
                    False,
                    f"adb did not become reachable within {total:g}s; TV was not woken.",
                )
            return await _wake_with_retries(event, controller, config)

        # Controller wake has its own system-level pre-suspend guard. TV lifecycle
        # handling must not add another controller settling delay here.
        result = await controller.set_power(False)
        return _power_event_result(event, result)
    except (TVControlError, TVProviderError) as exc:
        return EventResult(event, True, False, str(exc))


def _power_event_result(event: str, result: PowerResult) -> EventResult:
    return EventResult(event, True, result.success, result.message)


def _metadata_shutdown_type(body: list[Any]) -> str:
    if len(body) < 2 or not isinstance(body[1], dict):
        return "shutdown"
    metadata = body[1]
    value = metadata.get("type")
    if hasattr(value, "value"):
        value = value.value
    text = str(value or "").casefold()
    if "reboot" in text or "kexec" in text or "soft-reboot" in text:
        return "reboot"
    return "shutdown"


class LogindWatcher:
    """Listen for logind lifecycle signals while holding a delay inhibitor."""

    def __init__(self, config: AppConfig, paths: AppPaths) -> None:
        self.config = config
        self.paths = paths
        self.bus: Any = None
        self.inhibitor_fd: int | None = None
        self.sleeping = False
        self.shutting_down = False
        self._tasks: set[asyncio.Task[Any]] = set()
        self._legacy_shutdown_task: asyncio.Task[Any] | None = None
        self.effective_delay_seconds = max(1.0, config.service.inhibitor_delay_max_seconds)

    async def _read_inhibit_delay(self) -> None:
        from dbus_next import Message
        from dbus_next.constants import MessageType

        reply = await self.bus.call(
            Message(
                destination="org.freedesktop.login1",
                path="/org/freedesktop/login1",
                interface="org.freedesktop.DBus.Properties",
                member="Get",
                signature="ss",
                body=["org.freedesktop.login1.Manager", "InhibitDelayMaxUSec"],
            )
        )
        if reply.message_type is MessageType.ERROR or not reply.body:
            LOGGER.warning("Could not read logind InhibitDelayMaxUSec; using configured deadline")
            return
        variant = reply.body[0]
        microseconds = getattr(variant, "value", 0)
        try:
            system_limit = float(microseconds) / 1_000_000.0
        except (TypeError, ValueError):
            return
        if system_limit > 0:
            safe_system_limit = max(0.1, system_limit - 0.25)
            self.effective_delay_seconds = max(
                0.1,
                min(self.config.service.inhibitor_delay_max_seconds, safe_system_limit),
            )
        LOGGER.info("Using %.2f-second lifecycle deadline", self.effective_delay_seconds)

    async def _add_signal_match(self) -> None:
        from dbus_next import Message
        from dbus_next.constants import MessageType

        rule = (
            "type='signal',sender='org.freedesktop.login1',"
            "path='/org/freedesktop/login1',"
            "interface='org.freedesktop.login1.Manager'"
        )
        reply = await self.bus.call(
            Message(
                destination="org.freedesktop.DBus",
                path="/org/freedesktop/DBus",
                interface="org.freedesktop.DBus",
                member="AddMatch",
                signature="s",
                body=[rule],
            )
        )
        if reply.message_type is MessageType.ERROR:
            raise RuntimeError(reply.body[0] if reply.body else "Could not subscribe to logind signals")

    async def _acquire_inhibitor(self) -> None:
        try:
            from dbus_next import Message
            from dbus_next.constants import MessageType
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError("dbus-next is not installed") from exc

        reply = await self.bus.call(
            Message(
                destination="org.freedesktop.login1",
                path="/org/freedesktop/login1",
                interface="org.freedesktop.login1.Manager",
                member="Inhibit",
                signature="ssss",
                body=[
                    "sleep:shutdown",
                    "HTPC Control Center",
                    "Turn off the TV before the PC sleeps or shuts down",
                    "delay",
                ],
            )
        )
        if reply.message_type is MessageType.ERROR:
            raise RuntimeError(reply.body[0] if reply.body else "logind inhibitor request failed")
        if not reply.body or not reply.unix_fds:
            raise RuntimeError("logind returned no inhibitor file descriptor")
        fd_index = int(reply.body[0])
        if fd_index < 0 or fd_index >= len(reply.unix_fds):
            raise RuntimeError("logind returned an invalid inhibitor file descriptor index")
        self.inhibitor_fd = reply.unix_fds[fd_index]
        LOGGER.info("Acquired logind sleep/shutdown delay inhibitor")

    def _release_inhibitor(self) -> None:
        if self.inhibitor_fd is None:
            return
        with suppress(OSError):
            os.close(self.inhibitor_fd)
        self.inhibitor_fd = None
        LOGGER.info("Released logind inhibitor")

    def _track(self, coroutine: Any) -> asyncio.Task[Any]:
        task = asyncio.create_task(coroutine)
        self._tasks.add(task)

        def finished(done: asyncio.Task[Any]) -> None:
            self._tasks.discard(done)
            if done.cancelled():
                return
            try:
                done.result()
            except Exception:
                LOGGER.exception("Unhandled lifecycle watcher task failure")

        task.add_done_callback(finished)
        return task

    async def _run_event_with_deadline(self, event: str) -> None:
        timeout = self.effective_delay_seconds
        try:
            # Controller wake has a separate system-level suspend guard. Keep the
            # TV watcher independent so it only spends the logind inhibitor window
            # on the TV operation itself.
            result = await asyncio.wait_for(
                handle_event(event, self.config, self.paths),
                timeout=timeout,
            )
            log = LOGGER.info if result.success else LOGGER.error
            log("Lifecycle event %s: %s", event, result.message)
        except asyncio.TimeoutError:
            LOGGER.error("Lifecycle event %s exceeded %.1f seconds", event, timeout)
        except Exception:
            LOGGER.exception("Lifecycle event %s failed unexpectedly", event)
        finally:
            if event in {"suspend", "shutdown", "reboot"}:
                self._release_inhibitor()

    async def _on_resume(self) -> None:
        self.sleeping = False
        try:
            await self._acquire_inhibitor()
        except Exception:
            LOGGER.exception("Could not reacquire logind inhibitor after resume")
        result = await handle_event("resume", self.config, self.paths)
        log = LOGGER.info if result.success else LOGGER.error
        log("Lifecycle event resume: %s", result.message)

    async def _legacy_shutdown_after_grace(self) -> None:
        # Newer logind versions emit a metadata-bearing signal that can distinguish
        # reboot from poweroff. Give it a brief chance to arrive before falling back.
        await asyncio.sleep(0.15)
        if self.shutting_down:
            return
        self.shutting_down = True
        await self._run_event_with_deadline("shutdown")

    def _message_handler(self, message: Any) -> bool:
        try:
            from dbus_next.constants import MessageType
        except ImportError:  # pragma: no cover
            return False
        if message.message_type is not MessageType.SIGNAL:
            return False
        if message.interface != "org.freedesktop.login1.Manager":
            return False

        if message.member == "PrepareForSleep" and message.body:
            preparing = bool(message.body[0])
            if preparing and not self.sleeping:
                self.sleeping = True
                self._track(self._run_event_with_deadline("suspend"))
            elif not preparing and self.sleeping:
                self._track(self._on_resume())
            return False

        if message.member == "PrepareForShutdownWithMetadata" and message.body:
            preparing = bool(message.body[0])
            if preparing and not self.shutting_down:
                self.shutting_down = True
                if self._legacy_shutdown_task is not None:
                    self._legacy_shutdown_task.cancel()
                self._track(self._run_event_with_deadline(_metadata_shutdown_type(message.body)))
            return False

        if message.member == "PrepareForShutdown" and message.body:
            preparing = bool(message.body[0])
            if preparing and not self.shutting_down and self._legacy_shutdown_task is None:
                self._legacy_shutdown_task = self._track(self._legacy_shutdown_after_grace())
            return False
        return False

    async def run(self) -> None:
        try:
            from dbus_next.aio import MessageBus
            from dbus_next.constants import BusType
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError("dbus-next is not installed") from exc

        self.bus = await MessageBus(bus_type=BusType.SYSTEM, negotiate_unix_fd=True).connect()
        await self._read_inhibit_delay()
        await self._add_signal_match()
        self.bus.add_message_handler(self._message_handler)
        await self._acquire_inhibitor()

        startup = await handle_event("startup", self.config, self.paths)
        log = LOGGER.info if startup.success else LOGGER.error
        log("Lifecycle event startup: %s", startup.message)

        LOGGER.info("Watching logind for sleep and shutdown events")
        try:
            await self.bus.wait_for_disconnect()
        finally:
            self._release_inhibitor()
            for task in self._tasks:
                task.cancel()


async def run_watcher(paths: AppPaths | None = None) -> None:
    paths = paths or AppPaths.from_environment()
    config = load_config(paths)
    watcher = LogindWatcher(config, paths)
    await watcher.run()
