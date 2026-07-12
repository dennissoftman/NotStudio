from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from contextlib import suppress
from typing import Any

_tasks: dict[str, asyncio.Task[Any]] = {}


def start_job_task(job_id: str, runner: Callable[[str], Awaitable[dict[str, Any]]]) -> None:
    task = asyncio.create_task(runner(job_id), name=f"not-studio-job-{job_id}")
    _tasks[job_id] = task

    def cleanup(done: asyncio.Task[Any]) -> None:
        _tasks.pop(job_id, None)
        with suppress(asyncio.CancelledError, Exception):
            done.result()

    task.add_done_callback(cleanup)


def cancel_job_task(job_id: str) -> bool:
    task = _tasks.get(job_id)
    if task is None or task.done():
        return False
    task.cancel()
    return True


def active_job_ids() -> set[str]:
    return {job_id for job_id, task in _tasks.items() if not task.done()}


async def shutdown_job_tasks(timeout: float = 10.0) -> set[str]:
    job_ids = active_job_ids()
    if not job_ids:
        return set()

    tasks = [_tasks[job_id] for job_id in job_ids if job_id in _tasks]
    for task in tasks:
        task.cancel()

    with suppress(asyncio.TimeoutError):
        await asyncio.wait_for(asyncio.gather(*tasks, return_exceptions=True), timeout=timeout)
    return job_ids
