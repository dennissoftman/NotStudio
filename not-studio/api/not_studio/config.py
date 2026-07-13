from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# Stable anchors regardless of the process working directory.
_PACKAGE_DIR = Path(__file__).resolve().parent  # .../api/not_studio
_API_DIR = _PACKAGE_DIR.parent  # .../api


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="NOT_STUDIO_", env_file=".env", extra="ignore")

    app_name: str = "Not Studio API"
    debug: bool = False

    # Storage --------------------------------------------------------------
    data_dir: Path = _API_DIR / "data"
    database_url: str = ""  # derived from data_dir when empty

    # CORS -----------------------------------------------------------------
    cors_origins: list[str] = [
        "http://localhost:5173",
        "http://localhost:4173",
        "http://127.0.0.1:5173",
        "http://localhost:8080",
        "http://127.0.0.1:8080",
    ]

    # Audio defaults -------------------------------------------------------
    sample_rate: int = 44100
    channels: int = 2

    # Track generation -----------------------------------------------------
    default_music_provider: str = "stable_audio_local"
    preload_local_model_on_startup: bool = True
    runpod_endpoint_id: str = ""
    runpod_api_key: str = ""
    runpod_base_url: str = "https://api.runpod.ai/v2"
    runpod_timeout_seconds: float = 3600.0
    runpod_volume_id: str = ""
    runpod_s3_endpoint_url: str = ""
    runpod_s3_access_key_id: str = ""
    runpod_s3_secret_access_key: str = ""
    runpod_s3_region: str = ""

    def model_post_init(self, __context: object) -> None:
        self.data_dir = self.data_dir.expanduser().resolve()
        self.data_dir.mkdir(parents=True, exist_ok=True)
        if not self.database_url:
            self.database_url = f"sqlite+aiosqlite:///{self.data_dir / 'not-studio.db'}"

    def _subdir(self, name: str) -> Path:
        path = self.data_dir / name
        path.mkdir(parents=True, exist_ok=True)
        return path

    @property
    def audio_dir(self) -> Path:
        """Where generated batches / stems are stored (history files)."""
        return self._subdir("audio")

    @property
    def videos_dir(self) -> Path:
        """Where assembled YouTube-style videos are written."""
        return self._subdir("videos")

    @property
    def video_backgrounds_dir(self) -> Path:
        """Where user-uploaded visual backdrops are kept for rendering and retries."""
        return self._subdir("video-backgrounds")


@lru_cache
def get_settings() -> Settings:
    return Settings()
