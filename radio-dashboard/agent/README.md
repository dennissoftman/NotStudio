# Radio Agent — LLM control surface

This folder exposes the station's **job management** to an LLM "radio agent". Your
agent calls the API to run the station; the React UI stays as the human dashboard
and manual-override surface.

## What's here

| File | What |
|---|---|
| `system_prompt.md` | System prompt for the radio agent (station-director role). |
| `tools.gemini.json` | Tool specs as Gemini function declarations (schema sanitized: no `$ref`, optionals as `nullable`). |
| `tools.openai.json` | Same tools in OpenAI function format (`function.parameters`). |
| `tools.anthropic.json` | Same tools in Anthropic Messages format (`input_schema`). |
| `radio_agent.py` | Runnable reference agent: a Gemini function-calling loop over the API. |

These JSON files are **generated** from the API (the source of truth). Fetch the
live versions from a running server instead of trusting the snapshots:

```
GET  /api/agent/tools?format=gemini|openai|anthropic  # tool/function schemas (default: gemini)
GET  /api/agent/system_prompt?with_state=true   # prompt (+ live state snapshot)
GET  /api/agent/state                            # compact live station snapshot
GET  /api/agent/manifest                         # prompt + tools + state in one call
POST /api/agent/execute  {name, input}           # run one tool in-process
```

Regenerate the snapshots after changing tools:

```bash
cd api && uv run python -c "import json,pathlib as p; from radio_dashboard.agent.tools import anthropic_tools,openai_tools,gemini_tools; from radio_dashboard.agent.prompts import RADIO_AGENT_SYSTEM_PROMPT as S; d=p.Path('../agent'); d.joinpath('tools.gemini.json').write_text(json.dumps(gemini_tools(),indent=2)); d.joinpath('tools.openai.json').write_text(json.dumps(openai_tools(),indent=2)); d.joinpath('tools.anthropic.json').write_text(json.dumps(anthropic_tools(),indent=2)); d.joinpath('system_prompt.md').write_text(S+chr(10))"
```

## Two integration patterns

1. **Direct REST** — your agent host maps each tool to its HTTP call (method+path
   are in the API's OpenAPI at `/docs`). Most control, no extra endpoint.
2. **Thin relay (recommended)** — your agent host just relays each tool call to
   `POST /api/agent/execute {name, input}`; the API dispatches it in-process to the
   same endpoint logic. The reference agent uses this — the host code is ~40 lines.

## Run the reference agent

Uses the Google Gen AI SDK (Gemini) — get a key from Google AI Studio.

```bash
cd radio-dashboard/api
export GEMINI_API_KEY=...
uv run --extra agent python ../agent/radio_agent.py "Create a lo-fi program, make a stream, go live"
uv run --extra agent python ../agent/radio_agent.py "Break in on the main channel: 'Storm warning until 9pm.'"
uv run --extra agent python ../agent/radio_agent.py --dry-run "validate tool schemas without an API key"
```

Env: `RADIO_API` (default `http://localhost:8000`), `RADIO_AGENT_MODEL` (default
`gemini-flash-latest`; set `gemini-pro-latest` for harder planning).

## The tools (23)

- **Observe**: `get_station_state`, `list_streams`, `get_buffer_status`,
  `list_jobs`, `get_job`, `list_programs`, `list_backends`, `list_providers`,
  `list_schedules`, `list_history`.
- **Content now**: `insert_announcement` — render a short spoken message and air it
  right after the current segment (breaking news / live reads). This is the key
  automation primitive; program edits only affect batches 15-20 min out.
- **Configure**: `create_backend`, `create_program`, `update_program`,
  `create_stream`, `update_stream`.
- **Lifecycle & jobs**: `start_stream`, `stop_stream`, `submit_job`, `cancel_job`.
- **Scheduling**: `create_schedule`, `update_schedule`, `delete_schedule`.

## Guardrails

The prompt tells the agent to ground itself with `get_station_state` first, prefer
the smallest action, treat `stop_stream`/`delete_schedule` as disruptive, and fall
back to the `mock` backend when real providers are unavailable. For production,
also gate mutating tools behind your own auth/approval and consider withholding the
destructive tools from the agent's toolset entirely (serve a filtered
`/api/agent/tools`).
