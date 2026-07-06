from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from ..constants import utcnow
from ..deps import get_or_404, get_session
from ..models import Program
from ..schemas import ProgramCreate, ProgramUpdate

router = APIRouter(prefix="/programs", tags=["programs"])


@router.get("", response_model=list[Program])
async def list_programs(session: AsyncSession = Depends(get_session)) -> list[Program]:
    res = await session.execute(select(Program).order_by(Program.created_at))
    return list(res.scalars().all())


@router.get("/{program_id}", response_model=Program)
async def get_program(program_id: str, session: AsyncSession = Depends(get_session)) -> Program:
    return await get_or_404(session, Program, program_id)


@router.post("", response_model=Program, status_code=201)
async def create_program(
    payload: ProgramCreate, session: AsyncSession = Depends(get_session)
) -> Program:
    program = Program(
        name=payload.name,
        description=payload.description,
        music_backend_id=payload.music_backend_id,
        speech_backend_id=payload.speech_backend_id,
        config=payload.config.model_dump(),
    )
    session.add(program)
    await session.commit()
    await session.refresh(program)
    return program


@router.patch("/{program_id}", response_model=Program)
async def update_program(
    program_id: str,
    payload: ProgramUpdate,
    session: AsyncSession = Depends(get_session),
) -> Program:
    program = await get_or_404(session, Program, program_id)
    data = payload.model_dump(exclude_unset=True)
    if "config" in data and data["config"] is not None:
        program.config = payload.config.model_dump()  # type: ignore[union-attr]
        data.pop("config")
    for key, value in data.items():
        setattr(program, key, value)
    program.updated_at = utcnow()
    session.add(program)
    await session.commit()
    await session.refresh(program)
    return program


@router.delete("/{program_id}", status_code=204)
async def delete_program(program_id: str, session: AsyncSession = Depends(get_session)) -> None:
    program = await get_or_404(session, Program, program_id)
    await session.delete(program)
    await session.commit()
