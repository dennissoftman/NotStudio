# Not Studio

Not Studio is a human-in-the-loop music generation workspace. It focuses
on album batches, taste review, regeneration, and mix rendering.

## Workflow

1. Copy the GPT prompt kit from the Generate page.
2. Ask GPT to draft a JSON album plan using the included schema and taste profile.
3. Paste the JSON plan into Not Studio and generate a batch.
4. Listen to each track, like keepers, or regenerate a candidate in place.
5. Use the refreshed prompt kit so the next GPT batch learns from those reviews.
6. Select tracks in album order and download tagged FLACs plus a CUE in one ZIP.
7. Optionally choose a looping video and render the same ordered selection as an MP4.

## Capabilities

| Capability | Where |
|---|---|
| Paste-first prompt generation | `ui/src/pages/Generate.tsx`, `/api/studio/generate` |
| GPT schema + taste export | `/api/studio/prompt-kit` |
| Human review state | `/api/studio/tracks/{id}/review` |
| In-place track regeneration | `/api/studio/tracks/{id}/regenerate` |
| Embedded FLAC artwork | `/api/studio/tracks/{id}/artwork` |
| Album cover upload | `/api/studio/albums/artwork` |
| Album ZIP + CUE export | `/api/studio/albums/export` |
| Track history/playback | `/api/studio/tracks`, `/api/history/{id}/audio` |
| Mix/video rendering | `/api/studio/videos`, `/api/studio/video-backgrounds` |
| Music generation | Local Stable Audio 3 Medium |

## Layout

```text
not-studio/
├── api/
│   └── not_studio/
│       ├── backends/      # local Stable Audio adapter
│       ├── audio/         # DSP helpers
│       ├── routers/       # REST API
│       ├── tasks/         # local background jobs
│       └── video_export.py
└── ui/                    # React + Vite + TypeScript UI
```

## Quick Start

```bash
cd not-studio/ui && npm install
cd ../api && uv sync
uv run dev
```

`uv run dev` starts the API on `http://localhost:8001` and the UI on
`http://localhost:5173`. Jobs run as FastAPI background tasks inside the API.
Job state reaches the UI through a WebSocket instead of browser polling.

For a production-style local launch, run `uv run prod` (shorthand for
`uv run dev --production`). It builds and serves the UI
on `0.0.0.0:8080` and starts the API without reload on `0.0.0.0:8081`.

Run tests from `api/`:

```bash
uv run pytest
```

Build the UI from `ui/`:

```bash
npm run build
```

## Prompt plans and taste

Not Studio does not run an embedded LLM. The UI exposes a copyable GPT prompt
kit containing the exact JSON schema, an example, and up to 20 recent liked
prompts. The top-level object requires a `prompts` list; its `album_title`,
`notes`, and `artwork_prompt` fields provide defaults for the generated album.
Every prompt item requires `title`, `genre`, `prompt`, and `duration`. A prompt
may override the default grouping with `album_title` or an `album` object, which
lets one JSON plan create custom albums. Prompt items may also carry their own
`notes` and `artwork_prompt` for track icons.
The Generate page also keeps a browser-saved `artwork_guidance` value in the
copied GPT prompt kit for persistent visual style and constraint instructions.
After reviews change, copying the kit again includes the new taste signals automatically.

## Library and album export

The Library lists every generated track with search, album tabs, and sorting by
generation date, name, or album. Assign a track to an existing album, create a
new album from its card, or return it to Unfiled. The Mix page loads an album
into an editable ordered queue. An album tab can store a dedicated cover from a
PNG, JPEG, or WebP upload. Album export downloads a ZIP containing numbered
FLAC copies, the cover as `<album name>.png`, album and track-number metadata,
and a multi-file CUE sheet. Export only modifies the copies inside the ZIP;
library files remain unchanged.

## Mix export

The Mix page has separate Album export and Video mix tabs. Both use the same
editable ordered queue; the video tab adds the backdrop selection. There are no
visualizer, title, resolution, transition, or effect controls. The tracks play
consecutively in the selected order while the technical encoding details are
applied automatically.

The required video can use any container or codec that the local
FFmpeg build can decode, including MP4, MKV, AVI, MOV, and WebM. The input clip
keeps its dimensions, is muted, and loops for the complete audio sequence.
Regardless of the source codec, the downloaded result is an MP4 with H.264
high-profile video, yuv420p pixel format, AAC-LC audio, and fast-start metadata
for broad YouTube and browser compatibility. Python code builds and monitors
these operations through the documented `python-ffmpeg` package instead of
calling `subprocess` directly. FFmpeg timestamp progress is mapped onto the
existing job progress bar and live WebSocket updates.

Track previews use a custom Howler player backed by HTML5 audio streaming, with
play, pause, seek, elapsed time, and one-active-track coordination. Rendered
mixes use the browser's native video controls.

Library cards show track artwork at card height. Clicking the artwork opens a
large preview; PNG, JPEG, or WebP artwork can still be embedded directly in the
generated FLAC and replaced from the card.

## Audio Generation

`Stable Audio / Local` runs directly in a cancellable, persistent API worker
process using the checked-out `stable-audio-3` package. The API starts
immediately and loads the Medium model asynchronously
in that worker. `/api/health` reports `status: ok` throughout and exposes the
model state as `loading`, `ready`, or `failed`; the sidebar mirrors that state.
A generation submitted during warmup waits for the same worker, then reuses the
loaded model. A preload failure leaves the API available and is reported by the
health endpoint. Set `NOT_STUDIO_PRELOAD_LOCAL_MODEL_ON_STARTUP=false` only when
a cold local worker is intentional. For UI-only debugging, use
`uv run dev --no-model` (the same flag also works with `uv run prod`).

Generated and exported FLACs include artist, year, and ISO release-date tags.
Set `NOT_STUDIO_TRACK_AUTHOR` to override the default artist, `Not Studio`.
