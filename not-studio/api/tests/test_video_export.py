"""Media orchestration tests for the managed python-ffmpeg integration."""

from __future__ import annotations

import asyncio

import numpy as np
import pytest
from ffmpeg.asyncio import FFmpeg

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


async def test_mix_tracks_to_file_concatenates_and_reports_progress(tmp_path):
    sample_rate = 8000
    first = tmp_path / "first.flac"
    second = tmp_path / "second.flac"
    samples = np.linspace(-0.1, 0.1, sample_rate, dtype=np.float32)[:, None]
    dsp.write_audio_file(first, np.repeat(samples, 2, axis=1), sample_rate)
    higher_rate_samples = np.linspace(-0.1, 0.1, sample_rate * 2, dtype=np.float32)[:, None]
    dsp.write_audio_file(second, np.repeat(higher_rate_samples, 2, axis=1), sample_rate * 2)

    updates: list[tuple[float, str]] = []
    output = tmp_path / "mix.flac"
    duration, starts, output_rate, output_channels = await video_export.mix_tracks_to_file(
        [str(first), str(second)],
        output,
        on_progress=lambda progress, message: updates.append((progress, message)),
    )

    info = dsp.audio_file_info(str(output))
    assert output.exists()
    assert starts == [0.0, 1.0]
    assert abs(duration - 2.0) < 0.01
    assert abs(float(info["duration_seconds"]) - 2.0) < 0.02
    assert output_rate == sample_rate
    assert output_channels == 2
    assert info["sample_rate"] == sample_rate
    assert updates[-1] == (1.0, "Tracks combined")


def test_render_command_uses_managed_youtube_compatibility_policy(tmp_path):
    mix = tmp_path / "mix.flac"
    background = tmp_path / "background.mkv"
    output = tmp_path / "out.mp4"

    command = video_export.build_render_command(
        mix,
        output,
        background,
        duration=10.0,
        sample_rate=44100,
        channels=2,
    ).arguments

    assert command[0] == "ffmpeg"
    assert command[command.index("-stream_loop") + 1] == "-1"
    assert "1:v:0" in command
    assert "0:a:0" in command
    assert command[command.index("-codec:v") + 1] == "libx264"
    assert command[command.index("-pix_fmt") + 1] == "yuv420p"
    assert command[command.index("-codec:a") + 1] == "aac"
    assert command[command.index("-ar") + 1] == "44100"
    filters = command[command.index("-filter:v") + 1]
    assert "scale=trunc(iw/2)*2:trunc(ih/2)*2" in filters
    assert all(effect not in filters for effect in ("showcqt", "showspectrum", "showwaves"))


async def test_render_video_accepts_extensionless_input_and_reports_progress(tmp_path):
    sample_rate = 8000
    mix = tmp_path / "mix.flac"
    samples = np.linspace(-0.1, 0.1, sample_rate, dtype=np.float32)[:, None]
    dsp.write_audio_file(mix, np.repeat(samples, 2, axis=1), sample_rate)

    background = tmp_path / "uploaded-background"
    await (
        FFmpeg()
        .option("y")
        .option("hide_banner")
        .option("loglevel", "error")
        .input("testsrc2=size=320x180:rate=24:duration=0.25", f="lavfi")
        .output(str(background), {"codec:v": "mpeg4", "f": "avi"})
        .execute()
    )
    await video_export.validate_video_input(background)

    updates: list[tuple[float, str]] = []
    output = tmp_path / "out.mp4"
    await video_export.render_video(
        mix,
        output,
        background=str(background),
        on_progress=lambda progress, message: updates.append((progress, message)),
    )

    assert output.exists()
    assert output.stat().st_size > 0
    await video_export.validate_video_input(output)
    assert updates[-1] == (1.0, "Finalizing video")
    assert any("Encoding video" in message for _, message in updates)
