from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from ..db import session_scope
from ..deps import get_or_404, get_session
from ..models import HistoryItem

router = APIRouter(prefix="/history", tags=["history"])

_MEDIA_TYPES = {
    ".flac": "audio/flac",
    ".wav": "audio/wav",
    ".mp3": "audio/mpeg",
    ".m4a": "audio/mp4",
    ".mp4": "video/mp4",
}


@router.get("", response_model=list[HistoryItem])
async def list_history(
    session: AsyncSession = Depends(get_session),
    limit: int = Query(default=100, le=500),
) -> list[HistoryItem]:
    query = select(HistoryItem).order_by(HistoryItem.created_at.desc()).limit(limit)
    res = await session.execute(query)
    return list(res.scalars().all())


@router.get("/{item_id}", response_model=HistoryItem)
async def get_item(item_id: str, session: AsyncSession = Depends(get_session)) -> HistoryItem:
    return await get_or_404(session, HistoryItem, item_id)


@router.get("/{item_id}/audio")
async def get_audio(item_id: str) -> FileResponse:
    # Release the database connection before Starlette starts streaming the file.
    # A library page may request metadata for many audio elements concurrently.
    async with session_scope() as session:
        item = await get_or_404(session, HistoryItem, item_id)
        item_path = item.path
        item_title = item.title
    path = Path(item_path)
    if not path.exists():
        raise HTTPException(status_code=404, detail="Audio file missing")
    media = _MEDIA_TYPES.get(path.suffix.lower(), "application/octet-stream")
    safe_title = "".join(c for c in item_title if c.isalnum() or c in " ._-").strip()
    filename = f"{safe_title or 'track'}{path.suffix.lower()}"
    return FileResponse(path, media_type=media, filename=filename)


@router.delete("/{item_id}", status_code=204)
async def delete_item(item_id: str, session: AsyncSession = Depends(get_session)) -> None:
    item = await get_or_404(session, HistoryItem, item_id)
    Path(item.path).unlink(missing_ok=True)
    await session.delete(item)
    await session.commit()
