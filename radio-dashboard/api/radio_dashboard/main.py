from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlmodel import select

from .backends.registry import provider_infos
from .config import get_settings
from .db import init_db, session_scope
from .models import Stream
from .routers import api_router
from .streaming import PlayoutManager
from .tasks.queue import create_arq_pool

logger = logging.getLogger("radio_dashboard")


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    app.state.playout = PlayoutManager()

    try:
        app.state.arq = await create_arq_pool()
    except Exception as exc:  # noqa: BLE001 — API should boot even if Redis is down
        app.state.arq = None
        logger.warning("Redis/arq unavailable (%s); job submission disabled.", exc)

    # Resume playout for streams that were live before a restart.
    async with session_scope() as session:
        res = await session.execute(select(Stream).where(Stream.status == "live"))
        for stream in res.scalars().all():
            try:
                await app.state.playout.ensure_running(stream)
            except Exception:  # noqa: BLE001
                logger.exception("Failed to resume playout for stream %s", stream.id)

    try:
        yield
    finally:
        await app.state.playout.shutdown()
        if app.state.arq is not None:
            await app.state.arq.close()


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
            "queue": app.state.arq is not None,
            "providers": [p.model_dump() for p in provider_infos()],
        }

    return app


app = create_app()
