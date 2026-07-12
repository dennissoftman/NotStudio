from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Response, WebSocket, WebSocketDisconnect, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from ..constants import utcnow
from ..deps import get_or_404, get_session
from ..models import HistoryItem, Job
from ..tasks.registry import cancel_job_task
from ..tasks.events import jobs_version, notify_jobs_changed, wait_for_jobs_changed

router = APIRouter(prefix="/jobs", tags=["jobs"])


async def _jobs_snapshot() -> list[dict]:
    from ..db import session_scope

    async with session_scope() as session:
        res = await session.execute(select(Job).order_by(Job.created_at.desc()).limit(100))
        return [job.model_dump(mode="json") for job in res.scalars().all()]


@router.websocket("/ws")
async def jobs_websocket(websocket: WebSocket) -> None:
    await websocket.accept()
    version = jobs_version()
    previous: list[dict] | None = None
    try:
        while True:
            snapshot = await _jobs_snapshot()
            if snapshot != previous:
                await websocket.send_json({"type": "jobs", "jobs": snapshot})
                previous = snapshot
            version = await wait_for_jobs_changed(version)
    except WebSocketDisconnect:
        return


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
    cancel_job_task(job_id)
    await notify_jobs_changed()
    return job


@router.delete("/{job_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_job(job_id: str, session: AsyncSession = Depends(get_session)) -> Response:
    job = await get_or_404(session, Job, job_id)
    if job.status in ("queued", "in_progress"):
        job.status = "cancelled"
        job.finished_at = utcnow()
        job.message = "Removed while running"
        session.add(job)
        cancel_job_task(job_id)
    res = await session.execute(select(HistoryItem).where(HistoryItem.job_id == job_id))
    for item in res.scalars().all():
        item.job_id = None
        session.add(item)
    await session.delete(job)
    await session.commit()
    await notify_jobs_changed()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
