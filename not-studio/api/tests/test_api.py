"""API surface for the Not Studio workflow."""

from starlette.testclient import TestClient

from not_studio.main import app


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
