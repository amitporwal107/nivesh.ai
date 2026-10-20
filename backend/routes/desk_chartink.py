"""Smart trading desk: the user's Chartink dashboard as a second source of opportunities (MongoDB). Read-only; nothing here places an order.

Endpoints (all under /api/desk/chartink, signed-in user only; every document is scoped to its owner, so another user's scan answers 404):
    PUT    /source        {dashboard_url}  import https://chartink.com/dashboard/<digits> (public page, https only, host chartink.com only)
                          -> {source}; stock scans enabled and bullish, market statistics and unsupported scans disabled; a re-import keeps the
                             user's enabled/direction choices (by widget id). Clauses are left out unless ?include_clauses=1.
    GET    /source        -> {source} (null when none)
    PATCH  /scans/{id}    {enabled?, direction?} -> {scan}
    DELETE /source        removes the source and that user's hits
    POST   /refresh       runs the enabled scans now (2 at a time, >= 1 s apart, 30 s each, 25 at most; one run per user per 10 minutes: 429 with
                          retry_after_s) and stores today's (IST) hits, replacing the same scan and day -> per scan {id, name, ok, hits, error, seconds}
    GET    /hits?date=    the latest scan date's hits grouped by stock, joined with the AI scanner list and the symbol universe

Typed errors: detail = {"code", "message", ...}: invalid_dashboard_url, dashboard_fetch_failed, dashboard_too_large, redirect_off_site,
dashboard_page_changed, dashboard_empty, no_source, scan_not_found, scan_unsupported, refresh_cooldown. No Chartink credential is stored. Writes pass
through the app's CSRF middleware like every other desk write.
"""
from __future__ import annotations

import json
import logging
import re
from datetime import date
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query, Request, Response

from deps import db, get_current_user
from services.chartink_desk import dashboard as dash
from services.chartink_desk import hits as hits_mod
from services.chartink_desk import refresh as refresh_mod
from services.chartink_desk import store

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/desk/chartink", tags=["desk"])

_ID_MAX = 40
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def today() -> date:
    return date.fromisoformat(store.ist_date(store.utcnow()))


async def _body(request: Request) -> Any:
    try:
        return json.loads(await request.body())
    except ValueError:
        raise HTTPException(status_code=422, detail={"code": "invalid_body", "message": "The request body must be JSON."})


def _fail(e: Exception) -> HTTPException:
    if isinstance(e, (store.ChartinkError,)):
        return HTTPException(status_code=e.status, detail=e.detail, headers={"Retry-After": str(e.extra["retry_after_s"])} if "retry_after_s" in e.extra else None)
    if isinstance(e, dash.DashboardError):
        return HTTPException(status_code=e.status, detail={"code": e.code, "message": e.message})
    raise e


@router.put("/source")
async def put_source(request: Request, include_clauses: int = Query(0, ge=0, le=1)) -> Dict[str, Any]:
    user = await get_current_user(request)
    body = await _body(request)
    if not isinstance(body, dict):
        raise HTTPException(status_code=422, detail={"code": "invalid_body", "message": "Send {\"dashboard_url\": ...}."})
    try:
        doc = await store.put_source(db, user["user_id"], body.get("dashboard_url"))
    except (store.ChartinkError, dash.DashboardError) as e:
        raise _fail(e)
    return {"source": store.public_source(doc, bool(include_clauses))}


@router.get("/source")
async def get_source(request: Request, include_clauses: int = Query(0, ge=0, le=1)) -> Dict[str, Any]:
    user = await get_current_user(request)
    return {"source": store.public_source(await store.get_source(db, user["user_id"]), bool(include_clauses))}


@router.patch("/scans/{scan_id}")
async def patch_scan(request: Request, scan_id: str) -> Dict[str, Any]:
    user = await get_current_user(request)
    if len(scan_id) > _ID_MAX:
        raise HTTPException(status_code=404, detail={"code": "scan_not_found", "message": "No such scan on your Chartink dashboard."})
    body = await _body(request)
    try:
        return {"scan": await store.patch_scan(db, user["user_id"], scan_id, body)}
    except store.ChartinkError as e:
        raise _fail(e)


@router.delete("/source")
async def delete_source(request: Request) -> Dict[str, Any]:
    user = await get_current_user(request)
    return await store.delete_source(db, user["user_id"])


@router.post("/refresh")
async def refresh(request: Request) -> Dict[str, Any]:
    user = await get_current_user(request)
    try:
        return await refresh_mod.refresh_user(db, user["user_id"])
    except store.ChartinkError as e:
        raise _fail(e)


async def _scanner_scores(request: Request) -> tuple:
    """(symbol -> AI score for the merged scanner list the Overview card uses, failures). None scores when the scanner cannot be read."""
    from services.strategy_plan import selection
    watch, picks, fails = await selection.read_scanner(request)
    if watch is None and picks is None:
        return None, fails
    return {s["symbol"]: (round(s["score"], 1) if s["score"] is not None else None) for s in selection.merge_setups(watch, picks)}, fails


async def _universe() -> tuple:
    from services import symbol_lookup as sl
    try:
        return (await sl.get_universe()).entries, None
    except Exception as e:  # noqa: BLE001 — the names and F&O flags are optional: unknown, never invented
        return None, f"symbol universe: {type(e).__name__}: {str(e)[:120]}"


async def _suggest(symbol: str) -> Dict[str, Any]:
    from services import symbol_lookup as sl
    from services.strategy_plan.sources import SUGGESTION_KEYS
    try:
        found = await sl.lookup(symbol, 3)
    except (sl.BadQuery, RuntimeError):
        return {"suggestions": [], "suggested": None}
    strong = sl.strong_suggestion(found["results"])
    return {"suggestions": [{k: r.get(k) for k in SUGGESTION_KEYS} for r in found["results"] if r["has_prices"] is not False][:3],
            "suggested": strong["symbol"] if strong and strong["has_prices"] is not False else None}


@router.get("/hits")
async def hits(request: Request, date_: Optional[str] = Query(None, alias="date")) -> Dict[str, Any]:
    user = await get_current_user(request)
    if date_ is not None:
        try:
            if not _DATE_RE.match(date_):
                raise ValueError
            date.fromisoformat(date_)
        except ValueError:
            raise HTTPException(status_code=422, detail={"code": "invalid_date", "message": "date must be YYYY-MM-DD."})
    scores, fails = await _scanner_scores(request)
    universe, ufail = await _universe()
    return await hits_mod.hits_view(db, user["user_id"], date_, today(), scores, fails, universe, ufail, _suggest)
