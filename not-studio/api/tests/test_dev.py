from __future__ import annotations

import sys

from not_studio import dev


def test_prod_delegates_to_main_with_production_flag(monkeypatch) -> None:
    calls: list[list[str]] = []
    monkeypatch.setattr(sys, "argv", ["prod", "--no-ui", "--api-port", "9001"])
    monkeypatch.setattr(dev, "main", lambda: calls.append(sys.argv.copy()))

    dev.prod()

    assert calls == [["prod", "--production", "--no-ui", "--api-port", "9001"]]
