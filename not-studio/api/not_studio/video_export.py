"""Encode one static-cover, YouTube-compatible MP4 for an album track."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from contextlib import suppress
from pathlib import Path

from ffmpeg import FFmpegError, Progress
from ffmpeg.asyncio import FFmpeg

from .audio import dsp

ProgressCallback = Callable[[float, str], None]


def _ffmpeg() -> FFmpeg:
    return FFmpeg().option("y").option("hide_banner").option("loglevel", "error").option("stats")


async def _execute(command: FFmpeg) -> bytes:
    """Run a managed FFmpeg command and terminate it when its task is cancelled."""
    task = asyncio.create_task(command.execute())
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        with suppress(FFmpegError):
            command.terminate()
        with suppress(FFmpegError, asyncio.CancelledError):
            await task
        raise


def build_track_video_command(
    audio_path: Path,
    cover_path: Path,
    output_path: Path,
    *,
    duration: float,
    sample_rate: int,
    channels: int,
) -> FFmpeg:
    """Build the fixed 1 fps H.264/AAC policy used for per-track exports."""
    return (
        _ffmpeg()
        .input(str(cover_path), {"loop": 1, "framerate": 1})
        .input(str(audio_path))
        .output(
            str(output_path),
            {
                "map": ["0:v:0", "1:a:0"],
                "t": f"{duration:.3f}",
                "filter:v": "fps=1,scale=trunc(iw/2)*2:trunc(ih/2)*2,setsar=1,format=yuv420p",
                "r": 1,
                "codec:v": "libx264",
                "preset": "slow",
                "tune": "stillimage",
                "crf": 18,
                "pix_fmt": "yuv420p",
                "profile:v": "high",
                "g": 2,
                "bf": 2,
                "codec:a": "aac",
                "b:a": "320k",
                "ar": sample_rate,
                "ac": channels,
                "profile:a": "aac_low",
                "aac_coder": "twoloop",
                "shortest": None,
                "movflags": "+faststart",
            },
        )
    )


async def render_track_video(
    audio_path: Path,
    cover_path: Path,
    output_path: Path,
    *,
    on_progress: ProgressCallback | None = None,
) -> None:
    audio_path = Path(audio_path)
    cover_path = Path(cover_path)
    output_path = Path(output_path)
    if not audio_path.is_file():
        raise RuntimeError(f"audio not found: {audio_path}")
    if not cover_path.is_file():
        raise RuntimeError(f"cover not found: {cover_path}")
    output_path.parent.mkdir(parents=True, exist_ok=True)

    info = dsp.audio_file_info(str(audio_path))
    duration = float(info["duration_seconds"])
    command = build_track_video_command(
        audio_path,
        cover_path,
        output_path,
        duration=duration,
        sample_rate=int(info["sample_rate"]),
        channels=int(info["channels"]),
    )

    if on_progress:

        @command.on("progress")
        def report(progress: Progress) -> None:
            fraction = min(1.0, progress.time.total_seconds() / duration)
            on_progress(fraction, f"Encoding track video {fraction:.0%}")

    await _execute(command)
    if on_progress:
        on_progress(1.0, "Track video ready")
