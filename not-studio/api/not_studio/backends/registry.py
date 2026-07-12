"""Music backend registry: capability probing + instantiation."""

from __future__ import annotations

from collections.abc import Callable
import importlib.util
from typing import Any

from ..config import get_settings
from ..schemas import MusicProviderInfo


def _probe_stable_audio_local() -> tuple[bool, str]:
    if importlib.util.find_spec("stable_audio_3") is None:
        return (
            False,
            "stable-audio-3 is not installed in the API environment. Run `uv sync` in api/.",
        )
    return True, "Runs Stable Audio 3 directly inside a cancellable API worker process."


def _probe_stable_audio_runpod() -> tuple[bool, str]:
    settings = get_settings()
    required = {
        "NOT_STUDIO_RUNPOD_ENDPOINT_ID": settings.runpod_endpoint_id,
        "NOT_STUDIO_RUNPOD_API_KEY": settings.runpod_api_key,
        "NOT_STUDIO_RUNPOD_VOLUME_ID": settings.runpod_volume_id,
        "NOT_STUDIO_RUNPOD_S3_ENDPOINT_URL": settings.runpod_s3_endpoint_url,
        "NOT_STUDIO_RUNPOD_S3_ACCESS_KEY_ID": settings.runpod_s3_access_key_id,
        "NOT_STUDIO_RUNPOD_S3_SECRET_ACCESS_KEY": settings.runpod_s3_secret_access_key,
        "NOT_STUDIO_RUNPOD_S3_REGION": settings.runpod_s3_region,
    }
    missing = [name for name, value in required.items() if not value]
    if missing:
        return False, f"Set {missing[0]}."
    return True, f"RunPod Serverless endpoint {settings.runpod_endpoint_id}."


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
    "stable_audio_runpod": _Provider(
        "stable_audio_runpod",
        _probe_stable_audio_runpod,
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
