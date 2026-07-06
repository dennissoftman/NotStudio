from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any

from ..audio import dsp
from ..engine_bridge import run_engine_cli
from .base import AudioBuffer, SpeechBackend

DEFAULT_VOICE = "am_michael"


class KokoroSpeechBackend(SpeechBackend):
    """Reuses the parent project's ``speech.py`` (Kokoro TTS) via subprocess."""

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
        voice = voice or self.config.get("voice") or DEFAULT_VOICE
        rate = max(32000, sample_rate)  # speech.py requires >= 32000

        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "speech.flac"
            args = [
                "--text",
                text,
                "-o",
                str(out),
                "--rate",
                str(rate),
                "--voice",
                str(voice),
                "--no-progress",
            ]
            if self.config.get("device"):
                args += ["--device", str(self.config["device"])]
            if target_duration and target_duration > 0:
                words = max(1, len(text.split()))
                wpm = max(90.0, min(280.0, words * 60.0 / target_duration))
                args += ["--target-wpm", str(round(wpm, 1))]

            proc = run_engine_cli("speech.py", args)
            if proc.returncode != 0 or not out.exists():
                raise RuntimeError(
                    f"Kokoro synthesis failed (exit {proc.returncode}): "
                    f"{proc.stderr.strip() or proc.stdout.strip()}"
                )
            data = dsp.load_audio_file(str(out), sample_rate, channels)

        return AudioBuffer(data, sample_rate)
