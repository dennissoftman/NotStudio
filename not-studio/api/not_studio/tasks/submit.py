"""Local job submission helpers for FastAPI background tasks."""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from sqlalchemy.ext.asyncio import AsyncSession

from ..constants import utcnow
from ..models import Job
from ..models import Album, GenerationRun
from ..schemas import PromptPlan
from .jobs import generate_tracks_job
from .planning import plan_album_job
from .artwork import generate_covers_job
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


async def submit_plan_album(
    session: AsyncSession,
    *,
    run: GenerationRun,
    taste_profile: dict,
    duration_default: float,
) -> Job:
    job = Job(
        type="plan_album",
        status="queued",
        params={
            "run_id": run.id,
            "brief": run.brief,
            "artwork_guidance": run.artwork_guidance,
            "taste_profile": taste_profile,
            "duration_default": duration_default,
        },
        enqueued_at=utcnow(),
    )
    session.add(job)
    await session.commit()
    await session.refresh(job)
    run.plan_job_id = job.id
    session.add(run)
    await session.commit()
    await notify_jobs_changed()
    start_job_task(job.id, plan_album_job)
    return job


async def submit_generation_run(
    session: AsyncSession, *, run: GenerationRun, generate_covers: bool = True
) -> Job:
    if not run.plan:
        raise ValueError("Generation run does not have an approved plan")
    plan = PromptPlan.model_validate(run.plan)
    album = Album(
        title=(plan.album_title or "Untitled Album").strip(),
        summary=(plan.summary or "").strip(),
        notes=(plan.notes or "").strip(),
        artwork_prompt=(plan.artwork_prompt or "").strip(),
        artwork_guidance=run.artwork_guidance,
        visual_direction=(plan.visual_direction.model_dump() if plan.visual_direction else {}),
    )
    session.add(album)
    await session.commit()
    await session.refresh(album)
    run.album_id = album.id
    run.status = "generating_tracks"
    run.stage = "generating_tracks"
    run.updated_at = utcnow()
    job = Job(
        type="generate_album_pipeline",
        status="queued",
        params={
            "prompts": [prompt.model_dump(exclude_none=True) for prompt in plan.prompts],
            "provider": "ace_step_local",
            "model": "ACE-Step 1.5",
            "album": {
                "id": album.id,
                "title": album.title,
                "summary": album.summary,
                "notes": album.notes,
                "artwork_prompt": album.artwork_prompt,
            },
            "generation_run_id": run.id,
            "generate_covers": generate_covers,
        },
        enqueued_at=utcnow(),
    )
    session.add(job)
    await session.commit()
    await session.refresh(job)
    run.generation_job_id = job.id
    session.add(run)
    await session.commit()
    await notify_jobs_changed()
    start_job_task(job.id, generate_tracks_job)
    return job


async def submit_cover_assets(session: AsyncSession, *, asset_ids: list[str]) -> Job:
    job = Job(
        type="generate_covers",
        status="queued",
        params={"asset_ids": asset_ids},
        enqueued_at=utcnow(),
    )
    return await _submit(session, job, generate_covers_job)


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
