"""Studio track-generation progress and API workflow behavior."""

import asyncio
import io
import sys
import zipfile
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import soundfile as sf
from PIL import Image

from not_studio.album_export import create_album_archive, cue_duration
from not_studio.backends import ace_step
from not_studio.db import session_scope
from not_studio.models import HistoryItem, Job
from not_studio.routers.studio import build_album_prompts
from not_studio.schemas import GenerateAlbumRequest
from not_studio.tasks import jobs as jobs_module
from not_studio.main import app
from starlette.testclient import TestClient


def test_cue_duration_uses_zero_padded_hours_minutes_and_seconds():
    assert cue_duration(3661.6) == "01:01:02"


def test_generate_batch_reports_per_track_progress(tmp_path, monkeypatch):
    prompts = [
        {"title": "Track One", "prompt": "warm pads", "duration": 5},
        {"title": "Track Two", "prompt": "deep bass", "duration": 5},
    ]

    monkeypatch.setattr(ace_step, "_load_model", lambda model_name: object())
    monkeypatch.setattr(
        ace_step,
        "_load_language_model",
        lambda model: (object(), "acestep-5Hz-lm-0.6B", "pt"),
    )
    monkeypatch.setattr(
        ace_step,
        "_generate_audio_file",
        lambda model, language_model, request, path, **kwargs: path.write_bytes(b"stub"),
    )
    monkeypatch.setattr(
        ace_step.dsp,
        "tag_flac",
        lambda path, **kwargs: None,
    )

    updates: list[tuple[float, str]] = []
    produced = ace_step.generate_batch(
        prompts,
        sample_rate=44100,
        channels=2,
        model="ACE-Step 1.5",
        out_dir=tmp_path / "out",
        on_progress=lambda frac, msg: updates.append((round(frac, 3), msg)),
    )

    assert len(produced) == 2
    assert all(path.exists() for _, path in produced)
    messages = [m for _, m in updates]
    assert any("Loading models" in m for m in messages)
    assert any("acestep-5Hz-lm-0.6B" in m for m in messages)
    assert any("Rendering 1/2: Track One" in m for m in messages)
    assert any("1/2" in m for m in messages) and any("2/2" in m for m in messages)
    # progress is monotonic and ends near-complete (before the import/persist step)
    fractions = [f for f, _ in updates]
    assert fractions == sorted(fractions)
    assert fractions[-1] >= 0.9


def test_local_ace_step_preload_returns_serializable_readiness(monkeypatch):
    class Model:
        device = "mps"

    monkeypatch.setattr(ace_step, "_load_model", lambda model_name: Model())
    monkeypatch.setattr(
        ace_step,
        "_load_language_model",
        lambda model: (object(), "acestep-5Hz-lm-0.6B", "pt"),
    )

    assert ace_step.preload_model() == {
        "status": "ready",
        "provider": "ace_step_local",
        "model": "ACE-Step 1.5",
        "checkpoint": "acestep-v15-sft",
        "device": "mps",
        "language_model": "acestep-5Hz-lm-0.6B",
        "language_model_backend": "pt",
    }


def test_language_model_selection_matches_accelerator():
    assert ace_step._language_model_config("mps") == (
        "acestep-5Hz-lm-0.6B",
        "pt",
    )
    assert ace_step._language_model_config("cuda:0") == (
        "acestep-5Hz-lm-1.7B",
        "vllm",
    )
    assert ace_step._language_model_config("cpu") == (
        "acestep-5Hz-lm-0.6B",
        "pt",
    )


def test_music_model_loads_high_quality_sft_checkpoint(monkeypatch):
    calls = {}

    class Handler:
        def initialize_service(self, **kwargs):
            calls.update(kwargs)
            return "ready", True

    monkeypatch.setitem(sys.modules, "acestep.handler", SimpleNamespace(AceStepHandler=Handler))
    ace_step._MODELS.clear()
    try:
        ace_step._load_model()
    finally:
        ace_step._MODELS.clear()

    assert calls["config_path"] == "acestep-v15-sft"
    assert calls["device"] == "auto"


