"""API request/response schemas for Not Studio."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_serializer, field_validator

MusicProvider = Literal["ace_step_local"]


class MusicProviderInfo(BaseModel):
    provider: str
    kinds: list[str]
    available: bool
    detail: str = ""
    default_config: dict[str, Any] = Field(default_factory=dict)


class PromptSpec(BaseModel):
    model_config = ConfigDict(extra="allow")
    title: str = Field(min_length=1, max_length=160)
    genre: str = Field(min_length=1, max_length=120)
    prompt: str = Field(min_length=1, max_length=4000)
    duration: float = Field(ge=15.0, le=240.0)
    album_title: str | None = Field(default=None, max_length=160)
    album: dict[str, Any] | str | None = None
    notes: str | None = Field(default=None, max_length=1000)
    artwork_prompt: str | None = Field(default=None, max_length=2000)


class GenerateAlbumRequest(BaseModel):
    mood: str = Field(min_length=1, max_length=80)
    styles: list[str] = Field(default_factory=list, max_length=8)
    track_count: int = Field(default=4, ge=1, le=20)
    duration: float = Field(default=180.0, ge=15.0, le=240.0)
    duration_variation_percent: float = Field(default=0.0, ge=0.0, le=50.0)
    album_title: str | None = Field(default=None, max_length=120)
    provider: MusicProvider | None = None
    model: Literal["ACE-Step"] | None = None


class PromptPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")
    album_title: str | None = Field(default=None, max_length=160)
    notes: str | None = Field(default=None, max_length=2000)
    artwork_prompt: str | None = Field(default=None, max_length=2000)
    prompts: list[PromptSpec] = Field(min_length=1, max_length=20)


class GenerateTracksRequest(PromptPlan):
    provider: MusicProvider | None = None
    model: Literal["ACE-Step"] | None = None


class AlbumExportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(min_length=1, max_length=160)
    item_ids: list[str] = Field(min_length=1, max_length=100)
    include_track_videos: bool = False


class TrackReviewRequest(BaseModel):
    verdict: Literal["liked", "unreviewed"]
    note: str | None = Field(default=None, max_length=500)


class TrackAlbumRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    album_title: str | None = Field(default=None, max_length=160)

    @field_validator("album_title")
    @classmethod
    def normalize_album_title(cls, value: str | None) -> str | None:
        title = value.strip() if value else ""
        return title or None


class TasteExample(BaseModel):
    title: str
    genre: str
    prompt: str
    note: str | None = None

    @field_validator("genre")
    @classmethod
    def normalize_genre(cls, value: str) -> str:
        return " ".join(value.lower().split())


class TasteProfile(BaseModel):
    liked_genres: set[str]
    liked_examples: list[TasteExample]

    @field_validator("liked_genres", mode="before")
    @classmethod
    def normalize_genres(cls, value: object) -> set[str]:
        if not isinstance(value, (list, set, tuple)):
            raise ValueError("genres must be a collection")
        return {
            normalized for genre in value if (normalized := " ".join(str(genre).lower().split()))
        }

    @field_serializer("liked_genres")
    def serialize_genres(self, value: set[str]) -> list[str]:
        return sorted(value)


class PromptKitResponse(BaseModel):
    task: str
    requirements: list[str]
    artwork_guidance: str = ""
    output_schema: dict[str, Any]
    example: PromptPlan
    taste_profile: TasteProfile
