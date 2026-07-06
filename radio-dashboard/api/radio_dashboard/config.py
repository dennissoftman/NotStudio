from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# Stable anchors regardless of the process working directory.
_PACKAGE_DIR = Path(__file__).resolve().parent  # .../api/radio_dashboard
_API_DIR = _PACKAGE_DIR.parent  # .../api
_SUBPROJECT_DIR = _API_DIR.parent  # .../radio-dashboard
_REPO_ROOT = _SUBPROJECT_DIR.parent  # .../NeuralRadio (engine root)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="RADIO_", env_file=".env", extra="ignore")

    app_name: str = "Radio Dashboard API"
    debug: bool = False

    # Storage --------------------------------------------------------------
    data_dir: Path = _API_DIR / "data"
    database_url: str = ""  # derived from data_dir when empty

    # Redis / arq ----------------------------------------------------------
    redis_url: str = "redis://localhost:6379"
    # Max seconds a single job may run before arq cancels it. Track generation and
    # video renders take minutes, so this must sit well above arq's 300s default.
    job_timeout_seconds: int = 7200

    # CORS -----------------------------------------------------------------
    cors_origins: list[str] = [
        "http://localhost:5173",
        "http://localhost:4173",
        "http://127.0.0.1:5173",
    ]

    # Audio defaults -------------------------------------------------------
    sample_rate: int = 44100
    channels: int = 2

    # Pre-allocated buffer policy (feature #4) -----------------------------
    buffer_min_seconds: float = 900.0  # keep >= 15 min ready ahead of playout
    batch_target_seconds: float = 1080.0  # generate ~18 min per batch
    batch_max_seconds: float = 1200.0  # cap at 20 min per batch

    # Streaming ------------------------------------------------------------
    ffmpeg_path: str = "ffmpeg"
    stream_mp3_bitrate: str = "128k"
    playout_frame_seconds: float = 0.2  # PCM frame granularity for the live clock

    # Reuse of the parent Neural Radio engine (real backends via subprocess)
    engine_root: Path = _REPO_ROOT
    uv_path: str = "uv"

    # Track generation (local Stable Audio 3 via the parent main.py) --------
    default_music_provider: str = "stable_audio"  # "stable_audio" | "mock"
    default_music_model: str = "medium"  # Stable Audio 3 model (auto -> medium on MPS)

    def model_post_init(self, __context: object) -> None:
        self.data_dir = self.data_dir.expanduser().resolve()
        self.data_dir.mkdir(parents=True, exist_ok=True)
        if not self.database_url:
            self.database_url = f"sqlite+aiosqlite:///{self.data_dir / 'radio.db'}"
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
    def hls_dir(self) -> Path:
        """Where live HLS playlists/segments are written per stream."""
        return self._subdir("hls")

    @property
    def videos_dir(self) -> Path:
        """Where assembled YouTube-style videos are written."""
        return self._subdir("videos")


@lru_cache
def get_settings() -> Settings:
    return Settings()
