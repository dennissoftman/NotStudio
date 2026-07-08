# Not Studio

Not Studio is a human-in-the-loop music generation workspace. It focuses
on album batches, taste review, regeneration, and mix rendering.

## Workflow

1. Choose a mood.
2. Choose one or more styles.
3. Optionally ask an LLM to draft audio-generation prompts.
4. Choose a track count and generate a batch.
5. Listen to each track and mark it liked/disliked.
6. Regenerate until there are enough liked tracks.
7. Make a mix from the liked tracks.
8. Download the rendered MP4 for YouTube upload.

## Capabilities

| Capability | Where |
|---|---|
| Album generation controls | `ui/src/pages/Generate.tsx`, `/api/studio/albums/generate` |
| LLM prompt ideation | `/api/studio/prompts/generate` |
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
│       ├── prompt_generation.py
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

`uv run dev` starts the API on `http://localhost:8000` and the UI on
`http://localhost:5173`. Jobs run as FastAPI background tasks inside the API.

Run tests from `api/`:

```bash
uv run pytest
```

Build the UI from `ui/`:

```bash
npm run build
```

## LLM Prompt Providers

The Generate page can ask one of these providers to produce editable audio
prompts before track generation:

| Provider | Config |
|---|---|
| LM Studio | Start the local server, default `NOT_STUDIO_LM_STUDIO_BASE_URL=http://localhost:1234/v1` |
| OpenAI | `NOT_STUDIO_OPENAI_API_KEY`, optional `NOT_STUDIO_OPENAI_MODEL` |
| Anthropic | `NOT_STUDIO_ANTHROPIC_API_KEY`, optional `NOT_STUDIO_ANTHROPIC_MODEL` |
| Gemini | `NOT_STUDIO_GEMINI_API_KEY`, optional `NOT_STUDIO_GEMINI_MODEL` |

Copy `api/.env.example` to `api/.env` for the full list.

## Audio Generation

`Stable Audio / Local` runs the parent repo's `main.py --prompts` command once
for the whole batch. Sync the root environment and check out `stable-audio-3`.

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
    "prompts": [{"title": "Track 01", "prompt": "...", "duration": 180}],
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
