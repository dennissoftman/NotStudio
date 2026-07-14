from __future__ import annotations

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

    dev.main()

    assert captured[0] is not None
    assert captured[0]["NOT_STUDIO_PRELOAD_LOCAL_MODEL_ON_STARTUP"] == "false"
