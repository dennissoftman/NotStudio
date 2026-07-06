from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse, StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from .. import buffer as buffer_mod
from ..config import get_settings
from ..constants import utcnow
from ..deps import get_or_404, get_playout, get_pool, get_session
from ..models import Job, PlayoutSegment, Stream
from ..schemas import AnnounceRequest, BufferStatus, StreamCreate, StreamUpdate
from ..tasks.queue import submit_announcement, submit_batch

router = APIRouter(prefix="/streams", tags=["streams"])


@router.get("", response_model=list[Stream])
async def list_streams(session: AsyncSession = Depends(get_session)) -> list[Stream]:
    res = await session.execute(select(Stream).order_by(Stream.created_at))
    return list(res.scalars().all())


@router.get("/{stream_id}", response_model=Stream)
async def get_stream(stream_id: str, session: AsyncSession = Depends(get_session)) -> Stream:
    return await get_or_404(session, Stream, stream_id)


@router.post("", response_model=Stream, status_code=201)
async def create_stream(
    payload: StreamCreate, session: AsyncSession = Depends(get_session)
) -> Stream:
    stream = Stream(
        name=payload.name,
        program_id=payload.program_id,
        sample_rate=payload.sample_rate,
        channels=payload.channels,
        buffer_min_seconds=payload.buffer_min_seconds,
        batch_target_seconds=payload.batch_target_seconds,
        batch_max_seconds=payload.batch_max_seconds,
        icecast=payload.icecast.model_dump() if payload.icecast else None,
    )
    session.add(stream)
    await session.commit()
    await session.refresh(stream)
    return stream


@router.patch("/{stream_id}", response_model=Stream)
async def update_stream(
    stream_id: str,
    payload: StreamUpdate,
    session: AsyncSession = Depends(get_session),
) -> Stream:
    stream = await get_or_404(session, Stream, stream_id)
    data = payload.model_dump(exclude_unset=True)
    if "icecast" in data:
        stream.icecast = payload.icecast.model_dump() if payload.icecast else None
        data.pop("icecast")
    for key, value in data.items():
        setattr(stream, key, value)
    stream.updated_at = utcnow()
    session.add(stream)
    await session.commit()
    await session.refresh(stream)
    return stream


@router.delete("/{stream_id}", status_code=204)
async def delete_stream(
    stream_id: str,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> None:
    stream = await get_or_404(session, Stream, stream_id)
    await get_playout(request).stop(stream_id)
    await session.delete(stream)
    await session.commit()


@router.post("/{stream_id}/start", response_model=Stream)
async def start_stream(
    stream_id: str,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> Stream:
    """Go live: begin real-time playout and kick off buffer generation."""
    stream = await get_or_404(session, Stream, stream_id)
    stream.status = "live"
    stream.updated_at = utcnow()
    session.add(stream)
    await session.commit()
    await session.refresh(stream)

    # Real-time playout engine (emits silence until the first batch is ready).
    await get_playout(request).ensure_running(stream)

    # Seed the buffer immediately so audio starts sooner than the next tick.
    pool = getattr(request.app.state, "arq", None)
    if pool is not None and await buffer_mod.needs_batch(session, stream):
        await submit_batch(
            pool,
            session,
            stream_id=stream.id,
            program_id=stream.program_id,
            target_seconds=stream.batch_target_seconds,
        )
    return stream


@router.post("/{stream_id}/stop", response_model=Stream)
async def stop_stream(
    stream_id: str,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> Stream:
    stream = await get_or_404(session, Stream, stream_id)
    stream.status = "stopped"
    stream.updated_at = utcnow()
    session.add(stream)
    await session.commit()
    await session.refresh(stream)
    await get_playout(request).stop(stream_id)
    return stream


@router.get("/{stream_id}/buffer", response_model=BufferStatus)
async def buffer_status(
    stream_id: str,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> BufferStatus:
    stream = await get_or_404(session, Stream, stream_id)
    ready = await buffer_mod.ready_seconds(session, stream_id)
    ready_count, total = await buffer_mod.segment_counts(session, stream_id)
    generating = await buffer_mod.has_active_batch_job(session, stream_id)
    return BufferStatus(
        stream_id=stream_id,
        status=stream.status,
        ready_seconds=ready,
        min_seconds=stream.buffer_min_seconds,
        segments_ready=ready_count,
        segments_total=total,
        generating=generating,
    )


@router.get("/{stream_id}/segments", response_model=list[PlayoutSegment])
async def list_segments(
    stream_id: str, session: AsyncSession = Depends(get_session)
) -> list[PlayoutSegment]:
    res = await session.execute(
        select(PlayoutSegment)
        .where(PlayoutSegment.stream_id == stream_id)
        .order_by(PlayoutSegment.sequence)
    )
    return list(res.scalars().all())


@router.post("/{stream_id}/announce", response_model=Job)
async def announce(
    stream_id: str,
    payload: AnnounceRequest,
    session: AsyncSession = Depends(get_session),
    pool=Depends(get_pool),
) -> Job:
    """Air a short spoken announcement now (breaking news / live read, feature #2)."""
    await get_or_404(session, Stream, stream_id)
    return await submit_announcement(
        pool,
        session,
        stream_id=stream_id,
        text=payload.text,
        voice=payload.voice,
        play_next=payload.play_next,
    )


# --- live audio (feature #3) --------------------------------------------------
@router.get("/{stream_id}/live.mp3")
async def live_mp3(
    stream_id: str,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> StreamingResponse:
    stream = await get_or_404(session, Stream, stream_id)
    manager = get_playout(request)
    engine = manager.get(stream_id)
    if engine is None:
        if stream.status != "live":
            raise HTTPException(status_code=409, detail="Stream is not live")
        engine = await manager.ensure_running(stream)
    return StreamingResponse(
        engine.http_mp3(),
        media_type="audio/mpeg",
        headers={"Cache-Control": "no-store", "icy-name": stream.name},
    )


@router.get("/{stream_id}/hls/playlist.m3u8")
async def hls_playlist(stream_id: str) -> FileResponse:
    path = get_settings().hls_dir / stream_id / "playlist.m3u8"
    if not path.exists():
        raise HTTPException(status_code=404, detail="HLS not available yet")
    return FileResponse(
        path,
        media_type="application/vnd.apple.mpegurl",
        headers={"Cache-Control": "no-store"},
    )


@router.get("/{stream_id}/hls/{segment}")
async def hls_segment(stream_id: str, segment: str) -> FileResponse:
    if not (segment.startswith("seg_") and segment.endswith(".ts")):
        raise HTTPException(status_code=404, detail="Not found")
    path = get_settings().hls_dir / stream_id / segment
    if not path.exists():
        raise HTTPException(status_code=404, detail="Segment expired")
    return FileResponse(path, media_type="video/mp2t")
