"""Enqueue helpers + arq connection wiring.

A submitted Job row shares its id with the arq job id, so the same id is used to
track (status) and cancel (abort) it.
"""

from __future__ import annotations

from arq.connections import ArqRedis, RedisSettings, create_pool
from arq.jobs import Job as ArqJob
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..constants import utcnow
from ..models import Job

RENDER_BATCH_FUNCTION = "render_batch_job"


def redis_settings() -> RedisSettings:
    settings = RedisSettings.from_dsn(get_settings().redis_url)
    settings.conn_retries = 2  # fail fast so the API boots quickly when Redis is down
    return settings


async def create_arq_pool() -> ArqRedis:
    return await create_pool(redis_settings())


async def submit_batch(
    pool: ArqRedis,
    session: AsyncSession,
    *,
    stream_id: str | None,
    program_id: str | None = None,
    target_seconds: float | None = None,
    job_type: str = "batch",
    schedule_id: str | None = None,
) -> Job:
    """Create a Job row and enqueue it on arq (submit)."""
    job = Job(
        type=job_type,
        status="queued",
        stream_id=stream_id,
        program_id=program_id,
        schedule_id=schedule_id,
        params={"target_seconds": target_seconds},
        enqueued_at=utcnow(),
    )
    session.add(job)
    await session.commit()
    await session.refresh(job)

    await pool.enqueue_job(RENDER_BATCH_FUNCTION, job.id, _job_id=job.id)
    return job


async def cancel_job(pool: ArqRedis, job_id: str) -> bool:
    """Abort a queued/running arq job (cancel). Returns True if it was aborted."""
    arq_job = ArqJob(job_id, pool)
    try:
        return await arq_job.abort(timeout=5)
    except Exception:
        # Job may have already finished / not be abortable.
        return False
