"""Studio: the simple two-step flow — generate tracks, then assemble a video."""

from __future__ import annotations

from arq.connections import ArqRedis
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from ..deps import get_pool, get_session
from ..models import HistoryItem, Job
from ..schemas import GenerateTracksRequest, MakeVideoRequest
from ..tasks.queue import submit_generate_tracks, submit_make_video

router = APIRouter(prefix="/studio", tags=["studio"])


@router.post("/generate", response_model=Job, status_code=201)
async def generate(
    payload: GenerateTracksRequest,
    session: AsyncSession = Depends(get_session),
    pool: ArqRedis = Depends(get_pool),
) -> Job:
    """Generate tracks from a prompt list (local Stable Audio 3 by default)."""
    if not payload.prompts:
        raise HTTPException(status_code=400, detail="Provide at least one prompt")
    return await submit_generate_tracks(
        pool,
        session,
        prompts=[p.model_dump() for p in payload.prompts],
        provider=payload.provider,
        model=payload.model,
    )


@router.get("/tracks", response_model=list[HistoryItem])
async def list_tracks(
    session: AsyncSession = Depends(get_session),
    limit: int = Query(default=200, le=1000),
) -> list[HistoryItem]:
    res = await session.execute(
        select(HistoryItem)
        .where(HistoryItem.kind == "track")
        .order_by(HistoryItem.created_at.desc())
        .limit(limit)
    )
    return list(res.scalars().all())


@router.post("/videos", response_model=Job, status_code=201)
async def make_video(
    payload: MakeVideoRequest,
    session: AsyncSession = Depends(get_session),
    pool: ArqRedis = Depends(get_pool),
) -> Job:
    """Crossfade the selected tracks and render a YouTube-ready video."""
    if not payload.item_ids:
        raise HTTPException(status_code=400, detail="Select at least one track")
    return await submit_make_video(
        pool,
        session,
        item_ids=payload.item_ids,
        title=payload.title,
        visualizer=payload.visualizer,
        crossfade_seconds=payload.crossfade_seconds,
    )


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
