"""API surface + resource CRUD (no Redis; queue reported offline)."""

from starlette.testclient import TestClient

from radio_dashboard.main import app


def test_health_reports_providers():
    with TestClient(app) as client:
        health = client.get("/api/health").json()
        assert health["status"] == "ok"
        assert health["queue"] is False  # no Redis in tests
        providers = {p["provider"]: p for p in health["providers"]}
        assert providers["mock"]["available"] is True


def test_resource_crud_and_buffer_status():
    with TestClient(app) as client:
        music = client.post(
            "/api/backends",
            json={"name": "synth", "kind": "music", "provider": "mock"},
        )
        assert music.status_code == 201

        program = client.post(
            "/api/programs",
            json={
                "name": "Test Mix",
                "config": {
                    "music": {"prompts": ["bed"], "track_seconds": 10},
                    "inserts": [{"kind": "news", "cadence_seconds": 30, "texts": ["hi"]}],
                },
            },
        ).json()
        assert len(program["config"]["inserts"]) == 1

        stream = client.post(
            "/api/streams",
            json={"name": "Chan 1", "program_id": program["id"], "buffer_min_seconds": 900},
        ).json()

        buf = client.get(f"/api/streams/{stream['id']}/buffer").json()
        assert buf["ready_seconds"] == 0.0
        assert buf["min_seconds"] == 900.0
        assert buf["generating"] is False


def test_job_submit_requires_queue():
    with TestClient(app) as client:
        stream = client.post("/api/streams", json={"name": "Chan 2"}).json()
        resp = client.post("/api/jobs", json={"type": "batch", "stream_id": stream["id"]})
        assert resp.status_code == 503  # queue offline without Redis


def test_backend_rejects_unsupported_kind():
    with TestClient(app) as client:
        # stable_audio only supports music, not speech.
        resp = client.post(
            "/api/backends",
            json={"name": "bad", "kind": "speech", "provider": "stable_audio"},
        )
        assert resp.status_code == 400
