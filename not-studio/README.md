# Not Studio

Not Studio is a human-in-the-loop music generation and album construction
workspace built around ACE-Step.

## Workflow

1. Copy the GPT prompt kit from the Generate page.
2. Ask GPT for a JSON album plan using the included schema and taste profile.
3. Paste the plan and generate instrumental tracks with ACE-Step 1.5 Text2Music.
4. Listen, keep favorites, or regenerate a candidate in place.
5. Organize tracks into albums and attach a dedicated album cover.
6. Build the track order and download tagged FLACs plus a CUE in one ZIP.
7. Optionally include a static-cover YouTube MP4 for every album track.

## Capabilities

| Capability | Where |
|---|---|
| Paste-first prompt generation | `ui/src/pages/Generate.tsx`, `/api/studio/generate` |
| GPT schema + taste export | `/api/studio/prompt-kit` |
| Human review state | `/api/studio/tracks/{id}/review` |
| In-place track regeneration | `/api/studio/tracks/{id}/regenerate` |
| Embedded track artwork | `/api/studio/tracks/{id}/artwork` |
| Album cover upload | `/api/studio/albums/artwork` |
| Album ZIP, CUE, and optional MP4 export | `/api/studio/albums/export` |
| Track history/playback | `/api/studio/tracks`, `/api/history/{id}/audio` |
| Music generation | Local ACE-Step 1.5 Text2Music |

## Quick start

```bash
cd api
uv run dev
```

Before starting either service, the launcher runs `uv sync --locked` for the
API and `yarn install --immutable` for the UI. Dependency preparation failures
stop startup. `uv sync` installs ACE-Step 1.5 from its
[official Git repository](https://github.com/ace-step/ACE-Step-1.5).
`uv run dev` starts the API on `http://localhost:8001` and the UI on
`http://localhost:5173`. Generation jobs run in cancellable worker processes,
and job state reaches the UI through a WebSocket instead of browser polling.

For a production-style local launch, run `uv run prod` (shorthand for
`uv run dev --production`). It builds and serves the UI on `0.0.0.0:8080` and
starts the API without reload on `0.0.0.0:8081`.

## Prompt plans and generation

Not Studio does not run an embedded LLM. The UI exposes a copyable GPT prompt
kit containing the exact JSON schema, an example, and up to 20 recent liked
prompts. The top-level object requires a `prompts` list; `album_title`, `notes`,
and `artwork_prompt` provide album defaults. Every prompt requires `title`,
`genre`, `prompt`, and `duration`.

The ACE-Step 1.5 adapter currently fixes the task to prompt-first instrumental
`text2music` with empty lyrics, preserving the existing product flow. The
adapter keeps ACE-Step task and lyrics inputs behind an explicit request
boundary so lyric-driven, retake, edit, and extend workflows can be introduced
without replacing album or job infrastructure.

ACE-Step loads asynchronously in the persistent generation worker at startup.
`/api/health` exposes `loading`, `ready`, `failed`, or `disabled`, and the
sidebar mirrors that state. Set
`NOT_STUDIO_PRELOAD_LOCAL_MODEL_ON_STARTUP=false` for an intentional cold start,
or use `uv run dev --no-model` for UI-only work.

## Library and album export

The Library lists every generated track with search, album tabs, and sorting by
generation date, name, or album. Assign tracks to existing or new albums and
attach a PNG, JPEG, or WebP album cover. The Album page loads tracks into an
editable ordered list.

Album export downloads a ZIP containing numbered FLAC copies, album and track
metadata, a multi-file CUE, and the cover as `<album name>.png`. When a cover is
present it replaces the embedded picture on each exported FLAC copy; library
files remain unchanged.

The “Include a YouTube MP4 for each track” checkbox is off by default. When
enabled and an album cover exists, the ZIP also contains one MP4 beside each
FLAC. The cover is held at 1 fps and encoded as H.264 high-profile/yuv420p with
a slow still-image preset; audio is AAC-LC at 320 kbps. Fast-start metadata is
enabled. If the cover is absent, the FLAC album is still exported and MP4
creation is skipped.

Track previews use a custom Howler player backed by HTML5 audio streaming, with
play, pause, seek, elapsed time, and one-active-track coordination.

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

Generated and exported FLACs include artist, year, and ISO release-date tags.
Set `NOT_STUDIO_TRACK_AUTHOR` to override the default artist, `Not Studio`.
