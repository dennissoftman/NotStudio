"""Assemble selected tracks into a YouTube-ready video.

Crossfades the chosen tracks in-process (numpy, no torch), writes a mix + a .cue,
then shells out to the parent project's ``video.py`` (stdlib + ffmpeg) to master
the audio and draw the visualizer. Kept torch-free so making a video only needs
ffmpeg, independent of the (heavier) track generation step.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import numpy as np

from .audio import dsp
from .config import get_settings


def crossfade_tracks(
    paths: list[str],
    *,
    sample_rate: int,
    channels: int,
    crossfade_seconds: float,
) -> tuple[np.ndarray, list[float]]:
    """Equal-power crossfade the tracks into one buffer; return (mix, start_times)."""
    n = int(crossfade_seconds * sample_rate)
    arrays = [dsp.load_audio_file(p, sample_rate, channels) for p in paths]
    arrays = [a for a in arrays if len(a)]
    if not arrays:
        raise RuntimeError("No audio to combine.")

    mix = arrays[0]
    starts = [0.0]
    for track in arrays[1:]:
        starts.append(max(len(mix) - n, 0) / sample_rate)
        mix = dsp.equal_power_crossfade(mix, track, n)
    return mix, starts


def _cue_timestamp(seconds: float) -> str:
    frames = int(round(seconds * 75))  # CD frames, 75/sec (matches cross.py)
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


def render_video(
    mix_path: Path,
    out_path: Path,
    *,
    visualizer: str = "cqt",
    title: str | None = None,
    background: str | None = None,
) -> None:
    """Invoke the parent project's video.py (masters audio + draws visualizer)."""
    script = get_settings().engine_root / "video.py"
    if not script.is_file():
        raise RuntimeError(f"video.py not found at {script}")
    cmd = [
        sys.executable,
        str(script),
        str(mix_path),
        "-o",
        str(out_path),
        "--visualizer",
        visualizer,
    ]
    if title:
        cmd += ["--title", title]
    if background:
        cmd += ["--background", background]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0 or not Path(out_path).exists():
        raise RuntimeError(
            f"Video render failed (exit {proc.returncode}): "
            f"{proc.stderr.strip() or proc.stdout.strip()}"
        )
