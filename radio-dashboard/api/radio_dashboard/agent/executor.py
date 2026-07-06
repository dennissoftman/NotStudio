"""Execute a tool call against the app's own REST API (in-process).

Uses httpx's ASGI transport to dispatch to the running FastAPI app with no network
hop, so a single tool call reuses the exact same endpoint logic (validation, DB,
queue) the human dashboard uses. Agent hosts can either call the REST API directly
using the published tool schemas, or relay tool calls to POST /api/agent/execute
which funnels through here.
"""

from __future__ import annotations

from typing import Any

import httpx

from .tools import TOOL_BY_NAME, _PATH_PARAM_RE


async def execute_tool(app: Any, name: str, arguments: dict[str, Any] | None) -> dict[str, Any]:
    spec = TOOL_BY_NAME.get(name)
    if spec is None:
        return {"ok": False, "status": 400, "result": {"detail": f"unknown tool: {name}"}}

    args = dict(arguments or {})
    path = spec.path
    for key in _PATH_PARAM_RE.findall(spec.path):
        if key not in args:
            return {
                "ok": False,
                "status": 400,
                "result": {"detail": f"missing required argument: {key}"},
            }
        path = path.replace("{" + key + "}", str(args.pop(key)))

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://agent.internal", timeout=60.0
    ) as client:
        if spec.method in ("GET", "DELETE"):
            response = await client.request(spec.method, path, params=args or None)
        else:
            response = await client.request(spec.method, path, json=args)

    try:
        result = response.json()
    except Exception:  # noqa: BLE001
        result = {"raw": response.text}
    return {"ok": response.is_success, "status": response.status_code, "result": result}
