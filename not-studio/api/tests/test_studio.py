"""Studio track-generation progress and API workflow behavior."""

import asyncio
import io
import json
import zipfile

import httpx
import numpy as np
import soundfile as sf

from not_studio.backends import runpod_stable_audio
from not_studio.backends import stable_audio
from not_studio.config import get_settings
from not_studio.db import session_scope
from not_studio.models import HistoryItem, Job
from not_studio.routers.studio import build_album_prompts
from not_studio.schemas import GenerateAlbumRequest
from not_studio.tasks import jobs as jobs_module
from not_studio.main import app
from starlette.testclient import TestClient


def test_generate_batch_reports_per_track_progress(tmp_path, monkeypatch):
    prompts = [
        {"title": "Track One", "prompt": "warm pads", "duration": 5},
        {"title": "Track Two", "prompt": "deep bass", "duration": 5},
    ]

    monkeypatch.setattr(stable_audio, "_resolve_model_name", lambda requested: requested)
    monkeypatch.setattr(stable_audio, "_load_model", lambda model_name: object())
    monkeypatch.setattr(
        stable_audio,
        "_generate_audio_array",
        lambda model, prompt, duration, output_rate: np.zeros((output_rate, 2)),
    )
    monkeypatch.setattr(
        stable_audio.dsp,
        "write_audio_file",
        lambda path, audio, sample_rate, **kwargs: path.write_bytes(b"stub"),
    )

    updates: list[tuple[float, str]] = []
    produced = stable_audio.generate_batch(
        prompts,
        sample_rate=44100,
        model="medium",
        out_dir=tmp_path / "out",
        on_progress=lambda frac, msg: updates.append((round(frac, 3), msg)),
    )

    assert len(produced) == 2
    assert all(path.exists() for _, path in produced)
    messages = [m for _, m in updates]
    assert any("Loading model" in m for m in messages)
    assert any("Rendering 1/2: Track One" in m for m in messages)
    assert any("1/2" in m for m in messages) and any("2/2" in m for m in messages)
    # progress is monotonic and ends near-complete (before the import/persist step)
    fractions = [f for f, _ in updates]
    assert fractions == sorted(fractions)
    assert fractions[-1] >= 0.9


def test_local_stable_audio_always_resolves_to_medium():
    assert stable_audio._resolve_model_name("auto") == "medium"
    assert stable_audio._resolve_model_name("anything-else") == "medium"


def test_local_stable_audio_preload_returns_serializable_readiness(monkeypatch):
    class Model:
        device = "mps"

    monkeypatch.setattr(stable_audio, "_load_model", lambda model_name: Model())

    assert stable_audio.preload_model("anything") == {
        "status": "ready",
        "provider": "stable_audio_local",
        "model": "medium",
        "device": "mps",
    }


def test_generate_batch_honors_cancellation(tmp_path, monkeypatch):
    monkeypatch.setattr(stable_audio, "_resolve_model_name", lambda requested: requested)
    monkeypatch.setattr(stable_audio, "_load_model", lambda model_name: object())

    try:
        stable_audio.generate_batch(
            [{"title": "x", "prompt": "y", "duration": 5}],
            sample_rate=44100,
            model="medium",
            out_dir=tmp_path / "out",
            should_cancel=lambda: True,
        )
    except RuntimeError as exc:
        assert "cancelled" in str(exc)
    else:
        raise AssertionError("expected RuntimeError on cancellation")


