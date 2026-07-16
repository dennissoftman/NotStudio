# not-studio-api

FastAPI backend for Not Studio: prompt ideation, local ACE-Step 1.5 Text2Music
generation, human review state, history, and album construction.

Install and run:

```bash
uv sync
uv run uvicorn not_studio.main:app --reload --port 8001
```

ACE-Step 1.5 is installed from the
[official Git repository](https://github.com/ace-step/ACE-Step-1.5),
as recommended for library use by the upstream project.

Or start the API and UI together:

```bash
uv run dev
```

Jobs are visible through `/api/jobs`; live snapshots are streamed at
`/api/jobs/ws`. Startup warms ACE-Step asynchronously in the persistent
generation worker. `/api/health` stays available during warmup and reports the
model state, selected device, and any preload error. A generation submitted
while the model is loading waits for that worker and then reuses it.

Album export is handled by `/api/studio/albums/export`. Its optional
`include_track_videos` flag defaults to `false`. When true and an album cover
exists, `python-ffmpeg` adds one 1 fps H.264/yuv420p MP4 per FLAC with AAC-LC
320 kbps audio. No MP4 is created without a cover. The removed multi-track
video endpoints are no longer part of the API.

From this directory, `uv run prod` starts the API on `0.0.0.0:8081` and the
built UI on `0.0.0.0:8080`. Append `--no-model` to `uv run dev` or `uv run prod`
to skip ACE-Step warmup for UI-focused work.

Configuration is documented in `../README.md` and `.env.example`.
`NOT_STUDIO_TRACK_AUTHOR` controls the generated/exported FLAC artist tag and
defaults to `Not Studio`.
