"""TV provider registry and controller factory.

The GUI can grow additional TV operating-system providers without coupling any
of them to controller wake. Provider-specific onboarding UI can branch from the
registry while generic dashboard/lifecycle operations dispatch through the
factory below.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from ..config import AppConfig


class TVProviderError(RuntimeError):
    """Raised when a saved TV provider cannot be loaded."""


class TVController(Protocol):
    async def ensure_ready(self) -> None: ...
    async def set_power(self, target_on: bool): ...
    async def select_input(self, uri: str | None = None) -> None: ...
    async def wake_and_select_input(self): ...


@dataclass(frozen=True)
class TVProviderInfo:
    key: str
    name: str
    summary: str
    supported: bool = True


PROVIDERS: tuple[TVProviderInfo, ...] = (
    TVProviderInfo(
        key="android",
        name="Android TV / Google TV",
        summary="ADB over the local network for power and physical input selection.",
    ),
)


def provider_info(key: str) -> TVProviderInfo:
    normalized = (key or "android").strip().casefold()
    for provider in PROVIDERS:
        if provider.key == normalized:
            return provider
    raise TVProviderError(f"Unsupported TV provider: {key or '(empty)'}")


def create_controller(config: AppConfig) -> TVController:
    provider = provider_info(config.tv.provider)
    if provider.key == "android":
        from .android import ADBController

        return ADBController(config)
    # Keeping this explicit makes an accidentally registered provider fail loudly
    # until its controller implementation is wired up.
    raise TVProviderError(f"TV provider is registered but has no controller: {provider.key}")
