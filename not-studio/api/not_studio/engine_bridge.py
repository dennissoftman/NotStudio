"""Bridge to the parent audio engine.

Local generation reuses the parent project's ``main.py`` CLI via ``uv run --no-sync``
so none of the heavy deps (torch, stable-audio-3) are duplicated into this
subproject's environment.
"""

from __future__ import annotations

import subprocess
from collections.abc import Callable
from pathlib import Path

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
