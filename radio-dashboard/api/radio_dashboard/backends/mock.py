"""In-process synthetic backends — no models, no GPU, deterministic.

They produce audibly distinct "music" (chord beds) and "speech" (voiced word
bursts) so the whole pipeline — orchestration, buffer, streaming — can be
exercised and heard without downloading Kokoro / Stable Audio weights.
"""

from __future__ import annotations

import hashlib
from typing import Any

import numpy as np

from ..audio import dsp
from .base import AudioBuffer, MusicBackend, SpeechBackend

_WORDS_PER_SECOND = 2.6


def _seed(text: str) -> int:
    return int(hashlib.sha1(text.encode("utf-8")).hexdigest()[:8], 16)


def _count_words(text: str) -> int:
    return max(1, len([w for w in text.split() if w.strip()]))


class MockMusicBackend(MusicBackend):
    """Detuned-chord bed with slow tremolo + light noise."""

    def generate_music(
        self,
        *,
        prompt: str,
        duration: float,
        sample_rate: int,
        channels: int,
        **options: Any,
    ) -> AudioBuffer:
        n = max(1, int(round(duration * sample_rate)))
        t = np.arange(n, dtype=np.float64) / sample_rate
        rng = np.random.default_rng(_seed(prompt))

        base = 110.0 * (2.0 ** (rng.integers(0, 12) / 12.0))  # A2..A3
        ratios = (1.0, 1.5, 2.0, 3.0)
        amps = (1.0, 0.5, 0.3, 0.15)
        lfo = 0.6 + 0.4 * np.sin(2 * np.pi * 0.1 * t + rng.random() * np.pi)
        detune = 1.0 + 0.003 * (1 + rng.random())

        left = np.zeros(n)
        right = np.zeros(n)
        for r, a in zip(ratios, amps):
            left += a * np.sin(2 * np.pi * base * r * t)
            right += a * np.sin(2 * np.pi * base * r * detune * t)
        noise = rng.standard_normal(n) * 0.04
        left = (left * lfo + noise) * 0.18
        right = (right * lfo + noise) * 0.18

        data = np.stack([left, right], axis=1).astype(np.float32)
        data = dsp.apply_fade(data, 0.5, 0.5, sample_rate)
        return AudioBuffer(dsp.ensure_channels(data, channels), sample_rate)


class MockSpeechBackend(SpeechBackend):
    """Voiced word-burst synthesis paced to a word count or a target duration."""

    def synthesize(
        self,
        *,
        text: str,
        sample_rate: int,
        channels: int = 1,
        target_duration: float | None = None,
        voice: str | None = None,
        **options: Any,
    ) -> AudioBuffer:
        words = _count_words(text)
        total = target_duration or (words / _WORDS_PER_SECOND + 0.4)
        total = max(0.3, float(total))
        rng = np.random.default_rng(_seed(text + (voice or "")))

        slot = total / words
        voiced_frac = 0.72
        out = np.zeros(int(round(total * sample_rate)) + 1, dtype=np.float64)
        cursor = 0.0
        f0 = 100.0 + 40.0 * rng.random()  # base pitch, per utterance
        for _ in range(words):
            voiced = slot * voiced_frac
            word_f0 = f0 * (0.9 + 0.2 * rng.random())  # slight prosody
            burst = self._voiced_burst(voiced, sample_rate, word_f0)
            start = int(round(cursor * sample_rate))
            end = min(start + len(burst), len(out))
            out[start:end] += burst[: end - start]
            cursor += slot

        data = dsp.as_2d(out.astype(np.float32))
        data = dsp.apply_fade(data, 0.02, 0.05, sample_rate)
        return AudioBuffer(dsp.ensure_channels(data, channels), sample_rate)

    @staticmethod
    def _voiced_burst(duration: float, sample_rate: int, f0: float) -> np.ndarray:
        n = max(1, int(round(duration * sample_rate)))
        t = np.arange(n, dtype=np.float64) / sample_rate
        sig = np.zeros(n)
        for harmonic in range(1, 7):  # buzzy, vowel-ish
            sig += (1.0 / harmonic) * np.sin(2 * np.pi * f0 * harmonic * t)
        window = np.hanning(n) if n > 1 else np.ones(n)
        return (sig * window * 0.5).astype(np.float64)
