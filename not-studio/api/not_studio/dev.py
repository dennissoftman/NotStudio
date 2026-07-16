"""One-command dev launcher for the FastAPI API and Vite UI.

Pass --no-model to skip ACE-Step warmup during UI-focused debugging.
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

_PKG_DIR = Path(__file__).resolve().parent
_API_DIR = _PKG_DIR.parent
_SUBPROJECT_DIR = _API_DIR.parent
_UI_DIR = _SUBPROJECT_DIR / "ui"

_COLORS = {"dev": "\033[1m", "api": "\033[36m", "ui": "\033[32m"}
_RESET = "\033[0m"


def _log(name: str, message: str) -> None:
    print(f"{_COLORS.get(name, '')}[{name}]{_RESET} {message}", flush=True)


class _Proc:
    def __init__(
        self,
        name: str,
        cmd: list[str],
        cwd: Path,
        env: dict[str, str] | None = None,
    ) -> None:
        self.name = name
        self.cmd = cmd
        self.cwd = cwd
        self.env = env
        self.popen: subprocess.Popen[str] | None = None

    def start(self) -> None:
        self.popen = subprocess.Popen(
            self.cmd,
            cwd=str(self.cwd),
            env=self.env or os.environ.copy(),
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


def _yarn_command() -> list[str]:
    yarn = shutil.which("yarn")
    if yarn:
        return [yarn]
    corepack = shutil.which("corepack")
    if corepack:
        return [corepack, "yarn"]
    raise RuntimeError("Yarn or Corepack is required to prepare the UI environment")


def _prepare_dependencies(*, include_ui: bool) -> list[str] | None:
    uv = shutil.which("uv")
    if not uv:
        raise RuntimeError("uv is required to prepare the API environment")
    _log("dev", "syncing API dependencies")
    subprocess.run([uv, "sync", "--locked"], cwd=_API_DIR, check=True)

    if not include_ui:
        return None
    yarn = _yarn_command()
    _log("dev", "installing UI dependencies")
    subprocess.run([*yarn, "install", "--immutable"], cwd=_UI_DIR, check=True)
    return yarn


def main() -> None:
    args = set(sys.argv[1:])
    if "--help" in args or "-h" in args:
        print(__doc__)
        return

    production = "--production" in args
    skip_model_preload = "--no-model" in args
    api_port = "8081" if production else "8001"
    argv = sys.argv[1:]
    if "--api-port" in argv:
        api_port = argv[argv.index("--api-port") + 1]
    if _port_in_use(int(api_port)):
        _log(
            "dev",
            f"port {api_port} is already in use; pass --api-port or stop the old API.",
        )
        return

    include_ui = "--no-ui" not in args
    yarn = _prepare_dependencies(include_ui=include_ui)
    bindir = Path(sys.executable).parent
    api_command = [
        str(bindir / "uvicorn"),
        "not_studio.main:app",
        "--host",
        "0.0.0.0" if production else "127.0.0.1",
        "--port",
        api_port,
    ]
    if not production:
        api_command.append("--reload")
    api_env = os.environ.copy()
    if skip_model_preload:
        api_env["NOT_STUDIO_PRELOAD_LOCAL_MODEL_ON_STARTUP"] = "false"
        _log("dev", "ACE-Step model preload disabled")
    procs: list[_Proc] = [
        _Proc(
            "api",
            api_command,
            _API_DIR,
            api_env,
        )
    ]
    if include_ui:
        assert yarn is not None
        procs.append(_Proc("ui", [*yarn, "production" if production else "dev"], _UI_DIR))

    _log("dev", f"launching: {', '.join(p.name for p in procs)}")
    for proc in procs:
        proc.start()
    display_host = "0.0.0.0" if production else "localhost"
    _log("dev", f"API -> http://{display_host}:{api_port}  (docs at /docs)")
    _log("dev", f"UI  -> http://{display_host}:{8080 if production else 5173}")

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


def prod() -> None:
    """Run the dev launcher in production mode."""
    if "--production" not in sys.argv[1:]:
        sys.argv.insert(1, "--production")
    main()
