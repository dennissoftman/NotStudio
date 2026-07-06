"""The batch-render arq job (submit / track / cancel target of feature #1).

Generation is CPU/GPU-bound, so the render runs in a thread; cancellation is
cooperative — arq aborts the coroutine, we flip a threading.Event, and the
orchestrator's ``cancel_check`` raises at the next cue boundary. Progress is
mirrored into the Job row by a side task so the UI sees it live.
"""

from __future__ import annotations

import asyncio
import threading
from typing import Any

from ..audio import dsp
from ..audio.orchestrator import RenderResult, render_batch
from ..backends.base import MusicBackend, SpeechBackend
from ..backends.mock import MockMusicBackend, MockSpeechBackend
from ..backends.registry import build_backend
from ..config import get_settings
from ..constants import utcnow
from ..db import session_scope
from ..models import Backend, HistoryItem, Job, PlayoutSegment, Program, Stream
from .. import buffer as buffer_mod


class JobCancelled(Exception):
    """Raised inside the render thread when the job has been aborted."""


async def _update_job(job_id: str, **fields: Any) -> None:
    async with session_scope() as session:
        job = await session.get(Job, job_id)
        if job is None:
            return
        for key, value in fields.items():
            setattr(job, key, value)
        session.add(job)
        await session.commit()


async def _resolve_backends(
    session: Any, program: Program | None
) -> tuple[MusicBackend, SpeechBackend]:
    music: MusicBackend = MockMusicBackend()
    speech: SpeechBackend = MockSpeechBackend()
    if program is None:
        return music, speech

    if program.music_backend_id:
        row = await session.get(Backend, program.music_backend_id)
        if row and row.enabled:
            music = build_backend(provider=row.provider, kind="music", config=row.config)
    if program.speech_backend_id:
        row = await session.get(Backend, program.speech_backend_id)
        if row and row.enabled:
            speech = build_backend(provider=row.provider, kind="speech", config=row.config)
    return music, speech


async def _run_in_thread(stop: threading.Event, work: Any) -> Any:
    """Await a threaded render; on cancellation, signal the thread and unwind."""
    loop = asyncio.get_running_loop()
    future = loop.run_in_executor(None, work)
    try:
        return await future
    except asyncio.CancelledError:
        stop.set()
        try:
            await asyncio.shield(future)  # let the thread notice the stop flag
        except BaseException:
            pass
        raise


async def _persist_result(job: Job, result: RenderResult) -> HistoryItem:
    settings = get_settings()
    audio_path = settings.audio_dir / f"{job.id}.flac"
    vtt_path = settings.audio_dir / f"{job.id}.vtt"

    await asyncio.to_thread(dsp.write_audio_file, str(audio_path), result.data, result.sample_rate)
    vtt_path.write_text(result.vtt_text, encoding="utf-8")
    size = audio_path.stat().st_size if audio_path.exists() else 0

    async with session_scope() as session:
        item = HistoryItem(
            kind="batch",
            title=f"Batch {job.id[:8]}",
            stream_id=job.stream_id,
            program_id=job.program_id,
            job_id=job.id,
            path=str(audio_path),
            vtt_path=str(vtt_path),
            sample_rate=result.sample_rate,
            channels=result.channels,
            duration_seconds=result.duration,
            size_bytes=size,
            lufs=result.lufs,
            meta={
                "music_tracks": result.music_tracks,
                "inserts": result.inserts,
            },
        )
        session.add(item)

        # Append to the stream's pre-allocated playout buffer (feature #4).
        if job.stream_id:
            seq = await buffer_mod.next_sequence(session, job.stream_id)
            session.add(
                PlayoutSegment(
                    stream_id=job.stream_id,
                    history_item_id=item.id,
                    sequence=seq,
                    duration_seconds=result.duration,
                    state="ready",
                )
            )
        await session.commit()
        await session.refresh(item)
        return item


async def render_batch_job(ctx: dict[str, Any], job_id: str) -> dict[str, Any]:
    settings = get_settings()
    await _update_job(job_id, status="in_progress", started_at=utcnow(), progress=0.0)

    # Load everything we need up front.
    async with session_scope() as session:
        job = await session.get(Job, job_id)
        if job is None:
            return {"error": "job row missing"}
        stream = await session.get(Stream, job.stream_id) if job.stream_id else None
        program_id = job.program_id or (stream.program_id if stream else None)
        program = await session.get(Program, program_id) if program_id else None
        music_backend, speech_backend = await _resolve_backends(session, program)

    sample_rate = stream.sample_rate if stream else settings.sample_rate
    channels = stream.channels if stream else settings.channels
    target = (job.params or {}).get("target_seconds") or (
        stream.batch_target_seconds if stream else settings.batch_target_seconds
    )
    max_seconds = stream.batch_max_seconds if stream else settings.batch_max_seconds
    target = float(min(target, max_seconds))

    progress: dict[str, Any] = {"frac": 0.0, "msg": "starting"}
    stop = threading.Event()

    def cancel_check() -> None:
        if stop.is_set():
            raise JobCancelled()

    def on_progress(frac: float, msg: str) -> None:
        progress["frac"] = frac
        progress["msg"] = msg

    async def mirror_progress() -> None:
        while True:
            await asyncio.sleep(2.0)
            await _update_job(
                job_id, progress=float(progress["frac"]), message=str(progress["msg"])
            )

    def work() -> RenderResult:
        return render_batch(
            program_config=program.config if program else {},
            music_backend=music_backend,
            speech_backend=speech_backend,
            target_seconds=target,
            sample_rate=sample_rate,
            channels=channels,
            batch_index=int((job.params or {}).get("batch_index", 0)),
            station_name=stream.name if stream else "Neural FM",
            program_name=program.name if program else "Program",
            cancel_check=cancel_check,
            progress=on_progress,
        )

    mirror = asyncio.create_task(mirror_progress())
    try:
        result = await _run_in_thread(stop, work)
    except asyncio.CancelledError:
        await _update_job(job_id, status="cancelled", finished_at=utcnow(), message="Cancelled")
        raise
    except JobCancelled:
        await _update_job(job_id, status="cancelled", finished_at=utcnow(), message="Cancelled")
        return {"status": "cancelled"}
    except Exception as exc:  # noqa: BLE001 — surface any backend failure to the UI
        await _update_job(job_id, status="failed", error=str(exc), finished_at=utcnow())
        raise
    finally:
        mirror.cancel()

    item = await _persist_result(job, result)
    await _update_job(
        job_id,
        status="completed",
        progress=1.0,
        message="Batch complete",
        finished_at=utcnow(),
        result={
            "history_item_id": item.id,
            "duration_seconds": result.duration,
            "path": item.path,
            "music_tracks": result.music_tracks,
            "inserts": result.inserts,
        },
    )
    return {"history_item_id": item.id, "duration_seconds": result.duration}
