"""Local job submission helpers for FastAPI background tasks."""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from fastapi import BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession

from ..constants import utcnow
from ..models import Job
from .jobs import generate_tracks_job, make_video_job


async def submit_generate_tracks(
    background_tasks: BackgroundTasks,
    session: AsyncSession,
    *,
    prompts: list[dict],
    provider: str | None = None,
    model: str | None = None,
    album: dict | None = None,
) -> Job:
    job = Job(
        type="generate_tracks",
        status="queued",
        params={"prompts": prompts, "provider": provider, "model": model, "album": album or {}},
        enqueued_at=utcnow(),
    )
    return await _submit(background_tasks, session, job, generate_tracks_job)


async def submit_make_video(
    background_tasks: BackgroundTasks,
    session: AsyncSession,
    *,
    item_ids: list[str],
    title: str | None = None,
    visualizer: str = "cqt",
    crossfade_seconds: float = 6.0,
) -> Job:
    job = Job(
        type="make_video",
        status="queued",
        params={
            "item_ids": item_ids,
            "title": title,
            "visualizer": visualizer,
            "crossfade_seconds": crossfade_seconds,
        },
        enqueued_at=utcnow(),
    )
    return await _submit(background_tasks, session, job, make_video_job)


async def _submit(
    background_tasks: BackgroundTasks,
    session: AsyncSession,
    job: Job,
    runner: Callable[[str], Awaitable[dict]],
) -> Job:
    session.add(job)
    await session.commit()
    await session.refresh(job)
    background_tasks.add_task(runner, job.id)
    return job
