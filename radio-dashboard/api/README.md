# radio-dashboard-api

FastAPI backend for the Neural Radio dashboard: scheduling + task management,
audio/TTS backend configuration, program orchestration, a pre-allocated
generation buffer, history, and real-time HTTP/HLS/Icecast streaming.

Run:

```bash
uv sync
uv run uvicorn radio_dashboard.main:app --reload --port 8000   # API
uv run arq radio_dashboard.tasks.worker.WorkerSettings          # worker
```

See `../README.md` for the full picture.
