"""Smart trading desk — the stock-events calendar, forwarded to the data platform's /v1/desk/events-calendar*
(nidp/services/daas_api/routers/desk_events.py).

    GET /api/markets/events-calendar?month=YYYY-MM&universe=fno|n50|all
        one month of NSE stock events (results meetings, board meetings, dividend / bonus / split / buyback / rights /
        demerger meetings, ex-dates and record dates), NSE CM holidays (Muhurat flagged) and Nifty 50's daily closes,
        with `gaps` naming what is not shown
    GET /api/markets/events-calendar/history?symbol=&type=RESULTS|BOARD|DIVIDEND|BONUS|SPLIT|BUYBACK|RIGHTS|AGM|DEMERGER
        the stock's own event-day / next-day / one-week moves around its past occurrences, with average, min and max;
        `n` counts only occurrences the warehouse's prices cover (`coverage_from`)
    GET /api/markets/events-calendar/expectation?symbol=&date=YYYY-MM-DD
        for one results meeting: a baseline expectation of revenue, profit and EPS built from the company's own published
        quarters (not an analyst consensus), the band the method has actually been wrong by, the filed result beside it for a
        declared meeting, and recent exchange filings as evidence; `method.universe_backtest` shows how it did on every stock
    GET /api/markets/events-calendar/expectations?from=YYYY-MM-DD&to=YYYY-MM-DD&universe=fno|n50|all
        the same expectation (and the filed result when stored) for EVERY results meeting in a window of at most 3 days, one
        compact row each, declared first: the desk's "results today & tomorrow" board in one request. A company that has
        filed its board-meeting outcome today but whose figures are not stored yet is `filed_state: "pending"`, never a number

The rows live in nidp.* tables only the data platform reads, so each route validates, forwards and passes the answer
through unchanged. Signed-in users only. A data platform that is not configured, unreachable or failing is 502
upstream_unavailable, never an empty calendar. Macro releases are not served here: no macro-calendar source is ingested.
"""
from __future__ import annotations

import logging
from datetime import date as _date
from typing import Any, Dict, Literal

from fastapi import APIRouter, HTTPException, Query, Request

from deps import get_current_user
from services.copilot_tools import daas_client

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/markets", tags=["markets-events-calendar"])

SYMBOL_PATTERN = r"^[A-Za-z0-9&\-]+$"
MONTH_PATTERN = r"^\d{4}-(0[1-9]|1[0-2])$"
_UNAVAILABLE = "upstream_unavailable"
EventType = Literal["RESULTS", "BOARD", "DIVIDEND", "BONUS", "SPLIT", "BUYBACK", "RIGHTS", "AGM", "DEMERGER"]


async def _daas(path: str, params: Dict[str, Any], key: str, not_found_ok: bool = False) -> Dict[str, Any]:
    if not daas_client.is_configured():
        raise HTTPException(status_code=502, detail=_UNAVAILABLE)
    try:
        status, body = await daas_client.get_raw(path, params)
    except daas_client.DaasError as e:
        logger.warning("events-calendar DaaS %s failed: %s", path, e)
        raise HTTPException(status_code=502, detail=_UNAVAILABLE)
    if status == 200 and isinstance(body, dict) and isinstance(body.get(key), list):
        return body
    if not_found_ok and status == 404:
        raise HTTPException(status_code=404, detail="no results meeting for this symbol on that date")
    logger.warning("events-calendar DaaS %s answered HTTP %s", path, status)
    raise HTTPException(status_code=502, detail=_UNAVAILABLE)


@router.get("/events-calendar")
async def events_calendar(
    request: Request,
    month: str = Query(..., pattern=MONTH_PATTERN, description="YYYY-MM"),
    universe: Literal["fno", "n50", "all"] = Query("fno"),
) -> Dict[str, Any]:
    await get_current_user(request)
    return await _daas("/desk/events-calendar", {"month": month, "universe": universe}, "events")


@router.get("/events-calendar/history")
async def events_calendar_history(
    request: Request,
    symbol: str = Query(..., min_length=1, max_length=20, pattern=SYMBOL_PATTERN),
    type: EventType = Query(...),
) -> Dict[str, Any]:
    await get_current_user(request)
    return await _daas("/desk/events-calendar/history", {"symbol": symbol.upper(), "type": type}, "occurrences")


DATE_PATTERN = r"^\d{4}-\d{2}-\d{2}$"


@router.get("/events-calendar/expectation")
async def events_calendar_expectation(
    request: Request,
    symbol: str = Query(..., min_length=1, max_length=20, pattern=SYMBOL_PATTERN),
    date: str = Query(..., pattern=DATE_PATTERN, description="YYYY-MM-DD, the results meeting's date"),
) -> Dict[str, Any]:
    await get_current_user(request)
    return await _daas("/desk/events-calendar/expectation", {"symbol": symbol.upper(), "date": date}, "metrics", not_found_ok=True)


MAX_WINDOW_DAYS = 3


@router.get("/events-calendar/expectations")
async def events_calendar_expectations(
    request: Request,
    from_: str = Query(..., alias="from", pattern=DATE_PATTERN, description="YYYY-MM-DD"),
    to: str = Query(..., pattern=DATE_PATTERN, description="YYYY-MM-DD"),
    universe: Literal["fno", "n50", "all"] = Query("fno"),
) -> Dict[str, Any]:
    await get_current_user(request)
    try:
        lo, hi = _date.fromisoformat(from_), _date.fromisoformat(to)
    except ValueError:
        raise HTTPException(status_code=422, detail="from and to must be real dates (YYYY-MM-DD)")
    if hi < lo or (hi - lo).days + 1 > MAX_WINDOW_DAYS:
        raise HTTPException(status_code=422, detail=f"from must not be after to, and the window is at most {MAX_WINDOW_DAYS} days")
    return await _daas("/desk/events-calendar/expectations", {"from": from_, "to": to, "universe": universe}, "events")
