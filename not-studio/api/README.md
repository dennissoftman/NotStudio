# not-studio-api

FastAPI backend for Not Studio: album prompt ideation, local or RunPod Stable
Audio batch generation, human review state, history, and mix/video rendering.

Run:

```bash
uv sync
uv run uvicorn not_studio.main:app --reload --port 8000
```

Or use the combined API + UI launcher:

```bash
uv run dev
```

Jobs run as API background tasks and are visible through `/api/jobs`.

Configuration is documented in `../README.md` and `.env.example`. RunPod audio
is transferred from an attached network volume through its S3-compatible API;
the API does not accept base64 audio or a Hugging Face token.
