"""Studio: album batches, human track review, and album construction."""

from __future__ import annotations

import io
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Response, UploadFile
from PIL import Image, UnidentifiedImageError
from starlette.background import BackgroundTask
from starlette.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from ..album_export import create_album_archive, safe_filename
from ..config import get_settings
from ..constants import new_id, utcnow
from ..deps import get_session
from ..models import Album, CoverAsset, HistoryItem, Job
from ..schemas import (
    GenerateAlbumRequest,
    GenerateTracksRequest,
    AlbumExportRequest,
    PromptKitResponse,
    PromptPlan,
    PromptSpec,
    TasteExample,
    TasteProfile,
    TrackAlbumRequest,
    TrackReviewRequest,
)
from ..tasks.submit import submit_generate_tracks

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
    return float(max(15, min(240, duration)))


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


@router.post("/albums/export", response_class=FileResponse)
async def export_album(
    payload: AlbumExportRequest,
    session: AsyncSession = Depends(get_session),
) -> FileResponse:
    """Download tagged FLACs, a CUE, and optional per-track cover videos."""
    settings = get_settings()
    items: list[HistoryItem] = []
    for item_id in payload.item_ids:
        item = await session.get(HistoryItem, item_id)
        if item is None or item.kind != "track":
            raise HTTPException(status_code=404, detail=f"Track not found: {item_id}")
        path = Path(item.path)
        if path.suffix.lower() != ".flac" or not path.is_file():
            raise HTTPException(
                status_code=400, detail=f"Track is not an available FLAC: {item.title}"
            )
        items.append(item)

    output = tempfile.NamedTemporaryFile(prefix="not-studio-album-", suffix=".zip", delete=False)
    output.close()
    output_path = Path(output.name)
    album_cover_path = settings.album_artwork_path(payload.title)
    album_ids = {item.album_id for item in items if item.album_id}
    if len(album_ids) == 1:
        album_id = next(iter(album_ids))
        selected_album_cover = await session.execute(
            select(CoverAsset).where(
                CoverAsset.owner_type == "album",
                CoverAsset.owner_id == album_id,
                CoverAsset.selected.is_(True),
            )
        )
        cover = selected_album_cover.scalar_one_or_none()
        if cover and Path(cover.path).is_file():
            album_cover_path = Path(cover.path)
    track_cover_paths: dict[str, Path] = {}
    if items:
        selected_track_covers = await session.execute(
            select(CoverAsset).where(
                CoverAsset.owner_type == "track",
                CoverAsset.owner_id.in_([item.id for item in items]),
                CoverAsset.selected.is_(True),
            )
        )
        track_cover_paths = {
            cover.owner_id: Path(cover.path)
            for cover in selected_track_covers.scalars().all()
            if Path(cover.path).is_file()
        }
    try:
        await create_album_archive(
            payload.title.strip(),
            items,
            output_path,
            artist=settings.track_author,
            cover_path=album_cover_path,
            track_cover_paths=track_cover_paths,
            include_track_videos=payload.include_track_videos,
        )
    except Exception as exc:  # noqa: BLE001
        output_path.unlink(missing_ok=True)
        raise HTTPException(status_code=500, detail=f"Could not assemble album: {exc}") from exc
    filename = f"{safe_filename(payload.title, 'album')}.zip"
    return FileResponse(
        output_path,
        media_type="application/zip",
        filename=filename,
        background=BackgroundTask(output_path.unlink, missing_ok=True),
    )


