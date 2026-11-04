"""Trade Desk › Paper Trading › P&L dashboard: real-time P&L of the user's PAPER trades (docs/paper_pnl_dashboard/DESIGN.md).

Endpoints (all GET, under /api/desk, scoped to the signed-in user; 401 without a session; NOTHING here writes):
    GET /pnl              ?segment=ALL|EQUITY|FUTURES|OPTIONS &period=TODAY|1W|1M|ALL|CUSTOM &from=&to=
                          the whole dashboard: summary, by segment, positions (one per share trade / structure leg),
                          strategies, pending entries, closed trades of the period, risk (capital, limits, alerts),
                          analytics, reconciliation against the ledger, market / feed state; `sequence` rises with time
    GET /pnl/stream       the same filters; server-sent events: `event: snapshot` with the body above every
                          PNL_STREAM_SECONDS (3 s while the market is open, 30 s otherwise), `: heartbeat` comments between,
                          closed after 30 minutes (EventSource reconnects and gets a fresh snapshot)
    GET /pnl/timeseries   ?interval=1m|5m|15m|1h  the open book's P&L through the latest session from Kite candles

Paper only (owner, 4 Nov 2026): every row carries mode "PAPER". The trades are read without applying exits
(services/paper_pnl/book.py); prices follow the live -> Kite close -> end-of-day rule (services/paper_pnl/prices.py) and are
display-only: paper fills and exits stay on end-of-day prices at the evening check.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import StreamingResponse

from deps import db, get_current_user
from services import paper_account as acct
from services import risk_profile
from services.paper_pnl import book as book_mod
from services.paper_pnl import dashboard, prices, timeseries

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/desk", tags=["desk-pnl"])

STREAM_MAX_SECONDS = 30 * 60
HEARTBEAT_SECONDS = 15.0


def _cadence(session_open: bool) -> float:
    name, default = ("PNL_STREAM_SECONDS", 3.0) if session_open else ("PNL_STREAM_CLOSED_SECONDS", 30.0)
    try:
        return max(1.0, float(os.environ.get(name, default)))
    except ValueError:
        return default


def _filters(segment: str, period: str, start: Optional[str], end: Optional[str]) -> dashboard.Filters:
    try:
        return dashboard.make_filters(segment, period, start, end, prices.today_ist())
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))


async def snapshot(uid: str, filters: dashboard.Filters) -> Dict[str, Any]:
    """One dashboard body for the user. Read-only."""
    now = datetime.now(timezone.utc)
    book = await book_mod.read_book(db, uid)
    legs = [leg for item in book.open for leg in item.legs]
    quotes, market = await prices.resolve(legs, now=now)
    unders = {str(i.public.get("underlying") or "").upper() for i in book.open if i.kind == "strategy"}
    underlying_ltp = await prices.underlying_prices(unders, now=now) if unders else {}
    account = await acct.read(db, uid)
    try:
        limits = (await risk_profile.read(db, uid)).get("limits")
    except Exception as e:  # noqa: BLE001 — the limits are context here; the dashboard still answers without them
        logger.warning("desk_pnl: risk profile unreadable (%s)", type(e).__name__)
        limits = None
    body = dashboard.build(book, quotes, market, account, limits, filters, now=now, underlying_ltp=underlying_ltp)
    body["as_of"] = now.astimezone(prices.cfg.IST).isoformat()
    body["sequence"] = int(time.time() * 1000)
    body["read_only"] = True
    return body


@router.get("/pnl")
async def pnl(request: Request, segment: str = Query("ALL", max_length=10), period: str = Query("TODAY", max_length=10),
              start: Optional[str] = Query(None, alias="from", max_length=10),
              end: Optional[str] = Query(None, alias="to", max_length=10)) -> Dict[str, Any]:
    user = await get_current_user(request)
    return await snapshot(user["user_id"], _filters(segment, period, start, end))


@router.get("/pnl/stream")
async def pnl_stream(request: Request, segment: str = Query("ALL", max_length=10), period: str = Query("TODAY", max_length=10),
                     start: Optional[str] = Query(None, alias="from", max_length=10),
                     end: Optional[str] = Query(None, alias="to", max_length=10)):
    user = await get_current_user(request)
    uid = user["user_id"]
    filters = _filters(segment, period, start, end)

    async def gen():
        loop = asyncio.get_event_loop()
        started = loop.time()
        yield "retry: 3000\n\n"
        while loop.time() - started < STREAM_MAX_SECONDS:
            if await request.is_disconnected():
                return
            session_open = False
            try:
                body = await snapshot(uid, filters)
                session_open = (body.get("market") or {}).get("session") == "open"
                yield f"event: snapshot\ndata: {json.dumps(body, separators=(',', ':'), default=str)}\n\n"
            except Exception as e:  # noqa: BLE001 — tell the client, keep the stream; the client keeps its last snapshot
                logger.warning("desk_pnl stream pass failed: %s", type(e).__name__)
                yield f"event: problem\ndata: {json.dumps({'error': 'snapshot_unavailable', 'kind': type(e).__name__})}\n\n"
            wait = _cadence(session_open)
            while wait > 0:
                step = min(wait, HEARTBEAT_SECONDS)
                await asyncio.sleep(step)
                wait -= step
                if wait > 0:
                    if await request.is_disconnected():
                        return
                    yield ": heartbeat\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "Connection": "keep-alive"})


@router.get("/pnl/timeseries")
async def pnl_timeseries(request: Request, interval: str = Query("5m", max_length=4)) -> Dict[str, Any]:
    user = await get_current_user(request)
    uid = user["user_id"]
    if interval not in timeseries.ALLOWED:
        raise HTTPException(status_code=422, detail="invalid_interval")
    now = datetime.now(timezone.utc)
    book = await book_mod.read_book(db, uid)
    legs = [leg for item in book.open for leg in item.legs]
    quotes, _ = await prices.resolve(legs, now=now)
    charges = 0.0
    for item in book.open:
        if not item.entered:
            continue
        for leg in item.legs:
            q = quotes.get(leg.position_key)
            c = dashboard.leg_charges(item, leg, q.ltp if q else None)
            charges += c or 0.0
    return await timeseries.build(uid, book, quotes, interval, charges_estimated=round(charges, 2), now=now)
