from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from ..backends.registry import PROVIDERS, provider_infos
from ..deps import get_or_404, get_session
from ..models import Backend
from ..schemas import BackendCreate, BackendInfo, BackendUpdate

router = APIRouter(prefix="/backends", tags=["backends"])


@router.get("/providers", response_model=list[BackendInfo])
async def list_providers() -> list[BackendInfo]:
    """Static provider capabilities + availability (drives the UI picker)."""
    return provider_infos()


@router.get("", response_model=list[Backend])
async def list_backends(session: AsyncSession = Depends(get_session)) -> list[Backend]:
    res = await session.execute(select(Backend).order_by(Backend.created_at))
    return list(res.scalars().all())


@router.post("", response_model=Backend, status_code=201)
async def create_backend(
    payload: BackendCreate, session: AsyncSession = Depends(get_session)
) -> Backend:
    provider = PROVIDERS.get(payload.provider)
    if provider is None or payload.kind not in provider.classes:
        raise HTTPException(
            status_code=400,
            detail=f"Provider {payload.provider!r} does not support kind {payload.kind!r}",
        )
    backend = Backend(
        name=payload.name,
        kind=payload.kind,
        provider=payload.provider,
        config=payload.config,
        enabled=payload.enabled,
    )
    session.add(backend)
    await session.commit()
    await session.refresh(backend)
    return backend


@router.patch("/{backend_id}", response_model=Backend)
async def update_backend(
    backend_id: str,
    payload: BackendUpdate,
    session: AsyncSession = Depends(get_session),
) -> Backend:
    backend = await get_or_404(session, Backend, backend_id)
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(backend, key, value)
    session.add(backend)
    await session.commit()
    await session.refresh(backend)
    return backend


@router.delete("/{backend_id}", status_code=204)
async def delete_backend(backend_id: str, session: AsyncSession = Depends(get_session)) -> None:
    backend = await get_or_404(session, Backend, backend_id)
    await session.delete(backend)
    await session.commit()
