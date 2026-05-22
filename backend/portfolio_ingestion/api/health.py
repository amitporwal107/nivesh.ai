"""Health + readiness endpoints (T4.1).

GET /api/healthz  — liveness; no I/O; used by docker healthcheck.
GET /api/readyz   — readiness; checks Postgres + Mongo, reports pool size
                    and the highest applied migration. Returns 200 always
                    (with status="ok"|"degraded" in the body) so probers can
                    distinguish service crash from dependency hiccup.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from ..config import Settings
from ..deps import settings_dependency

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["health"])


class HealthResponse(BaseModel):
    status: str
    service: str
    version: str
    env: str


class ReadyzResponse(BaseModel):
    status: str
    service: str
    version: str
    env: str
    postgres: str
    mongo: str
    migration_version: str | None
    pg_pool_size: int | None


@router.get("/healthz", response_model=HealthResponse)
async def healthz(settings: Settings = Depends(settings_dependency)) -> HealthResponse:
    return HealthResponse(
        status="ok",
        service=settings.service_name,
        version=settings.version,
        env=settings.app_env,
    )


@router.get("/readyz", response_model=ReadyzResponse)
async def readyz(settings: Settings = Depends(settings_dependency)) -> ReadyzResponse:
    pg_status = "unconfigured"
    migration_version: str | None = None
    pg_pool_size: int | None = None

    if settings.postgres_url:
        try:
            from ..db.pool import get_pool
            pool = await get_pool()
            pg_pool_size = pool.get_size()
            async with pool.acquire() as conn:
                await conn.fetchval("SELECT 1")
                migration_version = await conn.fetchval(
                    "SELECT filename FROM portfolio_ingestion.schema_migrations "
                    "ORDER BY applied_at DESC LIMIT 1"
                )
            pg_status = "ok"
        except Exception as exc:
            pg_status = f"error: {exc!s}"[:120]
            log.warning("readyz postgres check failed",
                        extra={"eventType": "READYZ_PG_FAIL", "error": str(exc)})

    mongo_status = "unconfigured"
    if settings.mongo_url:
        try:
            from ..clients.mongo import get_database
            db = await get_database()
            await db.command("ping")
            mongo_status = "ok"
        except Exception as exc:
            mongo_status = f"error: {exc!s}"[:120]
            log.warning("readyz mongo check failed",
                        extra={"eventType": "READYZ_MONGO_FAIL", "error": str(exc)})

    overall = "ok" if pg_status in ("ok", "unconfigured") and \
                      mongo_status in ("ok", "unconfigured") else "degraded"

    return ReadyzResponse(
        status=overall,
        service=settings.service_name,
        version=settings.version,
        env=settings.app_env,
        postgres=pg_status,
        mongo=mongo_status,
        migration_version=migration_version,
        pg_pool_size=pg_pool_size,
    )
