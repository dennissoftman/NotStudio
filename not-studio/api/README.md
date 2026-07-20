# not-studio-api

FastAPI backend for Not Studio: local Qwen album planning, ACE-Step 1.5
Text2Music, FLUX.2 Klein cover generation, review state, and album construction.

The high-quality `acestep-v15-sft` music model runs with 50 diffusion steps and
CFG. Apple Silicon Macs with 16 GB or less of unified memory instead select
`acestep-v15-turbo` with its 8-step preset. It is paired with a device-selected
ACE-Step 5 Hz language model for thinking and prompt refinement: 0.6B with
PyTorch on Apple Silicon and CPU, and 1.7B with vLLM on NVIDIA CUDA. Missing
checkpoints are downloaded automatically on first startup.

Install and run:

```bash
uv sync --locked
uv run uvicorn not_studio.main:app --reload --port 8001
```

ACE-Step 1.5 is installed from the
[official Git repository](https://github.com/ace-step/ACE-Step-1.5),
as recommended for library use by the upstream project.

Or start the API and UI together:

```bash
uv run dev
```

The combined `dev` and `prod` launchers run `uv sync --locked` and
`yarn install --immutable` before starting their service processes.

Jobs are visible through `/api/jobs`; live snapshots are streamed at
`/api/jobs/ws`. One exclusive model process swaps between Qwen, ACE-Step, and
FLUX. `/api/health` reports the active accelerator family. Startup preloading is
off by default so a natural-language request can load Qwen directly.

Before first use on the CUDA host, run `uv run not-studio-preflight`, followed by
`uv run not-studio-gpu-smoke` for a complete one-track pipeline test.

Album export is handled by `/api/studio/albums/export`. Its optional
`include_track_videos` flag defaults to `false`. When true, `python-ffmpeg` adds
one 1 fps H.264/yuv420p MP4 per FLAC with AAC-LC 320 kbps audio. Each track uses
its selected cover and falls back to the album cover; an MP4 is skipped only
when neither exists. The removed multi-track video endpoints are no longer part
of the API.

From this directory, `uv run prod` starts the API on `0.0.0.0:8081` and the
built UI on `0.0.0.0:8080`. Append `--no-model` to `uv run dev` or `uv run prod`
to skip ACE-Step warmup for UI-focused work.

Configuration is documented in `../README.md` and `.env.example`.
`NOT_STUDIO_TRACK_AUTHOR` controls the generated/exported FLAC artist tag and
defaults to `Not Studio`.
