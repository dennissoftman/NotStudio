"""Agent control surface + the breaking-news announce primitive."""

from starlette.testclient import TestClient

from radio_dashboard import buffer as buffer_mod
from radio_dashboard.agent.tools import TOOLS, gemini_tools
from radio_dashboard.db import session_scope
from radio_dashboard.main import app
from radio_dashboard.models import PlayoutSegment, Stream


def test_tools_specs_both_formats():
    with TestClient(app) as client:
        anthropic = client.get("/api/agent/tools", params={"format": "anthropic"}).json()
        assert len(anthropic) == len(TOOLS)
        assert all({"name", "description", "input_schema"} <= set(t) for t in anthropic)
        # nested config models surface their $defs for the agent.
        create_program = next(t for t in anthropic if t["name"] == "create_program")
        assert "$defs" in create_program["input_schema"]

        openai = client.get("/api/agent/tools", params={"format": "openai"}).json()
        assert all(t["type"] == "function" for t in openai)


def test_state_and_execute_in_process():
    with TestClient(app) as client:
        state = client.get("/api/agent/state").json()
        assert {"streams", "active_jobs", "providers", "queue_online"} <= set(state)

        # /execute dispatches to the real endpoint in-process (read tool needs no queue).
        result = client.post(
            "/api/agent/execute", json={"name": "list_streams", "input": {}}
        ).json()
        assert result["ok"] is True and result["status"] == 200

        bad = client.post("/api/agent/execute", json={"name": "nope", "input": {}})
        assert bad.status_code == 400


def test_announce_requires_queue():
    with TestClient(app) as client:
        stream = client.post("/api/streams", json={"name": "Announce Chan"}).json()
        resp = client.post(f"/api/streams/{stream['id']}/announce", json={"text": "hello on air"})
        assert resp.status_code == 503  # queue offline in tests (no Redis)


async def test_front_sequence_jumps_the_queue():
    async with session_scope() as session:
        stream = Stream(name="FrontSeq")
        session.add(stream)
        await session.commit()
        await session.refresh(stream)

        # Empty buffer: front == append.
        assert await buffer_mod.front_sequence(
            session, stream.id
        ) == await buffer_mod.next_sequence(session, stream.id)

        for seq in (0, 1):
            session.add(
                PlayoutSegment(
                    stream_id=stream.id,
                    history_item_id=f"h{seq}",
                    sequence=seq,
                    duration_seconds=10.0,
                    state="ready",
                )
            )
        await session.commit()

        # front sorts before the lowest ready (0); append goes after the highest (1).
        assert await buffer_mod.front_sequence(session, stream.id) == -1
        assert await buffer_mod.next_sequence(session, stream.id) == 2


def test_gemini_tools_are_sanitized():
    """Gemini declarations must not carry $ref/$defs/anyOf; optionals -> nullable."""
    banned = {"$ref", "$defs", "anyOf", "oneOf", "allOf", "additionalProperties"}
    tools = {t["name"]: t for t in gemini_tools()}
    assert len(tools) == len(TOOLS)

    def walk(node: dict) -> None:
        assert not (banned & set(node)), node
        for sub in node.get("properties", {}).values():
            walk(sub)
        if "items" in node:
            walk(node["items"])

    for tool in tools.values():
        walk(tool["parameters"])

    # nested program config is inlined to a real object with properties.
    config = tools["create_program"]["parameters"]["properties"]["config"]
    assert config["type"] == "object" and "properties" in config
    # an optional field collapses to nullable rather than anyOf[..., null].
    voice = tools["insert_announcement"]["parameters"]["properties"]["voice"]
    assert voice.get("nullable") is True
