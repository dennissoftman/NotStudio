"""Local job submission helpers for FastAPI background tasks."""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from sqlalchemy.ext.asyncio import AsyncSession

from ..constants import utcnow
from ..models import Job
from .jobs import generate_tracks_job, make_video_job
from .events import notify_jobs_changed
from .registry import start_job_task


async def submit_generate_tracks(
    session: AsyncSession,
    *,
    prompts: list[dict],
    provider: str | None = None,
    model: str | None = None,
    album: dict | None = None,
    replacement_item_id: str | None = None,
) -> Job:
    job = Job(
        type="generate_tracks",
        status="queued",
        params={
            "prompts": prompts,
            "provider": provider,
            "model": model,
            "album": album or {},
            "replacement_item_id": replacement_item_id,
        },
        enqueued_at=utcnow(),
    )
    return await _submit(session, job, generate_tracks_job)


async def submit_make_video(
    session: AsyncSession,
    *,
    item_ids: list[str],
    background_id: str,
) -> Job:
    job = Job(
        type="make_video",
        status="queued",
        params={
            "item_ids": item_ids,
            "background_id": background_id,
        },
        enqueued_at=utcnow(),
    )
    return await _submit(session, job, make_video_job)


async def _submit(
    session: AsyncSession,
    job: Job,
    runner: Callable[[str], Awaitable[dict]],
) -> Job:
    session.add(job)
    await session.commit()
    await session.refresh(job)
    await notify_jobs_changed()
    start_job_task(job.id, runner)
    return job
