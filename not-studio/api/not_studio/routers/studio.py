"""Studio: album batches, human track review, then YouTube-ready mixes."""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from ..deps import get_session
from ..models import HistoryItem, Job
from ..schemas import (
    GenerateAlbumRequest,
    GeneratePromptIdeasRequest,
    GeneratePromptIdeasResponse,
    GenerateTracksRequest,
    MakeVideoRequest,
    PromptProviderInfo,
    TrackReviewRequest,
)
from ..tasks.submit import submit_generate_tracks, submit_make_video
from ..prompt_generation import generate_prompt_ideas, prompt_provider_infos

router = APIRouter(prefix="/studio", tags=["studio"])


def build_album_prompts(payload: GenerateAlbumRequest) -> list[dict]:
    """Translate product controls into concrete music prompts for the backend."""
    mood = payload.mood.strip()
    styles = [s.strip() for s in payload.styles if s.strip()]
    style_text = ", ".join(styles) if styles else "genre-fluid instrumental"
    album = payload.album_title.strip() if payload.album_title else mood.title()

    prompts: list[dict] = []
    for index in range(1, payload.track_count + 1):
        prompt = (
            f"{mood} mood, {style_text}, instrumental full track, polished arrangement, "
            f"track {index} of {payload.track_count}, no vocals"
        )
        prompts.append(
            {
                "title": f"{album} {index:02d}",
                "prompt": prompt,
                "duration": payload.duration,
                "mood": mood,
                "styles": styles,
                "album_title": album,
                "track_index": index,
                "track_count": payload.track_count,
            }
        )
    return prompts


@router.post("/albums/generate", response_model=Job, status_code=201)
async def generate_album(
    payload: GenerateAlbumRequest,
    background_tasks: BackgroundTasks,
    session: AsyncSession = Depends(get_session),
) -> Job:
    """Generate an album candidate batch from mood, style and track count controls."""
    prompts = build_album_prompts(payload)
    return await submit_generate_tracks(
        background_tasks,
        session,
        prompts=prompts,
        provider=payload.provider,
        model=payload.model,
        album={
            "title": payload.album_title,
            "mood": payload.mood.strip(),
            "styles": [s.strip() for s in payload.styles if s.strip()],
            "track_count": payload.track_count,
            "duration": payload.duration,
        },
    )


@router.post("/generate", response_model=Job, status_code=201)
async def generate(
    payload: GenerateTracksRequest,
    background_tasks: BackgroundTasks,
    session: AsyncSession = Depends(get_session),
) -> Job:
    """Generate tracks from a prompt list (local Stable Audio 3 by default)."""
    if not payload.prompts:
        raise HTTPException(status_code=400, detail="Provide at least one prompt")
    return await submit_generate_tracks(
        background_tasks,
        session,
        prompts=[p.model_dump() for p in payload.prompts],
        provider=payload.provider,
        model=payload.model,
    )


@router.get("/tracks", response_model=list[HistoryItem])
async def list_tracks(
    session: AsyncSession = Depends(get_session),
    verdict: str | None = Query(default=None, pattern="^(liked|disliked|unreviewed)$"),
    limit: int = Query(default=200, le=1000),
) -> list[HistoryItem]:
    res = await session.execute(
        select(HistoryItem)
        .where(HistoryItem.kind == "track")
        .order_by(HistoryItem.created_at.desc())
        .limit(limit)
    )
    tracks = list(res.scalars().all())
    if verdict is None:
        return tracks
    return [
        t
        for t in tracks
        if (t.meta or {}).get("review", {}).get("verdict", "unreviewed") == verdict
    ]


@router.patch("/tracks/{item_id}/review", response_model=HistoryItem)
async def review_track(
    item_id: str,
    payload: TrackReviewRequest,
    session: AsyncSession = Depends(get_session),
) -> HistoryItem:
    item = await session.get(HistoryItem, item_id)
    if item is None or item.kind != "track":
        raise HTTPException(status_code=404, detail="Track not found")

    meta = dict(item.meta or {})
    meta["review"] = {
        "verdict": payload.verdict,
        "note": payload.note,
        "reviewed_at": datetime.now(UTC).isoformat(),
    }
    item.meta = meta
    session.add(item)
    await session.commit()
    await session.refresh(item)
    return item


@router.post("/videos", response_model=Job, status_code=201)
async def make_video(
    payload: MakeVideoRequest,
    background_tasks: BackgroundTasks,
    session: AsyncSession = Depends(get_session),
) -> Job:
    """Crossfade the selected tracks and render a YouTube-ready video."""
    if not payload.item_ids:
        raise HTTPException(status_code=400, detail="Select at least one track")
    return await submit_make_video(
        background_tasks,
        session,
        item_ids=payload.item_ids,
        title=payload.title,
        visualizer=payload.visualizer,
        crossfade_seconds=payload.crossfade_seconds,
    )


@router.get("/prompt-providers", response_model=list[PromptProviderInfo])
async def list_prompt_providers() -> list[PromptProviderInfo]:
    return prompt_provider_infos()


@router.post("/prompts/generate", response_model=GeneratePromptIdeasResponse)
async def generate_prompts(payload: GeneratePromptIdeasRequest) -> GeneratePromptIdeasResponse:
    return await generate_prompt_ideas(payload)


@router.get("/videos", response_model=list[HistoryItem])
async def list_videos(
    session: AsyncSession = Depends(get_session),
    limit: int = Query(default=100, le=500),
) -> list[HistoryItem]:
    res = await session.execute(
        select(HistoryItem)
        .where(HistoryItem.kind == "video")
        .order_by(HistoryItem.created_at.desc())
        .limit(limit)
    )
    return list(res.scalars().all())
