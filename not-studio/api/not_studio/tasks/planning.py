from __future__ import annotations

import asyncio

from ..backends.planner import generate_album_plan
from ..config import get_settings
from ..constants import utcnow
from ..db import session_scope
from ..models import GenerationRun, Job
from .jobs import is_job_cancelled, update_job
from .processes import model_process_busy, run_in_model_process


async def plan_album_job(job_id: str) -> dict:
    settings = get_settings()
    await update_job(
        job_id,
        status="in_progress",
        started_at=utcnow(),
        progress=0.05,
        message="Preparing planner",
    )
    async with session_scope() as session:
        job = await session.get(Job, job_id)
        if job is None:
            return {"error": "job row missing"}
        params = dict(job.params or {})
        run = await session.get(GenerationRun, params.get("run_id"))
        if run is None:
            await update_job(job_id, status="failed", error="generation run missing")
            return {"error": "generation run missing"}
        run.status = "planning"
        run.stage = "planning"
        run.updated_at = utcnow()
        session.add(run)
        await session.commit()

    try:
        if model_process_busy():
            await update_job(job_id, message="Queued for local planner")
        await update_job(
            job_id, progress=0.12, message=f"Loading planner: {settings.planner_model}"
        )
        plan = await run_in_model_process(
            "qwen-planner",
            generate_album_plan,
            params["brief"],
            artwork_guidance=params.get("artwork_guidance", ""),
            taste_profile=params.get("taste_profile") or {},
            duration_default=float(params.get("duration_default", 180.0)),
            model=settings.planner_model,
            max_model_len=settings.planner_max_model_len,
            gpu_memory_utilization=settings.planner_gpu_memory_utilization,
        )
    except asyncio.CancelledError:
        await update_job(
            job_id, status="cancelled", message="Planning cancelled", finished_at=utcnow()
        )
        raise
    except Exception as exc:  # noqa: BLE001
        async with session_scope() as session:
            run = await session.get(GenerationRun, params.get("run_id"))
            if run:
                run.status = "failed"
                run.stage = "planning"
                run.error = str(exc)
                run.updated_at = utcnow()
                session.add(run)
                await session.commit()
        await update_job(job_id, status="failed", error=str(exc), finished_at=utcnow())
        return {"error": str(exc)}

    if await is_job_cancelled(job_id):
        return {"cancelled": True}
    async with session_scope() as session:
        run = await session.get(GenerationRun, params["run_id"])
        if run is None:
            return {"error": "generation run missing"}
        run.plan = plan
        run.status = "awaiting_review"
        run.stage = "awaiting_review"
        run.error = None
        run.updated_at = utcnow()
        session.add(run)
        await session.commit()

    await update_job(
        job_id,
        status="completed",
        progress=1.0,
        message=f"Planned {len(plan['prompts'])} track(s)",
        result={"run_id": params["run_id"], "plan": plan},
        finished_at=utcnow(),
    )
    if run.auto_start:
        from .submit import submit_generation_run

        async with session_scope() as session:
            current = await session.get(GenerationRun, run.id)
            if current and current.status == "awaiting_review":
                await submit_generation_run(session, run=current, generate_covers=True)
    return {"run_id": params["run_id"], "plan": plan}