@router.post("/albums/artwork")
async def set_album_artwork(
    title: str = Form(..., min_length=1, max_length=160),
    file: UploadFile = File(...),
    session: AsyncSession = Depends(get_session),
) -> dict[str, str]:
    """Store one album cover as PNG, converting supported source formats."""
    settings = get_settings()
    mime = (file.content_type or "").lower()
    if mime not in {"image/jpeg", "image/png", "image/webp"}:
        raise HTTPException(status_code=400, detail="Use a PNG, JPEG, or WebP image")
    data = await file.read(10 * 1024 * 1024 + 1)
    await file.close()
    if not data:
        raise HTTPException(status_code=400, detail="Album artwork file is empty")
    if len(data) > 10 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="Album artwork must be 10 MB or smaller")

    destination = settings.album_artwork_path(title)
    try:
        with Image.open(io.BytesIO(data)) as source:
            source.load()
            image = source.convert("RGBA" if "A" in source.getbands() else "RGB")
            image.save(destination, format="PNG", optimize=True)
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        destination.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail=f"Could not read album artwork: {exc}") from exc
    updated_at = datetime.now(UTC).isoformat()
    album_query = await session.execute(
        select(Album).where(Album.title == title.strip()).order_by(Album.created_at.desc()).limit(1)
    )
    album = album_query.scalar_one_or_none()
    cover_id = ""
    if album:
        selected = await session.execute(
            select(CoverAsset).where(
                CoverAsset.owner_type == "album",
                CoverAsset.owner_id == album.id,
                CoverAsset.selected.is_(True),
            )
        )
        for current in selected.scalars().all():
            current.selected = False
            current.selected_at = None
            session.add(current)
        versions = await session.execute(
            select(CoverAsset).where(
                CoverAsset.owner_type == "album", CoverAsset.owner_id == album.id
            )
        )
        asset_id = new_id()
        immutable_path = settings.cover_dir / f"{asset_id}.png"
        immutable_path.write_bytes(destination.read_bytes())
        asset = CoverAsset(
            id=asset_id,
            owner_type="album",
            owner_id=album.id,
            version=len(versions.scalars().all()) + 1,
            status="ready",
            selected=True,
            path=str(immutable_path),
            width=image.width,
            height=image.height,
            size_bytes=immutable_path.stat().st_size,
            provider="manual_upload",
            model="manual_upload",
            selected_at=utcnow(),
        )
        session.add(asset)
        await session.commit()
        cover_id = asset.id
    return {"title": title.strip(), "updated_at": updated_at, "cover_id": cover_id}


@router.get("/albums/artwork")
async def get_album_artwork(
    title: str = Query(min_length=1, max_length=160),
    session: AsyncSession = Depends(get_session),
) -> FileResponse:
    path = get_settings().album_artwork_path(title)
    album_query = await session.execute(
        select(Album).where(Album.title == title.strip()).order_by(Album.created_at.desc()).limit(1)
    )
    album = album_query.scalar_one_or_none()
    if album:
        selected = await session.execute(
            select(CoverAsset).where(
                CoverAsset.owner_type == "album",
                CoverAsset.owner_id == album.id,
                CoverAsset.selected.is_(True),
            )
        )
        cover = selected.scalar_one_or_none()
        if cover and Path(cover.path).is_file():
            path = Path(cover.path)
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Album artwork not found")
    return FileResponse(
        path,
        media_type="image/png",
        headers={"Cache-Control": "private, max-age=31536000, immutable"},
    )