def test_music_model_resumes_incomplete_sft_checkpoint(tmp_path, monkeypatch):
    calls = {}
    (tmp_path / "acestep-v15-sft").mkdir()

    downloader_module = SimpleNamespace(
        get_checkpoints_dir=lambda: tmp_path,
        check_model_exists=lambda model_name, checkpoints_dir: False,
        download_submodel=lambda model_name, **kwargs: (
            calls.update(model_name=model_name, **kwargs) or (True, "downloaded")
        ),
    )

    class Handler:
        def initialize_service(self, **kwargs):
            return "ready", True

    monkeypatch.setitem(sys.modules, "acestep.model_downloader", downloader_module)
    monkeypatch.setitem(sys.modules, "acestep.handler", SimpleNamespace(AceStepHandler=Handler))
    ace_step._MODELS.clear()
    try:
        ace_step._load_model()
    finally:
        ace_step._MODELS.clear()

    assert calls == {
        "model_name": "acestep-v15-sft",
        "checkpoints_dir": tmp_path,
        "force": True,
    }


def test_sft_generation_uses_full_diffusion_and_cfg(tmp_path, monkeypatch):
    calls = {}

    def generate_music(model, language_model, params, config, save_dir):
        calls.update(params=params, config=config)
        return SimpleNamespace(success=True)

    inference_module = SimpleNamespace(
        GenerationParams=lambda **kwargs: SimpleNamespace(**kwargs),
        GenerationConfig=lambda **kwargs: SimpleNamespace(**kwargs),
        generate_music=generate_music,
    )
    monkeypatch.setitem(sys.modules, "acestep.inference", inference_module)

    result = ace_step._run_generation(
        object(),
        object(),
        ace_step.GenerationInput(prompt="detailed composition", duration=180),
        tmp_path,
    )

    assert result.success is True
    assert calls["params"].inference_steps == 50
    assert calls["params"].guidance_scale == 7.0
    assert calls["params"].shift == 1.0
    assert calls["params"].thinking is True


def test_generate_batch_honors_cancellation(tmp_path, monkeypatch):
    monkeypatch.setattr(ace_step, "_load_model", lambda model_name: object())
    monkeypatch.setattr(
        ace_step,
        "_load_language_model",
        lambda model: (object(), "acestep-5Hz-lm-0.6B", "pt"),
    )

    try:
        ace_step.generate_batch(
            [{"title": "x", "prompt": "y", "duration": 5}],
            sample_rate=44100,
            channels=2,
            model="ACE-Step 1.5",
            out_dir=tmp_path / "out",
            should_cancel=lambda: True,
        )
    except RuntimeError as exc:
        assert "cancelled" in str(exc)
    else:
        raise AssertionError("expected RuntimeError on cancellation")


def test_generate_audio_uses_ace_step_text2music_without_lyrics(tmp_path, monkeypatch):
    calls = {}

    def fake_run_generation(model, language_model, request, save_dir):
        calls.update(
            task=request.task,
            lyrics=request.lyrics,
            duration=request.duration,
        )
        path = save_dir / "generated.wav"
        sf.write(path, np.zeros((800, 2)), 8000)
        return SimpleNamespace(success=True, audios=[{"path": str(path)}])

    monkeypatch.setattr(
        ace_step.dsp, "normalize_loudness_safely", lambda data, *args, **kwargs: data
    )
    monkeypatch.setattr(ace_step, "_run_generation", fake_run_generation)
    output = tmp_path / "track.flac"
    ace_step._generate_audio_file(
        object(),
        object(),
        ace_step.GenerationInput(prompt="long track", duration=180),
        output,
        sample_rate=8000,
        channels=2,
    )

    assert calls["task"] == "text2music"
    assert calls["lyrics"] == ""
    assert calls["duration"] == 180
    assert output.is_file()


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
        "provider": "ace_step_local",
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


