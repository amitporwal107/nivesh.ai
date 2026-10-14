"""Smart trading desk — the user's own paper trades and price alerts (MongoDB). Nothing here places an order.

Every route is scoped to the signed-in user (`user_id` from deps.get_current_user): a trade or alert that is
not yours answers 404, the same as one that does not exist. Writes pass through the app's CSRF middleware like
every other /api write; nothing here is exempt.

Endpoints (all under /api/desk):
    POST   /paper-trades               — open a paper trade (long only)  → 201 {trade}
             {symbol, quantity, entry_price, stop_price, target_price|null, note?, source?: {kind, bucket?, signal_date?}}
    GET    /paper-trades?status=open|closed|all
                                       — {as_of, checked_through, trades, summary, ...}; applies the exit rule first
    POST   /paper-trades/{id}/close    — {exit_price?}: close at that price, or at the last end-of-day close ("manual")
    POST   /alerts                     — {symbol, condition: "above"|"below", level, note?} → 201 {alert}
    GET    /alerts?status=active|fired|all
                                       — {as_of, checked_through, alerts, ...}; applies the firing rule first
    DELETE /alerts/{id}                — 204

Limits: 100 open paper trades and 50 active alerts per user (409 open_trade_limit / active_alert_limit).
Errors are HTTPException with a short code in `detail` (invalid_symbol, stop_not_below_entry, trade_not_found,
trade_already_closed, no_close_available, prices_unavailable, ...).

Prices are END-OF-DAY bars of raw traded prices (nidp.prices_eod through the data platform); the rules, the
series choice and the idempotent writes live in services/desk_trading.py, shared with the evening evaluator
scripts/check_desk_alerts.py. When the data platform cannot be read, the lists still answer with the stored
trades and alerts, marks null and `marks_error` set; a mark is never made up.
"""
from __future__ import annotations

import json
import logging
from datetime import timedelta
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query, Request, Response

from deps import db, get_current_user
from services import desk_trading as svc

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/desk", tags=["desk"])

_ID_MAX = 64


async def _body(request: Request, *, allow_empty: bool = False) -> Any:
    raw = await request.body()
    if allow_empty and not raw.strip():
        return {}
    try:
        return json.loads(raw)
    except ValueError:
        raise HTTPException(status_code=422, detail="invalid_body")


def _input_error(exc: svc.DeskInputError) -> HTTPException:
    return HTTPException(status_code=422, detail=exc.code)


def _sort_key(stamp_field: str):
    return lambda doc: str(doc.get(stamp_field) or "")


def _price_context() -> Dict[str, Any]:
    return {"source": svc.SOURCE, "price_basis": svc.PRICE_BASIS}


def _as_of(bars: Dict[str, List[Dict[str, Any]]]):
    """(newest session read, the session every symbol with prices has been read through)."""
    latest = [b["date"] for b in (svc.last_close(v) for v in bars.values()) if b]
    return svc.latest_day(latest), svc.earliest_day(latest)


# ── paper trades ─────────────────────────────────────────────────────────────
@router.post("/paper-trades", status_code=201)
async def create_paper_trade(request: Request) -> Dict[str, Any]:
    user = await get_current_user(request)
    uid = user["user_id"]
    try:
        doc = svc.new_trade(uid, await _body(request))
    except svc.DeskInputError as exc:
        raise _input_error(exc)
    await svc.ensure_indexes(db)
    open_filter = {"user_id": uid, "status": "open"}
    if await db[svc.TRADES].count_documents(open_filter) >= svc.MAX_OPEN_TRADES:
        raise HTTPException(status_code=409, detail="open_trade_limit")
    await db[svc.TRADES].insert_one(doc)
    # Two requests that both counted 99 can both insert; the later count catches it and takes ours back.
    if await db[svc.TRADES].count_documents(open_filter) > svc.MAX_OPEN_TRADES:
        await db[svc.TRADES].delete_one({"_id": doc["_id"], "user_id": uid})
        raise HTTPException(status_code=409, detail="open_trade_limit")
    logger.info("desk: user %s opened paper trade %s (%s)", uid, doc["_id"], doc["symbol"])
    return {"trade": svc.public_trade(doc), **_price_context()}


