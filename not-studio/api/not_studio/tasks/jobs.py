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

    await update_job(
        job_id,
        status="completed",
        progress=1.0,
        message=f"Generated {len(track_ids)} track(s)",
        finished_at=utcnow(),
        result={"track_ids": track_ids},
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

    if not items:
        await update_job(job_id, status="failed", error="no tracks selected", finished_at=utcnow())
        return {"error": "no tracks"}

    try:
        out_path, duration, sample_rate, channels = await run_in_process(
            _render_video,
            settings.audio_dir,
            settings.videos_dir,
            job_id,
            [it.path for it in items],
            [it.title for it in items],
            float(params.get("crossfade_seconds", 6.0)),
            str(params.get("visualizer", "cqt")),
            str(params.get("resolution", "1080p")),
            params.get("title"),
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
            title=params.get("title") or f"Mix of {len(items)} tracks",
            job_id=job_id,
            path=str(out_path),
            sample_rate=sample_rate,
            channels=channels,
            duration_seconds=duration,
            size_bytes=out_path.stat().st_size if out_path.exists() else 0,
            meta={
                "source_item_ids": item_ids,
                "visualizer": params.get("visualizer", "cqt"),
                "resolution": params.get("resolution", "1080p"),
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


def _render_video(
    audio_dir: Path,
    videos_dir: Path,
    job_id: str,
    paths: list[str],
    titles: list[str],
    crossfade_seconds: float,
    visualizer: str,
    resolution: str,
    title: str | None,
) -> tuple[Path, float, int, int]:
    from .. import video_export

    mix_path = audio_dir / f"mix-{job_id}.flac"
    duration, starts, sample_rate, channels = video_export.mix_tracks_to_file(
        paths,
        mix_path,
        crossfade_seconds=crossfade_seconds,
    )
    video_export.write_cue(mix_path.with_suffix(".cue"), mix_path.name, titles, starts)
    out_path = videos_dir / f"video-{job_id}.mp4"
    video_export.render_video(
        mix_path, out_path, visualizer=visualizer, resolution=resolution, title=title
    )
    return out_path, duration, sample_rate, channels
