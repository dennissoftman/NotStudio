"""Reference Neural Radio agent — a Gemini function-calling loop over the station API.

It loads the system prompt + Gemini tool declarations from the running API, then
lets Gemini drive the station by calling tools, which are executed in-process by
the API via POST /api/agent/execute. Any LLM stack can do the same using
GET /api/agent/tools (formats: gemini | openai | anthropic) and /api/agent/system_prompt.

Run (from radio-dashboard/api, so the `agent` extra / google-genai is available):

    export GEMINI_API_KEY=...          # or GOOGLE_API_KEY
    uv run --extra agent python ../agent/radio_agent.py "Spin up a lo-fi channel and go live"
    uv run --extra agent python ../agent/radio_agent.py "Break in: markets rallied today"
    uv run --extra agent python ../agent/radio_agent.py --dry-run "check tool schemas"

Env:
    RADIO_API          base URL of the API (default http://localhost:8000)
    RADIO_AGENT_MODEL  Gemini model id (default gemini-flash-latest;
                       set gemini-pro-latest for harder planning)
"""

from __future__ import annotations

import json
import os
import sys

import httpx
from google import genai
from google.genai import types

API = os.environ.get("RADIO_API", "http://localhost:8000").rstrip("/")
MODEL = os.environ.get("RADIO_AGENT_MODEL", "gemini-flash-latest")
MAX_STEPS = int(os.environ.get("RADIO_AGENT_MAX_STEPS", "20"))


def _load_context() -> tuple[list[types.Tool], str]:
    declarations = httpx.get(
        f"{API}/api/agent/tools", params={"format": "gemini"}, timeout=30
    ).json()
    system = httpx.get(
        f"{API}/api/agent/system_prompt", params={"with_state": "true"}, timeout=30
    ).json()["system_prompt"]
    fns = []
    for d in declarations:
        params = d.get("parameters")
        kwargs = {"name": d["name"], "description": d["description"]}
        if params and params.get("properties"):
            kwargs["parameters"] = params
        fns.append(types.FunctionDeclaration(**kwargs))
    return [types.Tool(function_declarations=fns)], system


def _execute(name: str, tool_input: dict) -> dict:
    resp = httpx.post(
        f"{API}/api/agent/execute",
        json={"name": name, "input": tool_input},
        timeout=120,
    )
    return resp.json()


def run(goal: str) -> None:
    tools, system = _load_context()
    client = genai.Client()  # reads GEMINI_API_KEY / GOOGLE_API_KEY
    config = types.GenerateContentConfig(
        system_instruction=system,
        tools=tools,
        temperature=0.2,
        # We execute tools ourselves over HTTP, so disable the SDK's auto-calling.
        automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
    )
    contents: list[types.Content] = [
        types.Content(role="user", parts=[types.Part(text=goal)])
    ]

    for _ in range(MAX_STEPS):
        response = client.models.generate_content(
            model=MODEL, contents=contents, config=config
        )
        candidate = response.candidates[0]
        contents.append(candidate.content)

        calls = []
        for part in candidate.content.parts or []:
            if getattr(part, "text", None) and part.text.strip():
                print(f"\n🎙  {part.text.strip()}")
            if getattr(part, "function_call", None):
                calls.append(part.function_call)

        if not calls:
            return

        results = []
        for call in calls:
            args = dict(call.args or {})
            print(f"   → {call.name}({json.dumps(args)})")
            output = _execute(call.name, args)
            print(
                f"     {'ok' if output.get('ok') else 'ERR ' + str(output.get('status'))}"
            )
            results.append(
                types.Part.from_function_response(name=call.name, response=output)
            )
        contents.append(types.Content(role="user", parts=results))

    print("\n⚠  Reached step limit without a final answer.")


def dry_run() -> None:
    """Validate that the Gemini tool declarations build without an API key."""
    tools, system = _load_context()
    n = sum(len(t.function_declarations) for t in tools)
    print(f"system prompt: {len(system)} chars")
    print(f"gemini tools built OK: {n} function declarations")


if __name__ == "__main__":
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        raise SystemExit(1)
    if args[0] == "--dry-run":
        dry_run()
    else:
        run(" ".join(args))
