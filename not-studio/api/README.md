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
With the local provider selected, startup begins warming the Stable Audio
Medium model asynchronously inside the persistent generation worker. The API
is available during warmup; `/api/health` exposes the model state, selected
device when ready, and any preload error. A generation submitted while the
model is loading waits for that worker and then reuses the loaded model.
Video validation, audio concatenation, and YouTube-compatible encoding use the
`python-ffmpeg` API. Its progress events update render-job percentages and
messages; application code does not invoke FFmpeg through `subprocess`.

From this directory, `uv run prod` (shorthand for `uv run dev --production`) starts the API on
`0.0.0.0:8081` and the built UI
on `0.0.0.0:8080`.

For UI-only debugging, append `--no-model` to `uv run dev` or `uv run prod` to skip
Stable Audio model warmup for that launched API process.

Configuration is documented in `../README.md` and `.env.example`. RunPod audio
is transferred from an attached network volume through its S3-compatible API;
the API does not accept base64 audio or a Hugging Face token.
