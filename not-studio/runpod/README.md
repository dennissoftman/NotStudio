# Stable Audio RunPod Worker

This worker loads Stable Audio 3 once per warm process, generates a prompt batch,
and writes FLAC files under `/runpod-volume/not-studio/<job-id>/`.

## Build

Use the repository root as Docker build context:

```bash
docker build -f not-studio/runpod/Dockerfile -t not-studio-stable-audio .
```

Push the image to a registry and use it for a RunPod Serverless endpoint.

## Endpoint Setup

1. Create and attach a RunPod network volume.
2. Create a RunPod secret named `huggingface_token` containing a Hugging Face
   token with access to `stabilityai/stable-audio-3-medium`.
3. Add this endpoint environment variable:

```text
HF_TOKEN={{ RUNPOD_SECRET_huggingface_token }}
```

Optional worker variables:

| Variable | Default | Purpose |
|---|---|---|
| `STABLE_AUDIO_MODEL` | `medium` | Default model when a request omits `model` |
| `RUNPOD_VOLUME_PATH` | `/runpod-volume` | Attached volume mount |
| `HF_HOME` | `/runpod-volume/huggingface` | Persistent Hugging Face model cache |

The worker fails before model loading when `HF_TOKEN` is absent or when the
network volume is not mounted.

## Binary Transfer

RunPod Serverless handlers exchange JSON job inputs and outputs. The worker
therefore returns storage keys, not FLAC bytes or base64. Not Studio downloads
each key through RunPod's S3-compatible API using the network volume ID and a
separate S3 API key.

RunPod does not support presigned URLs for its network-volume S3 API. Keep the
S3 credentials in the Not Studio API environment and never expose them to the
browser.