def test_generate_audio_grows_model_buffer_past_120_seconds(monkeypatch):
    import torch

    calls = {}

    class Inner:
        sample_rate = 100

    class Model:
        model = Inner()

        def generate(self, **kwargs):
            calls.update(kwargs)
            return torch.zeros((1, 2, int(kwargs["duration"] * 100)))

    monkeypatch.setattr("torchaudio.functional.resample", lambda audio, source, target: audio)
    monkeypatch.setattr(
        stable_audio.dsp, "normalize_loudness_safely", lambda data, *args, **kwargs: data
    )
    audio = stable_audio._generate_audio_array(Model(), "long track", 180, 100)

    assert calls["sample_size"] > 180 * 100
    assert audio.shape == (180 * 100, 2)


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
        duration_variation_percent=20,
        album_title="Late Roads",
    )

    prompts = build_album_prompts(payload)

    assert len(prompts) == 3
    assert prompts[0]["title"] == "Late Roads 01"
    assert prompts[0]["genre"] == "deep house"
    assert [p["duration"] for p in prompts] == [96.0, 120.0, 144.0]
    assert prompts[0]["target_duration"] == 120
    assert prompts[0]["duration_variation_percent"] == 20
    assert prompts[0]["mood"] == "night drive"
    assert prompts[0]["styles"] == ["deep house", "synthwave"]
    assert "night drive mood" in prompts[0]["prompt"]
    assert "deep house, synthwave" in prompts[0]["prompt"]


def test_prompt_plan_generation_persists_album_and_artwork_context(monkeypatch):
    monkeypatch.setattr("not_studio.tasks.submit.start_job_task", lambda job_id, runner: None)
    payload = {
        "album_title": "City Signals",
        "notes": "Starts restrained and becomes brighter near the end.",
        "artwork_prompt": "Square night city cover, violet glass, no text or logo.",
        "prompts": [
            {
                "title": "Last Train",
                "genre": "ambient techno",
                "prompt": "Muted pulse, glass pads, soft sub bass, instrumental.",
                "duration": 180,
                "notes": "A sparse opening track.",
                "artwork_prompt": "Empty night platform, violet glass, no text.",
            }
        ],
        "provider": "stable_audio_local",
    }

    with TestClient(app) as client:
        response = client.post("/api/studio/generate", json=payload)

    assert response.status_code == 201
    params = response.json()["params"]
    assert params["album"] == {
        "title": "City Signals",
        "notes": "Starts restrained and becomes brighter near the end.",
        "artwork_prompt": "Square night city cover, violet glass, no text or logo.",
        "track_count": 1,
    }
    assert params["prompts"] == payload["prompts"]


def test_prompt_plan_generation_rejects_legacy_top_level_list():
    with TestClient(app) as client:
        response = client.post(
            "/api/studio/generate",
            json=[
                {
                    "title": "Legacy",
                    "genre": "ambient",
                    "prompt": "Old top-level list",
                    "duration": 180,
                }
            ],
        )

    assert response.status_code == 422


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


def test_track_album_assignment_moves_and_unfiles_track():
    async def create_track() -> str:
        async with session_scope() as session:
            item = HistoryItem(
                kind="track",
                title="Album Candidate",
                path="/tmp/album-candidate.flac",
                meta={"review": {"verdict": "liked"}},
            )
            session.add(item)
            await session.commit()
            await session.refresh(item)
            return item.id

    with TestClient(app) as client:
        item_id = asyncio.run(create_track())
        assigned = client.patch(
            f"/api/studio/tracks/{item_id}/album", json={"album_title": "  Night Roads  "}
        )
        moved = client.patch(
            f"/api/studio/tracks/{item_id}/album", json={"album_title": "City Signals"}
        )
        unfiled = client.patch(f"/api/studio/tracks/{item_id}/album", json={"album_title": None})

    assert assigned.status_code == 200
    assert assigned.json()["meta"]["album"]["title"] == "Night Roads"
    assert assigned.json()["meta"]["review"]["verdict"] == "liked"
    assert moved.json()["meta"]["album"]["title"] == "City Signals"
    assert moved.json()["meta"]["album"]["assigned_at"]
    assert "album" not in unfiled.json()["meta"]
    assert unfiled.json()["meta"]["review"]["verdict"] == "liked"


