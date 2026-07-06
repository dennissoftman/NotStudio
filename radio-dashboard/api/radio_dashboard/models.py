"""SQLModel tables for the Radio Dashboard.

JSON columns hold flexible, provider-specific config so the schema stays stable
while backends / orchestration recipes evolve (see docs/CAPTIONS.md "Do Not
Hardcode").
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Column
from sqlmodel import Field, SQLModel

from .constants import new_id, utcnow


class Backend(SQLModel, table=True):
    """A configured audio-generation or TTS backend instance (feature #2)."""

    id: str = Field(default_factory=new_id, primary_key=True)
    name: str = Field(index=True)
    kind: str  # BackendKind: "speech" | "music"
    provider: str  # BackendProvider: "mock" | "kokoro" | "stable_audio"
    config: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    enabled: bool = True
    created_at: datetime = Field(default_factory=utcnow)


class Program(SQLModel, table=True):
    """An orchestration recipe: music + inserted speech/ads/info/jingles.

    ``config`` is the recipe consumed by the timeline builder, e.g.::

        {
          "target_lufs": -16.0,
          "crossfade_seconds": 4.0,
          "music": {"prompts": ["deep house radio bed"], "track_seconds": 210},
          "inserts": [
            {"kind": "station_id", "cadence_seconds": 900, "texts": ["Neural FM"]},
            {"kind": "news", "cadence_seconds": 600, "voice": "am_michael",
             "texts": ["..."], "ducking": true, "bed_volume_db": -8}
          ]
        }
    """

    id: str = Field(default_factory=new_id, primary_key=True)
    name: str = Field(index=True)
    description: str = ""
    music_backend_id: str | None = Field(default=None, foreign_key="backend.id")
    speech_backend_id: str | None = Field(default=None, foreign_key="backend.id")
    config: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class Stream(SQLModel, table=True):
    """A live channel that plays continuously from a pre-allocated buffer."""

    id: str = Field(default_factory=new_id, primary_key=True)
    name: str = Field(index=True)
    program_id: str | None = Field(default=None, foreign_key="program.id", index=True)
    status: str = "stopped"  # StreamStatus
    sample_rate: int = 44100
    channels: int = 2
    buffer_min_seconds: float = 900.0
    batch_target_seconds: float = 1080.0
    batch_max_seconds: float = 1200.0
    # Optional Icecast publish target (feature #3), e.g.
    # {"enabled": true, "host": "localhost", "port": 8000, "mount": "/neural.mp3",
    #  "username": "source", "password": "hackme", "format": "mp3"}
    icecast: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON, nullable=True))
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class Job(SQLModel, table=True):
    """A unit of queued work. ``id`` is also the arq job id (submit/track/cancel)."""

    id: str = Field(default_factory=new_id, primary_key=True)
    type: str = "batch"  # JobType
    status: str = "queued"  # JobStatus
    stream_id: str | None = Field(default=None, foreign_key="stream.id", index=True)
    program_id: str | None = Field(default=None, foreign_key="program.id")
    schedule_id: str | None = Field(default=None, foreign_key="schedule.id")
    params: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    progress: float = 0.0
    message: str = ""
    result: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON, nullable=True))
    error: str | None = None
    created_at: datetime = Field(default_factory=utcnow, index=True)
    enqueued_at: datetime | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None


class Schedule(SQLModel, table=True):
    """A recurring / one-shot trigger that submits Jobs (feature #1)."""

    id: str = Field(default_factory=new_id, primary_key=True)
    name: str = Field(index=True)
    action: str = "render_batch"  # ScheduleAction
    program_id: str | None = Field(default=None, foreign_key="program.id")
    stream_id: str | None = Field(default=None, foreign_key="stream.id")
    trigger_type: str = "interval"  # TriggerType
    # cron -> {"expr": "0 8 * * *"}; interval -> {"seconds": 3600}; date -> {"run_at": iso}
    trigger: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    enabled: bool = True
    last_run_at: datetime | None = None
    next_run_at: datetime | None = Field(default=None, index=True)
    created_at: datetime = Field(default_factory=utcnow)


class HistoryItem(SQLModel, table=True):
    """A saved generated audio artefact (feature #4 history)."""

    id: str = Field(default_factory=new_id, primary_key=True)
    kind: str = "batch"  # HistoryKind
    title: str = ""
    stream_id: str | None = Field(default=None, foreign_key="stream.id", index=True)
    program_id: str | None = Field(default=None, foreign_key="program.id")
    job_id: str | None = Field(default=None, foreign_key="job.id")
    path: str = ""  # absolute path to the audio file
    vtt_path: str | None = None  # the WebVTT timeline used to render it
    sample_rate: int = 44100
    channels: int = 2
    duration_seconds: float = 0.0
    size_bytes: int = 0
    lufs: float | None = None
    meta: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    created_at: datetime = Field(default_factory=utcnow, index=True)


class PlayoutSegment(SQLModel, table=True):
    """An ordered entry in a stream's pre-allocated playout buffer (feature #4)."""

    id: str = Field(default_factory=new_id, primary_key=True)
    stream_id: str = Field(foreign_key="stream.id", index=True)
    history_item_id: str = Field(foreign_key="historyitem.id")
    sequence: int = Field(index=True)
    duration_seconds: float = 0.0
    state: str = "ready"  # SegmentState
    created_at: datetime = Field(default_factory=utcnow)
    played_at: datetime | None = None
