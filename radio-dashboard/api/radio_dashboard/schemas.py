"""API request/response schemas.

Table models are returned directly for reads; these cover create/update payloads
and give the orchestration recipe real structure in the OpenAPI docs (the UI reads
this to render forms). Recipe models are permissive — extra keys are allowed so
backends can carry provider-specific options.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


# --- Backends -----------------------------------------------------------------
class BackendCreate(BaseModel):
    name: str
    kind: Literal["speech", "music"]
    provider: Literal["mock", "kokoro", "stable_audio"]
    config: dict[str, Any] = Field(default_factory=dict)
    enabled: bool = True


class BackendUpdate(BaseModel):
    name: str | None = None
    config: dict[str, Any] | None = None
    enabled: bool | None = None


# --- Program orchestration recipe (feature #2) --------------------------------
class MusicSpec(BaseModel):
    model_config = ConfigDict(extra="allow")
    prompts: list[str] = Field(default_factory=lambda: ["upbeat instrumental radio music bed"])
    genre: str | None = None
    track_seconds: float = 210.0  # target length of each music track
    crossfade_seconds: float = 4.0  # crossfade between tracks


class InsertSpec(BaseModel):
    """A spoken/asset element periodically woven into the music (feature #2)."""

    model_config = ConfigDict(extra="allow")
    kind: Literal["news", "info", "ad", "station_id", "jingle", "weather"] = "info"
    # Roughly how often this insert appears in the program, in seconds.
    cadence_seconds: float = 600.0
    # Round-robin pool of scripts to speak (for speech inserts).
    texts: list[str] = Field(default_factory=list)
    voice: str | None = None
    # For jingles/sfx: a pre-existing asset id/path resolved by the asset resolver.
    asset: str | None = None
    # Mixing: duck the music bed under this insert and set its gain.
    ducking: bool = True
    bed_volume_db: float = -8.0
    insert_volume_db: float = 0.0


class ProgramConfig(BaseModel):
    model_config = ConfigDict(extra="allow")
    target_lufs: float = -16.0
    crossfade_seconds: float = 4.0
    music: MusicSpec = Field(default_factory=MusicSpec)
    inserts: list[InsertSpec] = Field(default_factory=list)


class ProgramCreate(BaseModel):
    name: str
    description: str = ""
    music_backend_id: str | None = None
    speech_backend_id: str | None = None
    config: ProgramConfig = Field(default_factory=ProgramConfig)


class ProgramUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    music_backend_id: str | None = None
    speech_backend_id: str | None = None
    config: ProgramConfig | None = None


# --- Streams ------------------------------------------------------------------
class IcecastConfig(BaseModel):
    model_config = ConfigDict(extra="allow")
    enabled: bool = False
    host: str = "localhost"
    port: int = 8000
    mount: str = "/neural.mp3"
    username: str = "source"
    password: str = "hackme"
    format: Literal["mp3", "ogg"] = "mp3"


class StreamCreate(BaseModel):
    name: str
    program_id: str | None = None
    sample_rate: int = 44100
    channels: int = 2
    buffer_min_seconds: float = 900.0
    batch_target_seconds: float = 1080.0
    batch_max_seconds: float = 1200.0
    icecast: IcecastConfig | None = None


class StreamUpdate(BaseModel):
    name: str | None = None
    program_id: str | None = None
    buffer_min_seconds: float | None = None
    batch_target_seconds: float | None = None
    batch_max_seconds: float | None = None
    icecast: IcecastConfig | None = None


# --- Jobs ---------------------------------------------------------------------
class JobSubmit(BaseModel):
    type: Literal["batch", "oneoff", "program_render"] = "batch"
    stream_id: str | None = None
    program_id: str | None = None
    # For a "batch"/"program_render": how many seconds to generate (defaults to the
    # program/stream batch target). For "oneoff": free-form params for the backend.
    params: dict[str, Any] = Field(default_factory=dict)


# --- Schedules ----------------------------------------------------------------
class ScheduleCreate(BaseModel):
    name: str
    action: Literal["render_batch", "start_stream", "stop_stream"] = "render_batch"
    program_id: str | None = None
    stream_id: str | None = None
    trigger_type: Literal["cron", "interval", "date"] = "interval"
    trigger: dict[str, Any] = Field(default_factory=dict)
    enabled: bool = True


class ScheduleUpdate(BaseModel):
    name: str | None = None
    enabled: bool | None = None
    trigger_type: Literal["cron", "interval", "date"] | None = None
    trigger: dict[str, Any] | None = None


# --- Misc responses -----------------------------------------------------------
class BackendInfo(BaseModel):
    """Static capability info for a provider (drives the UI backend picker)."""

    provider: str
    kinds: list[str]
    available: bool
    detail: str = ""
    default_config: dict[str, Any] = Field(default_factory=dict)


class BufferStatus(BaseModel):
    stream_id: str
    status: str
    ready_seconds: float
    min_seconds: float
    segments_ready: int
    segments_total: int
    generating: bool
