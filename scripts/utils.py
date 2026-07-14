import os
import warnings
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pyloudnorm as pyln
import soundfile as sf
from mutagen.flac import FLAC


DEFAULT_AUDIO_PEAK = 0.999


def normalize_loudness(data, rate, target_lufs: float | None = -16.0):
    """Normalize (samples, channels) audio to target integrated LUFS."""
    if target_lufs is None:
        return data
    if len(data) < int(rate * 0.4):  # meter needs >= 400ms of audio
        return data
    meter = pyln.Meter(rate)
    loudness = meter.integrated_loudness(data)
    if not np.isfinite(loudness):  # silent block -> nothing to normalize
        return data
    return pyln.normalize.loudness(data, loudness, target_lufs)


def normalize_loudness_safely(
    data,
    rate,
    target_lufs: float | None = -16.0,
    peak=DEFAULT_AUDIO_PEAK,
):
    """Normalize loudness and peak-limit the result to avoid clipped output."""
    if target_lufs is None:
        return data

    with warnings.catch_warnings():
        warnings.filterwarnings(
            "ignore",
            message="Possible clipped samples in output.",
            category=UserWarning,
        )
        normalized = normalize_loudness(data, rate, target_lufs)

    return peak_limit(normalized, peak)


def peak_limit(data, peak=DEFAULT_AUDIO_PEAK):
    """Scale audio down only when its absolute peak exceeds the target peak."""
    if peak <= 0:
        raise ValueError("peak must be positive")

    max_peak = np.max(np.abs(data)) if len(data) else 0
    if max_peak > peak:
        return data / max_peak * peak
    return data


def write_audio_file(
    path,
    audio,
    sample_rate,
    title=None,
    genre=None,
    description=None,
    track_number=None,
):
    """Write audio with soundfile and FLAC tags when applicable."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    sf.write(path, audio, sample_rate)

    if path.suffix.lower() == ".flac":
        tag_flac(
            path,
            title or path.stem,
            genre=genre,
            prompt=description,
            track_number=track_number,
        )

    return path


def tag_flac(path, title, genre=None, prompt=None, track_number=None):
    """Write FLAC metadata tags, skipping any that are not provided."""
    release_date = datetime.now(UTC).date().isoformat()
    audio = FLAC(path)
    audio["title"] = title
    audio["artist"] = (
        os.getenv("NOT_STUDIO_TRACK_AUTHOR", "Not Studio").strip() or "Not Studio"
    )
    audio["date"] = release_date
    audio["year"] = release_date[:4]
    if genre:
        audio["genre"] = genre
    if prompt:
        audio["description"] = prompt
    if track_number is not None:
        audio["tracknumber"] = str(track_number)
    audio.save()
