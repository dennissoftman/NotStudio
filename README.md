# Not Studio

Not Studio is a local-first, human-in-the-loop workspace for turning a
free-form album idea into generated music and release-ready artwork. Local Qwen
planning produces a structured album plan, ACE-Step renders the tracks, and
FLUX.2 Klein creates the album and per-track covers.

## Current workflow

1. Describe the album mood, track count, musical direction, and story in
   ordinary language.
2. Optionally add custom artwork direction and a visual style-reference image.
3. Review or edit the schema-constrained plan generated locally by Qwen.
4. Generate up to 20 instrumental tracks with ACE-Step 1.5 and create an album
   cover plus one distinct cover per track with FLUX.2 Klein.
5. Listen, keep favorites, regenerate music or individual covers, and select
   the preferred immutable cover versions.
6. Order the album and export numbered, tagged FLACs, a CUE, selected artwork,
   and optional YouTube-compatible MP4s.

Generation runs as cancellable background jobs. One exclusive accelerator
process swaps Qwen, ACE-Step, and FLUX so only one model family occupies the GPU
at a time. The UI receives job snapshots over `/api/jobs/ws`, and only one track
preview plays at a time.

## Repository layout

```text
.
├── not-studio/
│   ├── api/          # FastAPI, SQLite state, model adapters, jobs, and export
│   └── ui/           # React, TypeScript, Vite, Tailwind, and Howler playback
├── scripts/          # standalone ACE-Step text-to-music helper
└── pyproject.toml    # repository-level development environment
```

The active product is the standalone `not-studio/` application. Its API has a
separate `uv` environment. Both environments install ACE-Step 1.5 directly from
the [official GitHub repository](https://github.com/ace-step/ACE-Step-1.5),
matching its library installation instructions.

## Requirements

- Python 3.11 or newer for the application API
- [`uv`](https://docs.astral.sh/uv/)
- Node.js and Corepack-enabled Yarn
- FFmpeg on `PATH` when per-track album MP4s are requested
- NVIDIA CUDA GPU with at least 12 GiB VRAM for the full local pipeline; 16 GiB
  is recommended
- At least 35 GiB of free disk for model caches and generated media
- Network access on first use so Qwen, ACE-Step, and FLUX can download weights

## Quick start

Start the local development services:

```bash
cd not-studio/api
uv run dev
```

The launcher runs `uv sync --locked` and `yarn install --immutable` before
starting any API or UI process. A failed dependency sync stops startup.

The UI is available at `http://localhost:5173`, the API at
`http://localhost:8001`, and the interactive API docs at
`http://localhost:8001/docs`.

Startup remains cold by default so Qwen can be the first model loaded for a new
album request. `/api/health` reports the current accelerator family and whether
it is idle, ready, or busy. Set
`NOT_STUDIO_PRELOAD_LOCAL_MODEL_ON_STARTUP=true` only to warm ACE-Step for a
music-only workflow. For UI-only debugging, use `uv run dev --no-model`.

Before the first full run on the CUDA host:

```bash
uv run not-studio-preflight
uv run not-studio-gpu-smoke
```

The preflight reports dependencies, CUDA, VRAM, RAM, and disk readiness. The
smoke test sequentially exercises local planning, music generation, and cover
generation without keeping multiple model families resident.

For a production-style local launch:

```bash
uv run prod
```

`uv run prod` is shorthand for `uv run dev --production`. It builds and serves
the UI on `0.0.0.0:8080` and runs the API on `0.0.0.0:8081`. Application data
defaults to `not-studio/api/data/`.

## Album export

Album ZIPs contain ordered FLAC copies with album and track metadata, the
selected album cover, and a multi-file CUE sheet. Each FLAC embeds its selected
track cover and falls back to the album cover. The optional per-track video
checkbox is off by default. When enabled, each track receives a matching
static-cover MP4 encoded at 1 fps with H.264 high-profile/yuv420p video, AAC-LC
320 kbps audio, and fast-start metadata. MP4 creation is skipped only when
neither a selected track cover nor an album cover exists.

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
yarn build
```

## Documentation

- [`not-studio/README.md`](not-studio/README.md) — product behavior and export details
- [`not-studio/api/README.md`](not-studio/api/README.md) — API launcher and runtime behavior

## License

MIT. See [`LICENSE`](LICENSE).