async def test_prompt_album_data_overrides_plan_album_when_tracks_are_saved(tmp_path, monkeypatch):
    track_path = tmp_path / "custom-album.flac"
    sf.write(track_path, np.zeros((441, 2)), 44100)
    spec = {
        "title": "Standalone Cut",
        "genre": "ambient techno",
        "prompt": "A restrained night pulse",
        "duration": 15,
        "album_title": "Custom Singles",
        "album": {"notes": "A manually grouped release."},
    }

    async with session_scope() as session:
        job = Job(
            type="generate_tracks",
            status="queued",
            params={
                "prompts": [spec],
                "provider": "ace_step_local",
                "album": {"title": "LLM Default", "notes": "Generated plan."},
            },
        )
        session.add(job)
        await session.commit()
        await session.refresh(job)
        job_id = job.id

    async def render(*args, **kwargs):
        return [(spec, str(track_path))]

    monkeypatch.setattr(jobs_module, "run_in_reusable_process", render)
    result = await jobs_module.generate_tracks_job(job_id)

    async with session_scope() as session:
        item = await session.get(HistoryItem, result["track_ids"][0])

    assert item is not None
    assert item.meta["album"] == {
        "title": "Custom Singles",
        "notes": "A manually grouped release.",
    }


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
                    "provider": "ace_step_local",
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
                "provider": "ace_step_local",
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
        cover = io.BytesIO()
        Image.new("RGB", (24, 24), (80, 40, 160)).save(cover, format="JPEG")
        uploaded_cover = client.post(
            "/api/studio/albums/artwork",
            data={"title": "City Signals"},
            files={"file": ("cover.jpg", cover.getvalue(), "image/jpeg")},
        )
        served_cover = client.get("/api/studio/albums/artwork", params={"title": "City Signals"})
        response = client.post(
            "/api/studio/albums/export",
            json={"title": "City Signals", "item_ids": [second_id, first_id]},
        )

    assert uploaded_cover.status_code == 200
    assert served_cover.status_code == 200
    assert served_cover.headers["content-type"] == "image/png"
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/zip"
    assert "City%20Signals.zip" in response.headers["content-disposition"]
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        assert archive.namelist() == [
            "01 - Night Drive.flac",
            "02 - Opening - Light.flac",
            "City Signals.png",
            "City Signals.cue",
        ]
        assert archive.read("City Signals.png").startswith(b"\x89PNG\r\n\x1a\n")
        cue = archive.read("City Signals.cue").decode()
        assert 'TITLE "City Signals"' in cue
        assert 'FILE "01 - Night Drive.flac" WAVE' in cue
        assert "  TRACK 01 AUDIO" in cue
        assert "    INDEX 01 00:00:00\n    DURATION 00:00:00" in cue
        assert 'FILE "02 - Opening - Light.flac" WAVE' in cue
        assert "  TRACK 02 AUDIO" in cue
        assert cue.count("    DURATION 00:00:00") == 2
        archive.extract("01 - Night Drive.flac", tmp_path / "extracted")
        archive.extract("02 - Opening - Light.flac", tmp_path / "extracted")

    first_export = FLAC(tmp_path / "extracted" / "01 - Night Drive.flac")
    second_export = FLAC(tmp_path / "extracted" / "02 - Opening - Light.flac")
    assert first_export["album"] == ["City Signals"]
    assert first_export["artist"] == ["Not Studio"]
    assert len(first_export["date"][0]) == 10
    assert first_export["year"] == [first_export["date"][0][:4]]
    assert first_export["tracknumber"] == ["1/2"]
    assert second_export["tracknumber"] == ["2/2"]
    assert second_export.pictures[0].data.startswith(b"\x89PNG\r\n\x1a\n")
    assert "album" not in FLAC(first_path)


async def test_album_export_adds_track_mp4s_only_when_cover_exists(tmp_path, monkeypatch):
    track_path = tmp_path / "track.flac"
    sf.write(track_path, np.zeros((441, 2)), 44100)
    item = HistoryItem(kind="track", title="Covered Track", path=str(track_path))
    cover_path = tmp_path / "cover.png"
    Image.new("RGB", (24, 24), (20, 30, 40)).save(cover_path)
    rendered: list[str] = []

    async def render(audio_path, cover, output_path):
        rendered.append(Path(output_path).name)
        Path(output_path).write_bytes(b"mp4")

    monkeypatch.setattr("not_studio.video_export.render_track_video", render)
    covered_archive = tmp_path / "covered.zip"
    await create_album_archive(
        "Covered",
        [item],
        covered_archive,
        cover_path=cover_path,
        include_track_videos=True,
    )
    without_cover_archive = tmp_path / "without-cover.zip"
    await create_album_archive(
        "No Cover",
        [item],
        without_cover_archive,
        include_track_videos=True,
    )

    assert rendered == ["01 - Covered Track.mp4"]
    with zipfile.ZipFile(covered_archive) as archive:
        assert "01 - Covered Track.mp4" in archive.namelist()
    with zipfile.ZipFile(without_cover_archive) as archive:
        assert not any(name.endswith(".mp4") for name in archive.namelist())
