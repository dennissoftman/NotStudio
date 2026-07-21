"""Aggregate API routers under the ``/api`` prefix."""

from fastapi import APIRouter

from . import generation, history, jobs, studio

api_router = APIRouter(prefix="/api")
api_router.include_router(studio.router)
api_router.include_router(generation.router)
api_router.include_router(jobs.router)
api_router.include_router(history.router)
