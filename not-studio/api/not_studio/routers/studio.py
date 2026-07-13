"""Studio: album batches, human track review, then YouTube-ready mixes."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from .. import video_export
from ..config import get_settings
from ..constants import new_id
from ..deps import get_session
from ..models import HistoryItem, Job
from ..schemas import (
    GenerateAlbumRequest,
    GenerateTracksRequest,
    MakeVideoRequest,
    PromptKitResponse,
    PromptSpec,
    TasteExample,
    TasteProfile,
    TrackReviewRequest,
    VideoBackgroundUpload,
)
from ..tasks.submit import submit_generate_tracks, submit_make_video

router = APIRouter(prefix="/studio", tags=["studio"])


def _track_duration(
    base_duration: float, variation_percent: float, index: int, total: int
) -> float:
    if variation_percent <= 0 or total <= 1:
        return base_duration
    spread = variation_percent / 100.0
    position = (index - 1) / (total - 1)
    deviation = (position * 2.0) - 1.0
    duration = round(base_duration * (1.0 + deviation * spread))
    return float(max(15, min(900, duration)))


def build_album_prompts(payload: GenerateAlbumRequest) -> list[dict]:
    """Translate product controls into concrete music prompts for the backend."""
    mood = payload.mood.strip()
    styles = [s.strip() for s in payload.styles if s.strip()]
    style_text = ", ".join(styles) if styles else "genre-fluid instrumental"
    album = payload.album_title.strip() if payload.album_title else mood.title()
    variation = payload.duration_variation_percent

    prompts: list[dict] = []
    for index in range(1, payload.track_count + 1):
        duration = _track_duration(payload.duration, variation, index, payload.track_count)
        prompt = (
            f"{mood} mood, {style_text}, instrumental full track, polished arrangement, "
            f"track {index} of {payload.track_count}, no vocals"
        )
        prompts.append(
            {
                "title": f"{album} {index:02d}",
                "genre": styles[0] if styles else "instrumental",
                "prompt": prompt,
                "duration": duration,
                "target_duration": payload.duration,
                "duration_variation_percent": variation,
                "mood": mood,
                "styles": styles,
                "album_title": album,
                "track_index": index,
                "track_count": payload.track_count,
            }
        )
    return prompts


@router.post("/albums/generate", response_model=Job, status_code=201)
async def generate_album(
    payload: GenerateAlbumRequest,
    session: AsyncSession = Depends(get_session),
) -> Job:
    """Generate an album candidate batch from mood, style and track count controls."""
    prompts = build_album_prompts(payload)
    return await submit_generate_tracks(
        session,
        prompts=prompts,
        provider=payload.provider,
        model=payload.model,
        album={
            "title": payload.album_title,
            "mood": payload.mood.strip(),
            "styles": [s.strip() for s in payload.styles if s.strip()],
            "track_count": payload.track_count,
            "duration": payload.duration,
            "duration_variation_percent": payload.duration_variation_percent,
        },
    )


@router.post("/generate", response_model=Job, status_code=201)
async def generate(
    payload: GenerateTracksRequest,
    session: AsyncSession = Depends(get_session),
) -> Job:
    """Generate tracks from a prompt list (local Stable Audio 3 by default)."""
    if not payload.prompts:
        raise HTTPException(status_code=400, detail="Provide at least one prompt")
    return await submit_generate_tracks(
        session,
        prompts=[p.model_dump() for p in payload.prompts],
        provider=payload.provider,
        model=payload.model,
    )


def _taste_example(item: HistoryItem) -> TasteExample:
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


def _genres(examples: list[TasteExample]) -> set[str]:
    return {example.genre for example in examples}


@router.get("/prompt-kit", response_model=PromptKitResponse)
async def get_prompt_kit(session: AsyncSession = Depends(get_session)) -> PromptKitResponse:
    """Return a GPT-ready prompt contract enriched with the user's reviews."""
    res = await session.execute(
        select(HistoryItem)
        .where(HistoryItem.kind == "track")
        .order_by(HistoryItem.created_at.desc())
        .limit(500)
    )
    liked: list[TasteExample] = []
    disliked: list[TasteExample] = []
    for item in res.scalars().all():
        verdict = (item.meta or {}).get("review", {}).get("verdict", "unreviewed")
        if verdict == "liked":
            if len(liked) < 20:
                liked.append(_taste_example(item))
        elif verdict == "disliked":
            if len(disliked) < 20:
                disliked.append(_taste_example(item))

    item_schema = PromptSpec.model_json_schema()
    return PromptKitResponse(
        task=(
            "Create a coherent batch of instrumental music-generation prompts. "
            "Return only the JSON array described by output_schema."
        ),
        requirements=[
            "Use liked examples as positive taste signals and disliked examples as negative signals.",
            "Infer reusable musical preferences; do not copy prior titles or prompts verbatim.",
            "Make each prompt specific about arrangement, instrumentation, texture, energy, and tempo feel.",
            "Avoid artist names and copyrighted song references.",
            "Keep duration between 15 and 900 seconds and provide a genre for every track.",
        ],
        output_schema={"type": "array", "minItems": 1, "maxItems": 20, "items": item_schema},
        example=[
            PromptSpec(
                title="Glass Transit",
                genre="ambient techno",
                prompt=(
                    "Instrumental ambient techno with a restrained four-on-the-floor pulse, "
                    "granular pads, muted sub bass, slow harmonic movement, and a spacious outro"
                ),
                duration=180,
            )
        ],
        taste_profile=TasteProfile(
            liked_genres=_genres(liked),
            disliked_genres=_genres(disliked),
            liked_examples=liked,
            disliked_examples=disliked,
        ),
    )


