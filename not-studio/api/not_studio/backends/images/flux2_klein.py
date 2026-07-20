"""FLUX.2 Klein 4B adapter for square cover generation and reference editing."""

from __future__ import annotations

import secrets
from collections.abc import Callable
from pathlib import Path
from typing import Any

from PIL import Image

MODEL_NAME = "black-forest-labs/FLUX.2-klein-4B"
_PIPELINES: dict[str, Any] = {}


def _load_pipeline(model: str = MODEL_NAME) -> Any:
    pipeline = _PIPELINES.get(model)
    if pipeline is not None:
        return pipeline
    try:
        import torch
        from diffusers import Flux2KleinPipeline
    except ImportError as exc:  # pragma: no cover - exercised by CUDA smoke test
        raise RuntimeError(
            "FLUX.2 generation dependencies are missing; run uv sync on the GPU host"
        ) from exc
    if not torch.cuda.is_available():
        raise RuntimeError("FLUX.2 Klein local generation requires an NVIDIA CUDA GPU")
    pipeline = Flux2KleinPipeline.from_pretrained(model, torch_dtype=torch.bfloat16)
    pipeline.to("cuda")
    pipeline.set_progress_bar_config(disable=True)
    _PIPELINES[model] = pipeline
    return pipeline


def preload_model(model: str = MODEL_NAME) -> dict[str, str]:
    _load_pipeline(model)
    import torch

    return {
        "status": "ready",
        "provider": "flux2_klein_local",
        "model": model,
        "device": str(torch.cuda.get_device_name(0)),
    }


def _reference_prompt(prompt: str, mode: str) -> str:
    if mode == "strong":
        return (
            "Use the supplied image as a strong visual style guide: preserve its medium, palette, "
            "texture, lighting language, and compositional rhythm without copying its subject. "
            + prompt
        )
    if mode == "loose":
        return (
            "Take loose visual inspiration from the supplied image's medium, palette, and texture, "
            "but create a new composition and subject. " + prompt
        )
    return prompt


def generate_cover(
    prompt: str,
    output_path: Path,
    *,
    reference_path: Path | None = None,
    reference_mode: str = "loose",
    generation_size: int = 1024,
    output_size: int = 2048,
    steps: int = 4,
    seed: int | None = None,
    model: str = MODEL_NAME,
    should_cancel: Callable[[], bool] | None = None,
) -> dict[str, Any]:
    """Generate one immutable PNG cover and return reproducibility metadata."""
    import torch

    if should_cancel and should_cancel():
        raise RuntimeError("Cover generation cancelled")
    actual_seed = seed if seed is not None else secrets.randbits(63)
    pipeline = _load_pipeline(model)
    kwargs: dict[str, Any] = {
        "prompt": prompt,
        "height": generation_size,
        "width": generation_size,
        "num_inference_steps": steps,
        "generator": torch.Generator(device="cuda").manual_seed(actual_seed),
    }
    reference: Image.Image | None = None
    if reference_path is not None:
        reference = Image.open(reference_path).convert("RGB")
        kwargs["image"] = reference
        kwargs["prompt"] = _reference_prompt(prompt, reference_mode)

    def callback(_pipe: Any, _step: int, _timestep: Any, callback_kwargs: dict) -> dict:
        if should_cancel and should_cancel():
            raise RuntimeError("Cover generation cancelled")
        return callback_kwargs

    kwargs["callback_on_step_end"] = callback
    try:
        image = pipeline(**kwargs).images[0].convert("RGB")
    finally:
        if reference is not None:
            reference.close()
    if image.size != (output_size, output_size):
        image = image.resize((output_size, output_size), Image.Resampling.LANCZOS)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    image.save(output_path, format="PNG", optimize=True)
    return {
        "path": str(output_path),
        "width": output_size,
        "height": output_size,
        "size_bytes": output_path.stat().st_size,
        "seed": actual_seed,
        "model": model,
        "provider": "flux2_klein_local",
        "generation_size": generation_size,
        "output_size": output_size,
        "steps": steps,
    }
