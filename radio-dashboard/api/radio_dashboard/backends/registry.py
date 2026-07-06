"""Provider registry: capability probing + instantiation from Backend rows."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from .. import engine_bridge
from ..schemas import BackendInfo
from .base import Backend
from .kokoro import KokoroSpeechBackend
from .mock import MockMusicBackend, MockSpeechBackend
from .stable_audio import StableAudioMusicBackend


def _probe_mock() -> tuple[bool, str]:
    return True, "Always available (in-process synthetic audio; no models)."


def _probe_kokoro() -> tuple[bool, str]:
    if not engine_bridge.engine_has("speech.py"):
        return False, "Parent engine speech.py not found."
    if not engine_bridge.engine_venv_ready():
        return False, "Parent engine env not synced. Run `uv sync` in the repo root."
    return True, "Reuses parent speech.py (Kokoro) via `uv run --no-sync`."


def _probe_stable_audio() -> tuple[bool, str]:
    if not engine_bridge.engine_has("main.py"):
        return False, "Parent engine main.py not found."
    if not engine_bridge.submodule_checked_out("stable-audio-3"):
        return False, "stable-audio-3 submodule not checked out."
    if not engine_bridge.engine_venv_ready():
        return False, "Parent engine env not synced. Run `uv sync` in the repo root."
    return True, "Reuses parent main.py (Stable Audio 3) via `uv run --no-sync`."


_Classes = dict[str, type[Backend]]


class _Provider:
    def __init__(
        self,
        name: str,
        classes: _Classes,
        probe: Callable[[], tuple[bool, str]],
        default_config: dict[str, Any],
    ) -> None:
        self.name = name
        self.classes = classes
        self.probe = probe
        self.default_config = default_config

    @property
    def kinds(self) -> list[str]:
        return sorted(self.classes)


PROVIDERS: dict[str, _Provider] = {
    "mock": _Provider(
        "mock",
        {"music": MockMusicBackend, "speech": MockSpeechBackend},
        _probe_mock,
        {},
    ),
    "kokoro": _Provider(
        "kokoro",
        {"speech": KokoroSpeechBackend},
        _probe_kokoro,
        {"voice": "am_michael", "device": "auto"},
    ),
    "stable_audio": _Provider(
        "stable_audio",
        {"music": StableAudioMusicBackend},
        _probe_stable_audio,
        {"model": "auto"},
    ),
}


def provider_infos() -> list[BackendInfo]:
    infos: list[BackendInfo] = []
    for provider in PROVIDERS.values():
        available, detail = provider.probe()
        infos.append(
            BackendInfo(
                provider=provider.name,
                kinds=provider.kinds,
                available=available,
                detail=detail,
                default_config=provider.default_config,
            )
        )
    return infos


def build_backend(*, provider: str, kind: str, config: dict[str, Any] | None) -> Backend:
    """Instantiate a backend for a (provider, kind) with its stored config."""
    prov = PROVIDERS.get(provider)
    if prov is None:
        raise ValueError(f"Unknown backend provider: {provider!r}")
    cls = prov.classes.get(kind)
    if cls is None:
        raise ValueError(f"Provider {provider!r} does not support kind {kind!r}")
    return cls(config or {})
