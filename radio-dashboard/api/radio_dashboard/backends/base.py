from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

import numpy as np

from ..audio import dsp


@dataclass
class AudioBuffer:
    """Float32 PCM, shape ``(num_samples, num_channels)``, at ``sample_rate``."""

    data: np.ndarray
    sample_rate: int

    def __post_init__(self) -> None:
        self.data = dsp.as_2d(self.data)

    @property
    def channels(self) -> int:
        return self.data.shape[1]

    @property
    def num_samples(self) -> int:
        return self.data.shape[0]

    @property
    def duration(self) -> float:
        return self.num_samples / self.sample_rate if self.sample_rate else 0.0

    def to(self, sample_rate: int, channels: int) -> "AudioBuffer":
        data = dsp.resample(self.data, self.sample_rate, sample_rate)
        data = dsp.ensure_channels(data, channels)
        return AudioBuffer(data, sample_rate)


class Backend(ABC):
    kind: str = ""

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        self.config = dict(config or {})


class MusicBackend(Backend):
    kind = "music"

    @abstractmethod
    def generate_music(
        self,
        *,
        prompt: str,
        duration: float,
        sample_rate: int,
        channels: int,
        **options: Any,
    ) -> AudioBuffer:
        """Generate ``duration`` seconds of music for ``prompt``."""


class SpeechBackend(Backend):
    kind = "speech"

    @abstractmethod
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
        """Synthesize ``text``. If ``target_duration`` is set, pace/pad to fit it."""
