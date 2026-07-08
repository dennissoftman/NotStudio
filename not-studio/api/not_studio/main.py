from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .backends.registry import provider_infos
from .config import get_settings
from .db import init_db
from .routers import api_router
from .prompt_generation import prompt_provider_infos


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    yield


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
            "providers": [p.model_dump() for p in provider_infos()],
            "prompt_providers": [p.model_dump() for p in prompt_provider_infos()],
        }

    return app


app = create_app()
