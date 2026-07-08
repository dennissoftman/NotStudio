"""RunPod Serverless worker for Stable Audio batch generation."""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

import numpy as np
import pyloudnorm as pyln
import runpod
import soundfile as sf
from stable_audio_3 import StableAudioModel
from torchaudio.functional import resample

_volume_root = Path(os.getenv("RUNPOD_VOLUME_PATH", "/runpod-volume"))
_models: dict[str, StableAudioModel] = {}


def _model(name: str) -> StableAudioModel:
    if not os.getenv("HF_TOKEN"):
        raise RuntimeError(
            "HF_TOKEN is required. Map a RunPod secret to the worker environment."
        )
    if name not in _models:
        _models[name] = StableAudioModel.from_pretrained(name)
    return _models[name]


def _slugify(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-") or "track"


def _normalize(audio: np.ndarray, sample_rate: int, target_lufs: float) -> np.ndarray:
    if len(audio) < int(sample_rate * 0.4):
        return audio
    meter = pyln.Meter(sample_rate)
    loudness = meter.integrated_loudness(audio)
    if np.isfinite(loudness):
        audio = pyln.normalize.loudness(audio, loudness, target_lufs)
    peak = float(np.max(np.abs(audio))) if audio.size else 0.0
    if peak > 0.999:
        audio = audio / peak * 0.999
    return np.clip(audio, -1.0, 1.0)


def _render_track(
    model: StableAudioModel,
    spec: dict[str, Any],
    sample_rate: int,
    target_lufs: float,
    output_path: Path,
) -> None:
    generated = (
        model.generate(
            prompt=str(spec["prompt"]),
            duration=float(spec.get("duration", 180)),
        )[0]
        .detach()
        .cpu()
    )
    source_rate = int(model.model.sample_rate)
    if source_rate != sample_rate:
        generated = resample(generated, source_rate, sample_rate)
    audio = _normalize(generated.transpose(0, 1).numpy(), sample_rate, target_lufs)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    sf.write(output_path, audio, sample_rate, format="FLAC")


def handler(job: dict[str, Any]) -> dict[str, Any]:
    payload = job.get("input") or {}
    prompts = payload.get("prompts")
    if not isinstance(prompts, list) or not prompts:
        raise ValueError("input.prompts must be a non-empty list")
    if not _volume_root.is_dir():
        raise RuntimeError(
            f"RunPod network volume is not mounted at {_volume_root}. "
            "Attach a network volume to the endpoint."
        )

    model_name = str(payload.get("model") or os.getenv("STABLE_AUDIO_MODEL", "medium"))
    sample_rate = int(payload.get("sample_rate", 44100))
    target_lufs = float(payload.get("target_lufs", -16.0))
    model = _model(model_name)
    job_id = str(job.get("id") or "local")
    batch_dir = Path("not-studio") / job_id

    tracks = []
    for index, spec in enumerate(prompts, start=1):
        if (
            not isinstance(spec, dict)
            or not spec.get("title")
            or not spec.get("prompt")
        ):
            raise ValueError(f"input.prompts[{index - 1}] requires title and prompt")
        storage_key = str(
            batch_dir / f"{index:02d}-{_slugify(str(spec['title']))}.flac"
        )
        _render_track(
            model,
            spec,
            sample_rate,
            target_lufs,
            _volume_root / storage_key,
        )
        tracks.append({"title": str(spec["title"]), "storage_key": storage_key})
    return {"tracks": tracks, "model": model_name, "sample_rate": sample_rate}


if __name__ == "__main__":
    runpod.serverless.start({"handler": handler})
