"""Smart trading desk — the user's own paper trades and price alerts (MongoDB). Nothing here places an order.

Every route is scoped to the signed-in user (`user_id` from deps.get_current_user): a trade or alert that is
not yours answers 404, the same as one that does not exist. Writes pass through the app's CSRF middleware like
every other /api write; nothing here is exempt.

Endpoints (all under /api/desk):
    POST   /paper-trades               — open a paper trade (long only)  → 201 {trade}
             {symbol, quantity, entry_price, stop_price, target_price|null, note?, source?: {kind, bucket?, signal_date?},
              entry_rule?: "at_once"|"break_above"|"pullback_to", entry_window_sessions?, max_hold_sessions?,
              signal_at?, strategy_version?, rationale?}       — PRD §13.4; costs, MFE / MAE and net P&L come back on reads
    GET    /paper-trades?status=open|closed|all
                                       — {as_of, checked_through, trades, summary, ...}; applies the exit rule first
    POST   /paper-trades  with kind "strategy" — a futures / option structure (services/desk_strategy_trades.py, rules
                                         desk-paper-v3): {kind, underlying, direction, family, reference_price, stop_underlying?,
                                         target_underlying?, legs[1-4], signal{signal_at, rule_version, evidence_summary, ...},
                                         strategy_plan_id?, max_hold_sessions?, note?}; the signal and legs are saved once, never edited
    GET    /paper-trades/{id}          — one trade with its lifecycle log (and, for a strategy, its signal); read-only
    POST   /paper-trades/{id}/close    — {exit_price?}: close at that price, or at the last end-of-day close ("manual");
                                         a trade whose conditional entry was not reached is "cancelled" (no P&L)
    POST   /alerts                     — {condition, ...the condition's fields, note?} → 201 {alert}
             above | below  {symbol, level}            filing    {symbol, impact?: "any"|"high"}
             category       {category, symbol?}        volume    {symbol, multiple}
             scanner        {symbol, stage?}           sector    {index, threshold_pct, direction?}
             risk           {symbol, level}            (rules and sources: services/desk_alerts.py)
    GET    /alerts?status=active|fired|all
                                       — {as_of, checked_through, alerts, conditions, check_errors, ...}; checks every
                                         active alert first. A fired alert carries `reason` and `evidence`
    DELETE /alerts/{id}                — 204

Limits: 100 open paper trades and 50 active alerts per user (409 open_trade_limit / active_alert_limit). An active
alert identical to one the user already has (same condition, stock, level and settings) is 409 duplicate_alert.
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
from services import desk_alerts as alerts_svc
from services import desk_strategy_trades as strat
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
    body = await _body(request)
    try:
        if isinstance(body, dict) and body.get("kind") == strat.KIND:
            doc = strat.new_strategy_trade(uid, body)
        else:
            if isinstance(body, dict) and "kind" in body:
                if body["kind"] != "cash":
                    raise svc.DeskInputError("invalid_kind")
                body = {k: v for k, v in body.items() if k != "kind"}
            doc = svc.new_trade(uid, body)
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
    return {"trade": _public(doc), **_price_context()}


def _public(doc: Dict[str, Any]) -> Dict[str, Any]:
    return strat.public_strategy_trade(doc, detail=True) if doc.get("kind") == strat.KIND else svc.public_trade(doc)


@router.get("/paper-trades")
async def list_paper_trades(request: Request, status_filter: str = Query("all", alias="status")) -> Dict[str, Any]:
    user = await get_current_user(request)
    uid = user["user_id"]
    if status_filter not in ("open", "closed", "all"):
        raise HTTPException(status_code=422, detail="invalid_status")
    await svc.ensure_indexes(db)

    all_open = await db[svc.TRADES].find({"user_id": uid, "status": "open"}).sort("opened_at", -1).to_list(svc.MAX_OPEN_TRADES * 2)
    open_docs = [d for d in all_open if d.get("kind") != strat.KIND]
    strategy_open = [d for d in all_open if d.get("kind") == strat.KIND]
    starts = svc.fetch_starts(open_docs, "opened_at")
    bars, errors = await svc.fetch_bars_many(starts) if starts else ({}, {})
    evaluated, counts = await svc.apply_trade_exits(db, open_docs, bars)
    strategy_evaluated, strategy_sims, strategy_errors = await strat.apply_exits(db, strategy_open) if strategy_open else ([], {}, {})

    # Read closed trades after the exits are written, so a trade closed just now is listed once, as closed.
    closed_docs = await db[svc.TRADES].find({"user_id": uid, "status": "closed"}).sort("closed_at", -1).to_list(svc.MAX_CLOSED_LISTED + 1)
    partial = len(closed_docs) > svc.MAX_CLOSED_LISTED
    closed_docs = closed_docs[: svc.MAX_CLOSED_LISTED]
    closed_ids = {d["_id"] for d in closed_docs}

    trades: List[Dict[str, Any]] = []
    for doc in sorted((d for d in evaluated if d.get("status") == "open" and d["_id"] not in closed_ids),
                      key=_sort_key("opened_at"), reverse=True):
        mark, mark_error = svc.mark_for(doc["symbol"], bars, errors)
        trades.append(svc.public_trade(doc, mark, mark_error, counts["checked_through"].get(doc["_id"]),
                                       sim=counts["paths"].get(doc["_id"])))
    for doc in sorted((d for d in strategy_evaluated if d.get("status") == "open" and d["_id"] not in closed_ids),
                      key=_sort_key("opened_at"), reverse=True):
        trades.append(strat.public_strategy_trade(doc, strategy_sims.get(doc["_id"]), strategy_errors.get(doc["_id"]), detail=True))
    trades.sort(key=lambda t: str(t.get("opened_at") or ""), reverse=True)        # cash and strategy trades, newest first
    trades.extend(_public(d) for d in closed_docs)

    as_of, checked_through = _as_of(bars)
    return {
        "as_of": as_of.isoformat() if as_of else None,
        "checked_through": checked_through.isoformat() if checked_through else None,
        **_price_context(),
        "exit_rule": svc.EXIT_RULE,
        "entry_rules": svc.ENTRY_RULE_TEXT,
        "rules_version": svc.RULES_VERSION,
        "cost_model": svc.COST_MODEL,
        "orders": svc.ORDERS_NOTE,
        "marks_error": svc.marks_error({**errors, **strategy_errors}, len(starts) + len(strategy_open)),
        "strategy_rules_version": strat.RULES_VERSION,
        "strategy_families": strat.FAMILIES,
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
    if doc.get("kind") == strat.KIND:
        return await _close_strategy(doc, body)

    start = svc.ist_date(doc["opened_at"]) - timedelta(days=svc.LOOKBACK_DAYS)
    try:
        bars: Optional[List[Dict[str, Any]]] = await svc.fetch_bars(doc["symbol"], start)
    except svc.PricesUnavailable as exc:
        logger.warning("desk: no end-of-day bars for %s while closing %s: %s", doc["symbol"], trade_id, exc)
        # A conditional entry cannot be closed blind: without bars nobody knows whether it was filled.
        if exit_price is None or (doc.get("entry_rule") or "at_once") != "at_once":
            raise HTTPException(status_code=503, detail="prices_unavailable")
        bars = None             # the user gave the price; the close does not need a mark

    session = None
    note = None
    sim: Optional[Dict[str, Any]] = None
    reason = "manual"
    if bars is not None:
        sim = svc.simulate(doc, bars)
        if sim["exit"] is not None:
            await svc.close_trade(db, doc, **sim["exit"], sim=sim)
            raise HTTPException(status_code=409, detail="trade_already_closed")
        if sim["entry_status"] not in svc.ENTERED:
            # Never filled: closing it cancels the plan; there is no position, so no price and no P&L.
            sim["entry_status"] = "not_reached"
            reason, exit_price, note = "cancelled", None, svc.CANCELLED_NOTE
        elif exit_price is None:
            bar = svc.last_close(bars)
            if bar is None:
                raise HTTPException(status_code=409, detail="no_close_available")
            exit_price, session = bar["close"], bar["date"]
            note = f"Closed at the last end-of-day close ({bar['date'].isoformat()})."

    stored, mine = await svc.close_trade(db, doc, exit_reason=reason, exit_price=exit_price,
                                         exit_session=session, exit_note=note, sim=sim)
    if not mine or stored is None:
        raise HTTPException(status_code=409, detail="trade_already_closed")
    logger.info("desk: user %s closed paper trade %s at %s", uid, trade_id, exit_price)
    return {"trade": svc.public_trade(stored), **_price_context()}


async def _close_strategy(doc: Dict[str, Any], body: Dict[str, Any]) -> Dict[str, Any]:
    """Close a strategy trade at the last end-of-day marks (reason "manual"), after the exit rules were checked: a
    trade the data shows already stopped, at target, expired or timed out is closed that way and answers 409."""
    if body:
        raise HTTPException(status_code=422, detail="unknown_field")        # a strategy closes at its marks, never at a typed price
    try:
        bars, rows = await strat.fetch_inputs(doc)
    except svc.PricesUnavailable as exc:
        logger.warning("desk: no prices for strategy trade %s while closing: %s", doc["_id"], exc)
        raise HTTPException(status_code=503, detail="prices_unavailable")
    sim = strat.simulate_strategy(doc, bars, rows)
    if sim["exit"] is not None:
        await strat.close_strategy_trade(db, doc, **sim["exit"], sim=sim)
        raise HTTPException(status_code=409, detail="trade_already_closed")
    last = sim["last_mark_session"]
    note = (f"Closed at the last end-of-day marks ({last.isoformat()})." if last
            else "Closed with no end-of-day marks on record for it yet; it has no P&L.")
    stored, mine = await strat.close_strategy_trade(db, doc, exit_reason="manual", exit_session=last, exit_note=note, sim=sim)
    if not mine or stored is None:
        raise HTTPException(status_code=409, detail="trade_already_closed")
    logger.info("desk: user %s closed strategy paper trade %s", doc["user_id"], doc["_id"])
    return {"trade": strat.public_strategy_trade(stored, detail=True), **_price_context()}


@router.get("/paper-trades/{trade_id}")
async def get_paper_trade(request: Request, trade_id: str) -> Dict[str, Any]:
    """One trade with its lifecycle log. Read-only: nothing is written, even when the data shows an exit that the
    next list read will record (it is reported as `pending_exit`). A strategy trade carries its immutable `signal`."""
    user = await get_current_user(request)
    uid = user["user_id"]
    doc = await db[svc.TRADES].find_one({"_id": trade_id, "user_id": uid}) if len(trade_id) <= _ID_MAX else None
    if not doc:
        raise HTTPException(status_code=404, detail="trade_not_found")
    if doc.get("kind") == strat.KIND:
        sim, error = None, None
        if doc.get("status") == "open":
            try:
                bars, rows = await strat.fetch_inputs(doc)
                sim = strat.simulate_strategy(doc, bars, rows)
            except svc.PricesUnavailable:
                error = svc.PRICES_UNAVAILABLE
        trade = strat.public_strategy_trade(doc, sim, error, detail=True)
        pending = sim["exit"] if sim else None
        trade["pending_exit"] = ({"exit_reason": pending["exit_reason"], "exit_session": pending["exit_session"].isoformat(),
                                  "exit_note": pending["exit_note"]} if pending else None)
        return {"trade": trade, **_price_context()}
    mark = mark_error = sim = None
    pending = None
    if doc.get("status") == "open":
        try:
            bars = await svc.fetch_bars(doc["symbol"], svc.ist_date(doc["opened_at"]) - timedelta(days=svc.LOOKBACK_DAYS))
            sim = svc.simulate(doc, bars)
            mark, mark_error = svc.mark_for(doc["symbol"], {doc["symbol"]: bars}, {})
            pending = sim["exit"]
        except svc.PricesUnavailable:
            mark_error = svc.PRICES_UNAVAILABLE
    trade = svc.public_trade(doc, mark, mark_error, sim=sim)
    trade["kind"] = "cash"
    trade["events"] = _cash_events(trade)
    trade["pending_exit"] = ({"exit_reason": pending["exit_reason"], "exit_session": pending["exit_session"].isoformat(),
                              "exit_note": pending["exit_note"]} if pending else None)
    return {"trade": trade, **_price_context()}


def _cash_events(trade: Dict[str, Any]) -> List[Dict[str, Any]]:
    """The lifecycle of a share trade, worked out from its stored fields (state changes only)."""
    events = [{"type": "created", "at": trade["opened_at"], "session": None, "text": "Paper trade recorded."}]
    if trade.get("entry_status") in svc.ENTERED:
        events.append({"type": "entered", "at": trade.get("entry_session") or trade["opened_at"], "session": trade.get("entry_session"),
                       "text": "Entry assumed when recorded." if trade["entry_status"] == "assumed" else "Entry level reached."})
    if trade["status"] == "closed":
        events.append({"type": "closed", "at": trade.get("closed_at"), "session": trade.get("exit_session"), "reason": trade.get("exit_reason"),
                       "text": trade.get("exit_note") or f"Closed ({trade.get('exit_reason')})."})
    return events


# ── alerts (price, filings, categories, volume, scanner, sector, risk — services/desk_alerts.py) ──────────────
@router.post("/alerts", status_code=201)
async def create_alert(request: Request) -> Dict[str, Any]:
    user = await get_current_user(request)
    uid = user["user_id"]
    try:
        doc = alerts_svc.new_alert(uid, await _body(request))
    except svc.DeskInputError as exc:
        raise _input_error(exc)
    await svc.ensure_indexes(db)
    active_filter = {"user_id": uid, "status": "active"}
    # Deduplicated: the same condition on the same stock with the same level and settings is one alert.
    key = alerts_svc.dedupe_key(doc)
    mine = await db[svc.ALERTS].find(active_filter).to_list(svc.MAX_ACTIVE_ALERTS * 2)
    if any(alerts_svc.dedupe_key(d) == key for d in mine):
        raise HTTPException(status_code=409, detail="duplicate_alert")
    if len(mine) >= svc.MAX_ACTIVE_ALERTS or await db[svc.ALERTS].count_documents(active_filter) >= svc.MAX_ACTIVE_ALERTS:
        raise HTTPException(status_code=409, detail="active_alert_limit")
    await db[svc.ALERTS].insert_one(doc)
    if await db[svc.ALERTS].count_documents(active_filter) > svc.MAX_ACTIVE_ALERTS:
        await db[svc.ALERTS].delete_one({"_id": doc["_id"], "user_id": uid})
        raise HTTPException(status_code=409, detail="active_alert_limit")
    logger.info("desk: user %s set alert %s (%s)", uid, doc["_id"], alerts_svc.describe(doc))
    return {"alert": alerts_svc.public_alert(doc), **_price_context()}


@router.get("/alerts")
async def list_alerts(request: Request, status_filter: str = Query("all", alias="status")) -> Dict[str, Any]:
    user = await get_current_user(request)
    uid = user["user_id"]
    if status_filter not in ("active", "fired", "all"):
        raise HTTPException(status_code=422, detail="invalid_status")
    await svc.ensure_indexes(db)

    active_docs = await db[svc.ALERTS].find({"user_id": uid, "status": "active"}).sort("created_at", -1).to_list(svc.MAX_ACTIVE_ALERTS * 2)
    starts = alerts_svc.bar_starts(active_docs)
    bars, errors = await svc.fetch_bars_many(starts) if starts else ({}, {})
    evaluated, counts = await alerts_svc.evaluate(db, active_docs, bars)

    fired_docs = await db[svc.ALERTS].find({"user_id": uid, "status": "fired"}).sort("fired_at", -1).to_list(svc.MAX_FIRED_LISTED)
    fired_ids = {d["_id"] for d in fired_docs}

    alerts: List[Dict[str, Any]] = []
    for doc in sorted((d for d in evaluated if d.get("status") == "active" and d["_id"] not in fired_ids),
                      key=_sort_key("created_at"), reverse=True):
        mark, mark_error = svc.mark_for(doc["symbol"], bars, errors) if doc.get("symbol") in starts else (None, None)
        alerts.append(alerts_svc.public_alert(doc, mark, mark_error, counts["checked_through"].get(doc["_id"]),
                                              counts["check_errors"].get(doc["_id"])))
    alerts.extend(alerts_svc.public_alert(d) for d in fired_docs)

    as_of, checked_through = _as_of(bars)
    return {
        "as_of": as_of.isoformat() if as_of else None,
        "checked_through": checked_through.isoformat() if checked_through else None,
        **_price_context(),
        "firing_rule": svc.FIRING_RULE,
        "marks_error": svc.marks_error(errors, len(starts)),
        "check_errors": sorted(set(counts["check_errors"].values())),
        "status": status_filter,
        "alerts": [a for a in alerts if status_filter == "all" or a["status"] == status_filter],
        "counts": {
            "active": sum(1 for a in alerts if a["status"] == "active"),
            "fired": sum(1 for a in alerts if a["status"] == "fired"),
        },
        "limits": {"max_active": svc.MAX_ACTIVE_ALERTS},
        **alerts_svc.catalogue(),
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
