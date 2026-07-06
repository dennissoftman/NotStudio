"""Periodic ticks run by the arq worker.

- ``buffer_tick`` keeps every live/buffering stream topped up to its minimum
  (feature #4): if < buffer_min_seconds is ready and nothing is generating, it
  submits the next batch.
- ``schedule_tick`` fires due Schedules (feature #1): interval / one-shot date /
  a small 5-field cron matcher.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from sqlmodel import select

from .. import buffer as buffer_mod
from ..constants import utcnow
from ..db import session_scope
from ..models import Schedule, Stream
from .queue import submit_batch


async def buffer_tick(ctx: dict[str, Any]) -> int:
    """Enqueue batches for streams that have dropped below their buffer minimum."""
    pool = ctx["redis"]
    submitted = 0
    async with session_scope() as session:
        res = await session.execute(select(Stream).where(Stream.status.in_(("live", "buffering"))))
        streams = res.scalars().all()
        for stream in streams:
            if await buffer_mod.needs_batch(session, stream):
                await submit_batch(
                    pool,
                    session,
                    stream_id=stream.id,
                    program_id=stream.program_id,
                    target_seconds=stream.batch_target_seconds,
                )
                submitted += 1
    return submitted


async def schedule_tick(ctx: dict[str, Any]) -> int:
    pool = ctx["redis"]
    now = utcnow()
    fired = 0
    async with session_scope() as session:
        res = await session.execute(select(Schedule).where(Schedule.enabled == True))  # noqa: E712
        schedules = res.scalars().all()
        for schedule in schedules:
            if not _is_due(schedule, now):
                continue
            await _run_schedule(pool, session, schedule)
            schedule.last_run_at = now
            schedule.next_run_at = _next_run(schedule, now)
            session.add(schedule)
            await session.commit()
            fired += 1
    return fired


async def _run_schedule(pool: Any, session: Any, schedule: Schedule) -> None:
    if schedule.action == "render_batch" and schedule.stream_id:
        stream = await session.get(Stream, schedule.stream_id)
        await submit_batch(
            pool,
            session,
            stream_id=schedule.stream_id,
            program_id=schedule.program_id or (stream.program_id if stream else None),
            target_seconds=stream.batch_target_seconds if stream else None,
            schedule_id=schedule.id,
        )
    elif schedule.action in ("start_stream", "stop_stream") and schedule.stream_id:
        stream = await session.get(Stream, schedule.stream_id)
        if stream:
            stream.status = "buffering" if schedule.action == "start_stream" else "stopped"
            stream.updated_at = utcnow()
            session.add(stream)


def _is_due(schedule: Schedule, now: datetime) -> bool:
    trig = schedule.trigger or {}
    last = schedule.last_run_at

    if schedule.trigger_type == "interval":
        seconds = float(trig.get("seconds", 3600))
        if last is None:
            return True
        return (now - _aware(last)).total_seconds() >= seconds

    if schedule.trigger_type == "date":
        run_at = trig.get("run_at")
        if not run_at or last is not None:
            return False
        return now >= _parse_iso(run_at)

    if schedule.trigger_type == "cron":
        expr = trig.get("expr", "* * * * *")
        if last is not None and _aware(last).replace(second=0, microsecond=0) == now.replace(
            second=0, microsecond=0
        ):
            return False  # already fired this minute
        return _cron_matches(expr, now)

    return False


def _next_run(schedule: Schedule, now: datetime) -> datetime | None:
    if schedule.trigger_type == "interval":
        return now + timedelta(seconds=float((schedule.trigger or {}).get("seconds", 3600)))
    return None  # cron/date computed on the fly


# --- helpers ------------------------------------------------------------------
def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _parse_iso(value: str) -> datetime:
    return _aware(datetime.fromisoformat(value.replace("Z", "+00:00")))


def _cron_matches(expr: str, now: datetime) -> bool:
    """Minimal 5-field cron: minute hour day-of-month month day-of-week (UTC)."""
    fields = expr.split()
    if len(fields) != 5:
        return False
    minute, hour, dom, month, dow = fields
    return (
        _field_matches(minute, now.minute, 0, 59)
        and _field_matches(hour, now.hour, 0, 23)
        and _field_matches(dom, now.day, 1, 31)
        and _field_matches(month, now.month, 1, 12)
        and _field_matches(dow, now.weekday() + 1 if now.weekday() != 6 else 0, 0, 6)
    )


def _field_matches(spec: str, value: int, low: int, high: int) -> bool:
    for part in spec.split(","):
        if part == "*":
            return True
        step = 1
        if "/" in part:
            base, step_s = part.split("/", 1)
            step = int(step_s)
            part = base if base != "*" else f"{low}-{high}"
        if "-" in part:
            start, end = (int(x) for x in part.split("-", 1))
        else:
            start = end = int(part)
        if start <= value <= end and (value - start) % step == 0:
            return True
    return False
