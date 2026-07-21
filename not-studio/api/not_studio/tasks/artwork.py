from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from sqlmodel import select

from ..config import get_settings
from ..constants import utcnow
from ..db import session_scope
from ..models import Album, CoverAsset, GenerationRun, HistoryItem, Job, StyleReference
from .jobs import is_job_cancelled, update_job
from .processes import model_process_busy, run_in_model_process


def compose_cover_prompt(
    prompt: str, *, artwork_guidance: str = "", visual_direction: dict[str, Any] | None = None
) -> str:
    pieces = [prompt.strip()]
    direction = visual_direction or {}
    if direction.get("style"):
        pieces.append(f"Shared visual style: {direction['style']}")
    if direction.get("palette"):
        pieces.append("Palette: " + ", ".join(map(str, direction["palette"])))
    if direction.get("motifs"):
        pieces.append("Recurring motifs: " + ", ".join(map(str, direction["motifs"])))
    if artwork_guidance.strip():
        pieces.append("Additional art direction: " + artwork_guidance.strip())
    avoids = [str(value) for value in direction.get("avoid", [])]
    avoids.extend(["text", "lettering", "logo", "watermark", "recognizable brand"])
    pieces.append("Square album artwork. Avoid: " + ", ".join(dict.fromkeys(avoids)))
    return ". ".join(piece.rstrip(". ") for piece in pieces if piece) + "."


async def select_cover(asset_id: str) -> CoverAsset:
    async with session_scope() as session:
        asset = await session.get(CoverAsset, asset_id)
        if asset is None or asset.status != "ready":
            raise RuntimeError("Cover is not ready for selection")
        res = await session.execute(
            select(CoverAsset).where(
                CoverAsset.owner_type == asset.owner_type,
                CoverAsset.owner_id == asset.owner_id,
                CoverAsset.selected.is_(True),
            )
        )
        for current in res.scalars().all():
            current.selected = False
            current.selected_at = None
            session.add(current)
        asset.selected = True
        asset.selected_at = utcnow()
        session.add(asset)
        if asset.owner_type == "track":
            track = await session.get(HistoryItem, asset.owner_id)
            if track:
                meta = dict(track.meta or {})
                meta["cover_asset_id"] = asset.id
                meta["artwork"] = {
                    "mime": asset.mime,
                    "updated_at": asset.selected_at.isoformat(),
                    "generated": True,
                }
                track.meta = meta
                session.add(track)
        await session.commit()
        await session.refresh(asset)
        return asset


async def create_cover_assets(
    *,
    owner_prompts: list[tuple[str, str, str]],
    job_id: str,
    style_reference_id: str | None,
    output_size: int,
    reference_mode: str,
    artwork_guidance: str = "",
    visual_direction: dict[str, Any] | None = None,
    seed: int | None = None,
) -> list[str]:
    ids: list[str] = []
    async with session_scope() as session:
        for owner_type, owner_id, prompt in owner_prompts:
            versions = await session.execute(
                select(CoverAsset).where(
                    CoverAsset.owner_type == owner_type, CoverAsset.owner_id == owner_id
                )
            )
            version = len(versions.scalars().all()) + 1
            asset = CoverAsset(
                owner_type=owner_type,
                owner_id=owner_id,
                version=version,
                status="queued",
                prompt=prompt,
                effective_prompt=compose_cover_prompt(
                    prompt,
                    artwork_guidance=artwork_guidance,
                    visual_direction=visual_direction,
                ),
                style_reference_id=style_reference_id,
                seed=seed,
                job_id=job_id,
                config={"output_size": output_size, "reference_mode": reference_mode},
            )
            session.add(asset)
            await session.commit()
            await session.refresh(asset)
            ids.append(asset.id)
    return ids


def _render_cover_batch(
    job_id: str,
    specs: list[dict[str, Any]],
    generation_size: int,
    default_steps: int,
    model: str,
) -> list[dict[str, Any]]:
    from ..backends.images.flux2_klein import generate_cover

    results: list[dict[str, Any]] = []
    total = len(specs)
    for index, spec in enumerate(specs, start=1):
        if asyncio.run(is_job_cancelled(job_id)):
            raise RuntimeError("Cover generation cancelled")
        asyncio.run(
            update_job(
                job_id,
                progress=0.70 + 0.27 * (index - 1) / max(1, total),
                message=f"Generating cover {index}/{total}",
            )
        )
        try:
            result = generate_cover(
                spec["prompt"],
                Path(spec["output_path"]),
                reference_path=Path(spec["reference_path"]) if spec.get("reference_path") else None,
                reference_mode=spec.get("reference_mode", "loose"),
                generation_size=generation_size,
                output_size=int(spec["output_size"]),
                steps=default_steps,
                seed=spec.get("seed"),
                model=model,
                should_cancel=lambda: asyncio.run(is_job_cancelled(job_id)),
            )
            results.append({"asset_id": spec["asset_id"], "result": result})
        except Exception as exc:  # noqa: BLE001 - preserve partial batch results
            results.append({"asset_id": spec["asset_id"], "error": str(exc)})
    return results


