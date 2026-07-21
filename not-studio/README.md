# Not Studio

Not Studio is a local, human-in-the-loop album generation workspace built around
Qwen, ACE-Step, and FLUX.2 Klein.

## Workflow

1. Describe an album, its track count, mood, sound, and story in ordinary language.
2. Review or edit the structured plan produced locally by Qwen3-4B-Instruct.
3. Generate instrumental tracks with ACE-Step 1.5.
4. Generate one album cover and one distinct cover per track with FLUX.2 Klein 4B.
5. Listen, keep favorites, regenerate music or covers, and select cover versions.
6. Build the track order and download tagged FLACs plus a CUE in one ZIP.
7. Optionally include a static-cover YouTube MP4 for every album track.

## Capabilities

| Capability                              | Where                                                  |
| --------------------------------------- | ------------------------------------------------------ |
| Natural-language album planning         | `/api/studio/album-runs`                               |
| Editable structured plan                | `/api/studio/album-runs/{id}/plan`                     |
| End-to-end local generation             | `/api/studio/album-runs/{id}/generate`                 |
| Reference-image visual guidance         | `/api/studio/style-references`                         |
| Versioned album and track covers        | `/api/studio/albums/{id}/covers`, `tracks/{id}/covers` |
| Legacy paste-first generation           | `/api/studio/generate`                                 |
| Human review and music regeneration     | `/api/studio/tracks/{id}/review`, `regenerate`         |
| Album ZIP, CUE, and optional MP4 export | `/api/studio/albums/export`                            |
| Track history/playback                  | `/api/studio/tracks`, `/api/history/{id}/audio`        |

The default models are:

- `Qwen/Qwen3-4B-Instruct-2507` for album planning (Apache 2.0).
- ACE-Step 1.5 for instrumental Text2Music.
- `black-forest-labs/FLUX.2-klein-4B` for generation and reference-guided covers
  (Apache 2.0).

ACE-Step uses `acestep-v15-sft` with 50 diffusion steps on normal hardware.
Apple Silicon machines with 16 GB or less automatically use its lower-memory
turbo checkpoint. ACE-Step's own 5 Hz language model remains dedicated to music
generation; it is not used as the album planner.

## Quick start

```bash
cd api
uv run dev
```

The launcher runs `uv sync --locked` for the API and `yarn install --immutable`
for the UI. It starts the API at `http://localhost:8001` and Vite at
`http://localhost:5173`. `uv run prod` builds the UI and serves it on port 8080
with the API on port 8081.

Jobs are cancellable and their state is streamed to the UI through
`/api/jobs/ws`. One exclusive accelerator process swaps between Qwen, ACE-Step,
and FLUX, so two model families are never resident on the GPU simultaneously.
The most recently used model is released after the configured idle timeout.

## GPU setup and validation

The production local path requires an NVIDIA CUDA host with at least 12 GiB
VRAM; 16 GiB is recommended. Reserve at least 35 GiB of free disk for model
caches and media. On the target machine run:

```bash
cd api
uv sync --locked
uv run not-studio-preflight
uv run not-studio-gpu-smoke
```

`not-studio-preflight` is read-only and reports CUDA, VRAM, RAM, disk, and
required imports. The smoke test sequentially loads all three model families,
creates a schema-valid one-track plan, renders a 15-second track, generates a
cover, and stores results under `data/smoke/`. Pass `--skip-audio` for a faster
planner/image-only check. First use downloads upstream model weights.

## Planning and generation

The Generate page accepts one free-form brief and an optional style-reference
image. Qwen produces JSON constrained by the same Pydantic schema used by the
API. It receives up to 20 liked tracks as preference signals. Semantic checks
then enforce requested track count, unique titles, duration limits, sufficiently
specific ACE-Step prompts, and album plus per-track artwork prompts.

Plans are editable before expensive generation begins. Advanced users can edit
the raw JSON; the original paste-first `/api/studio/generate` endpoint remains
available for integrations.

The default cover path generates at 1024×1024 and resizes to a configurable
2048×2048 final PNG. Supported final sizes are constrained by the backend and
default to 2048. A style-reference image is normalized, stripped of metadata,
stored immutably, and sent directly to FLUX.2 Klein's reference-image input.

Audio success is independent from artwork success. A failed cover leaves tracks
usable and can be retried. Each generation or manual upload creates an immutable
cover version; selecting a version never deletes previous results.

## Library and export

The Library supports searching, album assignment, likes, audio regeneration,
manual artwork upload, cover regeneration, and cover-version selection. Legacy
title-keyed albums are assigned stable IDs automatically during database startup.

Album export creates numbered FLAC copies, metadata, a multi-file CUE, and the
selected album cover. Each FLAC and optional MP4 uses its selected track cover,
falling back to the album cover when needed. Library source files are unchanged.

## Configuration

Copy `api/.env.example` to `.env`. Important settings include:

- `NOT_STUDIO_PLANNER_MODEL`
- `NOT_STUDIO_IMAGE_MODEL`
- `NOT_STUDIO_COVER_GENERATION_SIZE`
- `NOT_STUDIO_COVER_OUTPUT_SIZE`
- `NOT_STUDIO_COVER_MAX_OUTPUT_SIZE`
- `NOT_STUDIO_GPU_MODEL_IDLE_SECONDS`
- `NOT_STUDIO_TRACK_AUTHOR`

Startup model preloading is off by default because Qwen is normally the first
stage. Set `NOT_STUDIO_PRELOAD_LOCAL_MODEL_ON_STARTUP=true` only for music-only
workflows. Use `uv run dev --no-model` for UI-only work.

## Verification

```bash
cd api
uv run ruff check
uv run ruff format --check
uv run python -m pytest
uv lock --check

cd ../ui
yarn build
```
