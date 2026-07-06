"""Bridge to the parent Neural Radio engine.

Real backends reuse the parent project's CLIs (``speech.py`` / ``main.py``) via
``uv run --no-sync`` so none of the heavy deps (torch, kokoro, stable-audio-3)
are duplicated into this subproject's environment. The canonical typed-WebVTT
timeline parser is imported for optional validation of the timelines we emit.
"""

from __future__ import annotations

import subprocess
import sys
from collections.abc import Callable
from functools import lru_cache
from pathlib import Path
from types import ModuleType

from .config import get_settings


def engine_root() -> Path:
    return get_settings().engine_root


def engine_has(script: str) -> bool:
    return (engine_root() / script).is_file()


def engine_venv_ready() -> bool:
    root = engine_root()
    return (root / ".venv").exists() or (root / "uv.lock").is_file()


def submodule_checked_out(name: str) -> bool:
    path = engine_root() / name
    return path.is_dir() and any(path.iterdir())


@lru_cache
def load_timeline_module() -> ModuleType | None:
    """Import the engine's pure ``timeline`` module for validation, if present."""
    root = str(engine_root())
    if root not in sys.path:
        sys.path.append(root)  # append: never shadow our own packages
    try:
        import timeline  # type: ignore

        return timeline
    except Exception:
        return None


def run_engine_cli(
    script: str, args: list[str], timeout: float | None = 3600.0
) -> subprocess.CompletedProcess[str]:
    settings = get_settings()
    cmd = [
        settings.uv_path,
        "run",
        "--no-sync",
        "--project",
        str(settings.engine_root),
        "python",
        script,
        *args,
    ]
    return subprocess.run(
        cmd,
        cwd=str(settings.engine_root),
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def run_engine_cli_streaming(
    script: str,
    args: list[str],
    on_line: Callable[[str], None],
    timeout: float | None = None,
) -> int:
    """Run an engine CLI, streaming merged stdout+stderr lines to ``on_line``.

    Uses ``python -u`` so the child's prints appear immediately (for live
    progress). Returns the exit code.
    """
    settings = get_settings()
    cmd = [
        settings.uv_path,
        "run",
        "--no-sync",
        "--project",
        str(settings.engine_root),
        "python",
        "-u",
        script,
        *args,
    ]
    proc = subprocess.Popen(
        cmd,
        cwd=str(settings.engine_root),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )
    assert proc.stdout is not None
    for line in proc.stdout:
        on_line(line.rstrip("\n"))
    proc.wait(timeout=timeout)
    return proc.returncode or 0
