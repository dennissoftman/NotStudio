# Not Studio

Not Studio is a human-in-the-loop music generation workspace. It focuses
on album batches, taste review, regeneration, and mix rendering.

## Workflow

1. Copy the GPT prompt kit from the Generate page.
2. Ask GPT to draft a JSON track plan using the included schema and taste profile.
3. Paste the JSON plan into Not Studio and generate a batch.
4. Listen to each track and mark it liked/disliked.
5. Use the refreshed prompt kit so the next GPT batch learns from those reviews.
6. Make a mix from the liked tracks and download the rendered MP4.

## Capabilities

| Capability | Where |
|---|---|
| Paste-first prompt generation | `ui/src/pages/Generate.tsx`, `/api/studio/generate` |
| GPT schema + taste export | `/api/studio/prompt-kit` |
| Human review state | `/api/studio/tracks/{id}/review` |
| Track history/playback | `/api/studio/tracks`, `/api/history/{id}/audio` |
| Mix/video rendering | `/api/studio/videos` |
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

For a production-style local launch, run `uv run dev --production`. It builds and serves the UI
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
kit containing the exact JSON schema, an example, and up to 20 recent liked and
disliked prompts. Every prompt item requires `title`, `genre`, `prompt`, and
`duration`. After reviews change, copying the kit again includes the new taste
signals automatically.

## Mix export

The Review page can export 2160p, 1440p, 1080p, or 720p H.264 video. Audio is
encoded once into the MP4 as AAC-LC without increasing the source mix sample
rate, channel count, or bitrate. When source tracks differ, the mix uses the
lowest native sample rate and channel count so no lower-quality input is
interpolated upward. Crossfading is streamed through ffmpeg, so the full album
is not loaded into a growing in-memory buffer before rendering.

## Audio Generation

`Stable Audio / Local` runs directly in a cancellable API worker process using
the checked-out `stable-audio-3` package.

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
