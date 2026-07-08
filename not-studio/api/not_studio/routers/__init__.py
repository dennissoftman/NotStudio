"""Aggregate API routers under the ``/api`` prefix."""

from fastapi import APIRouter

from . import history, jobs, studio

api_router = APIRouter(prefix="/api")
api_router.include_router(studio.router)
api_router.include_router(jobs.router)
api_router.include_router(history.router)
