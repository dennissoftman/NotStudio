import asyncio
import io

from PIL import Image
from starlette.testclient import TestClient

from not_studio.backends.planner import requested_track_count, validate_plan_semantics
from not_studio.db import session_scope
from not_studio.main import app
from not_studio.models import CoverAsset, GenerationRun
from not_studio.schemas import PromptPlan, PromptSpec
from not_studio.tasks.artwork import compose_cover_prompt, select_cover


def valid_plan(track_count: int = 2) -> dict:
    return {
        "album_title": "Empty Signals",
        "summary": "A city becomes quiet before dawn.",
        "visual_direction": {
            "palette": ["violet", "amber"],
            "motifs": ["rail lines"],
            "style": "minimal cinematic abstraction",
            "avoid": ["people"],
        },
        "artwork_prompt": "Empty railway geometry at dawn, square cover, no text.",
        "prompts": [
            {
                "title": f"Signal {index}",
                "genre": "ambient techno",
                "prompt": "Instrumental ambient techno with analog pads, restrained percussion, and no vocals.",
                "duration": 60,
                "artwork_prompt": f"Abstract railway signal {index}, square composition, no text.",
            }
            for index in range(1, track_count + 1)
        ],
    }


def test_track_count_is_read_from_natural_language():
    assert requested_track_count("Make a 7-track album") == 7
    assert requested_track_count("I want seven tracks about winter") == 7
    assert requested_track_count("Write five songs about winter") == 5
    assert requested_track_count("A brief ambient record") is None


def test_semantic_validation_enforces_count_unique_titles_and_artwork():
    plan = PromptPlan.model_validate(valid_plan(2))
    assert validate_plan_semantics(plan, "A two-track record") == []
    broken = PromptPlan(
        album_title="Broken",
        artwork_prompt="cover",
        prompts=[
            PromptSpec(
                title="Same",
                genre="ambient",
                prompt="instrumental detailed ambient arrangement with pads and slowly changing harmonic texture",
                duration=60,
                artwork_prompt="cover one",
            ),
            PromptSpec(
                title="Same",
                genre="ambient",
                prompt="instrumental detailed ambient arrangement with pads and slowly changing harmonic texture",
                duration=60,
                artwork_prompt="cover two",
            ),
        ],
    )
    assert "track titles must be unique" in validate_plan_semantics(broken, "two tracks")


def test_cover_prompt_combines_shared_direction_and_safety_constraints():
    prompt = compose_cover_prompt(
        "An empty platform at dawn",
        artwork_guidance="Use soft film grain",
        visual_direction={
            "style": "cinematic abstraction",
            "palette": ["violet", "amber"],
            "motifs": ["rail lines"],
            "avoid": ["people"],
        },
    )
    assert "cinematic abstraction" in prompt
    assert "soft film grain" in prompt
    assert "text" in prompt and "watermark" in prompt


def test_style_reference_upload_and_generation_run_lifecycle(monkeypatch):
    started: list[tuple[str, str]] = []
    monkeypatch.setattr(
        "not_studio.tasks.submit.start_job_task",
        lambda job_id, runner: started.append((job_id, runner.__name__)),
    )
    image = io.BytesIO()
    Image.new("RGB", (40, 30), (30, 20, 80)).save(image, format="PNG")

    with TestClient(app) as client:
        assert client.get("/api/studio/covers?owner_type=track").status_code == 200
        assert client.get("/api/studio/covers?owner_type=invalid").status_code == 422
        reference = client.post(
            "/api/studio/style-references",
            files={"file": ("style.png", image.getvalue(), "image/png")},
        )
        assert reference.status_code == 201
        reference_id = reference.json()["id"]
        assert client.get(f"/api/studio/style-references/{reference_id}/image").status_code == 200

        created = client.post(
            "/api/studio/album-runs",
            json={
                "brief": "A two-track ambient album about an empty city at dawn.",
                "artwork_guidance": "Minimal abstraction",
                "style_reference_id": reference_id,
                "cover_output_size": 2048,
                "auto_start": False,
            },
        )
        assert created.status_code == 201
        run_id = created.json()["id"]
        assert created.json()["plan_job_id"]
        assert started[-1][1] == "plan_album_job"

        async def mark_plan_ready() -> None:
            async with session_scope() as session:
                run = await session.get(GenerationRun, run_id)
                run.status = "awaiting_review"
                run.stage = "awaiting_review"
                session.add(run)
                await session.commit()

        asyncio.run(mark_plan_ready())

        updated = client.patch(f"/api/studio/album-runs/{run_id}/plan", json={"plan": valid_plan()})
        assert updated.status_code == 200
        assert updated.json()["status"] == "awaiting_review"

        generated = client.post(
            f"/api/studio/album-runs/{run_id}/generate", json={"generate_covers": True}
        )
        assert generated.status_code == 201
        assert generated.json()["type"] == "generate_album_pipeline"
        assert started[-1][1] == "generate_tracks_job"

        album_id = client.get(f"/api/studio/album-runs/{run_id}").json()["album_id"]
        missing_reference = client.post(
            f"/api/studio/albums/{album_id}/covers/generate",
            json={"style_reference_id": "missing-reference", "reference_mode": "loose"},
        )
        assert missing_reference.status_code == 404
        reference_disabled = client.post(
            f"/api/studio/albums/{album_id}/covers/generate",
            json={"style_reference_id": "missing-reference", "reference_mode": "off"},
        )
        assert reference_disabled.status_code == 201


async def test_selecting_cover_keeps_versions_and_updates_selected_pointer(tmp_path):
    first_path = tmp_path / "first.png"
    second_path = tmp_path / "second.png"
    first_path.write_bytes(b"first")
    second_path.write_bytes(b"second")
    async with session_scope() as session:
        first = CoverAsset(
            owner_type="album",
            owner_id="album-selection-test",
            version=1,
            status="ready",
            selected=True,
            path=str(first_path),
        )
        second = CoverAsset(
            owner_type="album",
            owner_id="album-selection-test",
            version=2,
            status="ready",
            path=str(second_path),
        )
        session.add(first)
        session.add(second)
        await session.commit()
        await session.refresh(first)
        await session.refresh(second)
        first_id, second_id = first.id, second.id

    selected = await select_cover(second_id)
    assert selected.selected
    async with session_scope() as session:
        assert not (await session.get(CoverAsset, first_id)).selected
        assert (await session.get(CoverAsset, second_id)).selected
