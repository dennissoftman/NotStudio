"""Aggregate all API routers under the ``/api`` prefix."""

from fastapi import APIRouter

from . import agent, backends, history, jobs, programs, schedules, streams

api_router = APIRouter(prefix="/api")
api_router.include_router(backends.router)
api_router.include_router(programs.router)
api_router.include_router(streams.router)
api_router.include_router(jobs.router)
api_router.include_router(schedules.router)
api_router.include_router(history.router)
api_router.include_router(agent.router)
