"""Trade Desk › Paper Trading › P&L dashboard: real-time P&L of the user's PAPER trades (docs/paper_pnl_dashboard/DESIGN.md).

Endpoints (under /api/desk, scoped to the signed-in user; 401 without a session; only POST /pnl/exits/seen writes):
    GET /pnl              ?segment=ALL|EQUITY|FUTURES|OPTIONS &period=TODAY|1W|1M|ALL|CUSTOM &from=&to=
                          the whole dashboard: summary, by segment, positions (one per share trade / structure leg),
                          strategies, pending entries, closed trades of the period, risk (capital, limits, alerts),
                          analytics, reconciliation against the ledger, market / feed state; `sequence` rises with time
    GET /pnl/stream       the same filters; server-sent events: `event: snapshot` with the body above every
                          PNL_STREAM_SECONDS (3 s while the market is open, 30 s otherwise), `: heartbeat` comments between,
                          closed after 30 minutes (EventSource reconnects and gets a fresh snapshot)
    GET /pnl/timeseries   ?interval=1m|5m|15m|1h &mode=ALL|PAPER|LIVE &trade=<id>  the book's P&L through the latest session
                          from Kite candles; with `trade`, that one trade's curve (a paper share trade since its entry)
    GET /pnl/journal/{trade_id}   the Scan dashboard's signal for a paper share trade's stock on its signal day (v2)
    GET /pnl/exits        ?account=ALL|<broker account id>  Exit watch: the live broker positions' stop losses (2 × ATR
                          trail, your own stop, or a hedge's strike), their status and the user's exit alerts
                          (docs/paper_pnl_dashboard/EXIT_WATCH.md; services/exit_watch)
    POST /pnl/exits/seen  {} or {"ids": [...]}: marks the user's own exit alerts seen. The ONE write on this router; it
                          touches nothing but the caller's exit_alerts documents.

v2 (owner, 4 Nov 2026 afternoon): `mode=ALL|PAPER|LIVE` and `account=ALL|paper|<broker account id>` on /pnl and /pnl/stream.
Live = the user's broker NET positions, read-only (services/paper_pnl/live.py: the Open positions workspace's read, cached 60 s;
no order call). The paper trades are read without applying exits (services/paper_pnl/book.py); prices follow the live -> Kite
close -> end-of-day rule (services/paper_pnl/prices.py) and are display-only: paper fills and exits stay on end-of-day prices at
the evening check.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import StreamingResponse

from deps import db, get_current_user
from services import paper_account as acct
from services import risk_profile
from services.paper_pnl import book as book_mod
from services.exit_watch import service as exit_watch
from services.paper_pnl import dashboard, journal, live, prices, timeseries

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


def _filters(segment: str, period: str, start: Optional[str], end: Optional[str], mode: str = "ALL",
             account: str = "ALL") -> dashboard.Filters:
    try:
        return dashboard.make_filters(segment, period, start, end, prices.today_ist(), mode, account)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))


async def _live_side(request: Request, uid: str) -> Tuple[live.BrokerBook, List[live.LiveLeg]]:
    bb = await live.read_broker_book(request, db, uid)
    return bb, live.legs(bb)


async def _check_account(request: Request, uid: str, filters: dashboard.Filters) -> None:
    """422 invalid_account for an account id that is not one of the user's broker accounts."""
    if filters.account in ("ALL", dashboard.PAPER_ACCOUNT_ID):
        return
    bb = await live.read_broker_book(request, db, uid)
    if filters.account not in {str(e.get("account_id")) for e in bb.entries if e.get("account_id")}:
        raise HTTPException(status_code=422, detail="invalid_account")