@router.get("/tracks", response_model=list[HistoryItem])
async def list_tracks(
    session: AsyncSession = Depends(get_session),
    verdict: str | None = Query(default=None, pattern="^(liked|disliked|unreviewed)$"),
    limit: int = Query(default=200, le=1000),
) -> list[HistoryItem]:
    res = await session.execute(
        select(HistoryItem)
        .where(HistoryItem.kind == "track")
        .order_by(HistoryItem.created_at.desc())
        .limit(limit)
    )
    tracks = list(res.scalars().all())
    if verdict is None:
        return tracks
    return [
        t
        for t in tracks
        if (t.meta or {}).get("review", {}).get("verdict", "unreviewed") == verdict
    ]


@router.patch("/tracks/{item_id}/review", response_model=HistoryItem)
async def review_track(
    item_id: str,
    payload: TrackReviewRequest,
    session: AsyncSession = Depends(get_session),
) -> HistoryItem:
    item = await session.get(HistoryItem, item_id)
    if item is None or item.kind != "track":
        raise HTTPException(status_code=404, detail="Track not found")

    meta = dict(item.meta or {})
    meta["review"] = {
        "verdict": payload.verdict,
        "note": payload.note,
        "reviewed_at": datetime.now(UTC).isoformat(),
    }
    item.meta = meta
    session.add(item)
    await session.commit()
    await session.refresh(item)
    return item


@router.post("/videos", response_model=Job, status_code=201)
async def make_video(
    payload: MakeVideoRequest,
    session: AsyncSession = Depends(get_session),
) -> Job:
    """Combine the selected tracks with a looping video using automatic defaults."""
    if not payload.item_ids:
        raise HTTPException(status_code=400, detail="Select at least one track")
    background_path = get_settings().video_backgrounds_dir / payload.background_id
    if not background_path.is_file():
        raise HTTPException(status_code=404, detail="Uploaded video background not found")
    return await submit_make_video(
        session,
        item_ids=payload.item_ids,
        background_id=payload.background_id,
    )


@router.post("/video-backgrounds", response_model=VideoBackgroundUpload, status_code=201)
async def upload_video_background(file: UploadFile = File(...)) -> VideoBackgroundUpload:
    """Store and inspect any visual format supported by the installed FFmpeg build."""
    filename = Path(file.filename or "background").name
    background_id = new_id()
    destination = get_settings().video_backgrounds_dir / background_id
    size = 0
    try:
        with destination.open("wb") as output:
            while chunk := await file.read(1024 * 1024):
                output.write(chunk)
                size += len(chunk)
        if size == 0:
            raise HTTPException(status_code=400, detail="Background file is empty")
        await video_export.validate_video_input(destination)
    except HTTPException:
        destination.unlink(missing_ok=True)
        raise
    except Exception as exc:
        destination.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    finally:
        await file.close()

    return VideoBackgroundUpload(
        id=background_id,
        filename=filename,
        size_bytes=size,
    )


@router.get("/videos", response_model=list[HistoryItem])
async def list_videos(
    session: AsyncSession = Depends(get_session),
    limit: int = Query(default=100, le=500),
) -> list[HistoryItem]:
    res = await session.execute(
        select(HistoryItem)
        .where(HistoryItem.kind == "video")
        .order_by(HistoryItem.created_at.desc())
        .limit(limit)
    )
    return list(res.scalars().all())
