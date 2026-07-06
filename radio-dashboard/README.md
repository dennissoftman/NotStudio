# Radio Dashboard

A full-stack control panel for **Neural Radio** — schedule and manage generation
jobs, configure audio/TTS backends, orchestrate radio programs (music with
inserted news / info messages / ads / station IDs), keep a history of everything
generated, and stream a continuous channel using a **pre-allocated buffer**
(generate 15–20 min ahead, always keep ≥ 15 min ready).

This is a *subproject* of the Neural Radio dev repo. It **reuses** the existing
engine (`speech.py` Kokoro TTS, `main.py` Stable Audio 3 music, `timeline.py`
typed WebVTT timelines, `utils.py` loudness/mixing helpers) via pluggable
backend adapters, and adds:

| Feature | Where |
|---|---|
| 1. Scheduling + task management (submit / track / cancel) | `arq` queue + `Job`/`Schedule` models, `/jobs`, `/schedules` |
| 2. Configure audio + TTS backends, orchestrate streams | `Backend`/`Program` models, backend registry, timeline mixer |
| 3. Native radio streaming | Real-time playout → HTTP MP3 + HLS, optional **Icecast** publisher |
| 4. History + pre-allocated buffer | `HistoryItem`/`PlayoutSegment`, buffer manager (15–20 min batches) |

## Layout

```
radio-dashboard/
├── docker-compose.yml     # Redis (required for arq) + optional Icecast profile
├── api/                   # Python FastAPI backend (uv-managed)
│   └── radio_dashboard/
│       ├── backends/      # pluggable mock / kokoro / stable-audio adapters
│       ├── audio/         # timeline builder + numpy mixer
│       ├── tasks/         # arq worker + jobs + scheduler tick
│       ├── streaming/     # real-time playout, HTTP/HLS, Icecast
│       └── routers/       # REST API
└── ui/                    # React + Vite + TypeScript dashboard
```

## Quick start (local)

Everything runs on a **mock backend** out of the box — no model downloads, no GPU.

```bash
cd radio-dashboard/ui && npm install          # once, for the UI
cd ../api && uv sync
uv run dev                                     # Redis + API + worker + UI, together
```

`uv run dev` brings up **Redis** (via `docker compose`), the **API** (:8000), the
**arq worker**, and the **Vite UI** (:5173) with prefixed logs; Ctrl-C stops
everything. Flags: `--no-ui`, `--no-worker`, `--no-redis`, `--api-port N`.

Prefer separate terminals? Run the pieces by hand:

```bash
cd radio-dashboard && docker compose up -d redis                 # Redis (arq needs it)
cd api && uv sync
uv run uvicorn radio_dashboard.main:app --reload --port 8000     # terminal A
uv run arq radio_dashboard.tasks.worker.WorkerSettings           # terminal B
cd ../ui && npm install && npm run dev                           # terminal C -> :5173 (proxies /api -> :8000)
```

Tests: `uv run pytest` (from `api/`).

Open http://localhost:5173, create a Program, create a Stream, press **Go Live**.
The buffer manager generates 18-min batches ahead of playout; the player streams
`/api/streams/{id}/live.mp3`.

## Real backends (Kokoro / Stable Audio 3)

The mock backend is the default. To use the real engine, make sure the parent
Neural Radio project is synced (`uv sync` in the repo root, submodule checked out
for Stable Audio) and create `Backend` rows with provider `kokoro` / `stable_audio`.
The adapters shell out to the parent project's CLIs with `uv run --no-sync`, so no
heavy deps are duplicated into this subproject's environment.

## Icecast (feature #3)

HTTP MP3 + HLS work with no extra services. Icecast is an **optional, separate
server**, so it can't share the API's port — the API owns **:8000** and Icecast
runs on **:8010**:

```bash
docker compose --profile icecast up -d icecast   # listeners: http://localhost:8010/<mount>
```

Then set a stream's `icecast` config (`enabled: true`; `port: 8010`, mount and
credentials already default to match). The backend spawns an `ffmpeg` process
that pushes the live PCM to the mount; listeners tune in at
`http://localhost:8010/neural.mp3`.

**No `icecast.xml` mount is needed** — the `libretime/icecast` image patches its
`/etc/icecast.xml` from the `ICECAST_*` env vars in `docker-compose.yml`. Mount
your own config only for advanced control (custom listen port, extra mounts,
limits, per-mount auth); env vars can't change the listen port.

**One public port/domain for both?** Icecast and the API are distinct servers,
so combine them at the edge with a reverse proxy (Caddy/nginx or a Cloudflare
Tunnel): route `/api` → FastAPI and a `stream.` subdomain (or a path) → Icecast.

## Deploying to Cloudflare (later)

The React UI deploys to Cloudflare Pages. The API/worker run torch/Kokoro/Stable
Audio and therefore need a real box (the GPU host) — they are **not** Workers.
Put the UI on Pages and point it at the API host; optionally front the API with a
Cloudflare Tunnel. See `docs` in the parent repo for the timeline design.
