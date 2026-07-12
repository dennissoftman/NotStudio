"""API request/response schemas for Not Studio."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

MusicProvider = Literal["stable_audio_local", "stable_audio_runpod"]
PromptProvider = Literal["lm_studio", "gemini", "openai", "anthropic"]


class MusicProviderInfo(BaseModel):
    provider: str
    kinds: list[str]
    available: bool
    detail: str = ""
    default_config: dict[str, Any] = Field(default_factory=dict)


class PromptSpec(BaseModel):
    model_config = ConfigDict(extra="allow")
    title: str
    prompt: str
    duration: float = 180.0


class GenerateAlbumRequest(BaseModel):
    mood: str = Field(min_length=1, max_length=80)
    styles: list[str] = Field(default_factory=list, max_length=8)
    track_count: int = Field(default=4, ge=1, le=20)
    duration: float = Field(default=180.0, ge=15.0, le=900.0)
    duration_variation_percent: float = Field(default=0.0, ge=0.0, le=50.0)
    album_title: str | None = Field(default=None, max_length=120)
    provider: MusicProvider | None = None
    model: Literal["medium"] | None = None


class GenerateTracksRequest(BaseModel):
    prompts: list[PromptSpec]
    provider: MusicProvider | None = None
    model: Literal["medium"] | None = None


class TrackReviewRequest(BaseModel):
    verdict: Literal["liked", "disliked", "unreviewed"]
    note: str | None = Field(default=None, max_length=500)


class MakeVideoRequest(BaseModel):
    item_ids: list[str]
    title: str | None = None
    visualizer: Literal["cqt", "spectrum", "waves", "none"] = "cqt"
    crossfade_seconds: float = 6.0


class PromptProviderInfo(BaseModel):
    provider: PromptProvider
    available: bool
    detail: str = ""
    default_model: str = ""


class GeneratePromptIdeasRequest(BaseModel):
    provider: PromptProvider
    mood: str = Field(min_length=1, max_length=80)
    styles: list[str] = Field(default_factory=list, max_length=8)
    track_count: int = Field(default=4, ge=1, le=20)
    duration: float = Field(default=180.0, ge=15.0, le=900.0)
    duration_variation_percent: float = Field(default=0.0, ge=0.0, le=50.0)
    album_title: str | None = Field(default=None, max_length=120)
    taste_notes: str = Field(default="", max_length=1000)
    model: str | None = None


class GeneratePromptIdeasResponse(BaseModel):
    prompts: list[PromptSpec]
    provider: PromptProvider
    model: str
