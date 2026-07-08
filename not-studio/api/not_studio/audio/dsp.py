"""Lightweight numpy DSP for generated tracks and rendered mixes.

All buffers are float32 of shape ``(num_samples, num_channels)``. No torch — this
keeps the dashboard installable without the heavy engine deps; the real backends
resample through their own pipelines and hand us target-rate audio.
"""

from __future__ import annotations

from math import gcd

import numpy as np
import pyloudnorm as pyln
import soundfile as sf
from scipy.signal import resample_poly

DEFAULT_PEAK = 0.999


def db_to_gain(db: float) -> float:
    return float(10.0 ** (db / 20.0))


def silence(seconds: float, sample_rate: int, channels: int) -> np.ndarray:
    n = max(0, int(round(seconds * sample_rate)))
    return np.zeros((n, channels), dtype=np.float32)


def as_2d(data: np.ndarray) -> np.ndarray:
    """Coerce mono ``(n,)`` to ``(n, 1)``; leave ``(n, c)`` alone."""
    arr = np.asarray(data, dtype=np.float32)
    if arr.ndim == 1:
        arr = arr[:, None]
    return arr


def ensure_channels(data: np.ndarray, channels: int) -> np.ndarray:
    data = as_2d(data)
    have = data.shape[1]
    if have == channels:
        return data
    if have == 1:
        return np.repeat(data, channels, axis=1)
    if channels == 1:
        return data.mean(axis=1, keepdims=True)
    # Downmix/upmix by averaging then repeating.
    mono = data.mean(axis=1, keepdims=True)
    return np.repeat(mono, channels, axis=1)


def resample(data: np.ndarray, sr_in: int, sr_out: int) -> np.ndarray:
    if sr_in == sr_out:
        return as_2d(data)
    data = as_2d(data)
    g = gcd(sr_in, sr_out)
    up, down = sr_out // g, sr_in // g
    out = resample_poly(data, up, down, axis=0)
    return out.astype(np.float32, copy=False)


def apply_fade(
    data: np.ndarray, fade_in_seconds: float, fade_out_seconds: float, sample_rate: int
) -> np.ndarray:
    data = as_2d(data).copy()
    n = len(data)
    fi = min(int(fade_in_seconds * sample_rate), n)
    fo = min(int(fade_out_seconds * sample_rate), n)
    if fi > 0:
        data[:fi] *= np.linspace(0.0, 1.0, fi, dtype=np.float32)[:, None]
    if fo > 0:
        data[n - fo :] *= np.linspace(1.0, 0.0, fo, dtype=np.float32)[:, None]
    return data


def equal_power_crossfade(a: np.ndarray, b: np.ndarray, n: int) -> np.ndarray:
    """Concatenate a and b overlapping ``n`` samples with an equal-power fade."""
    a, b = as_2d(a), as_2d(b)
    if n <= 0 or len(a) < n or len(b) < n:
        return np.concatenate([a, b], axis=0)
    t = np.linspace(0.0, 1.0, n, dtype=np.float32)[:, None]
    fade_out = np.cos(t * np.pi / 2)
    fade_in = np.sin(t * np.pi / 2)
    overlap = a[-n:] * fade_out + b[:n] * fade_in
    return np.concatenate([a[:-n], overlap, b[n:]], axis=0)


def concat_crossfade(
    segments: list[np.ndarray], sample_rate: int, crossfade_seconds: float
) -> np.ndarray:
    segments = [as_2d(s) for s in segments if len(s)]
    if not segments:
        return np.zeros((0, 1), dtype=np.float32)
    n = int(crossfade_seconds * sample_rate)
    out = segments[0]
    for seg in segments[1:]:
        out = equal_power_crossfade(out, seg, n)
    return out


def overlay_with_duck(
    base: np.ndarray,
    insert: np.ndarray,
    at_seconds: float,
    sample_rate: int,
    *,
    ducking: bool = True,
    bed_gain: float = 1.0,
    insert_gain: float = 1.0,
    ramp_seconds: float = 0.3,
) -> np.ndarray:
    """Overlay ``insert`` onto ``base`` at ``at_seconds``, ducking the bed under it.

    Returns a (possibly longer) base buffer; both are coerced to the same channel
    count as ``base``.
    """
    base = as_2d(base).copy()
    channels = base.shape[1]
    insert = ensure_channels(insert, channels) * np.float32(insert_gain)

    start = max(0, int(round(at_seconds * sample_rate)))
    end = start + len(insert)
    if end > len(base):  # pad the bed so late inserts still fit
        base = np.concatenate(
            [base, np.zeros((end - len(base), channels), dtype=np.float32)], axis=0
        )

    if ducking and bed_gain != 1.0 and len(insert):
        ramp = min(int(ramp_seconds * sample_rate), len(insert) // 2)
        env = np.full(len(insert), bed_gain, dtype=np.float32)
        if ramp > 0:
            env[:ramp] = np.linspace(1.0, bed_gain, ramp, dtype=np.float32)
            env[len(insert) - ramp :] = np.linspace(bed_gain, 1.0, ramp, dtype=np.float32)
        base[start:end] *= env[:, None]

    base[start:end] += insert
    return base


def normalize_lufs(data: np.ndarray, sample_rate: int, target_lufs: float | None) -> np.ndarray:
    if target_lufs is None:
        return data
    data = as_2d(data)
    if len(data) < int(sample_rate * 0.4):  # meter needs >= 400ms
        return data
    meter = pyln.Meter(sample_rate)
    loudness = meter.integrated_loudness(data)
    if not np.isfinite(loudness):
        return data
    return pyln.normalize.loudness(data, loudness, target_lufs).astype(np.float32)


def measure_lufs(data: np.ndarray, sample_rate: int) -> float | None:
    data = as_2d(data)
    if len(data) < int(sample_rate * 0.4):
        return None
    loudness = pyln.Meter(sample_rate).integrated_loudness(data)
    return float(loudness) if np.isfinite(loudness) else None


def peak_limit(data: np.ndarray, peak: float = DEFAULT_PEAK) -> np.ndarray:
    data = as_2d(data)
    max_peak = float(np.max(np.abs(data))) if len(data) else 0.0
    if max_peak > peak:
        data = data / max_peak * peak
    return np.clip(data, -1.0, 1.0).astype(np.float32)


def to_int16_bytes(data: np.ndarray) -> bytes:
    """Interleaved little-endian s16 PCM (what we feed ffmpeg)."""
    data = np.clip(as_2d(data), -1.0, 1.0)
    return (data * 32767.0).astype("<i2").tobytes()


# --- File IO ------------------------------------------------------------------
def load_audio_file(path: str, target_sr: int, target_channels: int) -> np.ndarray:
    data, sr = sf.read(path, dtype="float32", always_2d=True)
    data = resample(data, sr, target_sr)
    return ensure_channels(data, target_channels)


def write_audio_file(path: str, data: np.ndarray, sample_rate: int) -> None:
    sf.write(path, as_2d(data), sample_rate)
