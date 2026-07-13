"""API surface for the Not Studio workflow."""

import asyncio
from unittest.mock import AsyncMock

from starlette.testclient import TestClient

from not_studio.db import init_db, session_scope
from not_studio.config import get_settings
from not_studio.main import app
from not_studio.models import HistoryItem, Job


def test_health_reports_music_providers():
    with TestClient(app) as client:
        health = client.get("/api/health").json()
        assert health["status"] == "ok"
        assert health["jobs"] == "local-background"
        providers = {p["provider"]: p for p in health["providers"]}
        assert set(providers) == {"stable_audio_local", "stable_audio_runpod"}


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


def test_failed_job_can_be_retried_with_the_same_params(monkeypatch):
    started: list[str] = []

    async def create_failed_job() -> str:
        async with session_scope() as session:
            job = Job(
                type="generate_tracks",
                status="failed",
                params={"prompts": [{"title": "Again", "prompt": "warm", "duration": 180}]},
                error="worker crashed",
            )
            session.add(job)
            await session.commit()
            await session.refresh(job)
            return job.id

    monkeypatch.setattr(
        "not_studio.routers.jobs.start_job_task", lambda job_id, runner: started.append(job_id)
    )
    with TestClient(app) as client:
        original_id = asyncio.run(create_failed_job())
        response = client.post(f"/api/jobs/{original_id}/retry")

    assert response.status_code == 201
    body = response.json()
    assert body["id"] != original_id
    assert body["status"] == "queued"
    assert body["params"]["prompts"][0]["duration"] == 180
    assert started == [body["id"]]


def test_prompt_kit_exposes_genre_schema_and_review_history():
    async def create_reviewed_tracks() -> None:
        async with session_scope() as session:
            session.add(
                HistoryItem(
                    kind="track",
                    title="Keep This",
                    path="/tmp/liked.flac",
                    meta={
                        "genre": "deep house",
                        "prompt": "warm bass and restrained percussion",
                        "review": {"verdict": "liked", "note": "good restraint"},
                    },
                )
            )
            session.add(
                HistoryItem(
                    kind="track",
                    title="Keep This Too",
                    path="/tmp/liked-too.flac",
                    meta={
                        "genre": "  DEEP   HOUSE ",
                        "prompt": "subtle percussion and warm low end",
                        "review": {"verdict": "liked"},
                    },
                )
            )
            session.add(
                HistoryItem(
                    kind="track",
                    title="Not This",
                    path="/tmp/disliked.flac",
                    meta={
                        "genre": "festival EDM",
                        "prompt": "huge drops and bright supersaws",
                        "review": {"verdict": "disliked"},
                    },
                )
            )
            await session.commit()

    with TestClient(app) as client:
        asyncio.run(create_reviewed_tracks())
        response = client.get("/api/studio/prompt-kit")

    assert response.status_code == 200
    body = response.json()
    required = body["output_schema"]["items"]["required"]
    assert "genre" in required
    assert body["taste_profile"]["liked_genres"] == ["deep house"]
    assert body["taste_profile"]["disliked_genres"] == ["festival edm"]
    assert "liked_count" not in body["taste_profile"]
    assert "disliked_count" not in body["taste_profile"]
    assert any(item["genre"] == "deep house" for item in body["taste_profile"]["liked_examples"])


def test_video_request_persists_only_track_and_video_decisions(monkeypatch):
    monkeypatch.setattr("not_studio.tasks.submit.start_job_task", lambda job_id, runner: None)
    background_id = "a" * 32
    (get_settings().video_backgrounds_dir / background_id).write_bytes(b"video")
    with TestClient(app) as client:
        response = client.post(
            "/api/studio/videos",
            json={
                "item_ids": ["track-id"],
                "background_id": background_id,
            },
        )

    assert response.status_code == 201
    assert response.json()["params"] == {
        "item_ids": ["track-id"],
        "background_id": background_id,
    }


def test_video_request_rejects_manual_render_controls(monkeypatch):
    monkeypatch.setattr("not_studio.tasks.submit.start_job_task", lambda job_id, runner: None)
    background_id = "b" * 32
    (get_settings().video_backgrounds_dir / background_id).write_bytes(b"video")
    with TestClient(app) as client:
        response = client.post(
            "/api/studio/videos",
            json={
                "item_ids": ["track-id"],
                "background_id": background_id,
                "visualizer": "waves",
                "resolution": "2160p",
                "crossfade_seconds": 4,
                "title": "Manual title",
            },
        )

    assert response.status_code == 422
    assert {error["loc"][-1] for error in response.json()["detail"]} == {
        "visualizer",
        "resolution",
        "crossfade_seconds",
        "title",
    }


def test_uploaded_video_background_is_inspected_and_attached_to_render_job(monkeypatch):
    monkeypatch.setattr("not_studio.tasks.submit.start_job_task", lambda job_id, runner: None)
    monkeypatch.setattr(
        "not_studio.video_export.validate_video_input",
        AsyncMock(return_value=None),
    )

    with TestClient(app) as client:
        uploaded = client.post(
            "/api/studio/video-backgrounds",
            files={"file": ("generated-loop.mkv", b"fake-matroska", "video/x-matroska")},
        )
        assert uploaded.status_code == 201
        background = uploaded.json()
        response = client.post(
            "/api/studio/videos",
            json={"item_ids": ["track-id"], "background_id": background["id"]},
        )

    assert background["filename"] == "generated-loop.mkv"
    assert (
        get_settings().video_backgrounds_dir / background["id"]
    ).read_bytes() == b"fake-matroska"
    assert response.status_code == 201
    assert response.json()["params"]["background_id"] == background["id"]


def test_video_request_rejects_missing_uploaded_background(monkeypatch):
    monkeypatch.setattr("not_studio.tasks.submit.start_job_task", lambda job_id, runner: None)
    with TestClient(app) as client:
        response = client.post(
            "/api/studio/videos",
            json={"item_ids": ["track-id"], "background_id": "0" * 32},
        )

    assert response.status_code == 404
    assert response.json()["detail"] == "Uploaded video background not found"


def test_video_request_requires_a_video_decision(monkeypatch):
    monkeypatch.setattr("not_studio.tasks.submit.start_job_task", lambda job_id, runner: None)
    with TestClient(app) as client:
        response = client.post("/api/studio/videos", json={"item_ids": ["track-id"]})

    assert response.status_code == 422
