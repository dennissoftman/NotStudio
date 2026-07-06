from __future__ import annotations

from typing import TypeVar

from arq.connections import ArqRedis
from fastapi import HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from .db import get_session  # noqa: F401 (re-exported for routers)
from .streaming import PlayoutManager

T = TypeVar("T")


def get_pool(request: Request) -> ArqRedis:
    pool = getattr(request.app.state, "arq", None)
    if pool is None:
        raise HTTPException(
            status_code=503,
            detail="Task queue unavailable — is Redis running? (docker compose up -d redis)",
        )
    return pool


def get_playout(request: Request) -> PlayoutManager:
    return request.app.state.playout


async def get_or_404(session: AsyncSession, model: type[T], obj_id: str) -> T:
    obj = await session.get(model, obj_id)
    if obj is None:
        raise HTTPException(status_code=404, detail=f"{model.__name__} not found")
    return obj