def test_regenerate_track_submits_replacement_with_original_prompt(monkeypatch):
    started: list[str] = []

    async def create_track() -> str:
        async with session_scope() as session:
            item = HistoryItem(
                kind="track",
                title="Try Again",
                path="/tmp/try-again.flac",
                duration_seconds=123,
                meta={
                    "prompt": "warm analog pads and a soft pulse",
                    "genre": "ambient techno",
                    "provider": "stable_audio_local",
                    "album": {"title": "Night Roads"},
                },
            )
            session.add(item)
            await session.commit()
            await session.refresh(item)
            return item.id

    monkeypatch.setattr(
        "not_studio.tasks.submit.start_job_task", lambda job_id, runner: started.append(job_id)
    )
    with TestClient(app) as client:
        item_id = asyncio.run(create_track())
        response = client.post(f"/api/studio/tracks/{item_id}/regenerate")

    assert response.status_code == 201
    job = response.json()
    assert job["params"]["replacement_item_id"] == item_id
    assert job["params"]["prompts"] == [
        {
            "title": "Try Again",
            "genre": "ambient techno",
            "prompt": "warm analog pads and a soft pulse",
            "duration": 123.0,
        }
    ]
    assert started == [job["id"]]


def test_track_artwork_is_embedded_and_served(tmp_path):
    track_path = tmp_path / "artwork-track.flac"
    sf.write(track_path, np.zeros((441, 2)), 44100)
    png = b"\x89PNG\r\n\x1a\ncover-bytes"

    async def create_track() -> str:
        async with session_scope() as session:
            item = HistoryItem(kind="track", title="Artwork Track", path=str(track_path))
            session.add(item)
            await session.commit()
            await session.refresh(item)
            return item.id

    with TestClient(app) as client:
        item_id = asyncio.run(create_track())
        uploaded = client.post(
            f"/api/studio/tracks/{item_id}/artwork",
            files={"file": ("cover.png", png, "image/png")},
        )
        artwork = client.get(f"/api/studio/tracks/{item_id}/artwork")
        download = client.get(f"/api/history/{item_id}/audio")

    assert uploaded.status_code == 200
    assert uploaded.json()["meta"]["artwork"]["mime"] == "image/png"
    assert artwork.status_code == 200
    assert artwork.headers["content-type"] == "image/png"
    assert artwork.content == png
    assert "Artwork%20Track.flac" in download.headers["content-disposition"]


def test_copy_flac_pictures_keeps_artwork_on_regenerated_audio(tmp_path):
    from mutagen.flac import FLAC, Picture

    source = tmp_path / "source.flac"
    destination = tmp_path / "destination.flac"
    sf.write(source, np.zeros((441, 2)), 44100)
    sf.write(destination, np.zeros((882, 2)), 44100)
    source_audio = FLAC(source)
    picture = Picture()
    picture.mime = "image/png"
    picture.data = b"cover"
    source_audio.add_picture(picture)
    source_audio.save()

    from not_studio.audio.dsp import copy_flac_pictures

    copy_flac_pictures(source, destination)

    assert FLAC(destination).pictures[0].data == b"cover"


