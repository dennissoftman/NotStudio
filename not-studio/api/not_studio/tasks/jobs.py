"""Local background jobs for the album-review workflow."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from ..audio import dsp
from ..config import get_settings
from ..constants import utcnow
from ..db import session_scope
from ..models import HistoryItem, Job
from .processes import reusable_process_busy, run_in_process, run_in_reusable_process
from .events import notify_jobs_changed

RUNNING_STATUSES = ("queued", "in_progress")


async def update_job(job_id: str, **fields: Any) -> None:
    async with session_scope() as session:
        job = await session.get(Job, job_id)
        if job is None:
            return
        if (
            job.status in ("completed", "failed", "cancelled")
            and fields.get("status") != job.status
        ):
            return
        for key, value in fields.items():
            setattr(job, key, value)
        session.add(job)
        await session.commit()
    await notify_jobs_changed()


async def fail_interrupted_jobs() -> int:
    """Mark non-terminal jobs from a previous API process as unrecoverable."""
    from sqlmodel import select

    async with session_scope() as session:
        res = await session.execute(select(Job).where(Job.status.in_(RUNNING_STATUSES)))
        jobs = list(res.scalars().all())
        now = utcnow()
        for job in jobs:
            job.status = "failed"
            job.finished_at = now
            job.error = "API restarted before this local job finished"
            job.message = "Interrupted by API restart"
            session.add(job)
        await session.commit()
        return len(jobs)


async def mark_jobs_cancelled_by_shutdown(job_ids: set[str]) -> int:
    if not job_ids:
        return 0
    async with session_scope() as session:
        jobs = [job for job in [await session.get(Job, job_id) for job_id in job_ids] if job]
        now = utcnow()
        count = 0
        for job in jobs:
            if job.status not in RUNNING_STATUSES:
                continue
            job.status = "cancelled"
            job.finished_at = now
            job.message = "Cancelled by API shutdown"
            session.add(job)
            count += 1
        await session.commit()
        return count


async def is_job_cancelled(job_id: str) -> bool:
    async with session_scope() as session:
        job = await session.get(Job, job_id)
        return job is None or job.status == "cancelled"


async def generate_tracks_job(job_id: str) -> dict[str, Any]:
    settings = get_settings()
    await update_job(
        job_id, status="in_progress", started_at=utcnow(), progress=0.05, message="Preparing"
    )

    async with session_scope() as session:
        job = await session.get(Job, job_id)
        if job is None:
            return {"error": "job row missing"}

    params = job.params or {}
    if job.status == "cancelled":
        return {"cancelled": True}
    prompts = list(params.get("prompts") or [])
    album = dict(params.get("album") or {})
    replacement_item_id = params.get("replacement_item_id")
    provider = params.get("provider") or settings.default_music_provider
    model = "medium"
    sr, ch = settings.sample_rate, settings.channels
    if not prompts:
        await update_job(job_id, status="failed", error="no prompts", finished_at=utcnow())
        return {"error": "no prompts"}

    try:
        if provider == "stable_audio_local":
            if reusable_process_busy("stable-audio-local"):
                await update_job(job_id, progress=0.05, message="Queued for local model")
            produced = await run_in_reusable_process(
                "stable-audio-local",
                _render_tracks,
                job_id,
                prompts,
                provider,
                model,
                sr,
                ch,
                settings.audio_dir,
            )
        else:
            produced = await run_in_process(
                _render_tracks,
                job_id,
                prompts,
                provider,
                model,
                sr,
                ch,
                settings.audio_dir,
            )
    except asyncio.CancelledError:
        await update_job(job_id, status="cancelled", message="Cancelled", finished_at=utcnow())
        return {"cancelled": True}
    except Exception as exc:  # noqa: BLE001
        if await is_job_cancelled(job_id):
            return {"cancelled": True}
        await update_job(job_id, status="failed", error=str(exc), finished_at=utcnow())
        return {"error": str(exc)}

    track_ids: list[str] = []
    if await is_job_cancelled(job_id):
        return {"cancelled": True}
    async with session_scope() as session:
        for spec, path_value in produced:
            path = Path(path_value)
            info = await asyncio.to_thread(dsp.audio_file_info, str(path))
            old_path: Path | None = None
            if replacement_item_id:
                item = await session.get(HistoryItem, replacement_item_id)
                if item is None or item.kind != "track":
                    path.unlink(missing_ok=True)
                    raise RuntimeError("Track selected for regeneration no longer exists")
                old_path = Path(item.path)
                if (item.meta or {}).get("artwork") and old_path.is_file():
                    await asyncio.to_thread(dsp.copy_flac_pictures, old_path, path)
                meta = dict(item.meta or {})
                meta.update(
                    {
                        "prompt": spec.get("prompt", ""),
                        "genre": spec.get("genre", ""),
                        "notes": spec.get("notes"),
                        "artwork_prompt": spec.get("artwork_prompt"),
                        "provider": provider,
                        "album": album or meta.get("album", {}),
                        "mood": spec.get("mood") or album.get("mood") or meta.get("mood"),
                        "styles": spec.get("styles")
                        or album.get("styles")
                        or meta.get("styles", []),
                        "review": {"verdict": "unreviewed"},
                    }
                )
                item.title = spec.get("title", item.title)
                item.job_id = job_id
                item.path = str(path)
                item.sample_rate = info["sample_rate"]
                item.channels = info["channels"]
                item.duration_seconds = info["duration_seconds"]
                item.size_bytes = path.stat().st_size if path.exists() else 0
                item.meta = meta
                item.created_at = utcnow()
            else:
                item = HistoryItem(
                    kind="track",
                    title=spec.get("title", "Track"),
                    job_id=job_id,
                    path=str(path),
                    sample_rate=info["sample_rate"],
                    channels=info["channels"],
                    duration_seconds=info["duration_seconds"],
                    size_bytes=path.stat().st_size if path.exists() else 0,
                    meta={
                        "prompt": spec.get("prompt", ""),
                        "genre": spec.get("genre", ""),
                        "notes": spec.get("notes"),
                        "artwork_prompt": spec.get("artwork_prompt"),
                        "provider": provider,
                        "album": album,
                        "mood": spec.get("mood") or album.get("mood"),
                        "styles": spec.get("styles") or album.get("styles") or [],
                        "review": {"verdict": "unreviewed"},
                    },
                )
            session.add(item)
            await session.commit()
            await session.refresh(item)
            track_ids.append(item.id)
            if old_path is not None and old_path != path:
                old_path.unlink(missing_ok=True)

    await update_job(
        job_id,
        status="completed",
        progress=1.0,
        message=f"Generated {len(track_ids)} track(s)",
        finished_at=utcnow(),
        result={"track_ids": track_ids, "replacement_item_id": replacement_item_id},
    )
    return {"track_ids": track_ids}


def _render_tracks(
    job_id: str,
    prompts: list[dict[str, Any]],
    provider: str,
    model: str,
    sample_rate: int,
    channels: int,
    audio_dir: Path,
) -> list[tuple[dict[str, Any], str]]:
    if provider == "stable_audio_local":
        from ..backends.stable_audio import generate_batch
    elif provider == "stable_audio_runpod":
        from ..backends.runpod_stable_audio import generate_batch
    else:
        raise ValueError(f"Unknown music provider: {provider}")

    def progress(fraction: float, message: str) -> None:
        asyncio.run(update_job(job_id, progress=fraction, message=message))

    def should_cancel() -> bool:
        return asyncio.run(is_job_cancelled(job_id))

    produced = generate_batch(
        prompts,
        sample_rate=sample_rate,
        model=model,
        out_dir=audio_dir / f"gen-{job_id}",
        on_progress=progress,
        should_cancel=should_cancel,
    )
    if should_cancel():
        raise RuntimeError("Track generation cancelled")
    return [(spec, str(path)) for spec, path in produced]


async def make_video_job(job_id: str) -> dict[str, Any]:
    settings = get_settings()
    await update_job(
        job_id, status="in_progress", started_at=utcnow(), progress=0.15, message="Loading tracks"
    )

    async with session_scope() as session:
        job = await session.get(Job, job_id)
        if job is None:
            return {"error": "job row missing"}
        if job.status == "cancelled":
            return {"cancelled": True}
        params = job.params or {}
        item_ids = list(params.get("item_ids") or [])
        items = [it for it in [await session.get(HistoryItem, i) for i in item_ids] if it]

    background_id = str(params.get("background_id") or "")
    background_path = settings.video_backgrounds_dir / background_id
    if not background_id or not background_path.is_file():
        await update_job(
            job_id,
            status="failed",
            error="uploaded background is missing",
            finished_at=utcnow(),
        )
        return {"error": "uploaded background is missing"}

    if not items:
        await update_job(job_id, status="failed", error="no tracks selected", finished_at=utcnow())
        return {"error": "no tracks"}

    try:
        out_path, duration, sample_rate, channels = await _render_video(
            audio_dir=settings.audio_dir,
            videos_dir=settings.videos_dir,
            job_id=job_id,
            paths=[it.path for it in items],
            titles=[it.title for it in items],
            background=str(background_path),
        )
    except asyncio.CancelledError:
        await update_job(job_id, status="cancelled", message="Cancelled", finished_at=utcnow())
        return {"cancelled": True}
    except Exception as exc:  # noqa: BLE001
        if await is_job_cancelled(job_id):
            return {"cancelled": True}
        await update_job(job_id, status="failed", error=str(exc), finished_at=utcnow())
        return {"error": str(exc)}

    if await is_job_cancelled(job_id):
        return {"cancelled": True}
    async with session_scope() as session:
        item = HistoryItem(
            kind="video",
            title=f"Mix of {len(items)} track{'s' if len(items) != 1 else ''}",
            job_id=job_id,
            path=str(out_path),
            sample_rate=sample_rate,
            channels=channels,
            duration_seconds=duration,
            size_bytes=out_path.stat().st_size if out_path.exists() else 0,
            meta={
                "source_item_ids": item_ids,
                "background_id": background_id,
                "background_looped": True,
                "video_codec": "h264",
                "pixel_format": "yuv420p",
            },
        )
        session.add(item)
        await session.commit()
        await session.refresh(item)
        video_id = item.id

    await update_job(
        job_id,
        status="completed",
        progress=1.0,
        message="Mix ready",
        finished_at=utcnow(),
        result={"video_id": video_id, "path": str(out_path)},
    )
    return {"video_id": video_id}


async def _render_video(
    audio_dir: Path,
    videos_dir: Path,
    job_id: str,
    paths: list[str],
    titles: list[str],
    background: str,
) -> tuple[Path, float, int, int]:
    from .. import video_export

    mix_path = audio_dir / f"mix-{job_id}.flac"
    progress_queue: asyncio.Queue[tuple[float, str] | None] = asyncio.Queue(maxsize=1)

    def queue_progress(progress: float, message: str) -> None:
        if progress_queue.full():
            progress_queue.get_nowait()
        progress_queue.put_nowait((progress, message))

    async def publish_progress() -> None:
        while update := await progress_queue.get():
            progress, message = update
            await update_job(job_id, progress=progress, message=message)

    publisher = asyncio.create_task(publish_progress())

    def mix_progress(progress: float, message: str) -> None:
        queue_progress(0.15 + progress * 0.15, message)

    def render_progress(progress: float, message: str) -> None:
        queue_progress(0.30 + progress * 0.68, message)

    try:
        duration, starts, sample_rate, channels = await video_export.mix_tracks_to_file(
            paths,
            mix_path,
            on_progress=mix_progress,
        )
        video_export.write_cue(mix_path.with_suffix(".cue"), mix_path.name, titles, starts)
        out_path = videos_dir / f"video-{job_id}.mp4"
        await video_export.render_video(
            mix_path,
            out_path,
            background=background,
            on_progress=render_progress,
        )
        return out_path, duration, sample_rate, channels
    finally:
        await progress_queue.put(None)
        await publisher
