from __future__ import annotations

from typing import TypeVar

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from .db import get_session  # noqa: F401 (re-exported for routers)

T = TypeVar("T")


async def get_or_404(session: AsyncSession, model: type[T], obj_id: str) -> T:
    obj = await session.get(model, obj_id)
    if obj is None:
        raise HTTPException(status_code=404, detail=f"{model.__name__} not found")
    return obj