@router.get("/paper-trades")
async def list_paper_trades(request: Request, status_filter: str = Query("all", alias="status")) -> Dict[str, Any]:
    user = await get_current_user(request)
    uid = user["user_id"]
    if status_filter not in ("open", "closed", "all"):
        raise HTTPException(status_code=422, detail="invalid_status")
    await svc.ensure_indexes(db)

    open_docs = await db[svc.TRADES].find({"user_id": uid, "status": "open"}).sort("opened_at", -1).to_list(svc.MAX_OPEN_TRADES * 2)
    starts = svc.fetch_starts(open_docs, "opened_at")
    bars, errors = await svc.fetch_bars_many(starts) if starts else ({}, {})
    evaluated, counts = await svc.apply_trade_exits(db, open_docs, bars)

    # Read closed trades after the exits are written, so a trade closed just now is listed once, as closed.
    closed_docs = await db[svc.TRADES].find({"user_id": uid, "status": "closed"}).sort("closed_at", -1).to_list(svc.MAX_CLOSED_LISTED + 1)
    partial = len(closed_docs) > svc.MAX_CLOSED_LISTED
    closed_docs = closed_docs[: svc.MAX_CLOSED_LISTED]
    closed_ids = {d["_id"] for d in closed_docs}

    trades: List[Dict[str, Any]] = []
    for doc in sorted((d for d in evaluated if d.get("status") == "open" and d["_id"] not in closed_ids),
                      key=_sort_key("opened_at"), reverse=True):
        mark, mark_error = svc.mark_for(doc["symbol"], bars, errors)
        trades.append(svc.public_trade(doc, mark, mark_error, counts["checked_through"].get(doc["_id"])))
    trades.extend(svc.public_trade(d) for d in closed_docs)

    as_of, checked_through = _as_of(bars)
    return {
        "as_of": as_of.isoformat() if as_of else None,
        "checked_through": checked_through.isoformat() if checked_through else None,
        **_price_context(),
        "exit_rule": svc.EXIT_RULE,
        "marks_error": svc.marks_error(errors, len(starts)),
        "status": status_filter,
        "trades": [t for t in trades if status_filter == "all" or t["status"] == status_filter],
        "summary": svc.summarize(trades, partial=partial),
        "limits": {"max_open": svc.MAX_OPEN_TRADES},
        "evaluated_at": svc.utcnow().isoformat(),
    }


@router.post("/paper-trades/{trade_id}/close")
async def close_paper_trade(request: Request, trade_id: str) -> Dict[str, Any]:
    """Close at `exit_price`, or at the last end-of-day close when none is given (reason "manual").
    The exit rule is checked first: a trade the bars show already stopped out or at target is closed that
    way and the request answers 409 trade_already_closed."""
    user = await get_current_user(request)
    uid = user["user_id"]
    body = await _body(request, allow_empty=True)
    if not isinstance(body, dict):
        raise HTTPException(status_code=422, detail="invalid_body")
    if set(body) - {"exit_price"}:
        raise HTTPException(status_code=422, detail="unknown_field")
    exit_price: Optional[float] = None
    if body.get("exit_price") is not None:
        try:
            exit_price = svc.clean_price(body["exit_price"], "invalid_exit_price")
        except svc.DeskInputError as exc:
            raise _input_error(exc)

    doc = await db[svc.TRADES].find_one({"_id": trade_id, "user_id": uid}) if len(trade_id) <= _ID_MAX else None
    if not doc:
        raise HTTPException(status_code=404, detail="trade_not_found")
    if doc.get("status") != "open":
        raise HTTPException(status_code=409, detail="trade_already_closed")

    start = svc.ist_date(doc["opened_at"]) - timedelta(days=svc.LOOKBACK_DAYS)
    try:
        bars: Optional[List[Dict[str, Any]]] = await svc.fetch_bars(doc["symbol"], start)
    except svc.PricesUnavailable as exc:
        logger.warning("desk: no end-of-day bars for %s while closing %s: %s", doc["symbol"], trade_id, exc)
        if exit_price is None:
            raise HTTPException(status_code=503, detail="prices_unavailable")
        bars = None             # the user gave the price; the close does not need a mark

    session = None
    note = None
    if bars is not None:
        exit_, _ = svc.find_trade_exit(doc, bars)
        if exit_ is not None:
            await svc.close_trade(db, doc, **exit_)
            raise HTTPException(status_code=409, detail="trade_already_closed")
        if exit_price is None:
            bar = svc.last_close(bars)
            if bar is None:
                raise HTTPException(status_code=409, detail="no_close_available")
            exit_price, session = bar["close"], bar["date"]
            note = f"Closed at the last end-of-day close ({bar['date'].isoformat()})."

    stored, mine = await svc.close_trade(db, doc, exit_reason="manual", exit_price=exit_price,
                                         exit_session=session, exit_note=note)
    if not mine or stored is None:
        raise HTTPException(status_code=409, detail="trade_already_closed")
    logger.info("desk: user %s closed paper trade %s at %s", uid, trade_id, exit_price)
    return {"trade": svc.public_trade(stored), **_price_context()}


