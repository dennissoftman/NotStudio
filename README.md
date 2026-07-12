# Not Studio

Not Studio is a human-in-the-loop music generation workspace for turning
music taste into generated albums, reviewed tracks, mixes, and rendered videos.

The main application lives in `not-studio/`:

- `not-studio/api/` - FastAPI backend for prompt ideation, generation jobs,
  review state, history, audio playback, and video rendering.
- `not-studio/ui/` - React + Vite interface for generating, reviewing, and
  assembling tracks.
- `not-studio/runpod/` - Stable Audio worker packaging for RunPod.
- `stable-audio-3/` - local Stable Audio dependency used by the API.

## Quick Start

Install and run the app:

```bash
cd not-studio/ui
npm install
cd ../api
uv sync
uv run dev
```

`uv run dev` starts the API at `http://localhost:8001` and the UI at
`http://localhost:5173`.

## Verification

Run API checks from `not-studio/api/`:

```bash
uv run python -m pytest
uv run ruff check
uv run ruff format --check
uv lock --check
```

Build the UI from `not-studio/ui/`:

```bash
npm run build
```

## Documentation

See `not-studio/README.md` for the product workflow, configuration, providers,
and RunPod storage contract.

## License

MIT. See `LICENSE`.