def live_lines(lives: List[live.LiveLeg], rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """The priced broker positions as curve lines (timeseries)."""
    by = {l.leg.position_key: l for l in lives}
    out = []
    for r in rows:
        l = by.get(r["position_id"])
        if l is None or not l.mapped or r["avg_price"] is None:
            continue
        out.append({"key": r["position_id"], "net_quantity": r["net_quantity"], "avg_price": r["avg_price"], "multiplier": 1.0,
                    "prev_close": r["prev_close"], "instrument": r["instrument"], "leg": l.leg})
    return out


async def _price_all(request: Request, uid: str, now: datetime):
    """(paper book, live legs, broker book, quotes, market): one resolver pass over the paper and the broker legs."""
    book = await book_mod.read_book(db, uid)
    bb, lives = await _live_side(request, uid)
    legs = [leg for item in book.open for leg in item.legs] + live.priceable(lives)
    quotes, market = await prices.resolve(legs, now=now)
    live.fill_expiries(lives, prices.expiry_of)
    return book, lives, bb, quotes, market


def live_view(bb: live.BrokerBook, lives: List[live.LiveLeg], quotes: Dict[str, Any], now: datetime) -> live.LiveView:
    accts = live.accounts(bb, now)
    rows = live.position_rows(lives, quotes, today=now.astimezone(prices.cfg.IST).date().isoformat(), now=now)
    return live.LiveView(positions=rows, accounts=accts, note=live.unavailable_note(bb, accts), legs=lives)


async def snapshot(request: Request, uid: str, filters: dashboard.Filters) -> Dict[str, Any]:
    """One dashboard body for the user. Read-only."""
    now = datetime.now(timezone.utc)
    book, lives, bb, quotes, market = await _price_all(request, uid, now)
    unders = {str(i.public.get("underlying") or "").upper() for i in book.open if i.kind == "strategy"}
    underlying_ltp = await prices.underlying_prices(unders, now=now) if unders else {}
    account = await acct.read(db, uid)
    try:
        limits = (await risk_profile.read(db, uid)).get("limits")
    except Exception as e:  # noqa: BLE001 — the limits are context here; the dashboard still answers without them
        logger.warning("desk_pnl: risk profile unreadable (%s)", type(e).__name__)
        limits = None
    body = dashboard.build(book, quotes, market, account, limits, filters, now=now, underlying_ltp=underlying_ltp,
                           live=live_view(bb, lives, quotes, now))
    body["as_of"] = now.astimezone(prices.cfg.IST).isoformat()
    body["sequence"] = int(time.time() * 1000)
    body["read_only"] = True
    return body


@router.get("/pnl")
async def pnl(request: Request, segment: str = Query("ALL", max_length=10), period: str = Query("TODAY", max_length=10),
              start: Optional[str] = Query(None, alias="from", max_length=10),
              end: Optional[str] = Query(None, alias="to", max_length=10),
              mode: str = Query("ALL", max_length=10), account: str = Query("ALL", max_length=80)) -> Dict[str, Any]:
    user = await get_current_user(request)
    filters = _filters(segment, period, start, end, mode, account)
    await _check_account(request, user["user_id"], filters)
    return await snapshot(request, user["user_id"], filters)


@router.get("/pnl/stream")
async def pnl_stream(request: Request, segment: str = Query("ALL", max_length=10), period: str = Query("TODAY", max_length=10),
                     start: Optional[str] = Query(None, alias="from", max_length=10),
                     end: Optional[str] = Query(None, alias="to", max_length=10),
                     mode: str = Query("ALL", max_length=10), account: str = Query("ALL", max_length=80)):
    user = await get_current_user(request)
    uid = user["user_id"]
    filters = _filters(segment, period, start, end, mode, account)
    await _check_account(request, uid, filters)

    async def gen():
        loop = asyncio.get_event_loop()
        started = loop.time()
        yield "retry: 3000\n\n"
        while loop.time() - started < STREAM_MAX_SECONDS:
            if await request.is_disconnected():
                return
            session_open = False
            try:
                body = await snapshot(request, uid, filters)
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
async def pnl_timeseries(request: Request, interval: str = Query("5m", max_length=4), mode: str = Query("ALL", max_length=10),
                         trade: Optional[str] = Query(None, max_length=200)) -> Dict[str, Any]:
    user = await get_current_user(request)
    uid = user["user_id"]
    if interval not in timeseries.ALLOWED:
        raise HTTPException(status_code=422, detail="invalid_interval")
    md = (mode or "ALL").upper()
    if md not in dashboard.MODES:
        raise HTTPException(status_code=422, detail="invalid_mode")
    now = datetime.now(timezone.utc)
    book, lives, bb, quotes, _ = await _price_all(request, uid, now)
    rows = live.position_rows(lives, quotes, today=now.astimezone(prices.cfg.IST).date().isoformat(), now=now)
    charges_by_key: Dict[str, Optional[float]] = {}
    for item in book.open:
        if not item.entered:
            continue
        for leg in item.legs:
            q = quotes.get(leg.position_key)
            charges_by_key[leg.position_key] = dashboard.leg_charges(item, leg, q.ltp if q else None)
    for r in rows:
        charges_by_key[r["position_id"]] = r["charges_estimated"]
    lines = live_lines(lives, rows)
    if trade:
        try:
            return await timeseries.build_trade(uid, book, quotes, interval, trade, charges_by_key=charges_by_key,
                                                live_lines=lines, now=now)
        except LookupError:
            raise HTTPException(status_code=404, detail="trade_not_found")
    paper_keys = {leg.position_key for item in book.open if item.entered for leg in item.legs}
    charges = sum((v or 0.0) for k, v in charges_by_key.items()
                  if (md in ("ALL", "PAPER") and k in paper_keys) or (md in ("ALL", "LIVE") and k not in paper_keys))
    return await timeseries.build(uid, book, quotes, interval, charges_estimated=round(charges, 2), now=now, mode=md,
                                  live_lines=lines)


@router.get("/pnl/journal/{trade_id}")
async def pnl_journal(request: Request, trade_id: str) -> Dict[str, Any]:
    """Signals at entry for one paper share trade; 404 journal_not_available for a structure, a broker position or a trade
    that is not the user's. Read-only."""
    user = await get_current_user(request)
    if len(trade_id) > 200:
        raise HTTPException(status_code=404, detail="journal_not_available")
    book = await book_mod.read_book(db, user["user_id"])
    body = await journal.journal(book, trade_id)
    if body is None:
        raise HTTPException(status_code=404, detail="journal_not_available")
    return body


@router.get("/pnl/exits")
async def pnl_exits(request: Request, account: str = Query("ALL", max_length=80)) -> Dict[str, Any]:
    """Exit watch for the user's live broker positions. Read-only: nothing here writes or reaches an order."""
    user = await get_current_user(request)
    try:
        acc = dashboard.clean_account(account)
        return await exit_watch.build(request, db, user["user_id"], acc)
    except ValueError as e:
        if str(e) == "invalid_account":
            raise HTTPException(status_code=422, detail="invalid_account")
        raise


@router.post("/pnl/exits/seen")
async def pnl_exits_seen(request: Request) -> Dict[str, Any]:
    """Mark the user's exit alerts seen: {} marks every unseen one, {"ids": [...]} only those."""
    user = await get_current_user(request)
    try:
        body = json.loads(await request.body() or b"{}")
        ids = exit_watch.clean_seen_body(body)
    except ValueError:                                   # bad JSON (json.JSONDecodeError is a ValueError) or a bad shape
        raise HTTPException(status_code=422, detail="invalid_body")
    return {"marked": await exit_watch.mark_seen(db, user["user_id"], ids)}
