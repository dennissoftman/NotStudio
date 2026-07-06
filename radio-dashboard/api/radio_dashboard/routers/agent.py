"""Agent control surface: tool specs, system prompt, live state, and executor."""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from .. import buffer as buffer_mod
from ..agent.executor import execute_tool
from ..agent.prompts import RADIO_AGENT_SYSTEM_PROMPT, render_system_prompt
from ..agent.tools import TOOL_BY_NAME, anthropic_tools, gemini_tools, openai_tools
from ..backends.registry import provider_infos
from ..deps import get_session
from ..models import Backend, Job, Program, Stream

router = APIRouter(prefix="/agent", tags=["agent"])


@router.get("/tools")
async def get_tools(
    format: Literal["anthropic", "openai", "gemini"] = "gemini",
) -> list[dict[str, Any]]:
    """Tool/function JSON specs for the radio agent (default: Gemini)."""
    if format == "openai":
        return openai_tools()
    if format == "anthropic":
        return anthropic_tools()
    return gemini_tools()


@router.get("/system_prompt")
async def get_system_prompt(
    request: Request,
    with_state: bool = Query(default=False, description="Append a live state snapshot."),
    session: AsyncSession = Depends(get_session),
) -> dict[str, str]:
    if with_state:
        return {"system_prompt": render_system_prompt(await _station_state(request, session))}
    return {"system_prompt": RADIO_AGENT_SYSTEM_PROMPT}


@router.get("/state")
async def get_state(
    request: Request, session: AsyncSession = Depends(get_session)
) -> dict[str, Any]:
    """A compact snapshot the agent uses to ground its decisions each turn."""
    return await _station_state(request, session)


class ExecuteRequest(BaseModel):
    name: str = Field(description="Tool name from GET /agent/tools")
    input: dict[str, Any] = Field(default_factory=dict)


@router.post("/execute")
async def execute(payload: ExecuteRequest, request: Request) -> dict[str, Any]:
    """Run a single tool call against the API in-process (thin-relay convenience)."""
    if payload.name not in TOOL_BY_NAME:
        raise HTTPException(status_code=400, detail=f"unknown tool: {payload.name}")
    return await execute_tool(request.app, payload.name, payload.input)


@router.get("/manifest")
async def manifest(
    request: Request, session: AsyncSession = Depends(get_session)
) -> dict[str, Any]:
    """Everything an agent needs to bootstrap in one call."""
    return {
        "system_prompt": RADIO_AGENT_SYSTEM_PROMPT,
        "tools": anthropic_tools(),
        "state": await _station_state(request, session),
    }


async def _station_state(request: Request, session: AsyncSession) -> dict[str, Any]:
    stream_rows = (
        (await session.execute(select(Stream).order_by(Stream.created_at))).scalars().all()
    )
    streams = []
    for stream in stream_rows:
        ready = await buffer_mod.ready_seconds(session, stream.id)
        ready_count, total = await buffer_mod.segment_counts(session, stream.id)
        streams.append(
            {
                "id": stream.id,
                "name": stream.name,
                "status": stream.status,
                "program_id": stream.program_id,
                "ready_seconds": round(ready, 1),
                "min_seconds": stream.buffer_min_seconds,
                "segments_ready": ready_count,
                "segments_total": total,
                "generating": await buffer_mod.has_active_batch_job(session, stream.id),
                "icecast_enabled": bool((stream.icecast or {}).get("enabled")),
            }
        )

    active = (
        (
            await session.execute(
                select(Job)
                .where(Job.status.in_(("queued", "in_progress")))
                .order_by(Job.created_at.desc())
                .limit(25)
            )
        )
        .scalars()
        .all()
    )
    programs = (await session.execute(select(Program).order_by(Program.created_at))).scalars().all()
    backends = (await session.execute(select(Backend).order_by(Backend.created_at))).scalars().all()

    return {
        "queue_online": getattr(request.app.state, "arq", None) is not None,
        "streams": streams,
        "active_jobs": [
            {
                "id": j.id,
                "type": j.type,
                "status": j.status,
                "progress": round(j.progress, 2),
                "stream_id": j.stream_id,
                "message": j.message,
            }
            for j in active
        ],
        "programs": [
            {"id": p.id, "name": p.name, "inserts": len((p.config or {}).get("inserts", []))}
            for p in programs
        ],
        "backends": [
            {
                "id": b.id,
                "name": b.name,
                "kind": b.kind,
                "provider": b.provider,
                "enabled": b.enabled,
            }
            for b in backends
        ],
        "providers": [{"provider": p.provider, "available": p.available} for p in provider_infos()],
    }
