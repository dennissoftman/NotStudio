"""Natural-language album runs, style references, and versioned covers."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, Response, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select
from starlette.responses import FileResponse

from ..config import get_settings
from ..constants import utcnow
from ..deps import get_session
from ..models import Album, CoverAsset, GenerationRun, HistoryItem, Job, StyleReference
from ..schemas import (
    CreateGenerationRunRequest,
    GenerateAllCoversRequest,
    GenerateCoverRequest,
    GenerateRunRequest,
    PromptPlan,
    SelectCoverRequest,
    UpdateGenerationPlanRequest,
)
from ..services.images import normalize_style_reference
from ..services.taste import build_taste_profile
from ..tasks.artwork import create_cover_assets, generate_covers_job, select_cover
from ..tasks.events import notify_jobs_changed
from ..tasks.registry import cancel_job_task, start_job_task
from ..tasks.submit import submit_generation_run, submit_plan_album

router = APIRouter(prefix="/studio", tags=["generation"])


async def _get_run(session: AsyncSession, run_id: str) -> GenerationRun:
    run = await session.get(GenerationRun, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Generation run not found")
    return run


@router.post("/style-references", response_model=StyleReference, status_code=201)
async def upload_style_reference(
    file: UploadFile = File(...), session: AsyncSession = Depends(get_session)
) -> StyleReference:
    reference = await normalize_style_reference(file, get_settings())
    session.add(reference)
    await session.commit()
    await session.refresh(reference)
    return reference


@router.get("/style-references/{reference_id}/image")
async def get_style_reference(
    reference_id: str, session: AsyncSession = Depends(get_session)
) -> FileResponse:
    reference = await session.get(StyleReference, reference_id)
    if reference is None or not Path(reference.path).is_file():
        raise HTTPException(status_code=404, detail="Style reference not found")
    return FileResponse(reference.path, media_type=reference.mime)


@router.post("/album-runs", response_model=GenerationRun, status_code=201)
async def create_album_run(
    payload: CreateGenerationRunRequest, session: AsyncSession = Depends(get_session)
) -> GenerationRun:
    settings = get_settings()
    if payload.cover_output_size > settings.cover_max_output_size:
        raise HTTPException(
            status_code=422,
            detail=f"Cover output size cannot exceed {settings.cover_max_output_size}",
        )
    if payload.style_reference_id:
        reference = await session.get(StyleReference, payload.style_reference_id)
        if reference is None:
            raise HTTPException(status_code=404, detail="Style reference not found")
    run = GenerationRun(
        brief=payload.brief.strip(),
        artwork_guidance=payload.artwork_guidance.strip(),
        style_reference_id=payload.style_reference_id,
        cover_output_size=payload.cover_output_size,
        auto_start=payload.auto_start,
        params={"duration_default": payload.duration_default},
    )
    session.add(run)
    await session.commit()
    await session.refresh(run)
    taste = await build_taste_profile(session)
    await submit_plan_album(
        session,
        run=run,
        taste_profile=taste.model_dump(mode="json"),
        duration_default=payload.duration_default,
    )
    await session.refresh(run)
    return run


@router.get("/album-runs", response_model=list[GenerationRun])
async def list_album_runs(session: AsyncSession = Depends(get_session)) -> list[GenerationRun]:
    res = await session.execute(
        select(GenerationRun).order_by(GenerationRun.created_at.desc()).limit(100)
    )
    return list(res.scalars().all())


@router.get("/album-runs/{run_id}", response_model=GenerationRun)
async def get_album_run(run_id: str, session: AsyncSession = Depends(get_session)) -> GenerationRun:
    return await _get_run(session, run_id)


@router.patch("/album-runs/{run_id}/plan", response_model=GenerationRun)
async def update_album_run_plan(
    run_id: str,
    payload: UpdateGenerationPlanRequest,
    session: AsyncSession = Depends(get_session),
) -> GenerationRun:
    run = await _get_run(session, run_id)
    if run.status not in {"awaiting_review", "failed"}:
        raise HTTPException(status_code=409, detail="Plan cannot be edited after generation starts")
    run.plan = payload.plan.model_dump(exclude_none=True)
    run.status = "awaiting_review"
    run.stage = "awaiting_review"
    run.error = None
    run.updated_at = utcnow()
    session.add(run)
    await session.commit()
    await session.refresh(run)
    return run


@router.post("/album-runs/{run_id}/replan", response_model=GenerationRun, status_code=201)
async def replan_album_run(
    run_id: str, session: AsyncSession = Depends(get_session)
) -> GenerationRun:
    run = await _get_run(session, run_id)
    if run.status in {"generating_tracks", "generating_covers"}:
        raise HTTPException(status_code=409, detail="Cannot replan while generation is running")
    run.status = "planning"
    run.stage = "planning"
    run.plan = None
    run.error = None
    run.updated_at = utcnow()
    session.add(run)
    await session.commit()
    taste = await build_taste_profile(session)
    await submit_plan_album(
        session,
        run=run,
        taste_profile=taste.model_dump(mode="json"),
        duration_default=float((run.params or {}).get("duration_default", 180.0)),
    )
    await session.refresh(run)
    return run


@router.post("/album-runs/{run_id}/generate", response_model=Job, status_code=201)
async def generate_album_run(
    run_id: str,
    payload: GenerateRunRequest,
    session: AsyncSession = Depends(get_session),
) -> Job:
    run = await _get_run(session, run_id)
    if run.status != "awaiting_review" or not run.plan:
        raise HTTPException(status_code=409, detail="Run must have a reviewed plan")
    try:
        PromptPlan.model_validate(run.plan)
        return await submit_generation_run(
            session, run=run, generate_covers=payload.generate_covers
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/album-runs/{run_id}/cancel", response_model=GenerationRun)
async def cancel_album_run(
    run_id: str, session: AsyncSession = Depends(get_session)
) -> GenerationRun:
    run = await _get_run(session, run_id)
    job_id = run.generation_job_id or run.plan_job_id
    if job_id:
        job = await session.get(Job, job_id)
        if job and job.status in {"queued", "in_progress"}:
            job.status = "cancelled"
            job.finished_at = utcnow()
            job.message = "Cancellation requested"
            session.add(job)
            cancel_job_task(job.id)
    run.status = "cancelled"
    run.stage = "cancelled"
    run.updated_at = utcnow()
    session.add(run)
    await session.commit()
    await session.refresh(run)
    await notify_jobs_changed()
    return run


async def _submit_cover_job(
    session: AsyncSession,
    *,
    owners: list[tuple[str, str, str]],
    request: GenerateCoverRequest,
    guidance: str,
    visual_direction: dict,
) -> Job:
    settings = get_settings()
    if request.output_size > settings.cover_max_output_size:
        raise HTTPException(
            status_code=422,
            detail=f"Cover output size cannot exceed {settings.cover_max_output_size}",
        )
    if any(not prompt.strip() for _, _, prompt in owners):
        raise HTTPException(status_code=422, detail="Every cover prompt must be non-empty")
    if request.reference_mode == "off":
        request = request.model_copy(update={"style_reference_id": None})
    elif request.style_reference_id:
        reference = await session.get(StyleReference, request.style_reference_id)
        if reference is None:
            raise HTTPException(status_code=404, detail="Style reference not found")
    job = Job(type="generate_covers", status="queued", params={}, enqueued_at=utcnow())
    session.add(job)
    await session.commit()
    await session.refresh(job)
    asset_ids = await create_cover_assets(
        owner_prompts=owners,
        job_id=job.id,
        style_reference_id=request.style_reference_id,
        output_size=request.output_size,
        reference_mode=request.reference_mode,
        artwork_guidance=guidance,
        visual_direction=visual_direction,
        seed=request.seed,
    )
    job.params = {"asset_ids": asset_ids}
    session.add(job)
    await session.commit()
    await session.refresh(job)
    await notify_jobs_changed()
    start_job_task(job.id, generate_covers_job)
    return job


async def _album_context(session: AsyncSession, album_id: str) -> tuple[Album, str | None]:
    album = await session.get(Album, album_id)
    if album is None:
        raise HTTPException(status_code=404, detail="Album not found")
    res = await session.execute(
        select(GenerationRun)
        .where(GenerationRun.album_id == album.id)
        .order_by(GenerationRun.created_at.desc())
        .limit(1)
    )
    run = res.scalar_one_or_none()
    return album, run.style_reference_id if run else None


@router.post("/albums/{album_id}/covers/generate", response_model=Job, status_code=201)
async def generate_album_cover(
    album_id: str,
    payload: GenerateCoverRequest,
    session: AsyncSession = Depends(get_session),
) -> Job:
    album, inherited_reference = await _album_context(session, album_id)
    request = payload.model_copy(
        update={"style_reference_id": payload.style_reference_id or inherited_reference}
    )
    prompt = payload.prompt or album.artwork_prompt
    if not prompt:
        raise HTTPException(status_code=422, detail="Album cover prompt is empty")
    return await _submit_cover_job(
        session,
        owners=[("album", album.id, prompt)],
        request=request,
        guidance=album.artwork_guidance,
        visual_direction=album.visual_direction,
    )


@router.post("/tracks/{track_id}/covers/generate", response_model=Job, status_code=201)
async def generate_track_cover(
    track_id: str,
    payload: GenerateCoverRequest,
    session: AsyncSession = Depends(get_session),
) -> Job:
    track = await session.get(HistoryItem, track_id)
    if track is None or track.kind != "track":
        raise HTTPException(status_code=404, detail="Track not found")
    album = await session.get(Album, track.album_id) if track.album_id else None
    prompt = payload.prompt or str((track.meta or {}).get("artwork_prompt") or "")
    if not prompt:
        raise HTTPException(status_code=422, detail="Track cover prompt is empty")
    inherited_reference: str | None = None
    if album:
        _album, inherited_reference = await _album_context(session, album.id)
    request = payload.model_copy(
        update={"style_reference_id": payload.style_reference_id or inherited_reference}
    )
    return await _submit_cover_job(
        session,
        owners=[("track", track.id, prompt)],
        request=request,
        guidance=album.artwork_guidance if album else "",
        visual_direction=album.visual_direction if album else {},
    )


@router.post("/albums/{album_id}/covers/generate-all", response_model=Job, status_code=201)
async def generate_all_album_covers(
    album_id: str,
    payload: GenerateAllCoversRequest,
    session: AsyncSession = Depends(get_session),
) -> Job:
    album, inherited_reference = await _album_context(session, album_id)
    tracks = await session.execute(
        select(HistoryItem)
        .where(HistoryItem.album_id == album.id, HistoryItem.kind == "track")
        .order_by(HistoryItem.created_at.asc())
    )
    owners = [("album", album.id, payload.prompt or album.artwork_prompt)]
    for track in tracks.scalars().all():
        prompt = payload.track_prompts.get(track.id) or str(
            (track.meta or {}).get("artwork_prompt") or (track.meta or {}).get("prompt") or ""
        )
        owners.append(("track", track.id, prompt))
    request = payload.model_copy(
        update={"style_reference_id": payload.style_reference_id or inherited_reference}
    )
    return await _submit_cover_job(
        session,
        owners=owners,
        request=request,
        guidance=album.artwork_guidance,
        visual_direction=album.visual_direction,
    )


@router.get("/covers/{cover_id}/image")
async def get_cover_image(
    cover_id: str, session: AsyncSession = Depends(get_session)
) -> FileResponse:
    asset = await session.get(CoverAsset, cover_id)
    if asset is None or asset.status != "ready" or not Path(asset.path).is_file():
        raise HTTPException(status_code=404, detail="Cover not found")
    return FileResponse(
        asset.path,
        media_type=asset.mime,
        headers={"Cache-Control": "private, max-age=31536000, immutable"},
    )


@router.get("/covers", response_model=list[CoverAsset])
async def list_covers(
    owner_type: str | None = None,
    session: AsyncSession = Depends(get_session),
) -> list[CoverAsset]:
    query = select(CoverAsset).order_by(CoverAsset.created_at.desc()).limit(1000)
    if owner_type:
        if owner_type not in {"album", "track"}:
            raise HTTPException(status_code=422, detail="owner_type must be album or track")
        query = query.where(CoverAsset.owner_type == owner_type)
    result = await session.execute(query)
    return list(result.scalars().all())


@router.put("/covers/{cover_id}/select", response_model=CoverAsset)
async def select_cover_version(
    cover_id: str,
    payload: SelectCoverRequest,
    session: AsyncSession = Depends(get_session),
) -> CoverAsset:
    if not payload.selected:
        raise HTTPException(status_code=422, detail="Select another cover instead of deselecting")
    try:
        return await select_cover(cover_id)
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/albums/{album_id}/covers", response_model=list[CoverAsset])
async def list_album_covers(
    album_id: str, session: AsyncSession = Depends(get_session)
) -> list[CoverAsset]:
    res = await session.execute(
        select(CoverAsset)
        .where(CoverAsset.owner_type == "album", CoverAsset.owner_id == album_id)
        .order_by(CoverAsset.created_at.desc())
    )
    return list(res.scalars().all())


@router.get("/tracks/{track_id}/covers", response_model=list[CoverAsset])
async def list_track_covers(
    track_id: str, session: AsyncSession = Depends(get_session)
) -> list[CoverAsset]:
    res = await session.execute(
        select(CoverAsset)
        .where(CoverAsset.owner_type == "track", CoverAsset.owner_id == track_id)
        .order_by(CoverAsset.created_at.desc())
    )
    return list(res.scalars().all())


@router.delete("/style-references/{reference_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_style_reference(
    reference_id: str, session: AsyncSession = Depends(get_session)
) -> Response:
    reference = await session.get(StyleReference, reference_id)
    if reference is None:
        return Response(status_code=status.HTTP_204_NO_CONTENT)
    in_use = await session.execute(
        select(GenerationRun).where(GenerationRun.style_reference_id == reference.id).limit(1)
    )
    if in_use.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Style reference is used by a generation run")
    cover_in_use = await session.execute(
        select(CoverAsset).where(CoverAsset.style_reference_id == reference.id).limit(1)
    )
    if cover_in_use.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Style reference is used by a cover version")
    Path(reference.path).unlink(missing_ok=True)
    await session.delete(reference)
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
