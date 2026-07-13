"""Assemble selected tracks into a YouTube-ready video through python-ffmpeg."""

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


async def validate_video_input(path: Path) -> None:
    """Ask FFmpeg to decode one video frame, rejecting unreadable or audio-only files."""
    command = (
        _ffmpeg()
        .input(str(path))
        .output(
            "pipe:1",
            {
                "map": "0:v:0",
                "frames:v": 1,
                "f": "null",
                "an": None,
            },
        )
    )
    await _execute(command)


async def mix_tracks_to_file(
    paths: list[str],
    output_path: Path,
    *,
    on_progress: ProgressCallback | None = None,
) -> tuple[float, list[float], int, int]:
    """Concatenate the selected tracks in order without creative audio effects."""
    if not paths:
        raise RuntimeError("No audio to combine.")
    source_paths = [Path(path) for path in paths]
    missing = next((path for path in source_paths if not path.is_file()), None)
    if missing:
        raise RuntimeError(f"audio not found: {missing}")

    source_info = [dsp.audio_file_info(str(path)) for path in source_paths]
    durations = [float(info["duration_seconds"]) for info in source_info]
    if any(duration <= 0 for duration in durations):
        raise RuntimeError("Could not determine every track duration.")

    starts = [0.0]
    elapsed = durations[0]
    for duration in durations[1:]:
        starts.append(elapsed)
        elapsed += duration

    sample_rate = min(int(info["sample_rate"]) for info in source_info)
    channels = min(int(info["channels"]) for info in source_info)
    layouts = {1: "mono", 2: "stereo"}
    if channels not in layouts:
        raise RuntimeError(f"Unsupported source channel count: {channels}")
    layout = layouts[channels]
    chains = [
        f"[{index}:a]aresample={sample_rate},"
        f"aformat=sample_fmts=fltp:channel_layouts={layout}[a{index}]"
        for index in range(len(paths))
    ]
    if len(paths) == 1:
        chains.append("[a0]anull[mix]")
    else:
        inputs_label = "".join(f"[a{index}]" for index in range(len(paths)))
        chains.append(f"{inputs_label}concat=n={len(paths)}:v=0:a=1[mix]")

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    command = _ffmpeg()
    for path in source_paths:
        command.input(str(path))
    command.output(
        str(output_path),
        {
            "filter_complex": ";".join(chains),
            "map": "[mix]",
            "codec:a": "flac",
            "ar": sample_rate,
            "ac": channels,
        },
    )

    if on_progress:

        @command.on("progress")
        def report(progress: Progress) -> None:
            fraction = min(1.0, progress.time.total_seconds() / elapsed)
            on_progress(fraction, f"Combining tracks {fraction:.0%}")

    await _execute(command)
    if on_progress:
        on_progress(1.0, "Tracks combined")
    return elapsed, starts, sample_rate, channels


def _cue_timestamp(seconds: float) -> str:
    frames = int(round(seconds * 75))
    minutes, rem = divmod(frames, 75 * 60)
    secs, frame = divmod(rem, 75)
    return f"{minutes:02d}:{secs:02d}:{frame:02d}"


def write_cue(path: Path, audio_name: str, titles: list[str], starts: list[float]) -> None:
    lines = [f'FILE "{audio_name}" FLAC']
    for index, (title, start) in enumerate(zip(titles, starts), start=1):
        lines += [
            f"  TRACK {index:02d} AUDIO",
            f'    TITLE "{title.replace(chr(34), chr(39))}"',
            f"    INDEX 01 {_cue_timestamp(start)}",
        ]
    Path(path).write_text("\n".join(lines) + "\n", encoding="utf-8")


def hms(seconds: float) -> str:
    total = int(round(seconds))
    hours, rem = divmod(total, 3600)
    minutes, secs = divmod(rem, 60)
    return f"{hours}:{minutes:02d}:{secs:02d}" if hours else f"{minutes}:{secs:02d}"


def cue_to_chapters(cue_path: Path) -> str | None:
    try:
        lines = cue_path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return None
    titles: list[str] = []
    starts: list[float] = []
    for line in lines:
        line = line.strip()
        if line.startswith("TITLE "):
            titles.append(line[6:].strip().strip('"'))
        elif line.startswith("INDEX 01 "):
            mm, ss, ff = line.split()[-1].split(":")
            starts.append(int(mm) * 60 + int(ss) + int(ff) / 75.0)
    if not starts or len(titles) < len(starts):
        return None
    out = [f"{hms(t)} {title}" for title, t in zip(titles, starts)]
    if out and not out[0].startswith("0:00 "):
        out[0] = "0:00 " + out[0].split(" ", 1)[1]
    return "\n".join(out) + "\n"


def build_render_command(
    mix_path: Path,
    out_path: Path,
    background: Path,
    *,
    duration: float,
    sample_rate: int,
    channels: int,
) -> FFmpeg:
    """Build the managed FFmpeg operation separately so its policy is testable."""
    return (
        _ffmpeg()
        .input(str(mix_path))
        .input(str(background), {"stream_loop": -1})
        .output(
            str(out_path),
            {
                "map": ["1:v:0", "0:a:0"],
                "t": f"{duration:.3f}",
                "filter:v": "fps=30,scale=trunc(iw/2)*2:trunc(ih/2)*2,setsar=1,format=yuv420p",
                "codec:v": "libx264",
                "preset": "veryfast",
                "crf": 20,
                "pix_fmt": "yuv420p",
                "profile:v": "high",
                "g": 60,
                "bf": 2,
                "codec:a": "aac",
                "b:a": "256k",
                "ar": sample_rate,
                "ac": channels,
                "profile:a": "aac_low",
                "aac_coder": "twoloop",
                "shortest": None,
                "movflags": "+faststart",
            },
        )
    )


async def render_video(
    mix_path: Path,
    out_path: Path,
    *,
    background: str,
    on_progress: ProgressCallback | None = None,
) -> None:
    mix_path = Path(mix_path)
    out_path = Path(out_path)
    background_path = Path(background)
    if not mix_path.is_file():
        raise RuntimeError(f"audio not found: {mix_path}")
    if not background_path.is_file():
        raise RuntimeError(f"background not found: {background_path}")
    out_path.parent.mkdir(parents=True, exist_ok=True)

    await validate_video_input(background_path)
    audio_info = dsp.audio_file_info(str(mix_path))
    duration = float(audio_info["duration_seconds"])
    sample_rate = int(audio_info["sample_rate"])
    channels = int(audio_info["channels"])
    command = build_render_command(
        mix_path,
        out_path,
        background_path,
        duration=duration,
        sample_rate=sample_rate,
        channels=channels,
    )

    if on_progress:

        @command.on("progress")
        def report(progress: Progress) -> None:
            fraction = min(1.0, progress.time.total_seconds() / duration)
            speed = f" · {progress.speed:.1f}×" if progress.speed > 0 else ""
            on_progress(fraction, f"Encoding video {fraction:.0%}{speed}")

    await _execute(command)
    if on_progress:
        on_progress(1.0, "Finalizing video")

    chapters = cue_to_chapters(mix_path.with_suffix(".cue"))
    if chapters:
        out_path.with_name("chapters.txt").write_text(chapters, encoding="utf-8")
