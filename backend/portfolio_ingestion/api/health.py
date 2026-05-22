"""Health endpoints.

``/api/healthz`` is a liveness probe — returns 200 with service identity, used
by docker healthcheck + nginx upstream readiness. The richer ``/api/readyz``
(checks DB + Mongo + Redis) lands when those dependencies are wired (T1.2+).
"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from ..config import Settings
from ..deps import settings_dependency

router = APIRouter(prefix="/api", tags=["health"])


class HealthResponse(BaseModel):
    status: str
    service: str
    version: str
    env: str


@router.get("/healthz", response_model=HealthResponse)
async def healthz(settings: Settings = Depends(settings_dependency)) -> HealthResponse:
    return HealthResponse(
        status="ok",
        service=settings.service_name,
        version=settings.version,
        env=settings.app_env,
    )
