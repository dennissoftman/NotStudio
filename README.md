# Not Studio

Not Studio is a local-first, human-in-the-loop workspace for turning music
direction into generated tracks and finished video mixes. GPT supplies a
structured prompt plan; Not Studio handles Stable Audio generation, listening,
taste feedback, track ordering, and YouTube-ready MP4 rendering.

## Current workflow

1. Copy the live prompt kit from the Generate page. It includes the JSON schema
   and up to 20 recent liked and disliked examples.
2. Ask GPT for a JSON track plan, then paste that plan into Not Studio.
3. Generate up to 20 tracks locally with Stable Audio 3 Medium.
4. Listen to the tracks, mark them liked or disliked, and copy the refreshed
   prompt kit for the next batch.
5. Select tracks in playback order, upload a looping video, and render a
   YouTube-compatible H.264/AAC MP4.

Generation and rendering run as cancellable background jobs. The UI receives
job snapshots over `/api/jobs/ws`, and only one track preview plays at a time.

## Repository layout

```text
.
├── not-studio/
│   ├── api/          # FastAPI API, SQLite state, jobs, audio, and video export
│   └── ui/           # React, TypeScript, Vite, Tailwind, and Howler playback
├── stable-audio-3/   # local Stable Audio 3 package used by the API
└── pyproject.toml    # repository-level engine/development environment
```

The active product is the standalone `not-studio/` application. Its API has a
separate `uv` environment and consumes the checked-out `stable-audio-3`
package through a local path dependency.

## Requirements

- Python 3.11 or newer
- [`uv`](https://docs.astral.sh/uv/)
- Node.js and npm
- FFmpeg on `PATH` for video validation and rendering
- Access to `stabilityai/stable-audio-3-medium` for local generation

## Quick start

Install the UI and API dependencies:

```bash
cd not-studio/ui
npm install

cd ../api
uv sync
```

Then, from `not-studio/api/`, start both services:

```bash
uv run dev
```

The UI is available at `http://localhost:5173`, the API at
`http://localhost:8001`, and the interactive API docs at
`http://localhost:8001/docs`.

The local Medium model begins loading in a persistent generation worker after
the API starts. `/api/health` remains available while its model status moves
from `loading` to `ready`; the UI shows the same state. A generation submitted
before warmup finishes waits on that worker. Set
`NOT_STUDIO_PRELOAD_LOCAL_MODEL_ON_STARTUP=false` to disable startup warmup.
For a UI-only debugging session, `uv run dev --no-model` applies that
setting just to the launched API process.

For a production-style local launch:

```bash
uv run prod
```

`uv run prod` is shorthand for `uv run dev --production`.

This builds and serves the UI on `0.0.0.0:8080` and runs the API without reload
on `0.0.0.0:8081`. Application data defaults to `not-studio/api/data/`.

## Verification

Run backend checks from `not-studio/api/`:

```bash
uv run ruff check
uv run ruff format --check
uv run python -m pytest
uv lock --check
```

Run frontend checks from `not-studio/ui/`:

```bash
npm run build
```

## Documentation

- [`not-studio/README.md`](not-studio/README.md) — product behavior, media
  export, and configuration
- [`not-studio/api/README.md`](not-studio/api/README.md) — API launcher and
  runtime behavior

## License

MIT. See [`LICENSE`](LICENSE).
