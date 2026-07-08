"""Studio track-generation progress: stream main.py output -> per-track callbacks."""

import asyncio
import json
from pathlib import Path

import httpx

from not_studio.backends import runpod_stable_audio
from not_studio.backends import stable_audio
from not_studio.config import get_settings
from not_studio.db import session_scope
from not_studio.models import HistoryItem
from not_studio.routers.studio import build_album_prompts
from not_studio.schemas import GenerateAlbumRequest
from not_studio.main import app
from starlette.testclient import TestClient


def test_generate_batch_reports_per_track_progress(tmp_path, monkeypatch):
    prompts = [
        {"title": "Track One", "prompt": "warm pads", "duration": 5},
        {"title": "Track Two", "prompt": "deep bass", "duration": 5},
    ]

    def fake_stream(script, args, on_line, timeout=None):
        # Emulate main.py --prompts: announce model load, then a line per track.
        on_line("Loading model: medium")
        out_dir = Path(args[args.index("-o") + 1])
        for spec in prompts:
            flac = out_dir / f"{stable_audio._slugify(spec['title'])}.flac"
            flac.write_bytes(b"stub")
            on_line(f"Saved: {flac}")
        return 0

    monkeypatch.setattr(stable_audio, "run_engine_cli_streaming", fake_stream)

    updates: list[tuple[float, str]] = []
    produced = stable_audio.generate_batch(
        prompts,
        sample_rate=44100,
        model="medium",
        out_dir=tmp_path / "out",
        on_progress=lambda frac, msg: updates.append((round(frac, 3), msg)),
    )

    assert len(produced) == 2
    messages = [m for _, m in updates]
    assert any("Loading model" in m for m in messages)
    assert any("1/2" in m for m in messages) and any("2/2" in m for m in messages)
    # progress is monotonic and ends near-complete (before the import/persist step)
    fractions = [f for f, _ in updates]
    assert fractions == sorted(fractions)
    assert fractions[-1] >= 0.9


def test_generate_batch_raises_with_output_tail(tmp_path, monkeypatch):
    def fake_stream(script, args, on_line, timeout=None):
        on_line("Traceback (most recent call last):")
        on_line("RuntimeError: CUDA out of memory")
        return 1

    monkeypatch.setattr(stable_audio, "run_engine_cli_streaming", fake_stream)

    try:
        stable_audio.generate_batch(
            [{"title": "x", "prompt": "y", "duration": 5}],
            sample_rate=44100,
            model="medium",
            out_dir=tmp_path / "out",
        )
    except RuntimeError as exc:
        assert "exit 1" in str(exc) and "CUDA out of memory" in str(exc)
    else:
        raise AssertionError("expected RuntimeError on non-zero exit")


def test_runpod_generate_batch_sends_one_request_and_writes_tracks(tmp_path, monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "runpod_endpoint_id", "endpoint-123")
    monkeypatch.setattr(settings, "runpod_api_key", "secret")
    monkeypatch.setattr(settings, "runpod_volume_id", "volume-123")
    monkeypatch.setattr(settings, "runpod_s3_endpoint_url", "https://s3api-eu.test")
    monkeypatch.setattr(settings, "runpod_s3_access_key_id", "access")
    monkeypatch.setattr(settings, "runpod_s3_secret_access_key", "storage-secret")
    monkeypatch.setattr(settings, "runpod_s3_region", "EU-TEST-1")
    prompts = [
        {"title": "Track One", "prompt": "warm pads", "duration": 30},
        {"title": "Track Two", "prompt": "deep bass", "duration": 45},
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v2/endpoint-123/runsync"
        assert request.headers["Authorization"] == "Bearer secret"
        payload = json.loads(request.content)
        assert payload["input"]["prompts"] == prompts
        assert payload["input"]["sample_rate"] == 44100
        return httpx.Response(
            200,
            json={
                "status": "COMPLETED",
                "output": {
                    "tracks": [
                        {"storage_key": "not-studio/job/01-track-one.flac"},
                        {"storage_key": "not-studio/job/02-track-two.flac"},
                    ]
                },
            },
        )

    class FakeStorage:
        objects = {
            "not-studio/job/01-track-one.flac": b"first-flac",
            "not-studio/job/02-track-two.flac": b"second-flac",
        }

        def download_fileobj(self, bucket, key, output):
            assert bucket == "volume-123"
            output.write(self.objects[key])

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        produced = runpod_stable_audio.generate_batch(
            prompts,
            sample_rate=44100,
            model="medium",
            out_dir=tmp_path,
            client=client,
            storage_client=FakeStorage(),
        )

    assert [path.read_bytes() for _, path in produced] == [b"first-flac", b"second-flac"]


def test_build_album_prompts_from_music_controls():
    payload = GenerateAlbumRequest(
        mood="night drive",
        styles=["deep house", "synthwave"],
        track_count=3,
        duration=120,
        album_title="Late Roads",
    )

    prompts = build_album_prompts(payload)

    assert len(prompts) == 3
    assert prompts[0]["title"] == "Late Roads 01"
    assert prompts[0]["mood"] == "night drive"
    assert prompts[0]["styles"] == ["deep house", "synthwave"]
    assert "night drive mood" in prompts[0]["prompt"]
    assert "deep house, synthwave" in prompts[0]["prompt"]


def test_track_review_updates_history_item_metadata():
    async def create_track() -> str:
        async with session_scope() as session:
            item = HistoryItem(
                kind="track",
                title="Candidate",
                path="/tmp/candidate.flac",
                meta={"review": {"verdict": "unreviewed"}},
            )
            session.add(item)
            await session.commit()
            await session.refresh(item)
            return item.id

    with TestClient(app) as client:
        item_id = asyncio.run(create_track())
        resp = client.patch(f"/api/studio/tracks/{item_id}/review", json={"verdict": "liked"})

    assert resp.status_code == 200
    body = resp.json()
    assert body["meta"]["review"]["verdict"] == "liked"
    assert body["meta"]["review"]["reviewed_at"]
