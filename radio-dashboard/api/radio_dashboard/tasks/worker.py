"""arq worker entrypoint.

Run with::

    uv run arq radio_dashboard.tasks.worker.WorkerSettings
"""

from __future__ import annotations

from typing import Any

from arq import cron

from ..config import get_settings
from ..db import init_db
from .jobs import (
    generate_tracks_job,
    make_video_job,
    render_announcement_job,
    render_batch_job,
)
from .queue import redis_settings
from .scheduler import buffer_tick, schedule_tick


async def startup(ctx: dict[str, Any]) -> None:
    await init_db()


class WorkerSettings:
    functions = [render_batch_job, render_announcement_job, generate_tracks_job, make_video_job]
    cron_jobs = [
        # Top up stream buffers every 15s (feature #4).
        cron(buffer_tick, second=set(range(0, 60, 15)), run_at_startup=True, unique=True),
        # Fire due schedules once a minute (feature #1).
        cron(schedule_tick, second={1}, run_at_startup=False, unique=True),
    ]
    redis_settings = redis_settings()
    allow_abort_jobs = True  # enables job.abort() -> cancel
    max_tries = 2
    keep_result = 3600
    # Generation / video renders run for minutes — don't let arq's 300s default
    # cancel them mid-run.
    job_timeout = get_settings().job_timeout_seconds
    on_startup = startup
