"""Pluggable audio-generation + TTS backends (feature #2).

The registry lets the dashboard run entirely on the in-process ``mock`` backend
(no models, no GPU) while ``kokoro`` and ``stable_audio`` reuse the parent Neural
Radio engine when it is available.
"""

from .base import AudioBuffer, MusicBackend, SpeechBackend  # noqa: F401
from .registry import build_backend, provider_infos  # noqa: F401
