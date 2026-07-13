from __future__ import annotations

import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

import numpy as np

from ..audio import dsp

_MODELS: dict[str, Any] = {}


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or "track"


def _resolve_model_name(_requested_model: str) -> str:
    """Not Studio always uses the medium Stable Audio 3 checkpoint."""
    return "medium"


def _load_model(model_name: str) -> Any:
    model = _MODELS.get(model_name)
    if model is None:
        from stable_audio_3 import StableAudioModel

        model = StableAudioModel.from_pretrained(model_name)
        _MODELS[model_name] = model
    return model


def preload_model(model: str = "medium") -> dict[str, str]:
    """Load the generation model into this worker and return serializable readiness data."""
    model_name = _resolve_model_name(model)
    loaded_model = _load_model(model_name)
    return {
        "status": "ready",
        "provider": "stable_audio_local",
        "model": model_name,
        "device": str(getattr(loaded_model, "device", "unknown")),
    }


def _generate_audio_array(model: Any, prompt: str, duration: float, output_rate: int) -> np.ndarray:
    import torch
    from torchaudio.functional import resample

    model_sample_rate = int(model.model.sample_rate)
    # Stable Audio's convenience API defaults to a ~120 second sample buffer.
    # It adapts shorter requests down, but cannot grow beyond that buffer unless
    # the caller supplies a matching upper bound.
    sample_size = int((duration + 7.0) * model_sample_rate)
    audio = model.generate(prompt=prompt, duration=duration, sample_size=sample_size)[0].cpu()
    if output_rate != model_sample_rate:
        audio = resample(audio, model_sample_rate, output_rate)

    # Stable Audio returns tensors as (channels, samples); the API DSP layer uses
    # soundfile's shape convention: (samples, channels).
    data = audio.transpose(0, 1).numpy()
    data = dsp.normalize_loudness_safely(data, output_rate, target_lufs=-16.0)
    return torch.from_numpy(data.T.copy()).clamp(-1, 1).numpy().T


def generate_batch(
    prompts: list[dict[str, Any]],
    *,
    sample_rate: int,
    model: str,
    out_dir: Path,
    on_progress: Callable[[float, str], None] | None = None,
    should_cancel: Callable[[], bool] | None = None,
) -> list[tuple[dict[str, Any], Path]]:
    """Generate tracks directly from the API process, without invoking scripts."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    total = max(1, len(prompts))
    model_name = _resolve_model_name(model)

    if on_progress:
        on_progress(0.12, f"Loading model: {model_name}")
    loaded_model = _load_model(model_name)

    produced: list[tuple[dict[str, Any], Path]] = []
    for index, spec in enumerate(prompts, start=1):
        if should_cancel and should_cancel():
            raise RuntimeError("Stable Audio generation cancelled")
        title = str(spec.get("title") or f"Track {index}")
        prompt = str(spec.get("prompt") or "")
        if not prompt:
            raise ValueError(f"Prompt item {index} must include prompt")
        duration = float(spec.get("duration", 180))
        if duration <= 0:
            raise ValueError(f"Prompt item {index} duration must be positive")

        if on_progress:
            frac = 0.12 + 0.83 * (index - 1) / total
            on_progress(frac, f"Rendering {index}/{total}: {title}")
        path = out_dir / f"{_slugify(title)}.flac"
        data = _generate_audio_array(loaded_model, prompt, duration, sample_rate)
        dsp.write_audio_file(
            path,
            data,
            sample_rate,
            title=title,
            genre=spec.get("genre"),
            description=prompt,
            track_number=index,
        )
        produced.append((spec, path))
        if on_progress:
            frac = min(0.95, 0.12 + 0.83 * index / total)
            on_progress(frac, f"Rendered {index}/{total} track(s)")

    if not produced:
        raise RuntimeError("Stable Audio produced no tracks.")
    return produced
