"""API surface for the Not Studio workflow."""

import asyncio

from starlette.testclient import TestClient

from not_studio.db import init_db, session_scope
from not_studio.main import app
from not_studio.models import HistoryItem, Job


def test_health_reports_music_and_prompt_providers():
    with TestClient(app) as client:
        health = client.get("/api/health").json()
        assert health["status"] == "ok"
        assert health["jobs"] == "local-background"
        providers = {p["provider"]: p for p in health["providers"]}
        assert set(providers) == {"stable_audio_local", "stable_audio_runpod"}
        prompt_providers = {p["provider"]: p for p in health["prompt_providers"]}
        assert "lm_studio" in prompt_providers
        assert "openai" in prompt_providers


def test_jobs_websocket_sends_initial_snapshot():
    with TestClient(app) as client:
        with client.websocket_connect("/api/jobs/ws") as websocket:
            message = websocket.receive_json()

    assert message["type"] == "jobs"
    assert isinstance(message["jobs"], list)


def test_jobs_can_be_cancelled_and_removed():
    async def create_job() -> str:
        async with session_scope() as session:
            job = Job(type="generate_tracks", status="in_progress", message="Working")
            session.add(job)
            await session.commit()
            await session.refresh(job)
            return job.id

    with TestClient(app) as client:
        job_id = asyncio.run(create_job())
        cancelled = client.post(f"/api/jobs/{job_id}/cancel")
        assert cancelled.status_code == 200
        assert cancelled.json()["status"] == "cancelled"

        deleted = client.delete(f"/api/jobs/{job_id}")
        assert deleted.status_code == 204
        assert client.get(f"/api/jobs/{job_id}").status_code == 404


def test_startup_marks_stale_running_jobs_failed():
    async def create_stale_job() -> str:
        await init_db()
        async with session_scope() as session:
            job = Job(
                type="generate_tracks",
                status="in_progress",
                progress=0.12,
                message="Loading model: medium",
            )
            session.add(job)
            await session.commit()
            await session.refresh(job)
            return job.id

    job_id = asyncio.run(create_stale_job())

    with TestClient(app) as client:
        resp = client.get(f"/api/jobs/{job_id}")

    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "failed"
    assert body["message"] == "Interrupted by API restart"
    assert body["error"] == "API restarted before this local job finished"
    assert body["finished_at"]


def test_removing_completed_job_keeps_saved_outputs():
    async def create_job_with_output() -> tuple[str, str]:
        async with session_scope() as session:
            job = Job(type="generate_tracks", status="completed", message="Done")
            session.add(job)
            await session.commit()
            await session.refresh(job)
            item = HistoryItem(kind="track", title="Saved", job_id=job.id, path="/tmp/saved.flac")
            session.add(item)
            await session.commit()
            await session.refresh(item)
            return job.id, item.id

    async def output_job_id(item_id: str) -> str | None:
        async with session_scope() as session:
            item = await session.get(HistoryItem, item_id)
            return item.job_id if item else "missing"

    with TestClient(app) as client:
        job_id, item_id = asyncio.run(create_job_with_output())
        deleted = client.delete(f"/api/jobs/{job_id}")

    assert deleted.status_code == 204
    assert asyncio.run(output_job_id(item_id)) is None
