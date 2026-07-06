from __future__ import annotations

from datetime import datetime, timezone
from typing import Final, Literal


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def new_id() -> str:
    from uuid import uuid4

    return uuid4().hex


# --- Backends -----------------------------------------------------------------
BackendKind = Literal["speech", "music"]
BackendProvider = Literal["mock", "kokoro", "stable_audio"]

# --- Jobs ---------------------------------------------------------------------
# Mirrors arq's lifecycle plus our terminal states.
JobStatus = Literal["queued", "in_progress", "completed", "failed", "cancelled", "deferred"]
JobType = Literal["batch", "oneoff", "program_render"]

TERMINAL_JOB_STATUSES: Final = frozenset({"completed", "failed", "cancelled"})

# --- Streams ------------------------------------------------------------------
StreamStatus = Literal["stopped", "buffering", "live"]

# --- Schedules ----------------------------------------------------------------
TriggerType = Literal["cron", "interval", "date"]
ScheduleAction = Literal["render_batch", "start_stream", "stop_stream"]

# --- Playout ------------------------------------------------------------------
SegmentState = Literal["ready", "playing", "played"]

# --- History ------------------------------------------------------------------
HistoryKind = Literal["batch", "segment", "stem"]

# --- Timeline cue kinds we insert into a program ------------------------------
InsertKind = Literal["news", "info", "ad", "station_id", "jingle", "weather"]
