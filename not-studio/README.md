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
| Album ZIP + CUE export | `/api/studio/albums/export` |
| Track history/playback | `/api/studio/tracks`, `/api/history/{id}/audio` |
| Mix/video rendering | `/api/studio/videos`, `/api/studio/video-backgrounds` |
| Music providers | Local Stable Audio and RunPod Stable Audio |

## Layout

```text
not-studio/
├── api/
│   └── not_studio/
│       ├── backends/      # local + RunPod Stable Audio adapters
│       ├── audio/         # DSP helpers
│       ├── routers/       # REST API
│       ├── tasks/         # local background jobs
│       └── video_export.py
├── runpod/                # deployable Stable Audio batch worker
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
prompts. The top-level object requires `album_title` and a `prompts` list, with
optional `notes` and `artwork_prompt` fields for album and future cover-art
direction. Every prompt item requires `title`, `genre`, `prompt`, and `duration`.
Prompt items may also carry their own `notes` and `artwork_prompt` for track icons.
The Generate page also keeps a browser-saved `artwork_guidance` value in the
copied GPT prompt kit for persistent visual style and constraint instructions.
After reviews change, copying the kit again includes the new taste signals automatically.

## Library and album export

The Library lists every generated track with search, album tabs, and sorting by
generation date, name, or album. Assign a track to an existing album, create a
new album from its card, or return it to Unfiled. The Mix page loads an album
into an editable ordered queue. Album export downloads a ZIP containing numbered
FLAC copies, embedded cover artwork, album and track-number metadata, and a
multi-file CUE sheet. Export only modifies the copies inside the ZIP; library
files remain unchanged.

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

Library cards can embed optional PNG, JPEG, or WebP cover artwork directly in
the generated FLAC. The same card downloads the FLAC with that artwork intact.

## Audio Generation

`Stable Audio / Local` runs directly in a cancellable, persistent API worker
process using the checked-out `stable-audio-3` package. When it is the default
provider, the API starts immediately and loads the Medium model asynchronously
in that worker. `/api/health` reports `status: ok` throughout and exposes the
model state as `loading`, `ready`, or `failed`; the sidebar mirrors that state.
A generation submitted during warmup waits for the same worker, then reuses the
loaded model. A preload failure leaves the API available and is reported by the
health endpoint. Set `NOT_STUDIO_PRELOAD_LOCAL_MODEL_ON_STARTUP=false` only when
a cold local worker is intentional. For UI-only debugging, use
`uv run dev --no-model` (the same flag also works with `uv run prod`).

`Stable Audio / RunPod` sends the entire batch to one RunPod Serverless
`/runsync` request. The worker writes FLAC files to an attached network volume;
the API downloads those files as binary streams through RunPod's S3-compatible
API.

```env
NOT_STUDIO_RUNPOD_ENDPOINT_ID=your-endpoint-id
NOT_STUDIO_RUNPOD_API_KEY=your-api-key
NOT_STUDIO_RUNPOD_VOLUME_ID=your-network-volume-id
NOT_STUDIO_RUNPOD_S3_ENDPOINT_URL=https://s3api-EU-RO-1.runpod.io
NOT_STUDIO_RUNPOD_S3_ACCESS_KEY_ID=your-s3-access-key
NOT_STUDIO_RUNPOD_S3_SECRET_ACCESS_KEY=your-s3-secret
NOT_STUDIO_RUNPOD_S3_REGION=EU-RO-1
```

RunPod's Serverless job API accepts and returns JSON, so it cannot return a raw
FLAC response body. Returning base64 would add about 33% overhead and retain
large audio in the job result. Network-volume storage keeps the job response
small while the API transfers the actual bytes directly.

Build the worker from the repository root:

```bash
docker build -f not-studio/runpod/Dockerfile -t not-studio-stable-audio .
```

In RunPod:

1. Create a network volume in a datacenter with S3 API support.
2. Attach that volume to the Serverless endpoint.
3. Create a RunPod secret containing a Hugging Face token that can access the
   Stable Audio 3 model.
4. Set the worker environment variable
   `HF_TOKEN={{ RUNPOD_SECRET_huggingface_token }}`.

The token stays inside the worker. Not Studio does not send it in generation
requests or store it in its local configuration.

The endpoint input remains JSON:

```json
{
  "input": {
    "prompts": [{"title": "Track 01", "genre": "deep house", "prompt": "...", "duration": 180}],
    "model": "medium",
    "sample_rate": 44100
  }
}
```

The small JSON response references the binary files:

```json
{
  "tracks": [
    {
      "title": "Track 01",
      "storage_key": "not-studio/RUNPOD_JOB_ID/01-track-01.flac"
    }
  ]
}
```

See `runpod/README.md` for deployment and storage setup.
