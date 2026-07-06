from __future__ import annotations

from datetime import timedelta

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from ..constants import utcnow
from ..deps import get_or_404, get_session
from ..models import Schedule
from ..schemas import ScheduleCreate, ScheduleUpdate

router = APIRouter(prefix="/schedules", tags=["schedules"])


def _initial_next_run(payload: ScheduleCreate):
    if payload.trigger_type == "interval":
        return utcnow() + timedelta(seconds=float(payload.trigger.get("seconds", 3600)))
    if payload.trigger_type == "date" and payload.trigger.get("run_at"):
        return None
    return None


@router.get("", response_model=list[Schedule])
async def list_schedules(session: AsyncSession = Depends(get_session)) -> list[Schedule]:
    res = await session.execute(select(Schedule).order_by(Schedule.created_at))
    return list(res.scalars().all())


@router.post("", response_model=Schedule, status_code=201)
async def create_schedule(
    payload: ScheduleCreate, session: AsyncSession = Depends(get_session)
) -> Schedule:
    schedule = Schedule(
        name=payload.name,
        action=payload.action,
        program_id=payload.program_id,
        stream_id=payload.stream_id,
        trigger_type=payload.trigger_type,
        trigger=payload.trigger,
        enabled=payload.enabled,
        next_run_at=_initial_next_run(payload),
    )
    session.add(schedule)
    await session.commit()
    await session.refresh(schedule)
    return schedule


@router.patch("/{schedule_id}", response_model=Schedule)
async def update_schedule(
    schedule_id: str,
    payload: ScheduleUpdate,
    session: AsyncSession = Depends(get_session),
) -> Schedule:
    schedule = await get_or_404(session, Schedule, schedule_id)
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(schedule, key, value)
    session.add(schedule)
    await session.commit()
    await session.refresh(schedule)
    return schedule


@router.delete("/{schedule_id}", status_code=204)
async def delete_schedule(schedule_id: str, session: AsyncSession = Depends(get_session)) -> None:
    schedule = await get_or_404(session, Schedule, schedule_id)
    await session.delete(schedule)
    await session.commit()
