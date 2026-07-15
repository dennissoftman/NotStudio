# Not Studio

Not Studio is a local-first, human-in-the-loop workspace for turning music
direction into generated tracks and constructed albums. GPT supplies a
structured prompt plan; Not Studio handles ACE-Step generation, listening,
taste feedback, album organization, and release export.

## Current workflow

1. Copy the live prompt kit from the Generate page. It includes the JSON schema
   and up to 20 recent liked examples.
2. Ask GPT for a JSON track plan, then paste that plan into Not Studio.
3. Generate up to 20 instrumental tracks of up to four minutes with ACE-Step Text2Music.
4. Listen, keep favorites, regenerate candidates, and organize tracks into albums.
5. Order an album and download numbered, tagged FLACs, its cover, and a CUE file.
6. Optionally include one YouTube-compatible MP4 per track in the album ZIP.

Generation runs as cancellable background jobs. The UI receives job snapshots
over `/api/jobs/ws`, and only one track preview plays at a time.

## Repository layout

```text
.
├── not-studio/
│   ├── api/          # FastAPI, SQLite state, ACE-Step adapter, and album export
│   └── ui/           # React, TypeScript, Vite, Tailwind, and Howler playback
├── scripts/          # standalone ACE-Step text-to-music helper
└── pyproject.toml    # repository-level development environment
```

The active product is the standalone `not-studio/` application. Its API has a
separate `uv` environment. Both environments install ACE-Step directly from
the [official GitHub repository](https://github.com/ace-step/ACE-Step#-installation),
matching its library installation instructions.

## Requirements

- Python 3.11 or newer for the application API
- [`uv`](https://docs.astral.sh/uv/)
- Node.js and npm
- FFmpeg on `PATH` when per-track album MP4s are requested
- Network access on first model startup so ACE-Step can download its checkpoints

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

ACE-Step begins loading in the persistent generation worker after the API
starts. `/api/health` remains available while its model status moves from
`loading` to `ready`; the UI shows the same state. A generation submitted
during warmup waits on that worker. Set
`NOT_STUDIO_PRELOAD_LOCAL_MODEL_ON_STARTUP=false` to use a cold model worker.
For UI-only debugging, `uv run dev --no-model` applies that setting to the
launched API process.

For a production-style local launch:

```bash
uv run prod
```

`uv run prod` is shorthand for `uv run dev --production`. It builds and serves
the UI on `0.0.0.0:8080` and runs the API on `0.0.0.0:8081`. Application data
defaults to `not-studio/api/data/`.

## Album export

Album ZIPs contain ordered FLAC copies with album and track metadata, the album
cover, and a multi-file CUE sheet. When a cover exists it is also embedded into
every exported FLAC. The optional per-track video checkbox is off by default.
When enabled, each FLAC receives a matching static-cover MP4 encoded at 1 fps
with H.264 high-profile/yuv420p video, AAC-LC 320 kbps audio, and fast-start
metadata for YouTube and browser compatibility. If the album has no cover,
video files are not created.

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

- [`not-studio/README.md`](not-studio/README.md) — product behavior and export details
- [`not-studio/api/README.md`](not-studio/api/README.md) — API launcher and runtime behavior

## License

MIT. See [`LICENSE`](LICENSE).
