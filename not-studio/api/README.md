# not-studio-api

FastAPI backend for Not Studio: album prompt ideation, local or RunPod Stable
Audio batch generation, human review state, history, and mix/video rendering.

Run:

```bash
uv sync
uv run uvicorn not_studio.main:app --reload --port 8001
```

Or use the combined API + UI launcher:

```bash
uv run dev
```

Jobs run as API background tasks and are visible through `/api/jobs`.
The live job snapshot stream is available at `/api/jobs/ws`.
With the local provider selected, startup warms the Stable Audio medium model
inside the persistent generation worker before the API becomes healthy. The
health response includes the model readiness state and selected device.
Video validation, audio concatenation, and YouTube-compatible encoding use the
`python-ffmpeg` API. Its progress events update render-job percentages and
messages; application code does not invoke FFmpeg through `subprocess`.

From this directory, `uv run dev --production` starts the API on `0.0.0.0:8081` and the built UI
on `0.0.0.0:8080`.

Configuration is documented in `../README.md` and `.env.example`. RunPod audio
is transferred from an attached network volume through its S3-compatible API;
the API does not accept base64 audio or a Hugging Face token.