async def test_regeneration_replaces_audio_but_keeps_item_and_artwork(tmp_path, monkeypatch):
    from mutagen.flac import FLAC, Picture

    old_path = tmp_path / "old.flac"
    new_path = tmp_path / "new.flac"
    sf.write(old_path, np.zeros((441, 2)), 44100)
    sf.write(new_path, np.zeros((882, 2)), 44100)
    old_audio = FLAC(old_path)
    picture = Picture()
    picture.mime = "image/png"
    picture.data = b"preserved-cover"
    old_audio.add_picture(picture)
    old_audio.save()

    async with session_scope() as session:
        item = HistoryItem(
            kind="track",
            title="Replace Me",
            path=str(old_path),
            meta={
                "prompt": "same prompt",
                "genre": "ambient",
                "artwork": {"mime": "image/png", "updated_at": "now"},
                "review": {"verdict": "liked"},
            },
        )
        session.add(item)
        await session.commit()
        await session.refresh(item)
        item_id = item.id
        job = Job(
            type="generate_tracks",
            status="queued",
            params={
                "prompts": [
                    {
                        "title": "Replace Me",
                        "prompt": "same prompt",
                        "genre": "ambient",
                        "duration": 15,
                        "notes": "Replacement context",
                        "artwork_prompt": "Quiet violet field, no text",
                    }
                ],
                "provider": "stable_audio_local",
                "replacement_item_id": item_id,
            },
        )
        session.add(job)
        await session.commit()
        await session.refresh(job)
        job_id = job.id

    async def render(*args, **kwargs):
        return [
            (
                {
                    "title": "Replace Me",
                    "prompt": "same prompt",
                    "genre": "ambient",
                    "duration": 15,
                    "notes": "Replacement context",
                    "artwork_prompt": "Quiet violet field, no text",
                },
                str(new_path),
            )
        ]

    monkeypatch.setattr(jobs_module, "run_in_reusable_process", render)
    result = await jobs_module.generate_tracks_job(job_id)

    async with session_scope() as session:
        replaced = await session.get(HistoryItem, item_id)
        completed_job = await session.get(Job, job_id)

    assert result["track_ids"] == [item_id]
    assert replaced is not None
    assert replaced.path == str(new_path)
    assert replaced.meta["review"]["verdict"] == "unreviewed"
    assert replaced.meta["notes"] == "Replacement context"
    assert replaced.meta["artwork_prompt"] == "Quiet violet field, no text"
    assert not old_path.exists()
    assert FLAC(new_path).pictures[0].data == b"preserved-cover"
    assert completed_job is not None and completed_job.status == "completed"


def test_album_export_downloads_ordered_tagged_flacs_and_cue(tmp_path):
    from mutagen.flac import FLAC, Picture

    first_path = tmp_path / "first.flac"
    second_path = tmp_path / "second.flac"
    sf.write(first_path, np.zeros((441, 2)), 44100)
    sf.write(second_path, np.zeros((882, 2)), 44100)
    first_audio = FLAC(first_path)
    picture = Picture()
    picture.mime = "image/png"
    picture.data = b"first-cover"
    first_audio.add_picture(picture)
    first_audio.save()

    async def create_tracks() -> tuple[str, str]:
        async with session_scope() as session:
            first = HistoryItem(kind="track", title="Opening / Light", path=str(first_path))
            second = HistoryItem(kind="track", title="Night Drive", path=str(second_path))
            session.add(first)
            session.add(second)
            await session.commit()
            await session.refresh(first)
            await session.refresh(second)
            return first.id, second.id

    with TestClient(app) as client:
        first_id, second_id = asyncio.run(create_tracks())
        response = client.post(
            "/api/studio/albums/export",
            json={"title": "City Signals", "item_ids": [second_id, first_id]},
        )

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/zip"
    assert "City%20Signals.zip" in response.headers["content-disposition"]
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        assert archive.namelist() == [
            "01 - Night Drive.flac",
            "02 - Opening - Light.flac",
            "City Signals.cue",
        ]
        cue = archive.read("City Signals.cue").decode()
        assert 'TITLE "City Signals"' in cue
        assert 'FILE "01 - Night Drive.flac" WAVE' in cue
        assert "  TRACK 01 AUDIO" in cue
        assert 'FILE "02 - Opening - Light.flac" WAVE' in cue
        assert "  TRACK 02 AUDIO" in cue
        archive.extract("01 - Night Drive.flac", tmp_path / "extracted")
        archive.extract("02 - Opening - Light.flac", tmp_path / "extracted")

    first_export = FLAC(tmp_path / "extracted" / "01 - Night Drive.flac")
    second_export = FLAC(tmp_path / "extracted" / "02 - Opening - Light.flac")
    assert first_export["album"] == ["City Signals"]
    assert first_export["tracknumber"] == ["1/2"]
    assert second_export["tracknumber"] == ["2/2"]
    assert second_export.pictures[0].data == b"first-cover"
    assert "album" not in FLAC(first_path)
