"""The radio agent's tool catalog.

Each tool is a logical station action bound to one REST endpoint. Input schemas
are derived from the same pydantic request models the API validates against, so
the agent-facing contract can't drift from the server. Exposed as Gemini function
declarations (default; schema sanitized — no $ref, optionals as nullable), and in
OpenAI (`function.parameters`) and Anthropic (`input_schema`) shapes.

Executor convention (see executor.py): keys named in the path template (e.g.
``{stream_id}``) are taken from the tool input and substituted into the path; the
remaining keys become the JSON body (POST/PATCH) or query string (GET/DELETE).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel

from ..schemas import (
    AnnounceRequest,
    BackendCreate,
    JobSubmit,
    ProgramCreate,
    ProgramUpdate,
    ScheduleCreate,
    ScheduleUpdate,
    StreamCreate,
    StreamUpdate,
)

_PATH_PARAM_RE = re.compile(r"{(\w+)}")


def _schema(
    model: type[BaseModel] | None = None,
    *,
    path_params: dict[str, str] | None = None,
    properties: dict[str, dict] | None = None,
    required: list[str] | None = None,
) -> dict[str, Any]:
    """Build a JSON Schema from a pydantic model + path/extra params."""
    props: dict[str, Any] = {}
    req: list[str] = []
    defs: dict[str, Any] | None = None

    for name, description in (path_params or {}).items():
        props[name] = {"type": "string", "description": description}
        req.append(name)

    if model is not None:
        js = model.model_json_schema()
        props.update(js.get("properties", {}))
        req.extend(js.get("required", []))
        defs = js.get("$defs")

    if properties:
        props.update(properties)
    if required:
        req.extend(required)

    schema: dict[str, Any] = {"type": "object", "properties": props}
    if req:
        schema["required"] = req
    if defs:
        schema["$defs"] = defs
    return schema


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    method: str
    path: str
    input_schema: dict[str, Any] = field(
        default_factory=lambda: {"type": "object", "properties": {}}
    )
    mutating: bool = False

    @property
    def path_params(self) -> list[str]:
        return _PATH_PARAM_RE.findall(self.path)


TOOLS: list[ToolSpec] = [
    # --- observe ------------------------------------------------------------
    ToolSpec(
        "get_station_state",
        "Snapshot of the whole station: streams with live buffer status, active "
        "jobs, programs, backends and provider availability. ALWAYS call this "
        "first to ground yourself before acting.",
        "GET",
        "/api/agent/state",
    ),
    ToolSpec("list_streams", "List all channels and their status.", "GET", "/api/streams"),
    ToolSpec(
        "get_buffer_status",
        "Buffer readiness for one stream: ready_seconds vs min_seconds, whether a "
        "batch is generating, and segment counts.",
        "GET",
        "/api/streams/{stream_id}/buffer",
        _schema(path_params={"stream_id": "Stream id."}),
    ),
    ToolSpec(
        "list_jobs",
        "List generation jobs (most recent first). Optionally filter by stream or "
        "status (queued|in_progress|completed|failed|cancelled).",
        "GET",
        "/api/jobs",
        _schema(
            properties={
                "stream_id": {"type": "string", "description": "Filter to one stream."},
                "status": {"type": "string", "description": "Filter by job status."},
            }
        ),
    ),
    ToolSpec(
        "get_job",
        "Fetch one job to track its status, progress and result/error.",
        "GET",
        "/api/jobs/{job_id}",
        _schema(path_params={"job_id": "Job id."}),
    ),
    ToolSpec("list_programs", "List orchestration programs (recipes).", "GET", "/api/programs"),
    ToolSpec("list_backends", "List configured audio/TTS backends.", "GET", "/api/backends"),
    ToolSpec(
        "list_providers",
        "List backend providers (mock/kokoro/stable_audio) and whether each is "
        "available in this environment.",
        "GET",
        "/api/backends/providers",
    ),
    ToolSpec("list_schedules", "List schedules.", "GET", "/api/schedules"),
    ToolSpec(
        "list_history",
        "List saved generated audio (batches + announcements), newest first.",
        "GET",
        "/api/history",
        _schema(
            properties={"stream_id": {"type": "string", "description": "Filter to one stream."}}
        ),
    ),
    # --- content: the key automation primitive ------------------------------
    ToolSpec(
        "insert_announcement",
        "Render a SHORT spoken message and air it on a LIVE stream immediately "
        "(breaking news, live read, time-sensitive info). With play_next=true it "
        "plays right after the current segment. Use this for timely one-off "
        "speech; use update_program for recurring content.",
        "POST",
        "/api/streams/{stream_id}/announce",
        _schema(AnnounceRequest, path_params={"stream_id": "Live stream to interrupt."}),
        mutating=True,
    ),
    # --- backends / programs ------------------------------------------------
    ToolSpec(
        "create_backend",
        "Register an audio (music) or TTS (speech) backend. Provider mock needs no "
        "config; kokoro/stable_audio reuse the real engine.",
        "POST",
        "/api/backends",
        _schema(BackendCreate),
        mutating=True,
    ),
    ToolSpec(
        "create_program",
        "Create an orchestration program: a music bed plus spoken inserts "
        "(news/info/ad/station_id/weather) with cadence, scripts, ducking.",
        "POST",
        "/api/programs",
        _schema(ProgramCreate),
        mutating=True,
    ),
    ToolSpec(
        "update_program",
        "Update a program's music, inserts or backends. Affects FUTURE batches "
        "only (15-20 min out) — not currently-playing audio.",
        "PATCH",
        "/api/programs/{program_id}",
        _schema(ProgramUpdate, path_params={"program_id": "Program id."}),
        mutating=True,
    ),
    # --- streams / lifecycle ------------------------------------------------
    ToolSpec(
        "create_stream",
        "Create a channel bound to a program, with buffer/batch settings and "
        "optional Icecast publishing.",
        "POST",
        "/api/streams",
        _schema(StreamCreate),
        mutating=True,
    ),
    ToolSpec(
        "update_stream",
        "Update a stream's program, buffer policy or Icecast config.",
        "PATCH",
        "/api/streams/{stream_id}",
        _schema(StreamUpdate, path_params={"stream_id": "Stream id."}),
        mutating=True,
    ),
    ToolSpec(
        "start_stream",
        "Take a stream live: begins real-time playout and seeds buffer generation.",
        "POST",
        "/api/streams/{stream_id}/start",
        _schema(path_params={"stream_id": "Stream id."}),
        mutating=True,
    ),
    ToolSpec(
        "stop_stream",
        "Take a stream off the air (stops playout). Disruptive — only when intended.",
        "POST",
        "/api/streams/{stream_id}/stop",
        _schema(path_params={"stream_id": "Stream id."}),
        mutating=True,
    ),
    # --- jobs ---------------------------------------------------------------
    ToolSpec(
        "submit_job",
        "Submit a generation batch for a stream (buffers ahead) or a one-off "
        "render for a program. Use params.target_seconds to size it.",
        "POST",
        "/api/jobs",
        _schema(JobSubmit),
        mutating=True,
    ),
    ToolSpec(
        "cancel_job",
        "Cancel a queued or running job.",
        "POST",
        "/api/jobs/{job_id}/cancel",
        _schema(path_params={"job_id": "Job id."}),
        mutating=True,
    ),
    # --- schedules ----------------------------------------------------------
    ToolSpec(
        "create_schedule",
        "Schedule recurring/one-shot actions: render_batch, start_stream or "
        "stop_stream, via interval (seconds), cron (5-field, UTC) or date (run_at).",
        "POST",
        "/api/schedules",
        _schema(ScheduleCreate),
        mutating=True,
    ),
    ToolSpec(
        "update_schedule",
        "Enable/disable or retime a schedule.",
        "PATCH",
        "/api/schedules/{schedule_id}",
        _schema(ScheduleUpdate, path_params={"schedule_id": "Schedule id."}),
        mutating=True,
    ),
    ToolSpec(
        "delete_schedule",
        "Delete a schedule.",
        "DELETE",
        "/api/schedules/{schedule_id}",
        _schema(path_params={"schedule_id": "Schedule id."}),
        mutating=True,
    ),
]

TOOL_BY_NAME: dict[str, ToolSpec] = {t.name: t for t in TOOLS}


def anthropic_tools() -> list[dict[str, Any]]:
    """Anthropic Messages API tool format."""
    return [
        {"name": t.name, "description": t.description, "input_schema": t.input_schema}
        for t in TOOLS
    ]


def openai_tools() -> list[dict[str, Any]]:
    """OpenAI Chat Completions / Responses function-tool format."""
    return [
        {
            "type": "function",
            "function": {
                "name": t.name,
                "description": t.description,
                "parameters": t.input_schema,
            },
        }
        for t in TOOLS
    ]


# Keys kept in a Gemini schema; everything else (title/default/additionalProperties
# /$schema/...) is dropped.
_GEMINI_KEEP = ("type", "description", "enum", "properties", "required", "items", "nullable")


def _gemini_schema(node: dict[str, Any], defs: dict[str, Any]) -> dict[str, Any]:
    """Sanitize a JSON Schema node for Gemini function declarations.

    Gemini doesn't support $ref/$defs/allOf/additionalProperties and expresses
    optionality with ``nullable`` instead of ``anyOf: [T, null]``.
    """
    if "$ref" in node:
        target = defs.get(node["$ref"].split("/")[-1], {})
        node = {**target, **{k: v for k, v in node.items() if k != "$ref"}}
    if "allOf" in node and len(node["allOf"]) == 1:
        node = {**node["allOf"][0], **{k: v for k, v in node.items() if k != "allOf"}}

    variants = node.get("anyOf") or node.get("oneOf")
    if variants:
        non_null = [v for v in variants if v.get("type") != "null"]
        base = _gemini_schema(non_null[0], defs) if non_null else {"type": "string"}
        if any(v.get("type") == "null" for v in variants):
            base["nullable"] = True
        if "description" in node:
            base.setdefault("description", node["description"])
        return base

    out: dict[str, Any] = {k: node[k] for k in _GEMINI_KEEP if k in node}
    if out.get("type") == "object" or "properties" in node:
        out["type"] = "object"
        out["properties"] = {
            name: _gemini_schema(sub, defs) for name, sub in node.get("properties", {}).items()
        }
        required = [r for r in node.get("required", []) if r in out["properties"]]
        out["required"] = required if required else out.pop("required", None) or []
        if not out["required"]:
            out.pop("required")
    if out.get("type") == "array" or "items" in node:
        out["type"] = "array"
        if "items" in node:
            out["items"] = _gemini_schema(node["items"], defs)
    if "enum" in out and "type" not in out:
        out["type"] = "string"
    return out


def gemini_tools() -> list[dict[str, Any]]:
    """Google Gemini function-declaration format (schema sanitized for Gemini)."""
    tools: list[dict[str, Any]] = []
    for t in TOOLS:
        defs = t.input_schema.get("$defs", {})
        params = _gemini_schema({k: v for k, v in t.input_schema.items() if k != "$defs"}, defs)
        params.setdefault("type", "object")
        params.setdefault("properties", {})
        tools.append({"name": t.name, "description": t.description, "parameters": params})
    return tools
