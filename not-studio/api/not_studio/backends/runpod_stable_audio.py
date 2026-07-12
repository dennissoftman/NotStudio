"""RunPod Stable Audio batch adapter with binary network-volume downloads."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import boto3
import httpx

from ..config import get_settings
from .stable_audio import _slugify


def generate_batch(
    prompts: list[dict[str, Any]],
    *,
    sample_rate: int,
    model: str,
    out_dir: Path,
    on_progress: Callable[[float, str], None] | None = None,
    should_cancel: Callable[[], bool] | None = None,
    client: httpx.Client | None = None,
    storage_client: Any | None = None,
) -> list[tuple[dict[str, Any], Path]]:
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
        raise RuntimeError(f"RunPod Stable Audio requires {', '.join(missing)}.")

    url = f"{settings.runpod_base_url.rstrip('/')}/{settings.runpod_endpoint_id}/runsync"
    payload = {
        "input": {
            "prompts": [
                {
                    "title": spec["title"],
                    "prompt": spec["prompt"],
                    "duration": float(spec.get("duration", 180)),
                }
                for spec in prompts
            ],
            "model": model,
            "sample_rate": sample_rate,
        }
    }
    if on_progress:
        on_progress(0.1, f"Submitted {len(prompts)} tracks to RunPod")
    if should_cancel and should_cancel():
        raise RuntimeError("RunPod Stable Audio batch cancelled")

    owns_client = client is None
    http = client or httpx.Client(timeout=settings.runpod_timeout_seconds)
    try:
        if on_progress:
            on_progress(0.12, f"Waiting for RunPod to render {len(prompts)} track(s)")
        response = http.post(
            url,
            headers={"Authorization": f"Bearer {settings.runpod_api_key}"},
            json=payload,
        )
        response.raise_for_status()
        body = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise RuntimeError(f"RunPod Stable Audio request failed: {exc}") from exc
    finally:
        if owns_client:
            http.close()

    if body.get("status") != "COMPLETED":
        detail = body.get("error") or body.get("status") or "unknown response"
        raise RuntimeError(f"RunPod Stable Audio batch did not complete: {detail}")
    if should_cancel and should_cancel():
        raise RuntimeError("RunPod Stable Audio batch cancelled")

    output = body.get("output")
    tracks = output.get("tracks") if isinstance(output, dict) else output
    if not isinstance(tracks, list):
        raise RuntimeError("RunPod Stable Audio output must contain a tracks list.")
    if len(tracks) != len(prompts):
        raise RuntimeError(
            f"RunPod Stable Audio returned {len(tracks)} tracks for {len(prompts)} prompts."
        )

    out_dir.mkdir(parents=True, exist_ok=True)
    s3 = storage_client or boto3.client(
        "s3",
        endpoint_url=settings.runpod_s3_endpoint_url,
        aws_access_key_id=settings.runpod_s3_access_key_id,
        aws_secret_access_key=settings.runpod_s3_secret_access_key,
        region_name=settings.runpod_s3_region,
    )
    produced: list[tuple[dict[str, Any], Path]] = []
    for index, (spec, track) in enumerate(zip(prompts, tracks, strict=True), start=1):
        if should_cancel and should_cancel():
            raise RuntimeError("RunPod Stable Audio batch cancelled")
        if not isinstance(track, dict):
            raise RuntimeError(f"RunPod Stable Audio track {index} is not an object.")
        storage_key = track.get("storage_key")
        if not isinstance(storage_key, str) or not storage_key:
            raise RuntimeError(f"RunPod Stable Audio track {index} has no storage key.")
        path = out_dir / f"{_slugify(spec['title'])}.flac"
        if on_progress:
            on_progress(
                0.1 + 0.85 * (index - 1) / len(prompts), f"Downloading {index}/{len(prompts)}"
            )
        try:
            with path.open("wb") as output_file:
                s3.download_fileobj(settings.runpod_volume_id, storage_key, output_file)
        except Exception as exc:  # boto3 exposes provider-specific exception classes
            path.unlink(missing_ok=True)
            raise RuntimeError(
                f"Could not download RunPod Stable Audio track {index}: {exc}"
            ) from exc
        produced.append((spec, path))
        if on_progress:
            on_progress(0.1 + 0.85 * index / len(prompts), f"Downloaded {index}/{len(prompts)}")
    return produced
