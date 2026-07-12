"""In-process notifications for job WebSocket subscribers."""

from __future__ import annotations

import asyncio

_condition = asyncio.Condition()
_version = 0


async def notify_jobs_changed() -> None:
    global _version
    async with _condition:
        _version += 1
        _condition.notify_all()


async def wait_for_jobs_changed(version: int, timeout: float = 2.0) -> int:
    async with _condition:
        if _version != version:
            return _version
        try:
            await asyncio.wait_for(_condition.wait_for(lambda: _version != version), timeout)
        except TimeoutError:
            pass
        return _version


def jobs_version() -> int:
    return _version
