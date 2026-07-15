"""SQLModel tables for Not Studio."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Column
from sqlmodel import Field, SQLModel

from .constants import new_id, utcnow


class Job(SQLModel, table=True):
    """A local background job for generation."""

    id: str = Field(default_factory=new_id, primary_key=True)
    type: str = "generate_tracks"
    status: str = "queued"
    params: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    progress: float = 0.0
    message: str = ""
    result: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON, nullable=True))
    error: str | None = None
    created_at: datetime = Field(default_factory=utcnow, index=True)
    enqueued_at: datetime | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None


class HistoryItem(SQLModel, table=True):
    """A generated track saved for human review."""

    id: str = Field(default_factory=new_id, primary_key=True)
    kind: str = "track"
    title: str = ""
    job_id: str | None = Field(default=None, foreign_key="job.id")
    path: str = ""
    sample_rate: int = 44100
    channels: int = 2
    duration_seconds: float = 0.0
    size_bytes: int = 0
    lufs: float | None = None
    meta: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    created_at: datetime = Field(default_factory=utcnow, index=True)