# ── price alerts ─────────────────────────────────────────────────────────────
@router.post("/alerts", status_code=201)
async def create_alert(request: Request) -> Dict[str, Any]:
    user = await get_current_user(request)
    uid = user["user_id"]
    try:
        doc = svc.new_alert(uid, await _body(request))
    except svc.DeskInputError as exc:
        raise _input_error(exc)
    await svc.ensure_indexes(db)
    active_filter = {"user_id": uid, "status": "active"}
    if await db[svc.ALERTS].count_documents(active_filter) >= svc.MAX_ACTIVE_ALERTS:
        raise HTTPException(status_code=409, detail="active_alert_limit")
    await db[svc.ALERTS].insert_one(doc)
    if await db[svc.ALERTS].count_documents(active_filter) > svc.MAX_ACTIVE_ALERTS:
        await db[svc.ALERTS].delete_one({"_id": doc["_id"], "user_id": uid})
        raise HTTPException(status_code=409, detail="active_alert_limit")
    logger.info("desk: user %s set alert %s (%s %s %s)", uid, doc["_id"], doc["symbol"], doc["condition"], doc["level"])
    return {"alert": svc.public_alert(doc), **_price_context()}


@router.get("/alerts")
async def list_alerts(request: Request, status_filter: str = Query("all", alias="status")) -> Dict[str, Any]:
    user = await get_current_user(request)
    uid = user["user_id"]
    if status_filter not in ("active", "fired", "all"):
        raise HTTPException(status_code=422, detail="invalid_status")
    await svc.ensure_indexes(db)

    active_docs = await db[svc.ALERTS].find({"user_id": uid, "status": "active"}).sort("created_at", -1).to_list(svc.MAX_ACTIVE_ALERTS * 2)
    starts = svc.fetch_starts(active_docs, "created_at")
    bars, errors = await svc.fetch_bars_many(starts) if starts else ({}, {})
    evaluated, counts = await svc.apply_alert_fires(db, active_docs, bars)

    fired_docs = await db[svc.ALERTS].find({"user_id": uid, "status": "fired"}).sort("fired_at", -1).to_list(svc.MAX_FIRED_LISTED)
    fired_ids = {d["_id"] for d in fired_docs}

    alerts: List[Dict[str, Any]] = []
    for doc in sorted((d for d in evaluated if d.get("status") == "active" and d["_id"] not in fired_ids),
                      key=_sort_key("created_at"), reverse=True):
        mark, mark_error = svc.mark_for(doc["symbol"], bars, errors)
        alerts.append(svc.public_alert(doc, mark, mark_error, counts["checked_through"].get(doc["_id"])))
    alerts.extend(svc.public_alert(d) for d in fired_docs)

    as_of, checked_through = _as_of(bars)
    return {
        "as_of": as_of.isoformat() if as_of else None,
        "checked_through": checked_through.isoformat() if checked_through else None,
        **_price_context(),
        "firing_rule": svc.FIRING_RULE,
        "marks_error": svc.marks_error(errors, len(starts)),
        "status": status_filter,
        "alerts": [a for a in alerts if status_filter == "all" or a["status"] == status_filter],
        "counts": {
            "active": sum(1 for a in alerts if a["status"] == "active"),
            "fired": sum(1 for a in alerts if a["status"] == "fired"),
        },
        "limits": {"max_active": svc.MAX_ACTIVE_ALERTS},
        "evaluated_at": svc.utcnow().isoformat(),
    }


@router.delete("/alerts/{alert_id}", status_code=204, response_class=Response)
async def delete_alert(request: Request, alert_id: str) -> Response:
    user = await get_current_user(request)
    uid = user["user_id"]
    res = await db[svc.ALERTS].delete_one({"_id": alert_id, "user_id": uid}) if len(alert_id) <= _ID_MAX else None
    if res is None or res.deleted_count == 0:
        raise HTTPException(status_code=404, detail="alert_not_found")
    logger.info("desk: user %s deleted alert %s", uid, alert_id)
    return Response(status_code=204)
