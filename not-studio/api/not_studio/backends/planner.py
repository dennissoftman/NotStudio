"""Local natural-language album planning with schema-constrained output."""

from __future__ import annotations

import json
import re
from typing import Any

from pydantic import ValidationError

from ..schemas import PromptPlan

MODEL_NAME = "Qwen/Qwen3-4B-Instruct-2507"
_ENGINES: dict[tuple[str, int, float], tuple[Any, Any, Any]] = {}

_COUNT_WORDS = {
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "eleven": 11,
    "twelve": 12,
    "thirteen": 13,
    "fourteen": 14,
    "fifteen": 15,
    "sixteen": 16,
    "seventeen": 17,
    "eighteen": 18,
    "nineteen": 19,
    "twenty": 20,
}


def requested_track_count(brief: str) -> int | None:
    item = r"(?:tracks?|songs?|pieces?)"
    numeric = re.search(rf"\b([1-9]|1\d|20)[- ]?{item}\b", brief, re.IGNORECASE)
    if numeric:
        return int(numeric.group(1))
    words = "|".join(_COUNT_WORDS)
    named = re.search(rf"\b({words})[- ]?{item}\b", brief, re.IGNORECASE)
    return _COUNT_WORDS.get(named.group(1).lower()) if named else None


def validate_plan_semantics(plan: PromptPlan, brief: str) -> list[str]:
    errors: list[str] = []
    expected = requested_track_count(brief)
    if expected is not None and len(plan.prompts) != expected:
        errors.append(f"brief requests {expected} tracks but plan contains {len(plan.prompts)}")
    titles = [prompt.title.casefold().strip() for prompt in plan.prompts]
    if len(set(titles)) != len(titles):
        errors.append("track titles must be unique")
    if not (plan.album_title or "").strip():
        errors.append("album_title is required")
    if not (plan.artwork_prompt or "").strip():
        errors.append("album artwork_prompt is required")
    for index, prompt in enumerate(plan.prompts, start=1):
        if len(prompt.prompt.split()) < 8:
            errors.append(f"track {index} music prompt is too vague")
        if not (prompt.artwork_prompt or "").strip():
            errors.append(f"track {index} artwork_prompt is required")
    return errors


def _system_prompt(duration_default: float) -> str:
    return f"""You are the album planner inside Not Studio. Convert the user's free-form album
brief into a coherent instrumental album plan for ACE-Step 1.5 and FLUX.2 Klein.

Requirements:
- Infer the requested track count, mood, genre, story arc, and production direction.
- Use exactly the requested number of tracks when the brief specifies one; otherwise choose 4.
- Every music prompt must be directly usable by ACE-Step: instrumentation, arrangement, texture,
  energy, tempo feel, progression, and an explicit no-vocals/instrumental instruction.
- Default duration is {duration_default:g} seconds and every duration must be 15-240 seconds.
- Create an original album title and unique track titles. Do not imitate named artists or songs.
- Make the sequence tell the requested story while remaining a coherent album.
- Provide a shared visual direction, one square album-cover prompt, and a distinct square prompt
  for every track. Artwork prompts must request no text, logo, watermark, or recognizable brand.
- Taste examples are preference signals only. Never copy their titles or prompts.
- Return only data matching the supplied JSON schema."""


def build_planner_messages(
    brief: str,
    *,
    artwork_guidance: str,
    taste_profile: dict[str, Any],
    duration_default: float,
    correction: list[str] | None = None,
) -> list[dict[str, str]]:
    payload = {
        "album_brief": brief,
        "artwork_guidance": artwork_guidance,
        "taste_profile": taste_profile,
    }
    user = json.dumps(payload, ensure_ascii=False, indent=2)
    if correction:
        user += "\n\nCorrect these validation failures:\n- " + "\n- ".join(correction)
    return [
        {"role": "system", "content": _system_prompt(duration_default)},
        {"role": "user", "content": user},
    ]


def _engine(model: str, max_model_len: int, memory: float) -> tuple[Any, Any, Any]:
    key = (model, max_model_len, memory)
    if key not in _ENGINES:
        try:
            import torch
            from outlines import Generator, from_transformers
            from transformers import AutoModelForCausalLM, AutoTokenizer
        except ImportError as exc:  # pragma: no cover - exercised by CUDA smoke test
            raise RuntimeError(
                "Local planner requires Transformers and Outlines; run uv sync"
            ) from exc
        if not torch.cuda.is_available():
            raise RuntimeError("Local Qwen planning requires an NVIDIA CUDA GPU")
        tokenizer = AutoTokenizer.from_pretrained(model, trust_remote_code=False)
        loaded = AutoModelForCausalLM.from_pretrained(
            model,
            torch_dtype=torch.bfloat16,
            device_map={"": "cuda"},
            trust_remote_code=False,
            low_cpu_mem_usage=True,
        )
        loaded.eval()
        wrapped = from_transformers(loaded, tokenizer)
        _ENGINES[key] = (tokenizer, Generator(wrapped, PromptPlan), loaded)
    return _ENGINES[key]


def generate_album_plan(
    brief: str,
    *,
    artwork_guidance: str = "",
    taste_profile: dict[str, Any] | None = None,
    duration_default: float = 180.0,
    model: str = MODEL_NAME,
    max_model_len: int = 8192,
    gpu_memory_utilization: float = 0.8,
) -> dict[str, Any]:
    """Generate and semantically validate a plan, allowing one corrective pass."""
    _tokenizer, generator, _loaded = _engine(model, max_model_len, gpu_memory_utilization)
    from outlines.inputs import Chat

    corrections: list[str] | None = None

    for _ in range(2):
        messages = build_planner_messages(
            brief,
            artwork_guidance=artwork_guidance,
            taste_profile=taste_profile or {"liked_genres": [], "liked_examples": []},
            duration_default=duration_default,
            correction=corrections,
        )
        raw = generator(
            Chat(messages),
            max_new_tokens=min(6000, max_model_len - 1024),
            do_sample=True,
            temperature=0.7,
            top_p=0.9,
        )
        try:
            plan = PromptPlan.model_validate_json(raw)
        except ValidationError as exc:
            corrections = [str(exc)]
            continue
        corrections = validate_plan_semantics(plan, brief)
        if not corrections:
            return plan.model_dump(exclude_none=True)
    raise RuntimeError("Planner returned an invalid album plan: " + "; ".join(corrections or []))


def preload_planner(
    model: str = MODEL_NAME, max_model_len: int = 8192, gpu_memory_utilization: float = 0.8
) -> dict[str, str]:
    _, _, loaded = _engine(model, max_model_len, gpu_memory_utilization)
    return {
        "status": "ready",
        "provider": "qwen_local",
        "model": model,
        "device": str(getattr(loaded, "device", "cuda")),
    }
