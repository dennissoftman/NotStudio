"""Point the app at a throwaway data dir + an unused Redis port before import.

The DB engine and settings are created at import time, so these must be set
before ``radio_dashboard`` is imported (conftest is imported first by pytest).
"""

import os
import tempfile

os.environ.setdefault("RADIO_DATA_DIR", tempfile.mkdtemp(prefix="radio-test-"))
# A closed port so create_arq_pool fails fast and the queue is reported offline.
os.environ.setdefault("RADIO_REDIS_URL", "redis://127.0.0.1:6399")
