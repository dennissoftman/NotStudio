"""Local background jobs for the album-review workflow."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from ..audio import dsp
from ..config import get_settings
from ..constants import new_id, utcnow
from ..db import session_scope
from ..models import HistoryItem, Job


async def update_job(job_id: str, **fields: Any) -> None:
    async with session_scope() as session:
        job = await session.get(Job, job_id)
        if job is None:
            return
        for key, value in fields.items():
            setattr(job, key, value)
        session.add(job)
        await session.commit()


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
    prompts = list(params.get("prompts") or [])
    album = dict(params.get("album") or {})
    provider = params.get("provider") or settings.default_music_provider
    model = params.get("model") or settings.default_music_model
    sr, ch = settings.sample_rate, settings.channels
    if not prompts:
        await update_job(job_id, status="failed", error="no prompts", finished_at=utcnow())
        return {"error": "no prompts"}

    try:
        rendered = await asyncio.to_thread(
            _render_tracks,
            job_id,
            prompts,
            provider,
            model,
            sr,
            ch,
            settings.audio_dir,
        )
    except Exception as exc:  # noqa: BLE001
        await update_job(job_id, status="failed", error=str(exc), finished_at=utcnow())
        return {"error": str(exc)}

    track_ids: list[str] = []
    async with session_scope() as session:
        for spec, data in rendered:
            path = settings.audio_dir / f"track-{new_id()}.flac"
            await asyncio.to_thread(dsp.write_audio_file, str(path), data, sr)
            item = HistoryItem(
                kind="track",
                title=spec.get("title", "Track"),
                job_id=job_id,
                path=str(path),
                sample_rate=sr,
                channels=ch,
                duration_seconds=len(data) / sr,
                size_bytes=path.stat().st_size if path.exists() else 0,
                meta={
                    "prompt": spec.get("prompt", ""),
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
) -> list[tuple[dict[str, Any], Any]]:
    rendered: list[tuple[dict[str, Any], Any]] = []
    if provider == "stable_audio_local":
        from ..backends.stable_audio import generate_batch
    elif provider == "stable_audio_runpod":
        from ..backends.runpod_stable_audio import generate_batch
    else:
        raise ValueError(f"Unknown music provider: {provider}")

    def progress(fraction: float, message: str) -> None:
        asyncio.run(update_job(job_id, progress=fraction, message=message))

    produced = generate_batch(
        prompts,
        sample_rate=sample_rate,
        model=model,
        out_dir=audio_dir / f"gen-{job_id}",
        on_progress=progress,
    )
    for spec, path in produced:
        rendered.append((spec, dsp.load_audio_file(str(path), sample_rate, channels)))
    return rendered


async def make_video_job(job_id: str) -> dict[str, Any]:
    settings = get_settings()
    await update_job(
        job_id, status="in_progress", started_at=utcnow(), progress=0.15, message="Loading tracks"
    )

    async with session_scope() as session:
        job = await session.get(Job, job_id)
        if job is None:
            return {"error": "job row missing"}
        params = job.params or {}
        item_ids = list(params.get("item_ids") or [])
        items = [it for it in [await session.get(HistoryItem, i) for i in item_ids] if it]

    if not items:
        await update_job(job_id, status="failed", error="no tracks selected", finished_at=utcnow())
        return {"error": "no tracks"}

    try:
        out_path, duration = await asyncio.to_thread(
            _render_video,
            settings.audio_dir,
            settings.videos_dir,
            job_id,
            [it.path for it in items],
            [it.title for it in items],
            int(settings.sample_rate),
            int(settings.channels),
            float(params.get("crossfade_seconds", 6.0)),
            str(params.get("visualizer", "cqt")),
            params.get("title"),
        )
    except Exception as exc:  # noqa: BLE001
        await update_job(job_id, status="failed", error=str(exc), finished_at=utcnow())
        return {"error": str(exc)}

    async with session_scope() as session:
        item = HistoryItem(
            kind="video",
            title=params.get("title") or f"Mix of {len(items)} tracks",
            job_id=job_id,
            path=str(out_path),
            sample_rate=settings.sample_rate,
            channels=settings.channels,
            duration_seconds=duration,
            size_bytes=out_path.stat().st_size if out_path.exists() else 0,
            meta={"source_item_ids": item_ids, "visualizer": params.get("visualizer", "cqt")},
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
    sample_rate: int,
    channels: int,
    crossfade_seconds: float,
    visualizer: str,
    title: str | None,
) -> tuple[Path, float]:
    from .. import video_export

    mix, starts = video_export.crossfade_tracks(
        paths, sample_rate=sample_rate, channels=channels, crossfade_seconds=crossfade_seconds
    )
    mix_path = audio_dir / f"mix-{job_id}.flac"
    dsp.write_audio_file(str(mix_path), mix, sample_rate)
    video_export.write_cue(mix_path.with_suffix(".cue"), mix_path.name, titles, starts)
    out_path = videos_dir / f"video-{job_id}.mp4"
    video_export.render_video(mix_path, out_path, visualizer=visualizer, title=title)
    return out_path, len(mix) / sample_rate
