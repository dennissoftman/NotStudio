# Neural Radio Studio

A simple **Studio** UI to generate AI music tracks from prompts and turn them into
YouTube-ready videos — on top of a full FastAPI backend that also does radio
automation (scheduling, pluggable backends, program orchestration, buffered
HTTP/HLS/Icecast streaming) and an **LLM agent** control surface.

The **UI is two clicks**: **Generate** (paste a prompt list → tracks land in the
library) and **Library** (tick tracks → crossfade → video). The **API** keeps the
broader radio/agent feature set for programmatic use.

This is a *subproject* of the Neural Radio dev repo. It **reuses** the existing
engine (`main.py` Stable Audio 3, `speech.py` Kokoro TTS, `cross.py` crossfade,
`video.py` video export, `timeline.py` timelines) rather than reimplementing it.

| Capability | Where |
|---|---|
| Studio UI: generate tracks + assemble videos | `/api/studio/*`, Generate + Library pages |
| Local music generation (Stable Audio 3, medium by default) | `generate_tracks` job → `main.py --prompts` |
| Video export (crossfade + visualizer, −14 LUFS master) | `make_video` job → `video.py` |
| Scheduling + jobs (submit / track / cancel) | `arq` queue, `/jobs`, `/schedules` |
| Radio streaming (HTTP MP3 + HLS + Icecast) + pre-allocated buffer | real-time playout, `/streams/*` |
| LLM agent control surface | `/api/agent/*`, `agent/` |

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
│       ├── routers/       # REST API
│       └── agent/         # LLM tool specs + system prompt + executor
├── ui/                    # React + Vite + TypeScript dashboard
└── agent/                 # LLM agent: JSON tool specs, system prompt, reference agent
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

Open http://localhost:5173:

1. **Generate** — paste a prompt list (JSON array of `{title, prompt, duration}`),
   pick **Stable Audio 3** (local) or **Mock** (instant, for testing), click
   **Generate tracks**. Stable Audio needs the parent repo env synced
   (`uv sync` at the repo root; medium model downloads on first run).
2. **Library** — tick tracks in order, choose a visualizer + crossfade, click
   **Make video**. The rendered mp4 appears under **Videos** to play or download.

The radio-automation and agent features (streams, programs, schedules, Icecast,
`/api/agent/*`) remain available via the API even though the UI focuses on the
Studio flow.

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

## LLM radio agent

Automate the station with an LLM that calls the API. The **UI stays the human
dashboard / override**; the agent handles routine operations and reacts to events.

- Tool/function specs: `GET /api/agent/tools?format=gemini|openai|anthropic`
  (default `gemini`; snapshotted in `agent/tools.*.json`).
- System prompt: `GET /api/agent/system_prompt?with_state=true` (also
  `agent/system_prompt.md`).
- Live grounding: `GET /api/agent/state`; one-call bootstrap: `GET /api/agent/manifest`.
- Run a tool in-process: `POST /api/agent/execute {name, input}`.

The standout primitive is **`insert_announcement`** — render a short spoken message
and air it right after the current segment (breaking news / live reads), vs.
program edits that only affect batches 15–20 min out.

Run the reference agent (a Gemini function-calling loop; default model
`gemini-flash-latest`, `gemini-pro-latest` optional):

```bash
cd api && export GEMINI_API_KEY=...
uv run --extra agent python ../agent/radio_agent.py "Break in on the main channel: storm warning until 9pm"
```

See `agent/README.md` for integration patterns and guardrails.

## Deploying to Cloudflare (later)

The React UI deploys to Cloudflare Pages. The API/worker run torch/Kokoro/Stable
Audio and therefore need a real box (the GPU host) — they are **not** Workers.
Put the UI on Pages and point it at the API host; optionally front the API with a
Cloudflare Tunnel. See `docs` in the parent repo for the timeline design.
