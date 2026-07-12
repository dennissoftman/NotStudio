import asyncio
import time
from pathlib import Path

import pytest

from not_studio.tasks.processes import (
    run_in_process,
    run_in_reusable_process,
    shutdown_reusable_processes,
)

_counter = 0


def _slow_write(path: str) -> None:
    time.sleep(5)
    Path(path).write_text("finished", encoding="utf-8")


def _return_pair() -> tuple[str, str]:
    return ("ok", "value")


def _increment_counter() -> int:
    global _counter
    _counter += 1
    return _counter


async def test_run_in_process_returns_success_payload():
    assert await run_in_process(_return_pair) == ("ok", "value")


async def test_reusable_process_keeps_child_state_between_calls():
    try:
        first = await run_in_reusable_process("test-counter", _increment_counter)
        second = await run_in_reusable_process("test-counter", _increment_counter)
    finally:
        await shutdown_reusable_processes()

    assert (first, second) == (1, 2)


async def test_run_in_process_terminates_child_on_cancellation(tmp_path):
    marker = tmp_path / "marker.txt"
    task = asyncio.create_task(run_in_process(_slow_write, str(marker)))

    await asyncio.sleep(0.3)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert not marker.exists()