async def render_cover_assets(job_id: str, asset_ids: list[str]) -> tuple[list[str], list[str]]:
    settings = get_settings()
    specs: list[dict[str, Any]] = []
    async with session_scope() as session:
        for asset_id in asset_ids:
            asset = await session.get(CoverAsset, asset_id)
            if asset is None:
                continue
            reference = (
                await session.get(StyleReference, asset.style_reference_id)
                if asset.style_reference_id
                else None
            )
            asset.status = "generating"
            session.add(asset)
            specs.append(
                {
                    "asset_id": asset.id,
                    "prompt": asset.effective_prompt,
                    "output_path": str(settings.cover_dir / f"{asset.id}.png"),
                    "reference_path": reference.path if reference else None,
                    "reference_mode": asset.config.get("reference_mode", "loose"),
                    "output_size": asset.config.get("output_size", settings.cover_output_size),
                    "seed": asset.seed,
                }
            )
        await session.commit()

    if model_process_busy():
        await update_job(job_id, message="Queued for image model")
    results = await run_in_model_process(
        "flux2-klein",
        _render_cover_batch,
        job_id,
        specs,
        settings.cover_generation_size,
        settings.cover_steps,
        settings.image_model,
    )
    if await is_job_cancelled(job_id):
        raise asyncio.CancelledError
    ready: list[str] = []
    failed: list[str] = []
    async with session_scope() as session:
        for entry in results:
            asset = await session.get(CoverAsset, entry["asset_id"])
            if asset is None:
                continue
            if entry.get("error"):
                asset.status = "failed"
                asset.error = entry["error"]
                failed.append(asset.id)
            else:
                result = entry["result"]
                asset.status = "ready"
                asset.path = result["path"]
                asset.width = result["width"]
                asset.height = result["height"]
                asset.size_bytes = result["size_bytes"]
                asset.seed = result["seed"]
                asset.model = result["model"]
                asset.provider = result["provider"]
                asset.config = {**asset.config, **result}
                asset.error = None
                ready.append(asset.id)
            session.add(asset)
        await session.commit()
    for asset_id in ready:
        await select_cover(asset_id)
    return ready, failed


async def generate_covers_job(job_id: str) -> dict[str, Any]:
    await update_job(
        job_id,
        status="in_progress",
        started_at=utcnow(),
        progress=0.05,
        message="Preparing covers",
    )
    async with session_scope() as session:
        job = await session.get(Job, job_id)
        if job is None:
            return {"error": "job row missing"}
        asset_ids = list((job.params or {}).get("asset_ids") or [])
    try:
        ready, failed = await render_cover_assets(job_id, asset_ids)
    except asyncio.CancelledError:
        await update_job(job_id, status="cancelled", message="Cancelled", finished_at=utcnow())
        raise
    except Exception as exc:  # noqa: BLE001
        await update_job(job_id, status="failed", error=str(exc), finished_at=utcnow())
        return {"error": str(exc)}
    await update_job(
        job_id,
        status="completed",
        progress=1.0,
        message=f"Generated {len(ready)} cover(s)" + (f", {len(failed)} failed" if failed else ""),
        result={"cover_ids": ready, "failed_cover_ids": failed},
        finished_at=utcnow(),
    )
    return {"cover_ids": ready, "failed_cover_ids": failed}


async def create_run_cover_assets(
    job_id: str, run_id: str, album_id: str, track_ids: list[str]
) -> list[str]:
    async with session_scope() as session:
        run = await session.get(GenerationRun, run_id)
        album = await session.get(Album, album_id)
        if run is None or album is None or run.plan is None:
            raise RuntimeError("Run artwork context is missing")
        prompts = list(run.plan.get("prompts") or [])
        owners: list[tuple[str, str, str]] = [
            ("album", album.id, str(run.plan.get("artwork_prompt") or album.artwork_prompt))
        ]
        for track_id, prompt in zip(track_ids, prompts):
            owners.append(
                ("track", track_id, str(prompt.get("artwork_prompt") or prompt["prompt"]))
            )
        return await create_cover_assets(
            owner_prompts=owners,
            job_id=job_id,
            style_reference_id=run.style_reference_id,
            output_size=run.cover_output_size,
            reference_mode="loose",
            artwork_guidance=run.artwork_guidance,
            visual_direction=run.plan.get("visual_direction") or {},
        )
