"""Per-track album video policy tests for python-ffmpeg integration."""

from __future__ import annotations

import asyncio

import numpy as np
import pytest
from PIL import Image

from not_studio import video_export
from not_studio.audio import dsp


async def test_managed_ffmpeg_is_terminated_when_cancelled():
    stopped = asyncio.Event()

    class FakeCommand:
        terminated = False

        async def execute(self) -> bytes:
            await stopped.wait()
            return b""

        def terminate(self) -> None:
            self.terminated = True
            stopped.set()

    command = FakeCommand()
    task = asyncio.create_task(video_export._execute(command))  # type: ignore[arg-type]
    await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert command.terminated


def test_track_video_command_uses_static_youtube_compatibility_policy(tmp_path):
    command = video_export.build_track_video_command(
        tmp_path / "track.flac",
        tmp_path / "cover.png",
        tmp_path / "track.mp4",
        duration=10.0,
        sample_rate=44100,
        channels=2,
    ).arguments

    assert command[0] == "ffmpeg"
    assert command[command.index("-loop") + 1] == "1"
    assert command[command.index("-framerate") + 1] == "1"
    assert command[command.index("-r") + 1] == "1"
    assert "0:v:0" in command
    assert "1:a:0" in command
    assert command[command.index("-codec:v") + 1] == "libx264"
    assert command[command.index("-pix_fmt") + 1] == "yuv420p"
    assert command[command.index("-codec:a") + 1] == "aac"
    assert command[command.index("-b:a") + 1] == "320k"
    assert "fps=1" in command[command.index("-filter:v") + 1]


async def test_render_track_video_encodes_cover_and_audio(tmp_path):
    sample_rate = 44100
    audio = tmp_path / "track.flac"
    samples = np.linspace(-0.1, 0.1, sample_rate, dtype=np.float32)[:, None]
    dsp.write_audio_file(audio, np.repeat(samples, 2, axis=1), sample_rate)
    cover = tmp_path / "cover.png"
    Image.new("RGB", (64, 64), (30, 60, 120)).save(cover)
    output = tmp_path / "track.mp4"
    updates: list[tuple[float, str]] = []

    await video_export.render_track_video(
        audio,
        cover,
        output,
        on_progress=lambda progress, message: updates.append((progress, message)),
    )

    assert output.is_file()
    assert output.stat().st_size > 0
    assert updates[-1] == (1.0, "Track video ready")
