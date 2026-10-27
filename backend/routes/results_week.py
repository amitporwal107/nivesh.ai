"""Results week (Earnings Surprise & Guidance Tracker, P1) — docs/EARNINGS_SURPRISE_TRACKER.md §5. Signed in; reads only.

GET /api/desk/results-week?date=YYYY-MM-DD
    the date's week of results meetings (Monday .. Saturday), each declared result rated "vs historical trend" (the
    company's own past quarters, not analyst consensus), the Earnings Intelligence Score with its coverage, the market
    reaction vs Nifty, the OI build-up, the AI scanner's technicals and your Chartink confirmation; plus two idea lists
    (F&O names / all names) ordered for review, labelled with the study's result (no measurable skill so far).

    date omitted → today (IST), built live and cached for CACHE_S (a build that takes longer than LIVE_WAIT_S answers
    with the previous build, or 503 {code: building, retry_after_s} before the first one). A past date answers from the nightly snapshot
    (results_week_days, scripts/build_results_week.py): 404 not_stored when none was stored. A future date or a
    malformed one → 422. The results calendar failing entirely → 502 upstream_unavailable (never an empty week); any
    other source failing nulls its block and names it in `gaps`.

The market strip and the macro calendar are not in this answer: the screen composes them from the desk's existing
routes. Ideas for review, not recommendations; nothing places an order.
"""
from __future__ import annotations

import asyncio
import logging
import time
from datetime import date, datetime, timezone
from typing import Any, Dict, Optional, Tuple

from fastapi import APIRouter, HTTPException, Query, Request

from deps import db, get_current_user
from services.results_week import build as rw_build
from services.results_week import loaders, store

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/desk/results-week", tags=["desk"])

CACHE_S = 600.0                    # today's live answer is rebuilt at most every 10 minutes
LIVE_WAIT_S = 45.0                 # a request waits this long for a build; then the previous answer, or 503 building
RETRY_AFTER_S = 20
_live: Dict[str, Tuple[float, Dict[str, Any]]] = {}
_building: Dict[str, "asyncio.Task[Dict[str, Any]]"] = {}


def today_ist() -> date:
    return datetime.now(loaders.IST).date()


def _bad(message: str) -> HTTPException:
    return HTTPException(status_code=422, detail={"code": "invalid_date", "message": message})


async def _build_and_keep(day: date) -> Dict[str, Any]:
    body = await rw_build.build_day(day, now=datetime.now(timezone.utc), live=True, db=db)
    for k in [k for k in _live if k != day.isoformat()]:
        _live.pop(k, None)                 # only today's answer is kept
    _live[day.isoformat()] = (time.monotonic(), body)
    return body


async def _live_body(day: date) -> Dict[str, Any]:
    """Today's answer: the cached one when fresh; else one build at a time (requests share it). A build that takes
    longer than LIVE_WAIT_S keeps running in the background: the request gets the previous answer (its `as_of` says
    when it was built) or, with none yet, 503 building with Retry-After."""
    key = day.isoformat()
    hit = _live.get(key)
    if hit and time.monotonic() - hit[0] < CACHE_S:
        return hit[1]
    task = _building.get(key)
    if task is None or task.done():
        task = asyncio.ensure_future(_build_and_keep(day))
        task.add_done_callback(lambda t: t.cancelled() or t.exception())   # a failure is read here, never left unretrieved
        _building[key] = task
    try:
        return await asyncio.wait_for(asyncio.shield(task), LIVE_WAIT_S)
    except asyncio.TimeoutError:
        if hit:
            return hit[1]
        raise HTTPException(status_code=503, headers={"Retry-After": str(RETRY_AFTER_S)},
                            detail={"code": "building", "retry_after_s": RETRY_AFTER_S,
                                    "message": "Today's results week is being built; try again in a few seconds."})
    except loaders.SourceUnavailable as e:
        logger.warning("results week %s: results calendar unavailable: %s", key, e)
        if hit:
            return hit[1]
        raise HTTPException(status_code=502, detail="upstream_unavailable")


@router.get("")
async def get_results_week(request: Request,
                           day: Optional[str] = Query(None, alias="date", description="YYYY-MM-DD; default today (IST)")) -> Dict[str, Any]:
    user = await get_current_user(request)
    today = today_ist()
    if day is None:
        d = today
    else:
        try:
            d = date.fromisoformat(day)
        except ValueError:
            raise _bad("date must be a real date, YYYY-MM-DD")
        if len(day) != 10:
            raise _bad("date must be a real date, YYYY-MM-DD")
    if d > today:
        raise _bad(f"date {d.isoformat()} is in the future; today (IST) is {today.isoformat()}")
    if d == today:
        body = await _live_body(d)
    else:
        body = await store.get_day(d.isoformat(), db=db)
        if body is None:
            raise HTTPException(status_code=404, detail={"code": "not_stored",
                                                         "message": f"No results-week snapshot is stored for {d.isoformat()}. "
                                                                    "The nightly job stores each weekday at 22:45 IST."})
    by, meta = await loaders.chartink_for(db, user["user_id"], d)
    return rw_build.join_chartink(body, by, meta)
