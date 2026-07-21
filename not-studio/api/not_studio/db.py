from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy import text
from sqlmodel import SQLModel

from .config import get_settings

_settings = get_settings()

engine = create_async_engine(_settings.database_url, echo=_settings.debug, future=True)
async_session_maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def init_db() -> None:
    """Create tables. Imports models so their metadata is registered."""
    from . import models  # noqa: F401  (populates SQLModel.metadata)

    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
        # SQLModel's create_all creates new tables but does not add columns to an
        # existing SQLite database. Keep this tiny, idempotent migration here so
        # upgrades from the original title-keyed album schema remain automatic.
        columns = {
            row[1] for row in (await conn.execute(text("PRAGMA table_info(historyitem)"))).all()
        }
        if "album_id" not in columns:
            await conn.execute(text("ALTER TABLE historyitem ADD COLUMN album_id VARCHAR"))
            await conn.execute(
                text("CREATE INDEX IF NOT EXISTS ix_historyitem_album_id ON historyitem (album_id)")
            )
    await _backfill_album_ids()


async def _backfill_album_ids() -> None:
    """Give legacy tracks stable album IDs using their existing metadata titles."""
    from sqlmodel import select

    from .models import Album, HistoryItem

    async with async_session_maker() as session:
        result = await session.execute(
            select(HistoryItem).where(HistoryItem.kind == "track", HistoryItem.album_id.is_(None))
        )
        tracks = list(result.scalars().all())
        if not tracks:
            return
        albums: dict[str, Album] = {}
        for track in tracks:
            raw_album = (track.meta or {}).get("album") or {}
            title = (
                str(raw_album.get("title") or "").strip()
                if isinstance(raw_album, dict)
                else str(raw_album).strip()
            )
            if not title:
                continue
            album = albums.get(title)
            if album is None:
                existing = await session.execute(
                    select(Album)
                    .where(Album.title == title)
                    .order_by(Album.created_at.desc())
                    .limit(1)
                )
                album = existing.scalar_one_or_none() or Album(title=title)
                session.add(album)
                await session.flush()
                albums[title] = album
            track.album_id = album.id
            meta = dict(track.meta or {})
            current_album = meta.get("album") or {}
            legacy_album = (
                dict(current_album)
                if isinstance(current_album, dict)
                else {"title": str(current_album)}
            )
            legacy_album["id"] = album.id
            meta["album"] = legacy_album
            track.meta = meta
            session.add(track)
        await session.commit()


@asynccontextmanager
async def session_scope() -> AsyncIterator[AsyncSession]:
    """Context-managed session for workers / background code."""
    async with async_session_maker() as session:
        yield session


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency."""
    async with async_session_maker() as session:
        yield session
