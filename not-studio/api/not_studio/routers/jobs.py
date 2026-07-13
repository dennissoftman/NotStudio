from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, Query, Response, WebSocket, WebSocketDisconnect, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from ..constants import utcnow
from ..deps import get_or_404, get_session
from ..models import HistoryItem, Job
from ..tasks.jobs import generate_tracks_job, make_video_job
from ..tasks.registry import cancel_job_task, start_job_task
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
            changed = asyncio.create_task(wait_for_jobs_changed(version))
            disconnected = asyncio.create_task(websocket.receive())
            done, pending = await asyncio.wait(
                {changed, disconnected}, return_when=asyncio.FIRST_COMPLETED
            )
            for task in pending:
                task.cancel()
            if pending:
                await asyncio.gather(*pending, return_exceptions=True)
            if disconnected in done:
                return
            version = changed.result()
    except (WebSocketDisconnect, RuntimeError, asyncio.CancelledError):
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


@router.post("/{job_id}/retry", response_model=Job, status_code=201)
async def retry(job_id: str, session: AsyncSession = Depends(get_session)) -> Job:
    original = await get_or_404(session, Job, job_id)
    if original.status not in ("failed", "cancelled"):
        from fastapi import HTTPException

        raise HTTPException(status_code=409, detail="Only failed or cancelled jobs can be retried")
    runners = {
        "generate_tracks": generate_tracks_job,
        "make_video": make_video_job,
    }
    runner = runners.get(original.type)
    if runner is None:
        from fastapi import HTTPException

        raise HTTPException(status_code=400, detail=f"Job type {original.type} cannot be retried")
    retried = Job(
        type=original.type,
        status="queued",
        params=dict(original.params or {}),
        message="Queued retry",
        enqueued_at=utcnow(),
    )
    session.add(retried)
    await session.commit()
    await session.refresh(retried)
    await notify_jobs_changed()
    start_job_task(retried.id, runner)
    return retried


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
