from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from ..constants import utcnow
from ..deps import get_or_404, get_session
from ..models import Job

router = APIRouter(prefix="/jobs", tags=["jobs"])


@router.get("", response_model=list[Job])
async def list_jobs(
    session: AsyncSession = Depends(get_session),
    status: str | None = Query(default=None),
    limit: int = Query(default=100, le=500),
) -> list[Job]:
    query = select(Job).order_by(Job.created_at.desc()).limit(limit)
    if status:
        query = query.where(Job.status == status)
    res = await session.execute(query)
    return list(res.scalars().all())


@router.get("/{job_id}", response_model=Job)
async def get_job(job_id: str, session: AsyncSession = Depends(get_session)) -> Job:
    return await get_or_404(session, Job, job_id)


@router.post("/{job_id}/cancel", response_model=Job)
async def cancel(job_id: str, session: AsyncSession = Depends(get_session)) -> Job:
    job = await get_or_404(session, Job, job_id)
    if job.status in ("completed", "failed", "cancelled"):
        return job
    job.status = "cancelled"
    job.finished_at = utcnow()
    job.message = "Cancellation requested"
    session.add(job)
    await session.commit()
    await session.refresh(job)
    return job
