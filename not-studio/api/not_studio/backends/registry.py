"""Music backend registry: capability probing + instantiation."""

from __future__ import annotations

from collections.abc import Callable
import importlib.util
from typing import Any

from ..schemas import MusicProviderInfo


def _probe_stable_audio_local() -> tuple[bool, str]:
    if importlib.util.find_spec("stable_audio_3") is None:
        return (
            False,
            "stable-audio-3 is not installed in the API environment. Run `uv sync` in api/.",
        )
    return True, "Runs Stable Audio 3 directly inside a cancellable API worker process."


class _Provider:
    def __init__(
        self,
        name: str,
        probe: Callable[[], tuple[bool, str]],
        default_config: dict[str, Any],
    ) -> None:
        self.name = name
        self.probe = probe
        self.default_config = default_config


PROVIDERS: dict[str, _Provider] = {
    "stable_audio_local": _Provider(
        "stable_audio_local",
        _probe_stable_audio_local,
        {"model": "medium"},
    ),
}


def provider_infos() -> list[MusicProviderInfo]:
    infos: list[MusicProviderInfo] = []
    for provider in PROVIDERS.values():
        available, detail = provider.probe()
        infos.append(
            MusicProviderInfo(
                provider=provider.name,
                kinds=["music"],
                available=available,
                detail=detail,
                default_config=provider.default_config,
            )
        )
    return infos
