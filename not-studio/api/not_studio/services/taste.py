from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from ..models import HistoryItem
from ..schemas import TasteExample, TasteProfile


def taste_example(item: HistoryItem) -> TasteExample:
    meta = item.meta or {}
    review = meta.get("review") or {}
    genre = str(meta.get("genre") or "").strip()
    if not genre:
        styles = meta.get("styles") or []
        genre = str(styles[0]) if styles else "unspecified"
    return TasteExample(
        title=item.title,
        genre=genre,
        prompt=str(meta.get("prompt") or ""),
        note=review.get("note"),
    )


async def build_taste_profile(session: AsyncSession, limit: int = 20) -> TasteProfile:
    res = await session.execute(
        select(HistoryItem)
        .where(HistoryItem.kind == "track")
        .order_by(HistoryItem.created_at.desc())
        .limit(500)
    )
    liked: list[TasteExample] = []
    for item in res.scalars().all():
        if (item.meta or {}).get("review", {}).get("verdict") == "liked":
            liked.append(taste_example(item))
            if len(liked) >= limit:
                break
    return TasteProfile(
        liked_genres={example.genre for example in liked},
        liked_examples=liked,
    )
