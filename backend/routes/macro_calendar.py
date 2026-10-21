"""Smart trading desk — the macro-release calendar (India and US), forwarded to the data platform's /v1/desk/macro-calendar*
(nidp/services/daas_api/routers/desk_macro.py).

    GET /api/markets/macro-calendar?month=YYYY-MM&country=IN,US&impact=H,M,L
        one month of scheduled releases (US: CPI, core PCE, payrolls, unemployment, GDP, jobless claims, retail sales,
        PPI, the Fed decision; India: RBI policy decisions, CPI, IIP, GDP, the PLFS bulletin) with each release's
        previous / actual where a free source gives them, NSE CM holidays and Nifty 50's daily closes. `estimate` is
        always null (no free consensus source) and `gaps` names every other thing not shown.
    GET /api/markets/macro-calendar/history?code=US_CPI_YOY[&country=US]
        Nifty 50's moves on the first session after past releases of that indicator (that session, the next one, one
        week later) with average, min and max; `n` counts only releases Nifty history covers (`coverage_from`).

Signed-in users only. The rows live in nidp.* tables only the data platform reads, so each route validates, forwards and
passes the answer through unchanged; a data platform that is not configured, unreachable or failing is 502
upstream_unavailable, never an empty calendar.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException, Query, Request

from deps import get_current_user
from services.copilot_tools import daas_client

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/markets", tags=["markets-macro-calendar"])

MONTH_PATTERN = r"^\d{4}-(0[1-9]|1[0-2])$"
COUNTRY_PATTERN = r"^(IN|US)(,(IN|US))*$"
IMPACT_PATTERN = r"^(H|M|L)(,(H|M|L))*$"
CODE_PATTERN = r"^[A-Z0-9_]{3,40}$"
_UNAVAILABLE = "upstream_unavailable"


async def _daas(path: str, params: Dict[str, Any], key: str) -> Dict[str, Any]:
    if not daas_client.is_configured():
        raise HTTPException(status_code=502, detail=_UNAVAILABLE)
    try:
        status, body = await daas_client.get_raw(path, params)
    except daas_client.DaasError as e:
        logger.warning("macro-calendar DaaS %s failed: %s", path, e)
        raise HTTPException(status_code=502, detail=_UNAVAILABLE)
    if status == 200 and isinstance(body, dict) and isinstance(body.get(key), list):
        return body
    logger.warning("macro-calendar DaaS %s answered HTTP %s", path, status)
    raise HTTPException(status_code=502, detail=_UNAVAILABLE)


@router.get("/macro-calendar")
async def macro_calendar(
    request: Request,
    month: str = Query(..., pattern=MONTH_PATTERN, description="YYYY-MM"),
    country: str = Query("IN,US", pattern=COUNTRY_PATTERN, description="comma-separated: IN, US"),
    impact: str = Query("H,M,L", pattern=IMPACT_PATTERN, description="comma-separated: H, M, L"),
) -> Dict[str, Any]:
    await get_current_user(request)
    return await _daas("/desk/macro-calendar", {"month": month, "country": country, "impact": impact}, "events")


@router.get("/macro-calendar/history")
async def macro_calendar_history(
    request: Request,
    code: str = Query(..., pattern=CODE_PATTERN, description="indicator code, e.g. US_CPI_YOY"),
    country: Optional[str] = Query(None, pattern=r"^(IN|US)$"),
) -> Dict[str, Any]:
    await get_current_user(request)
    params: Dict[str, Any] = {"code": code}
    if country:
        params["country"] = country
    return await _daas("/desk/macro-calendar/history", params, "occurrences")
