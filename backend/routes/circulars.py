"""Regulator circulars (SEBI) for the trading desk's Market intelligence tab, forwarded to the data platform's
/v1/circulars/sebi (nidp/services/daas_api/routers/circulars.py).

    GET /api/markets/circulars?days=30&limit=50   SEBI circulars and master circulars issued in the last `days`
                                                  days (IST), newest first: title, url, kind, issued_on

The rows live in nidp.sebi_circulars (filled from SEBI's RSS feed every 3 h Mon-Sat, plus a one-off backfill of
the listing pages), which only the data platform can read, so the route forwards there and passes the answer
through unchanged: `as_of` (the day SEBI was last read), `checked_at`, `source` and every row are the data
platform's. Enforcement orders and recovery notices are never stored, so they never appear here.

Signed-in users only, like the rest of /api/markets. Errors: a data platform that is not configured, unreachable or
failing is 502 upstream_unavailable, never an empty or an older list. No circular in the window is 200 with
`rows: []`.
"""
from __future__ import annotations

import logging
from typing import Any, Dict

from fastapi import APIRouter, HTTPException, Query, Request

from deps import get_current_user
from services.copilot_tools import daas_client

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/markets", tags=["circulars"])

_UNAVAILABLE = "upstream_unavailable"


@router.get("/circulars")
async def circulars(
    request: Request,
    days: int = Query(30, ge=1, le=365, description="Look-back in days (IST), by issue date"),
    limit: int = Query(50, ge=1, le=200),
) -> Dict[str, Any]:
    """SEBI circulars and master circulars issued in the last `days` days, newest first."""
    await get_current_user(request)
    path = "/circulars/sebi"
    if not daas_client.is_configured():
        raise HTTPException(status_code=502, detail=_UNAVAILABLE)
    try:
        status, body = await daas_client.get_raw(path, {"days": days, "limit": limit})
    except daas_client.DaasError as e:
        logger.warning("circulars DaaS %s failed: %s", path, e)
        raise HTTPException(status_code=502, detail=_UNAVAILABLE)
    if status == 200 and isinstance(body, dict) and isinstance(body.get("rows"), list):
        return body
    logger.warning("circulars DaaS %s answered HTTP %s", path, status)
    raise HTTPException(status_code=502, detail=_UNAVAILABLE)
