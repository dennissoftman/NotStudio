"""Point the app at a throwaway data dir before import.

The DB engine and settings are created at import time, so these must be set
before ``not_studio`` is imported (conftest is imported first by pytest).
"""

import os
import tempfile

os.environ.setdefault("NOT_STUDIO_DATA_DIR", tempfile.mkdtemp(prefix="not-studio-test-"))
os.environ.setdefault("NOT_STUDIO_DEFAULT_MUSIC_PROVIDER", "stable_audio_local")
os.environ.setdefault("NOT_STUDIO_PRELOAD_LOCAL_MODEL_ON_STARTUP", "false")
