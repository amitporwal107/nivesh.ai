"""Benchmark Index Data Service API.

Three GETs (per PRD):
  * GET /api/index/latest?name=NIFTY_50
  * GET /api/index/history?name=NIFTY_50&period=1Y
  * GET /api/index/benchmark?category=Large%20Cap

Plus one admin POST:
  * POST /api/index/refresh         — run the daily refresh on demand
"""
from __future__ import annotations
import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query, Request

from deps import get_current_user, require_admin
from services import benchmark_index

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/index", tags=["benchmark"])


@router.get("/latest")
async def get_latest(name: str = Query(..., min_length=2, max_length=64),
                      request: Request = None) -> Dict[str, Any]:
    """Latest snapshot for an index — close, OHLC, full metrics bundle.

    Cached in Redis for ~1h, so cost-of-call is dominated by network
    round-trip, not PG.
    """
    await get_current_user(request)
    snap = await benchmark_index.get_latest_index(name.strip().upper())
    if not snap:
        raise HTTPException(404, f"no data for index {name!r}")
    return snap


@router.get("/history")
async def get_history(
    name: str = Query(..., min_length=2, max_length=64),
    period: str = Query("1Y", regex="^(1M|3M|6M|1Y|3Y|5Y|MAX)$"),
    request: Request = None,
) -> Dict[str, Any]:
    """OHLC history for the given period."""
    await get_current_user(request)
    rows = await benchmark_index.get_history(name.strip().upper(), period=period)
    return {"index": name.strip().upper(), "period": period,
            "n_points": len(rows), "rows": rows}


@router.get("/benchmark")
async def get_benchmark(
    category: str = Query(..., min_length=2, max_length=80),
    request: Request = None,
) -> Dict[str, Any]:
    """Map a fund category → its configured benchmark index."""
    await get_current_user(request)
    bench = await benchmark_index.get_benchmark_for_category(category)
    if not bench:
        raise HTTPException(404, f"no benchmark configured for category {category!r}")
    return {"category": category, "benchmark": bench}


@router.post("/refresh")
async def trigger_refresh(request: Request,
                            name: Optional[str] = Query(None)) -> Dict[str, Any]:
    """Admin-only: trigger refresh now (rather than waiting for the
    daily cron). If `name` is set, refresh just that one index."""
    await require_admin(request)
    if name:
        return await benchmark_index.refresh_index(name.strip().upper())
    return {"results": await benchmark_index.refresh_all()}
