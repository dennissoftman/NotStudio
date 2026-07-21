"""Opt-in CUDA smoke test for planner -> ACE-Step -> FLUX model swapping."""

from __future__ import annotations

import argparse
import asyncio
import json

from .backends.ace_step import generate_batch
from .backends.images.flux2_klein import generate_cover
from .backends.planner import generate_album_plan
from .config import get_settings
from .constants import new_id
from .preflight import collect_preflight
from .tasks.processes import run_in_model_process, shutdown_reusable_processes


async def smoke(skip_audio: bool = False) -> dict:
    settings = get_settings()
    readiness = collect_preflight()
    if not readiness["ready"]:
        raise RuntimeError("GPU preflight failed: " + "; ".join(readiness["recommendations"]))
    output_dir = settings.data_dir / "smoke" / new_id()
    output_dir.mkdir(parents=True, exist_ok=True)
    plan = await run_in_model_process(
        "qwen-planner",
        generate_album_plan,
        "A one-track instrumental ambient album about dawn after a storm.",
        artwork_guidance="Minimal cinematic abstraction, no text.",
        taste_profile={},
        duration_default=15.0,
        model=settings.planner_model,
        max_model_len=settings.planner_max_model_len,
        gpu_memory_utilization=settings.planner_gpu_memory_utilization,
    )
    audio_paths: list[str] = []
    if not skip_audio:
        produced = await run_in_model_process(
            "ace-step-local",
            generate_batch,
            plan["prompts"],
            sample_rate=settings.sample_rate,
            channels=settings.channels,
            model="ACE-Step 1.5",
            out_dir=output_dir / "audio",
            artist=settings.track_author,
        )
        audio_paths = [str(path) for _, path in produced]
    cover_path = output_dir / "cover.png"
    cover = await run_in_model_process(
        "flux2-klein",
        generate_cover,
        plan["artwork_prompt"],
        cover_path,
        generation_size=settings.cover_generation_size,
        output_size=settings.cover_output_size,
        steps=settings.cover_steps,
        model=settings.image_model,
    )
    await shutdown_reusable_processes()
    return {
        "status": "ok",
        "output_dir": str(output_dir),
        "plan": plan,
        "audio_paths": audio_paths,
        "cover": cover,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--skip-audio", action="store_true")
    args = parser.parse_args()
    result = asyncio.run(smoke(skip_audio=args.skip_audio))
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
