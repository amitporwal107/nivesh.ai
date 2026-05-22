"""Operator endpoints (T4.3).

GET /api/admin/jobs/stale  — jobs stuck in non-terminal status > N minutes.
GET /api/admin/jobs/summary — counts by status over the last 24h.

Guarded by a static admin token in ``PI_ADMIN_TOKEN``. Not a substitute for
real RBAC; suitable for staging + internal ops curl.
"""
from __future__ import annotations

import os
from typing import Annotated

from fastapi import APIRouter, Header, HTTPException, Query
from pydantic import BaseModel

from ..db.pool import get_pool

router = APIRouter(prefix="/api/admin", tags=["admin"])


@router.get("/verify")
async def verify(
    x_admin_token: Annotated[str | None, Header(alias="X-Admin-Token")] = None,
) -> dict:
    """Confirm an admin token is valid — used by the staging test UI to gate
    access before exposing the upload form. No side effects."""
    _check_admin(x_admin_token)
    return {"status": "ok"}


def _check_admin(token: str | None) -> None:
    expected = os.environ.get("PI_ADMIN_TOKEN")
    if not expected:
        raise HTTPException(status_code=503, detail="PI_ADMIN_TOKEN not configured")
    if token != expected:
        raise HTTPException(status_code=401, detail="invalid admin token")


class StaleJob(BaseModel):
    id: str
    pan_hash_prefix: str
    source_type: str
    method: str
    status: str
    minutes_stuck: int


class JobSummary(BaseModel):
    status: str
    count: int


@router.get("/jobs/stale", response_model=list[StaleJob])
async def stale_jobs(
    x_admin_token: Annotated[str | None, Header(alias="X-Admin-Token")] = None,
    min_age_minutes: int = Query(15, ge=1, le=1440),
) -> list[StaleJob]:
    """Jobs in pending_upload/received/parsing for more than ``min_age_minutes``."""
    _check_admin(x_admin_token)

    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, pan_hash, source_type, method, status,
                   EXTRACT(EPOCH FROM (now() - created_at))::int / 60 AS minutes_stuck
              FROM portfolio_ingestion.ingestion_jobs
             WHERE status IN ('pending_upload', 'received', 'parsing')
               AND created_at < now() - ($1 || ' minutes')::interval
             ORDER BY created_at ASC
             LIMIT 200
            """,
            str(min_age_minutes),
        )
    return [
        StaleJob(
            id=str(r["id"]),
            pan_hash_prefix=r["pan_hash"][:8],
            source_type=r["source_type"],
            method=r["method"],
            status=r["status"],
            minutes_stuck=int(r["minutes_stuck"]),
        )
        for r in rows
    ]


@router.get("/jobs/summary", response_model=list[JobSummary])
async def jobs_summary(
    x_admin_token: Annotated[str | None, Header(alias="X-Admin-Token")] = None,
) -> list[JobSummary]:
    """Job counts by status over the last 24h."""
    _check_admin(x_admin_token)

    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT status, COUNT(*) AS count
              FROM portfolio_ingestion.ingestion_jobs
             WHERE created_at > now() - interval '24 hours'
             GROUP BY status
             ORDER BY count DESC
            """,
        )
    return [JobSummary(status=r["status"], count=int(r["count"])) for r in rows]
