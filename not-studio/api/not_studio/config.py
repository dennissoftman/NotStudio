from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# Stable anchors regardless of the process working directory.
_PACKAGE_DIR = Path(__file__).resolve().parent  # .../api/not_studio
_API_DIR = _PACKAGE_DIR.parent  # .../api
_SUBPROJECT_DIR = _API_DIR.parent  # .../not-studio
_REPO_ROOT = _SUBPROJECT_DIR.parent  # parent engine root


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
    ]

    # Audio defaults -------------------------------------------------------
    sample_rate: int = 44100
    channels: int = 2

    # Reuse of the parent audio engine (real backends via subprocess)
    engine_root: Path = _REPO_ROOT
    uv_path: str = "uv"

    # Track generation -----------------------------------------------------
    default_music_provider: str = "stable_audio_local"
    default_music_model: str = "medium"  # Stable Audio 3 model (auto -> medium on MPS)
    runpod_endpoint_id: str = ""
    runpod_api_key: str = ""
    runpod_base_url: str = "https://api.runpod.ai/v2"
    runpod_timeout_seconds: float = 3600.0
    runpod_volume_id: str = ""
    runpod_s3_endpoint_url: str = ""
    runpod_s3_access_key_id: str = ""
    runpod_s3_secret_access_key: str = ""
    runpod_s3_region: str = ""

    # LLM prompt generation ------------------------------------------------
    lm_studio_base_url: str = "http://localhost:1234/v1"
    lm_studio_api_key: str = ""
    lm_studio_model: str = "local-model"
    openai_base_url: str = "https://api.openai.com/v1"
    openai_api_key: str = ""
    openai_model: str = "gpt-5.5"
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-sonnet-4-5"
    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.5-flash"

    def model_post_init(self, __context: object) -> None:
        self.data_dir = self.data_dir.expanduser().resolve()
        self.data_dir.mkdir(parents=True, exist_ok=True)
        if not self.database_url:
            self.database_url = f"sqlite+aiosqlite:///{self.data_dir / 'not-studio.db'}"
        self.engine_root = self.engine_root.expanduser().resolve()

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


@lru_cache
def get_settings() -> Settings:
    return Settings()
