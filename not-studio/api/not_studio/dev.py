"""One-command dev launcher for the FastAPI API and Vite UI."""

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

_PKG_DIR = Path(__file__).resolve().parent
_API_DIR = _PKG_DIR.parent
_SUBPROJECT_DIR = _API_DIR.parent
_UI_DIR = _SUBPROJECT_DIR / "ui"

_COLORS = {"dev": "\033[1m", "api": "\033[36m", "ui": "\033[32m"}
_RESET = "\033[0m"


def _log(name: str, message: str) -> None:
    print(f"{_COLORS.get(name, '')}[{name}]{_RESET} {message}", flush=True)


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
            start_new_session=True,
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


def _port_in_use(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.3)
        return sock.connect_ex(("127.0.0.1", port)) == 0


def main() -> None:
    args = set(sys.argv[1:])
    if "--help" in args or "-h" in args:
        print(__doc__)
        return

    api_port = "8001"
    argv = sys.argv[1:]
    if "--api-port" in argv:
        api_port = argv[argv.index("--api-port") + 1]
    if _port_in_use(int(api_port)):
        _log(
            "dev",
            f"port {api_port} is already in use; pass --api-port or stop the old API.",
        )
        return

    bindir = Path(sys.executable).parent
    procs: list[_Proc] = [
        _Proc(
            "api",
            [
                str(bindir / "uvicorn"),
                "not_studio.main:app",
                "--reload",
                "--port",
                api_port,
            ],
            _API_DIR,
        )
    ]
    if "--no-ui" not in args:
        npm = shutil.which("npm")
        if npm and (_UI_DIR / "node_modules").is_dir():
            procs.append(_Proc("ui", [npm, "run", "dev"], _UI_DIR))
        elif npm:
            _log("ui", "skipped: run `npm install` in ui/ first.")
        else:
            _log("ui", "skipped: npm not found on PATH.")

    _log("dev", f"launching: {', '.join(p.name for p in procs)}")
    for proc in procs:
        proc.start()
    _log("dev", f"API -> http://localhost:{api_port}  (docs at /docs)")
    _log("dev", "UI  -> http://localhost:5173")

    stop = threading.Event()
    signal.signal(signal.SIGINT, lambda *_: stop.set())
    signal.signal(signal.SIGTERM, lambda *_: stop.set())

    try:
        while not stop.is_set() and any(p.alive() for p in procs):
            time.sleep(0.4)
    finally:
        _log("dev", "shutting down")
        for proc in procs:
            proc.terminate()
