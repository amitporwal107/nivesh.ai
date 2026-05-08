"""Public, auth-free health probe — Cloud Run + uptime checks hit this."""
from __future__ import annotations

import time
from typing import Any, Dict

from fastapi import APIRouter

from nidp.shared.storage.pg import get_pool


router = APIRouter(prefix="", tags=["meta"])


@router.get("/health", summary="Liveness + DB readiness")
async def health() -> Dict[str, Any]:
    t0 = time.time()
    db_ok, db_err = False, None
    try:
        pool = await get_pool()
        async with pool.acquire() as conn:
            await conn.fetchval("SELECT 1")
        db_ok = True
    except Exception as e:                                            # noqa: BLE001
        db_err = f"{type(e).__name__}: {str(e)[:200]}"
    return {
        "ok":            db_ok,
        "service":       "nidp-daas-api",
        "db_ok":         db_ok,
        "db_latency_ms": int((time.time() - t0) * 1000),
        "error":         db_err,
    }
