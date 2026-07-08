"""LLM adapters for generating audio prompts from human taste controls."""

from __future__ import annotations

import json
import re
import socket
from urllib.parse import urlparse

import httpx
from fastapi import HTTPException

from .config import get_settings
from .schemas import (
    GeneratePromptIdeasRequest,
    GeneratePromptIdeasResponse,
    PromptProviderInfo,
    PromptSpec,
)


def prompt_provider_infos() -> list[PromptProviderInfo]:
    settings = get_settings()
    lm_studio_ready = _endpoint_reachable(settings.lm_studio_base_url)
    return [
        PromptProviderInfo(
            provider="lm_studio",
            available=lm_studio_ready,
            detail=(
                f"Local server ready at {settings.lm_studio_base_url}."
                if lm_studio_ready
                else f"Start the local server at {settings.lm_studio_base_url}."
            ),
            default_model=settings.lm_studio_model,
        ),
        PromptProviderInfo(
            provider="gemini",
            available=bool(settings.gemini_api_key),
            detail="Set NOT_STUDIO_GEMINI_API_KEY to enable Gemini prompt generation.",
            default_model=settings.gemini_model,
        ),
        PromptProviderInfo(
            provider="openai",
            available=bool(settings.openai_api_key),
            detail="Set NOT_STUDIO_OPENAI_API_KEY to enable OpenAI prompt generation.",
            default_model=settings.openai_model,
        ),
        PromptProviderInfo(
            provider="anthropic",
            available=bool(settings.anthropic_api_key),
            detail="Set NOT_STUDIO_ANTHROPIC_API_KEY to enable Anthropic prompt generation.",
            default_model=settings.anthropic_model,
        ),
    ]


def _endpoint_reachable(url: str) -> bool:
    parsed = urlparse(url)
    host = parsed.hostname or "localhost"
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    try:
        with socket.create_connection((host, port), timeout=0.15):
            return True
    except OSError:
        return False


async def generate_prompt_ideas(
    payload: GeneratePromptIdeasRequest,
) -> GeneratePromptIdeasResponse:
    settings = get_settings()
    model = payload.model or _default_model(payload.provider)
    messages = _messages(payload)

    if payload.provider == "lm_studio":
        text = await _chat_completions(
            base_url=settings.lm_studio_base_url,
            api_key=settings.lm_studio_api_key or "lm-studio",
            model=model,
            messages=messages,
        )
    elif payload.provider == "openai":
        if not settings.openai_api_key:
            raise HTTPException(
                status_code=400, detail="NOT_STUDIO_OPENAI_API_KEY is not configured"
            )
        text = await _chat_completions(
            base_url=settings.openai_base_url,
            api_key=settings.openai_api_key,
            model=model,
            messages=messages,
        )
    elif payload.provider == "anthropic":
        if not settings.anthropic_api_key:
            raise HTTPException(
                status_code=400, detail="NOT_STUDIO_ANTHROPIC_API_KEY is not configured"
            )
        text = await _anthropic(settings.anthropic_api_key, model, messages)
    else:
        if not settings.gemini_api_key:
            raise HTTPException(
                status_code=400, detail="NOT_STUDIO_GEMINI_API_KEY is not configured"
            )
        text = await _gemini(settings.gemini_api_key, model, messages)

    prompts = _parse_prompts(text, payload)
    return GeneratePromptIdeasResponse(prompts=prompts, provider=payload.provider, model=model)


def _default_model(provider: str) -> str:
    settings = get_settings()
    return {
        "lm_studio": settings.lm_studio_model,
        "openai": settings.openai_model,
        "anthropic": settings.anthropic_model,
        "gemini": settings.gemini_model,
    }[provider]


