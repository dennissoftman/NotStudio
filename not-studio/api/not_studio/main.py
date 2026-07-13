from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .backends.registry import provider_infos
from .config import get_settings
from .db import init_db
from .routers import api_router
from .tasks.jobs import fail_interrupted_jobs, mark_jobs_cancelled_by_shutdown
from .tasks.processes import run_in_reusable_process, shutdown_reusable_processes
from .tasks.registry import shutdown_job_tasks

logger = logging.getLogger(__name__)


async def preload_generation_model(app: FastAPI) -> None:
    settings = get_settings()
    if not settings.preload_local_model_on_startup:
        app.state.model = {
            "status": "disabled",
            "provider": "stable_audio_local",
            "model": "medium",
            "device": "",
        }
        return
    if settings.default_music_provider != "stable_audio_local":
        app.state.model = {
            "status": "skipped",
            "provider": settings.default_music_provider,
            "model": "medium",
            "device": "",
        }
        return

    from .backends.stable_audio import preload_model

    app.state.model = {
        "status": "loading",
        "provider": "stable_audio_local",
        "model": "medium",
        "device": "",
    }
    logger.info("Preloading Stable Audio 3 medium model in the generation worker")
    model_info = await run_in_reusable_process(
        "stable-audio-local",
        preload_model,
        "medium",
    )
    app.state.model = model_info
    logger.info(
        "Stable Audio 3 %s model ready on %s",
        model_info["model"],
        model_info["device"],
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    await fail_interrupted_jobs()
    try:
        await preload_generation_model(app)
        yield
    finally:
        job_ids = await shutdown_job_tasks()
        await mark_jobs_cancelled_by_shutdown(job_ids)
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
        }

    return app


app = create_app()
