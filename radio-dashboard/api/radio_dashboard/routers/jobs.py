from __future__ import annotations

from arq.connections import ArqRedis
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from ..constants import utcnow
from ..deps import get_or_404, get_pool, get_session
from ..models import Job
from ..schemas import JobSubmit
from ..tasks.queue import cancel_job, submit_batch

router = APIRouter(prefix="/jobs", tags=["jobs"])


@router.post("", response_model=Job, status_code=201)
async def submit_job(
    payload: JobSubmit,
    request: Request,
    session: AsyncSession = Depends(get_session),
    pool: ArqRedis = Depends(get_pool),
) -> Job:
    """Submit a generation job (feature #1)."""
    if not payload.stream_id and not payload.program_id:
        raise HTTPException(status_code=400, detail="Provide stream_id and/or program_id")
    return await submit_batch(
        pool,
        session,
        stream_id=payload.stream_id,
        program_id=payload.program_id,
        target_seconds=payload.params.get("target_seconds"),
        job_type=payload.type,
    )


@router.get("", response_model=list[Job])
async def list_jobs(
    session: AsyncSession = Depends(get_session),
    stream_id: str | None = Query(default=None),
    status: str | None = Query(default=None),
    limit: int = Query(default=100, le=500),
) -> list[Job]:
    query = select(Job).order_by(Job.created_at.desc()).limit(limit)
    if stream_id:
        query = query.where(Job.stream_id == stream_id)
    if status:
        query = query.where(Job.status == status)
    res = await session.execute(query)
    return list(res.scalars().all())


@router.get("/{job_id}", response_model=Job)
async def get_job(job_id: str, session: AsyncSession = Depends(get_session)) -> Job:
    return await get_or_404(session, Job, job_id)


@router.post("/{job_id}/cancel", response_model=Job)
async def cancel(
    job_id: str,
    session: AsyncSession = Depends(get_session),
    pool: ArqRedis = Depends(get_pool),
) -> Job:
    """Cancel a queued/running job (feature #1)."""
    job = await get_or_404(session, Job, job_id)
    if job.status in ("completed", "failed", "cancelled"):
        return job
    await cancel_job(pool, job_id)
    # A queued (not-yet-started) job is removed from the queue and never runs, so
    # the worker won't update it — reflect the cancellation here.
    if job.status == "queued":
        job.status = "cancelled"
        job.finished_at = utcnow()
        job.message = "Cancelled before start"
        session.add(job)
        await session.commit()
        await session.refresh(job)
    return job
