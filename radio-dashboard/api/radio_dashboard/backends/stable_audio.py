from __future__ import annotations

import json
import re
import tempfile
from pathlib import Path
from typing import Any

from ..audio import dsp
from ..engine_bridge import run_engine_cli
from .base import AudioBuffer, MusicBackend


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or "track"


def generate_batch(
    prompts: list[dict[str, Any]],
    *,
    sample_rate: int,
    model: str,
    out_dir: Path,
) -> list[tuple[dict[str, Any], Path]]:
    """Generate many tracks in ONE ``main.py --prompts`` call (single model load).

    ``prompts`` items need ``title`` + ``prompt`` (optional ``duration``). Returns
    ``(spec, flac_path)`` for each track that was produced (main.py names outputs
    ``<slug(title)>.flac``).
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        spec_path = Path(tmp) / "prompts.json"
        spec_path.write_text(
            json.dumps(
                [
                    {
                        "title": p["title"],
                        "prompt": p["prompt"],
                        "duration": float(p.get("duration", 180)),
                    }
                    for p in prompts
                ]
            ),
            encoding="utf-8",
        )
        args = ["--prompts", str(spec_path), "-o", str(out_dir), "-r", str(sample_rate)]
        if model and model != "auto":
            args += ["--model", model]
        proc = run_engine_cli("main.py", args, timeout=None)
        if proc.returncode != 0:
            raise RuntimeError(
                f"Stable Audio batch failed (exit {proc.returncode}): "
                f"{proc.stderr.strip() or proc.stdout.strip()}"
            )

    produced = [(p, out_dir / f"{_slugify(p['title'])}.flac") for p in prompts]
    produced = [(p, path) for p, path in produced if path.exists()]
    if not produced:
        raise RuntimeError("Stable Audio produced no tracks (check the parent engine env).")
    return produced


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