def _messages(payload: GeneratePromptIdeasRequest) -> list[dict[str, str]]:
    styles = ", ".join(payload.styles) if payload.styles else "open style"
    title = payload.album_title or payload.mood.title()
    user = f"""
Create {payload.track_count} production-ready text prompts for AI instrumental music generation.
Album title: {title}
Mood: {payload.mood}
Styles: {styles}
Taste notes from human reviewer: {payload.taste_notes or "none"}

Return strict JSON only:
[
  {{"title": "Track title", "prompt": "detailed audio generation prompt", "duration": 180}}
]

Every prompt must be instrumental, specific about arrangement, sound palette, energy, tempo feel,
and must avoid artist names, copyrighted song references, and vocals unless explicitly requested.
"""
    return [
        {
            "role": "system",
            "content": "You are a music director who writes concise prompts for audio-generation models.",
        },
        {"role": "user", "content": user.strip()},
    ]


async def _chat_completions(
    *, base_url: str, api_key: str, model: str, messages: list[dict[str, str]]
) -> str:
    url = base_url.rstrip("/") + "/chat/completions"
    async with httpx.AsyncClient(timeout=90) as client:
        res = await client.post(
            url,
            headers={"Authorization": f"Bearer {api_key}"},
            json={"model": model, "messages": messages, "temperature": 0.8},
        )
    if res.status_code >= 400:
        raise HTTPException(status_code=502, detail=f"Prompt provider failed: {res.text[:500]}")
    body = res.json()
    return str(body["choices"][0]["message"]["content"])


async def _anthropic(api_key: str, model: str, messages: list[dict[str, str]]) -> str:
    system = messages[0]["content"]
    user = messages[1]["content"]
    async with httpx.AsyncClient(timeout=90) as client:
        res = await client.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": model,
                "max_tokens": 2000,
                "temperature": 0.8,
                "system": system,
                "messages": [{"role": "user", "content": user}],
            },
        )
    if res.status_code >= 400:
        raise HTTPException(status_code=502, detail=f"Anthropic failed: {res.text[:500]}")
    body = res.json()
    return "".join(part.get("text", "") for part in body.get("content", []))


async def _gemini(api_key: str, model: str, messages: list[dict[str, str]]) -> str:
    prompt = messages[0]["content"] + "\n\n" + messages[1]["content"]
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    async with httpx.AsyncClient(timeout=90) as client:
        res = await client.post(
            url,
            params={"key": api_key},
            json={"contents": [{"parts": [{"text": prompt}]}]},
        )
    if res.status_code >= 400:
        raise HTTPException(status_code=502, detail=f"Gemini failed: {res.text[:500]}")
    body = res.json()
    return str(body["candidates"][0]["content"]["parts"][0]["text"])


def _parse_prompts(text: str, payload: GeneratePromptIdeasRequest) -> list[PromptSpec]:
    raw = _extract_json(text)
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise HTTPException(
            status_code=502, detail=f"Prompt provider returned invalid JSON: {exc}"
        ) from exc
    if not isinstance(data, list):
        raise HTTPException(
            status_code=502, detail="Prompt provider returned JSON that is not a list"
        )

    prompts: list[PromptSpec] = []
    for index, item in enumerate(data[: payload.track_count], start=1):
        if not isinstance(item, dict):
            continue
        title = str(
            item.get("title") or f"{payload.album_title or payload.mood.title()} {index:02d}"
        )
        prompt = str(item.get("prompt") or "").strip()
        if not prompt:
            continue
        duration = float(item.get("duration") or 180)
        prompts.append(PromptSpec(title=title, prompt=prompt, duration=duration))
    if not prompts:
        raise HTTPException(status_code=502, detail="Prompt provider returned no usable prompts")
    return prompts


def _extract_json(text: str) -> str:
    stripped = text.strip()
    if stripped.startswith("["):
        return stripped
    match = re.search(r"```(?:json)?\s*(\[.*?\])\s*```", stripped, flags=re.DOTALL)
    if match:
        return match.group(1)
    start = stripped.find("[")
    end = stripped.rfind("]")
    if start >= 0 and end > start:
        return stripped[start : end + 1]
    return stripped
