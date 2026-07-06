from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any

from ..audio import dsp
from ..engine_bridge import run_engine_cli
from .base import AudioBuffer, MusicBackend


class StableAudioMusicBackend(MusicBackend):
    """Reuses the parent project's ``main.py`` (Stable Audio 3) via subprocess."""

    def generate_music(
        self,
        *,
        prompt: str,
        duration: float,
        sample_rate: int,
        channels: int,
        **options: Any,
    ) -> AudioBuffer:
        model = str(self.config.get("model", "auto"))

        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "music.flac"
            args = [
                prompt,
                "-d",
                str(round(float(duration), 3)),
                "-o",
                str(out),
                "-r",
                str(sample_rate),
            ]
            if model and model != "auto":
                args += ["--model", model]

            proc = run_engine_cli("main.py", args)
            if proc.returncode != 0 or not out.exists():
                raise RuntimeError(
                    f"Stable Audio generation failed (exit {proc.returncode}): "
                    f"{proc.stderr.strip() or proc.stdout.strip()}"
                )
            data = dsp.load_audio_file(str(out), sample_rate, channels)

        return AudioBuffer(data, sample_rate)
