from __future__ import annotations

import json
import re
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

from ..engine_bridge import run_engine_cli_streaming


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or "track"


def generate_batch(
    prompts: list[dict[str, Any]],
    *,
    sample_rate: int,
    model: str,
    out_dir: Path,
    on_progress: Callable[[float, str], None] | None = None,
) -> list[tuple[dict[str, Any], Path]]:
    """Generate many tracks in ONE ``main.py --prompts`` call (single model load).

    ``prompts`` items need ``title`` + ``prompt`` (optional ``duration``). Streams
    main.py's output so ``on_progress(frac, message)`` fires on model load and after
    each track. Returns ``(spec, flac_path)`` for each track produced (main.py names
    outputs ``<slug(title)>.flac``).
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    total = max(1, len(prompts))
    tail: list[str] = []
    state = {"done": 0}

    def handle(line: str) -> None:
        if line.strip():
            tail.append(line)
            del tail[:-40]  # keep a short tail for error messages
        if on_progress is None:
            return
        if "loading model" in line.lower():
            on_progress(0.12, "Loading model…")
        elif line.startswith("Saved:"):
            state["done"] += 1
            frac = min(0.95, 0.12 + 0.83 * state["done"] / total)
            on_progress(frac, f"Rendered {state['done']}/{total} track(s)")

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
        code = run_engine_cli_streaming("main.py", args, handle)
    if code != 0:
        raise RuntimeError(
            f"Stable Audio batch failed (exit {code}): {' / '.join(tail[-6:]) or 'no output'}"
        )

    produced = [(p, out_dir / f"{_slugify(p['title'])}.flac") for p in prompts]
    produced = [(p, path) for p, path in produced if path.exists()]
    if not produced:
        raise RuntimeError("Stable Audio produced no tracks (check the parent engine env).")
    return produced
