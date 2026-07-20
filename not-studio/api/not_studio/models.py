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
    album_id: str | None = Field(default=None, foreign_key="album.id", index=True)
    job_id: str | None = Field(default=None, foreign_key="job.id")
    path: str = ""
    sample_rate: int = 44100
    channels: int = 2
    duration_seconds: float = 0.0
    size_bytes: int = 0
    lufs: float | None = None
    meta: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    created_at: datetime = Field(default_factory=utcnow, index=True)


class Album(SQLModel, table=True):
    """A stable album identity independent of its editable display title."""

    id: str = Field(default_factory=new_id, primary_key=True)
    title: str = Field(index=True)
    summary: str = ""
    notes: str = ""
    artwork_prompt: str = ""
    artwork_guidance: str = ""
    visual_direction: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    created_at: datetime = Field(default_factory=utcnow, index=True)
    updated_at: datetime = Field(default_factory=utcnow)


class GenerationRun(SQLModel, table=True):
    """Durable state for natural-language planning and end-to-end generation."""

    id: str = Field(default_factory=new_id, primary_key=True)
    status: str = Field(default="planning", index=True)
    stage: str = "planning"
    brief: str
    artwork_guidance: str = ""
    style_reference_id: str | None = Field(default=None, index=True)
    cover_output_size: int = 2048
    auto_start: bool = False
    plan: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON, nullable=True))
    params: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    album_id: str | None = Field(default=None, foreign_key="album.id", index=True)
    plan_job_id: str | None = Field(default=None, foreign_key="job.id")
    generation_job_id: str | None = Field(default=None, foreign_key="job.id")
    error: str | None = None
    created_at: datetime = Field(default_factory=utcnow, index=True)
    updated_at: datetime = Field(default_factory=utcnow)


class StyleReference(SQLModel, table=True):
    """A normalized image used to guide an album's visual identity."""

    id: str = Field(default_factory=new_id, primary_key=True)
    path: str
    mime: str = "image/png"
    width: int
    height: int
    size_bytes: int
    original_name: str = ""
    created_at: datetime = Field(default_factory=utcnow, index=True)


class CoverAsset(SQLModel, table=True):
    """An immutable generated or uploaded album/track cover version."""

    id: str = Field(default_factory=new_id, primary_key=True)
    owner_type: str = Field(index=True)
    owner_id: str = Field(index=True)
    version: int = 1
    status: str = Field(default="queued", index=True)
    selected: bool = Field(default=False, index=True)
    path: str = ""
    mime: str = "image/png"
    width: int = 0
    height: int = 0
    size_bytes: int = 0
    prompt: str = ""
    effective_prompt: str = ""
    style_reference_id: str | None = Field(default=None, index=True)
    seed: int | None = None
    provider: str = "flux2_klein_local"
    model: str = "black-forest-labs/FLUX.2-klein-4B"
    config: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    job_id: str | None = Field(default=None, foreign_key="job.id", index=True)
    error: str | None = None
    created_at: datetime = Field(default_factory=utcnow, index=True)
    selected_at: datetime | None = None
