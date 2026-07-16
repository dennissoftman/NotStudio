from __future__ import annotations

import subprocess
import sys

from not_studio import dev


def test_prod_delegates_to_main_with_production_flag(monkeypatch) -> None:
    calls: list[list[str]] = []
    monkeypatch.setattr(sys, "argv", ["prod", "--no-ui", "--api-port", "9001"])
    monkeypatch.setattr(dev, "main", lambda: calls.append(sys.argv.copy()))

    dev.prod()

    assert calls == [["prod", "--production", "--no-ui", "--api-port", "9001"]]


def test_no_preload_model_flag_disables_api_warmup(monkeypatch) -> None:
    captured: list[dict[str, str] | None] = []

    class FakeProc:
        def __init__(self, name, cmd, cwd, env=None):
            assert name == "api"
            self.name = name
            captured.append(env)

        def start(self) -> None:
            pass

        def alive(self) -> bool:
            return False

        def terminate(self) -> None:
            pass

    monkeypatch.setattr(sys, "argv", ["dev", "--no-ui", "--no-model"])
    monkeypatch.setattr(dev, "_Proc", FakeProc)
    monkeypatch.setattr(dev, "_port_in_use", lambda _: False)
    monkeypatch.setattr(dev, "_prepare_dependencies", lambda **_: None)

    dev.main()

    assert captured[0] is not None
    assert captured[0]["NOT_STUDIO_PRELOAD_LOCAL_MODEL_ON_STARTUP"] == "false"


def test_dev_launches_ui_with_yarn(tmp_path, monkeypatch) -> None:
    commands: list[tuple[str, list[str]]] = []

    class FakeProc:
        def __init__(self, name, cmd, cwd, env=None):
            self.name = name
            commands.append((name, cmd))

        def start(self) -> None:
            pass

        def alive(self) -> bool:
            return False

        def terminate(self) -> None:
            pass

    monkeypatch.setattr(sys, "argv", ["dev"])
    monkeypatch.setattr(dev, "_Proc", FakeProc)
    monkeypatch.setattr(dev, "_UI_DIR", tmp_path)
    monkeypatch.setattr(dev, "_port_in_use", lambda _: False)
    monkeypatch.setattr(dev, "_prepare_dependencies", lambda **_: ["/usr/bin/yarn"])

    dev.main()

    assert commands[1] == ("ui", ["/usr/bin/yarn", "dev"])


def test_prepare_dependencies_syncs_uv_and_yarn(monkeypatch) -> None:
    calls: list[tuple[list[str], object, bool]] = []
    executables = {"uv": "/usr/bin/uv", "yarn": "/usr/bin/yarn"}
    monkeypatch.setattr(dev.shutil, "which", executables.get)
    monkeypatch.setattr(
        dev.subprocess,
        "run",
        lambda command, cwd, check: calls.append((command, cwd, check)),
    )

    yarn = dev._prepare_dependencies(include_ui=True)

    assert yarn == ["/usr/bin/yarn"]
    assert calls == [
        (["/usr/bin/uv", "sync", "--locked"], dev._API_DIR, True),
        (["/usr/bin/yarn", "install", "--immutable"], dev._UI_DIR, True),
    ]


def test_yarn_command_uses_corepack_when_yarn_shim_is_unavailable(monkeypatch) -> None:
    executables = {"corepack": "/usr/bin/corepack"}
    monkeypatch.setattr(dev.shutil, "which", executables.get)

    assert dev._yarn_command() == ["/usr/bin/corepack", "yarn"]


def test_prepare_dependencies_stops_when_yarn_install_fails(monkeypatch) -> None:
    executables = {"uv": "/usr/bin/uv", "yarn": "/usr/bin/yarn"}
    monkeypatch.setattr(dev.shutil, "which", executables.get)

    def fail_yarn(command, cwd, check):
        if command[0] == "/usr/bin/yarn":
            raise subprocess.CalledProcessError(1, command)

    monkeypatch.setattr(dev.subprocess, "run", fail_yarn)

    try:
        dev._prepare_dependencies(include_ui=True)
    except subprocess.CalledProcessError:
        pass
    else:
        raise AssertionError("expected a failed Yarn install to stop startup")
