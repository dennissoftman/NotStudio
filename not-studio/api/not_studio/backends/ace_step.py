from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from ..audio import dsp

MODEL_NAME = "ACE-Step 1.5"
MODEL_CONFIG = "acestep-v15-turbo"
_MODELS: dict[str, Any] = {}


@dataclass(frozen=True)
class GenerationInput:
    """ACE-Step request boundary, ready for additional generation tasks later."""

    prompt: str
    duration: float
    task: Literal["text2music"] = "text2music"
    lyrics: str = ""


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or "track"


def _load_model(model_name: str = MODEL_NAME) -> Any:
    model = _MODELS.get(model_name)
    if model is None:
        from acestep.handler import AceStepHandler

        model = AceStepHandler()
        status, ready = model.initialize_service(
            project_root="",
            config_path=MODEL_CONFIG,
            device="auto",
        )
        if not ready:
            raise RuntimeError(f"ACE-Step 1.5 failed to initialize: {status}")
        _MODELS[model_name] = model
    return model


def preload_model(model: str = MODEL_NAME) -> dict[str, str]:
    """Load ACE-Step in this worker and return serializable readiness data."""
    loaded_model = _load_model(model)
    return {
        "status": "ready",
        "provider": "ace_step_local",
        "model": MODEL_NAME,
        "device": str(getattr(loaded_model, "device", "unknown")),
    }


def _generated_path(result: Any, requested_path: Path) -> Path:
    audios = getattr(result, "audios", None)
    if audios and isinstance(audios[0], dict) and audios[0].get("path"):
        return Path(audios[0]["path"])
    if isinstance(result, list) and result and isinstance(result[0], (str, Path)):
        return Path(result[0])
    if requested_path.is_file():
        return requested_path
    raise RuntimeError("ACE-Step did not return a generated audio file")


def _remove_sidecar(audio_path: Path) -> None:
    audio_path.with_suffix(".json").unlink(missing_ok=True)
    audio_path.with_name(f"{audio_path.stem}_input_params.json").unlink(missing_ok=True)


def _run_generation(model: Any, request: GenerationInput, save_dir: Path) -> Any:
    from acestep.inference import GenerationConfig, GenerationParams, generate_music

    params = GenerationParams(
        task_type=request.task,
        caption=request.prompt,
        lyrics="[Instrumental]",
        instrumental=True,
        duration=request.duration,
        thinking=False,
        use_cot_metas=False,
        use_cot_caption=False,
        use_cot_language=False,
        shift=3.0,
    )
    config = GenerationConfig(batch_size=1, audio_format="wav")
    result = generate_music(model, None, params, config, save_dir=str(save_dir))
    if not result.success:
        raise RuntimeError(f"ACE-Step 1.5 generation failed: {result.error}")
    return result


def _generate_audio_file(
    model: Any,
    request: GenerationInput,
    output_path: Path,
    *,
    sample_rate: int,
    channels: int,
) -> None:
    """Run one ACE-Step task and convert its result to the app's FLAC policy."""
    if request.task != "text2music" or request.lyrics:
        raise ValueError("Only ACE-Step text-to-music generation is enabled for now")

    raw_path = output_path.with_suffix(".ace-step.wav")
    result = _run_generation(model, request, output_path.parent)
    generated_path = _generated_path(result, raw_path)
    try:
        data = dsp.load_audio_file(str(generated_path), sample_rate, channels)
        data = dsp.normalize_loudness_safely(data, sample_rate, target_lufs=-16.0)
        dsp.write_audio_file(output_path, data, sample_rate)
    finally:
        generated_path.unlink(missing_ok=True)
        _remove_sidecar(generated_path)


def generate_batch(
    prompts: list[dict[str, Any]],
    *,
    sample_rate: int,
    channels: int,
    model: str,
    out_dir: Path,
    artist: str = "Not Studio",
    release_date: str | None = None,
    on_progress: Callable[[float, str], None] | None = None,
    should_cancel: Callable[[], bool] | None = None,
) -> list[tuple[dict[str, Any], Path]]:
    """Generate prompt-first instrumental tracks with ACE-Step Text2Music."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    total = max(1, len(prompts))

    if on_progress:
        on_progress(0.12, f"Loading model: {MODEL_NAME}")
    loaded_model = _load_model(model)

    produced: list[tuple[dict[str, Any], Path]] = []
    for index, spec in enumerate(prompts, start=1):
        if should_cancel and should_cancel():
            raise RuntimeError("ACE-Step generation cancelled")
        title = str(spec.get("title") or f"Track {index}")
        prompt = str(spec.get("prompt") or "")
        if not prompt:
            raise ValueError(f"Prompt item {index} must include prompt")
        duration = float(spec.get("duration", 180))
        if duration <= 0:
            raise ValueError(f"Prompt item {index} duration must be positive")

        if on_progress:
            fraction = 0.12 + 0.83 * (index - 1) / total
            on_progress(fraction, f"Rendering {index}/{total}: {title}")
        path = out_dir / f"{_slugify(title)}.flac"
        _generate_audio_file(
            loaded_model,
            GenerationInput(prompt=prompt, duration=duration),
            path,
            sample_rate=sample_rate,
            channels=channels,
        )
        dsp.tag_flac(
            path,
            title=title,
            genre=spec.get("genre"),
            description=prompt,
            track_number=index,
            artist=artist,
            release_date=release_date,
        )
        produced.append((spec, path))
        if on_progress:
            fraction = min(0.95, 0.12 + 0.83 * index / total)
            on_progress(fraction, f"Rendered {index}/{total} track(s)")

    if not produced:
        raise RuntimeError("ACE-Step produced no tracks")
    return produced
