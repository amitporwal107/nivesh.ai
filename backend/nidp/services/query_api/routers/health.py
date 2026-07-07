"""Health check — auth-free so Cloud Run + uptime probes can hit it.

  * /health  — liveness. ALWAYS HTTP 200; db_ok in the body reflects DB state.
  * /readyz  — readiness. HTTP 503 when the DB is unreachable, so an
               HTTP-status-only uptime check catches a DB-down outage that
               /health hides by always returning 200.
"""
from __future__ import annotations

import time
from typing import Any, Dict, Optional, Tuple

from fastapi import APIRouter, Response

from nidp.shared.storage.pg import get_pool


router = APIRouter(prefix="", tags=["health"])

_SERVICE = "nidp-query-api"


async def _db_probe() -> Tuple[bool, Optional[str], int]:
    t0 = time.time()
    try:
        pool = await get_pool()
        async with pool.acquire() as conn:
            await conn.fetchval("SELECT 1")
        return True, None, int((time.time() - t0) * 1000)
    except Exception as e:                                            # noqa: BLE001
        return False, f"{type(e).__name__}: {str(e)[:200]}", int((time.time() - t0) * 1000)


def _payload(db_ok: bool, db_err: Optional[str], latency: int) -> Dict[str, Any]:
    return {
        "ok":            db_ok,
        "service":       _SERVICE,
        "db_ok":         db_ok,
        "db_latency_ms": latency,
        "error":         db_err,
    }


@router.get("/health")
async def health() -> Dict[str, Any]:
    db_ok, db_err, latency = await _db_probe()
    return _payload(db_ok, db_err, latency)


@router.get("/readyz", summary="Readiness — HTTP 503 when the DB is unreachable")
async def readyz(response: Response) -> Dict[str, Any]:
    db_ok, db_err, latency = await _db_probe()
    if not db_ok:
        response.status_code = 503
    return _payload(db_ok, db_err, latency)
