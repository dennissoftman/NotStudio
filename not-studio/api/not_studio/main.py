from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .backends.registry import provider_infos
from .config import get_settings
from .db import init_db
from .routers import api_router
from .tasks.jobs import fail_interrupted_jobs, mark_jobs_cancelled_by_shutdown
from .tasks.processes import (
    configure_model_idle_timeout,
    model_process_status,
    run_in_model_process,
    shutdown_reusable_processes,
)
from .tasks.registry import shutdown_job_tasks

logger = logging.getLogger(__name__)

# Compatibility seam retained for tests and downstream monkeypatches from the
# original reusable-worker implementation.
run_in_reusable_process = run_in_model_process


async def preload_generation_model(app: FastAPI) -> None:
    settings = get_settings()
    if not settings.preload_local_model_on_startup:
        app.state.model = {
            "status": "disabled",
            "provider": "ace_step_local",
            "model": "ACE-Step 1.5",
            "device": "",
        }
        return
    app.state.model = {
        "status": "loading",
        "provider": "ace_step_local",
        "model": "ACE-Step 1.5",
        "device": "",
    }
    logger.info("Preloading ACE-Step in the generation worker")
    try:
        from .backends.ace_step import preload_model

        model_info = await run_in_reusable_process(
            "ace-step-local",
            preload_model,
            "ACE-Step 1.5",
        )
    except asyncio.CancelledError:
        raise
    except Exception as exc:  # noqa: BLE001 - preload failure must not stop the API
        app.state.model = {
            "status": "failed",
            "provider": "ace_step_local",
            "model": "ACE-Step 1.5",
            "device": "",
            "error": str(exc),
        }
        logger.exception("ACE-Step model preload failed; API remains available")
        return

    app.state.model = model_info
    logger.info(
        "%s model ready on %s with %s",
        model_info["model"],
        model_info["device"],
        model_info.get("language_model", "no language model"),
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_model_idle_timeout(get_settings().gpu_model_idle_seconds)
    await init_db()
    await fail_interrupted_jobs()
    preload_task = asyncio.create_task(
        preload_generation_model(app),
        name="not-studio-model-preload",
    )
    try:
        yield
    finally:
        preload_task.cancel()
        job_ids = await shutdown_job_tasks()
        await mark_jobs_cancelled_by_shutdown(job_ids)
        await asyncio.gather(preload_task, return_exceptions=True)
        await shutdown_reusable_processes()


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title=settings.app_name,
        version="0.1.0",
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(api_router)

    @app.get("/api/health", tags=["meta"])
    async def health() -> dict:
        return {
            "status": "ok",
            "jobs": "local-background",
            "model": getattr(app.state, "model", None),
            "providers": [p.model_dump() for p in provider_infos()],
            "accelerator": model_process_status(),
        }

    return app


app = create_app()
