"""Pre-allocated buffer accounting (feature #4).

Shared by the buffer-tick (which decides when to generate the next batch) and the
API's buffer-status endpoint. A stream keeps >= ``buffer_min_seconds`` of ready
audio ahead of playout; each generated batch adds ``batch_target_seconds``.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from .constants import TERMINAL_JOB_STATUSES
from .models import Job, PlayoutSegment, Stream


async def ready_seconds(session: AsyncSession, stream_id: str) -> float:
    """Seconds of audio queued and not yet played (state == 'ready')."""
    res = await session.execute(
        select(PlayoutSegment.duration_seconds).where(
            PlayoutSegment.stream_id == stream_id,
            PlayoutSegment.state == "ready",
        )
    )
    return float(sum(res.scalars().all()))


async def segment_counts(session: AsyncSession, stream_id: str) -> tuple[int, int]:
    res = await session.execute(
        select(PlayoutSegment.state).where(PlayoutSegment.stream_id == stream_id)
    )
    states = list(res.scalars().all())
    ready = sum(1 for s in states if s == "ready")
    return ready, len(states)


async def has_active_batch_job(session: AsyncSession, stream_id: str) -> bool:
    """True if a batch job for this stream is queued or running (avoid double-gen)."""
    res = await session.execute(
        select(Job.status).where(Job.stream_id == stream_id, Job.type == "batch")
    )
    return any(s not in TERMINAL_JOB_STATUSES for s in res.scalars().all())


async def next_sequence(session: AsyncSession, stream_id: str) -> int:
    res = await session.execute(
        select(PlayoutSegment.sequence)
        .where(PlayoutSegment.stream_id == stream_id)
        .order_by(PlayoutSegment.sequence.desc())
        .limit(1)
    )
    top = res.scalars().first()
    return (top + 1) if top is not None else 0


async def front_sequence(session: AsyncSession, stream_id: str) -> int:
    """A sequence that sorts before all ready segments (breaking-news queue jump).

    The engine plays the lowest-sequence ``ready`` segment next, so an
    announcement placed here airs right after the current (``playing``) segment.
    """
    res = await session.execute(
        select(PlayoutSegment.sequence)
        .where(
            PlayoutSegment.stream_id == stream_id,
            PlayoutSegment.state == "ready",
        )
        .order_by(PlayoutSegment.sequence)
        .limit(1)
    )
    lowest_ready = res.scalars().first()
    if lowest_ready is None:
        return await next_sequence(session, stream_id)
    return lowest_ready - 1


async def needs_batch(session: AsyncSession, stream: Stream) -> bool:
    """Should we enqueue another batch right now?"""
    if stream.status not in ("live", "buffering"):
        return False
    if await has_active_batch_job(session, stream.id):
        return False
    return await ready_seconds(session, stream.id) < stream.buffer_min_seconds
