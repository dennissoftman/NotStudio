"""One-command dev launcher: ``uv run dev``.

Brings up Redis (via ``docker compose``), the API (uvicorn --reload), the arq
worker (--watch), and the Vite UI together, with prefixed logs and a clean
Ctrl-C shutdown of the whole tree.

    uv run dev                 # everything
    uv run dev --no-ui         # backend only
    uv run dev --no-worker     # API only (+ redis)
    uv run dev --no-redis      # don't touch docker
    uv run dev --api-port 8001

Run the test suite with ``uv run pytest``.
"""

from __future__ import annotations

import os
import shutil
import signal
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path
from urllib.parse import urlparse

from .config import get_settings

_PKG_DIR = Path(__file__).resolve().parent  # .../api/radio_dashboard
_API_DIR = _PKG_DIR.parent  # .../api
_SUBPROJECT_DIR = _API_DIR.parent  # .../radio-dashboard
_UI_DIR = _SUBPROJECT_DIR / "ui"

_COLORS = {
    "dev": "\033[1m",
    "redis": "\033[33m",
    "api": "\033[36m",
    "worker": "\033[35m",
    "ui": "\033[32m",
}
_RESET = "\033[0m"


def _log(name: str, message: str) -> None:
    print(f"{_COLORS.get(name, '')}[{name}]{_RESET} {message}", flush=True)


def _redis_reachable(url: str) -> bool:
    parsed = urlparse(url)
    host, port = parsed.hostname or "localhost", parsed.port or 6379
    try:
        with socket.create_connection((host, port), timeout=0.5):
            return True
    except OSError:
        return False


def _ensure_redis() -> None:
    url = get_settings().redis_url
    if _redis_reachable(url):
        _log("redis", "already running")
        return
    if not shutil.which("docker"):
        _log("redis", "not running and docker not found — start Redis yourself.")
        return
    _log("redis", "starting via `docker compose up -d redis`…")
    subprocess.run(
        ["docker", "compose", "up", "-d", "redis"],
        cwd=str(_SUBPROJECT_DIR),
        check=False,
    )
    for _ in range(20):
        if _redis_reachable(url):
            _log("redis", "ready")
            return
        time.sleep(0.5)
    _log("redis", "did not come up in time — the worker may fail to connect.")


class _Proc:
    def __init__(self, name: str, cmd: list[str], cwd: Path) -> None:
        self.name = name
        self.cmd = cmd
        self.cwd = cwd
        self.popen: subprocess.Popen[str] | None = None

    def start(self) -> None:
        self.popen = subprocess.Popen(
            self.cmd,
            cwd=str(self.cwd),
            env=os.environ.copy(),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            start_new_session=True,  # own process group -> we can kill the whole tree
        )
        threading.Thread(target=self._pump, daemon=True).start()

    def _pump(self) -> None:
        assert self.popen and self.popen.stdout
        for line in self.popen.stdout:
            _log(self.name, line.rstrip())

    def alive(self) -> bool:
        return self.popen is not None and self.popen.poll() is None

    def terminate(self) -> None:
        if not self.alive():
            return
        assert self.popen
        try:
            os.killpg(os.getpgid(self.popen.pid), signal.SIGTERM)
        except (ProcessLookupError, PermissionError):
            pass

    def kill(self) -> None:
        if not self.alive():
            return
        assert self.popen
        try:
            os.killpg(os.getpgid(self.popen.pid), signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass


def main() -> None:
    args = set(sys.argv[1:])
    if "--help" in args or "-h" in args:
        print(__doc__)
        return

    api_port = "8000"
    argv = sys.argv[1:]
    if "--api-port" in argv:
        api_port = argv[argv.index("--api-port") + 1]

    if "--no-redis" not in args:
        _ensure_redis()

    bindir = Path(sys.executable).parent
    procs: list[_Proc] = [
        _Proc(
            "api",
            [str(bindir / "uvicorn"), "radio_dashboard.main:app", "--reload", "--port", api_port],
            _API_DIR,
        )
    ]
    if "--no-worker" not in args:
        procs.append(
            _Proc(
                "worker",
                [
                    str(bindir / "arq"),
                    "radio_dashboard.tasks.worker.WorkerSettings",
                    "--watch",
                    "radio_dashboard",
                ],
                _API_DIR,
            )
        )
    if "--no-ui" not in args:
        npm = shutil.which("npm")
        if npm and (_UI_DIR / "node_modules").is_dir():
            procs.append(_Proc("ui", [npm, "run", "dev"], _UI_DIR))
        elif npm:
            _log("ui", "skipped — run `npm install` in ui/ first.")
        else:
            _log("ui", "skipped — npm not found on PATH.")

    _log("dev", f"launching: {', '.join(p.name for p in procs)}")
    for proc in procs:
        proc.start()
    _log("dev", f"API   → http://localhost:{api_port}  (docs at /docs)")
    _log("dev", "UI    → http://localhost:5173")
    _log("dev", "Ctrl-C stops everything.")

    stop = threading.Event()
    signal.signal(signal.SIGINT, lambda *_: stop.set())
    signal.signal(signal.SIGTERM, lambda *_: stop.set())

    try:
        while not stop.is_set() and any(p.alive() for p in procs):
            time.sleep(0.4)
    finally:
        _log("dev", "shutting down…")
        for proc in procs:
            proc.terminate()
        deadline = time.time() + 5
        for proc in procs:
            if proc.popen:
                try:
                    proc.popen.wait(timeout=max(0.1, deadline - time.time()))
                except subprocess.TimeoutExpired:
                    proc.kill()
