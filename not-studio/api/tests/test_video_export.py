"""Fast mix/video orchestration tests."""

from __future__ import annotations

import json
import subprocess

import numpy as np

from not_studio import video_export
from not_studio.audio import dsp


def test_mix_tracks_to_file_streams_crossfade_through_ffmpeg(tmp_path):
    sample_rate = 8000
    first = tmp_path / "first.flac"
    second = tmp_path / "second.flac"
    samples = np.linspace(-0.1, 0.1, sample_rate, dtype=np.float32)[:, None]
    dsp.write_audio_file(first, np.repeat(samples, 2, axis=1), sample_rate)
    higher_rate_samples = np.linspace(-0.1, 0.1, sample_rate * 2, dtype=np.float32)[:, None]
    dsp.write_audio_file(second, np.repeat(higher_rate_samples, 2, axis=1), sample_rate * 2)

    output = tmp_path / "mix.flac"
    duration, starts, output_rate, output_channels = video_export.mix_tracks_to_file(
        [str(first), str(second)],
        output,
        crossfade_seconds=0.25,
    )

    info = dsp.audio_file_info(str(output))
    assert output.exists()
    assert starts == [0.0, 0.75]
    assert abs(duration - 1.75) < 0.01
    assert abs(float(info["duration_seconds"]) - 1.75) < 0.02
    assert output_rate == sample_rate
    assert output_channels == 2
    assert info["sample_rate"] == sample_rate


def test_render_video_uses_one_ffmpeg_encode_pass(tmp_path, monkeypatch):
    mix = tmp_path / "mix.flac"
    mix.write_bytes(b"placeholder")
    commands: list[list[str]] = []

    def fake_run(cmd: list[str], capture: bool = False):
        commands.append(cmd)
        stdout = ""
        if cmd[0] == video_export.FFPROBE:
            stdout = json.dumps(
                {
                    "streams": [{"sample_rate": "44100", "channels": 2, "bit_rate": "256000"}],
                    "format": {"duration": "10.0", "bit_rate": "256000"},
                }
            )
        return subprocess.CompletedProcess(cmd, 0, stdout=stdout, stderr="")

    monkeypatch.setattr(video_export, "_run", fake_run)
    video_export.render_video(mix, tmp_path / "out.mp4", visualizer="waves", resolution="1440p")

    ffmpeg_commands = [cmd for cmd in commands if cmd[0] == video_export.FFMPEG]
    assert len(ffmpeg_commands) == 1
    command = ffmpeg_commands[0]
    assert "veryfast" in command
    assert "[audio]" in command
    assert "2560x1440" in " ".join(command)
    assert "256000" in command
    assert "44100" in command
    assert "48000" not in command
    assert "loudnorm" not in " ".join(command)
    assert "aresample" not in " ".join(command)
    assert "aac_low" in command
    assert "twoloop" in command
    assert "medium" not in command
