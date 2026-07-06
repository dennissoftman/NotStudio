"""The orchestration + mixing core, exercised with the in-process mock backends."""

import numpy as np
import pytest

from radio_dashboard.audio.orchestrator import render_batch
from radio_dashboard.backends.mock import MockMusicBackend, MockSpeechBackend
from radio_dashboard.tasks.jobs import JobCancelled

PROGRAM = {
    "target_lufs": -16.0,
    "crossfade_seconds": 2.0,
    "music": {"prompts": ["deep house bed", "warm pads"], "track_seconds": 8.0},
    "inserts": [
        {"kind": "station_id", "cadence_seconds": 15, "texts": ["Neural FM"]},
        {
            "kind": "news",
            "cadence_seconds": 20,
            "voice": "am_michael",
            "texts": ["Markets rose today.", "Clear skies tonight."],
            "ducking": True,
            "bed_volume_db": -8,
        },
    ],
}


def test_render_batch_shape_and_loudness():
    result = render_batch(
        program_config=PROGRAM,
        music_backend=MockMusicBackend(),
        speech_backend=MockSpeechBackend(),
        target_seconds=25.0,
        sample_rate=22050,
        channels=2,
    )
    assert result.data.dtype == np.float32
    assert result.channels == 2
    assert result.data.shape[1] == 2
    # Duration is at least the target (inserts near the end may extend the bed).
    assert result.duration >= 25.0
    assert abs(result.duration - 25.0) < 5.0
    assert result.music_tracks >= 3
    assert result.inserts >= 2
    # Loudness normalized close to target.
    assert result.lufs is not None and abs(result.lufs - -16.0) < 1.5
    # No clipping.
    assert float(np.max(np.abs(result.data))) <= 1.0


def test_render_batch_emits_valid_webvtt():
    result = render_batch(
        program_config=PROGRAM,
        music_backend=MockMusicBackend(),
        speech_backend=MockSpeechBackend(),
        target_seconds=20.0,
        sample_rate=22050,
        channels=1,
    )
    assert result.vtt_text.startswith("WEBVTT")
    assert "NOTE type=music_track" in result.vtt_text
    assert "NOTE type=speech" in result.vtt_text


def test_render_batch_is_cancellable():
    calls = {"n": 0}

    def cancel_check():
        calls["n"] += 1
        if calls["n"] >= 2:
            raise JobCancelled()

    with pytest.raises(JobCancelled):
        render_batch(
            program_config=PROGRAM,
            music_backend=MockMusicBackend(),
            speech_backend=MockSpeechBackend(),
            target_seconds=60.0,
            sample_rate=22050,
            channels=2,
            cancel_check=cancel_check,
        )


def test_mock_speech_matches_target_duration():
    backend = MockSpeechBackend()
    buf = backend.synthesize(text="hello world", sample_rate=22050, target_duration=3.0)
    assert abs(buf.duration - 3.0) < 0.2
