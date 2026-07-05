import numpy as np
import pyloudnorm as pyln
from mutagen.flac import FLAC


def normalize_loudness(data, rate, target_lufs=-16.0):
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


def tag_flac(path, title, genre=None, prompt=None, track_number=None):
    """Write FLAC metadata tags, skipping any that are not provided."""
    audio = FLAC(path)
    audio["title"] = title
    if genre:
        audio["genre"] = genre
    if prompt:
        audio["description"] = prompt
    if track_number is not None:
        audio["tracknumber"] = str(track_number)
    audio.save()
