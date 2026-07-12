import numpy as np

from not_studio.audio import dsp


def test_normalize_loudness_safely_peak_limits_short_audio():
    audio = np.array([[2.0, -2.0], [0.5, -0.5]], dtype=np.float32)

    normalized = dsp.normalize_loudness_safely(audio, 44100)

    assert normalized.shape == audio.shape
    assert np.max(np.abs(normalized)) <= dsp.DEFAULT_PEAK


def test_write_audio_file_accepts_metadata_kwargs(tmp_path):
    path = tmp_path / "nested" / "track.flac"
    audio = np.zeros((4410, 2), dtype=np.float32)

    dsp.write_audio_file(
        path,
        audio,
        44100,
        title="Track",
        genre="ambient",
        description="soft pads",
        track_number=1,
    )

    assert path.exists()