@router.post("/generate", response_model=Job, status_code=201)
async def generate(
    payload: GenerateTracksRequest,
    session: AsyncSession = Depends(get_session),
) -> Job:
    """Generate tracks from a prompt list with local ACE-Step Text2Music."""
    if not payload.prompts:
        raise HTTPException(status_code=400, detail="Provide at least one prompt")
    return await submit_generate_tracks(
        session,
        prompts=[p.model_dump(exclude_none=True) for p in payload.prompts],
        provider=payload.provider,
        model=payload.model,
        album={
            "title": payload.album_title.strip() if payload.album_title else "",
            "notes": payload.notes.strip() if payload.notes else None,
            "artwork_prompt": payload.artwork_prompt.strip() if payload.artwork_prompt else None,
            "track_count": len(payload.prompts),
        },
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
    """Return an external-LLM prompt contract enriched with the user's reviews."""
    res = await session.execute(
        select(HistoryItem)
        .where(HistoryItem.kind == "track")
        .order_by(HistoryItem.created_at.desc())
        .limit(500)
    )
    liked: list[TasteExample] = []
    for item in res.scalars().all():
        verdict = (item.meta or {}).get("review", {}).get("verdict", "unreviewed")
        if verdict == "liked":
            if len(liked) < 20:
                liked.append(_taste_example(item))

    return PromptKitResponse(
        task=(
            "Create a coherent instrumental album plan. "
            "Return only the JSON object described by output_schema."
        ),
        requirements=[
            "Use liked examples as positive taste signals.",
            "Infer reusable musical preferences; do not copy prior titles or prompts verbatim.",
            "Give the album a concise original title and optional notes about its overall direction.",
            "Provide an optional artwork_prompt describing a square cover without text or logos.",
            "Individual prompts may also include notes and artwork_prompt for track-specific icons.",
            "Follow artwork_guidance when writing album and track artwork_prompt fields.",
            "Make each prompt specific about arrangement, instrumentation, texture, energy, and tempo feel.",
            "Avoid artist names and copyrighted song references.",
            "Keep duration between 15 and 240 seconds and provide a genre for every track.",
        ],
        artwork_guidance="",
        output_schema=PromptPlan.model_json_schema(),
        example=PromptPlan(
            album_title="Glass Transit",
            notes="A restrained nocturnal arc that grows warmer toward the final track.",
            artwork_prompt=(
                "Square abstract cover, translucent glass forms crossing dark rail lines, "
                "midnight violet and muted cyan, soft grain, no text, no logo"
            ),
            prompts=[
                PromptSpec(
                    title="Last Platform",
                    genre="ambient techno",
                    prompt=(
                        "Instrumental ambient techno with a restrained four-on-the-floor pulse, "
                        "granular pads, muted sub bass, slow harmonic movement, and a spacious outro"
                    ),
                    duration=180,
                    notes="The quiet opening track; lonely but not bleak.",
                    artwork_prompt=(
                        "Square track icon, empty glass railway platform at night, "
                        "violet reflections, minimal composition, no text"
                    ),
                )
            ],
        ),
        taste_profile=TasteProfile(
            liked_genres=_genres(liked),
            liked_examples=liked,
        ),
    )


@router.get("/tracks", response_model=list[HistoryItem])
async def list_tracks(
    session: AsyncSession = Depends(get_session),
    verdict: str | None = Query(default=None, pattern="^(liked|unreviewed)$"),
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
        if ("liked" if (t.meta or {}).get("review", {}).get("verdict") == "liked" else "unreviewed")
        == verdict
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


@router.patch("/tracks/{item_id}/album", response_model=HistoryItem)
async def set_track_album(
    item_id: str,
    payload: TrackAlbumRequest,
    session: AsyncSession = Depends(get_session),
) -> HistoryItem:
    """Assign a track to an album, move it between albums, or leave it unfiled."""
    item = await session.get(HistoryItem, item_id)
    if item is None or item.kind != "track":
        raise HTTPException(status_code=404, detail="Track not found")

    meta = dict(item.meta or {})
    if payload.album_title is None:
        meta.pop("album", None)
        item.album_id = None
    else:
        existing = await session.execute(
            select(Album)
            .where(Album.title == payload.album_title)
            .order_by(Album.created_at.desc())
            .limit(1)
        )
        album_record = existing.scalar_one_or_none()
        if album_record is None:
            album_record = Album(title=payload.album_title)
            session.add(album_record)
            await session.flush()
        item.album_id = album_record.id
        album = dict(meta.get("album") or {})
        album["id"] = album_record.id
        album["title"] = payload.album_title
        album["assigned_at"] = datetime.now(UTC).isoformat()
        meta["album"] = album
    item.meta = meta
    session.add(item)
    await session.commit()
    await session.refresh(item)
    return item


@router.post("/tracks/{item_id}/regenerate", response_model=Job, status_code=201)
async def regenerate_track(
    item_id: str,
    session: AsyncSession = Depends(get_session),
) -> Job:
    """Regenerate one track from its original prompt and replace it on success."""
    item = await session.get(HistoryItem, item_id)
    if item is None or item.kind != "track":
        raise HTTPException(status_code=404, detail="Track not found")
    meta = dict(item.meta or {})
    prompt = str(meta.get("prompt") or "").strip()
    genre = str(meta.get("genre") or "instrumental").strip()
    if not prompt:
        raise HTTPException(status_code=400, detail="Track does not have a reusable prompt")
    spec = {
        "title": item.title,
        "genre": genre,
        "prompt": prompt,
        "duration": max(15.0, min(240.0, item.duration_seconds)),
    }
    for key in (
        "target_duration",
        "duration_variation_percent",
        "mood",
        "styles",
        "album_title",
        "track_index",
        "track_count",
        "notes",
        "artwork_prompt",
    ):
        if key in meta:
            spec[key] = meta[key]
    return await submit_generate_tracks(
        session,
        prompts=[spec],
        provider=str(meta.get("provider") or "") or None,
        album=dict(meta.get("album") or {}),
        replacement_item_id=item.id,
    )


@router.post("/tracks/{item_id}/artwork", response_model=HistoryItem)
async def set_track_artwork(
    item_id: str,
    file: UploadFile = File(...),
    session: AsyncSession = Depends(get_session),
) -> HistoryItem:
    """Embed optional cover artwork into a FLAC track."""
    item = await session.get(HistoryItem, item_id)
    if item is None or item.kind != "track":
        raise HTTPException(status_code=404, detail="Track not found")
    path = Path(item.path)
    if path.suffix.lower() != ".flac" or not path.is_file():
        raise HTTPException(status_code=400, detail="Artwork embedding requires an existing FLAC")
    mime = (file.content_type or "").lower()
    if mime not in {"image/jpeg", "image/png", "image/webp"}:
        raise HTTPException(status_code=400, detail="Use a PNG, JPEG, or WebP image")
    data = await file.read(10 * 1024 * 1024 + 1)
    await file.close()
    if not data:
        raise HTTPException(status_code=400, detail="Artwork file is empty")
    if len(data) > 10 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="Artwork must be 10 MB or smaller")
    try:
        from mutagen.flac import FLAC, Picture

        audio = FLAC(path)
        picture = Picture()
        picture.type = 3
        picture.mime = mime
        picture.desc = "Cover"
        picture.data = data
        audio.clear_pictures()
        audio.add_picture(picture)
        audio.save()
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"Could not embed artwork: {exc}") from exc
    meta = dict(item.meta or {})
    updated_at = datetime.now(UTC)
    selected = await session.execute(
        select(CoverAsset).where(
            CoverAsset.owner_type == "track",
            CoverAsset.owner_id == item.id,
            CoverAsset.selected.is_(True),
        )
    )
    for current in selected.scalars().all():
        current.selected = False
        current.selected_at = None
        session.add(current)
    versions = await session.execute(
        select(CoverAsset).where(CoverAsset.owner_type == "track", CoverAsset.owner_id == item.id)
    )
    asset_id = new_id()
    suffix = {"image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp"}[mime]
    immutable_path = get_settings().cover_dir / f"{asset_id}{suffix}"
    immutable_path.write_bytes(data)
    asset = CoverAsset(
        id=asset_id,
        owner_type="track",
        owner_id=item.id,
        version=len(versions.scalars().all()) + 1,
        status="ready",
        selected=True,
        path=str(immutable_path),
        mime=mime,
        size_bytes=len(data),
        provider="manual_upload",
        model="manual_upload",
        selected_at=updated_at,
    )
    session.add(asset)
    meta["cover_asset_id"] = asset.id
    meta["artwork"] = {"mime": mime, "updated_at": updated_at.isoformat()}
    item.meta = meta
    item.size_bytes = path.stat().st_size
    session.add(item)
    await session.commit()
    await session.refresh(item)
    return item


@router.get("/tracks/{item_id}/artwork")
async def get_track_artwork(item_id: str, session: AsyncSession = Depends(get_session)) -> Response:
    item = await session.get(HistoryItem, item_id)
    if item is None or item.kind != "track":
        raise HTTPException(status_code=404, detail="Track not found")
    generated = await session.execute(
        select(CoverAsset).where(
            CoverAsset.owner_type == "track",
            CoverAsset.owner_id == item.id,
            CoverAsset.selected.is_(True),
        )
    )
    selected = generated.scalar_one_or_none()
    if selected and Path(selected.path).is_file():
        return FileResponse(
            selected.path,
            media_type=selected.mime,
            headers={"Cache-Control": "private, max-age=31536000, immutable"},
        )
    try:
        from mutagen.flac import FLAC

        pictures = FLAC(Path(item.path)).pictures
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=404, detail="Track artwork not found") from exc
    if not pictures:
        raise HTTPException(status_code=404, detail="Track artwork not found")
    picture = pictures[0]
    return Response(
        content=picture.data,
        media_type=picture.mime or "application/octet-stream",
        headers={"Cache-Control": "private, max-age=31536000, immutable"},
    )
