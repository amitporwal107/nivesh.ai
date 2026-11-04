"""Paper positions from fills (DESIGN.md §3 `spt_positions`, §5; WF §12.5, §13, §16, §17.2).

CREATED ONLY ON THE FIRST FILL (WF §12.5). The position document is inserted with its first entry fill already applied;
unique indexes allow one position per entry order and one OPEN position per (user, symbol, direction).

QUANTITY = entry fills − exit fills. Every fill is applied once: the update is conditional on the fill id not yet being
in `fill_ids` and on the version read, so a replay changes nothing.

COST BASIS: WEIGHTED AVERAGE of the entry fills' prices (slippage included, costs excluded); exit fills never change it.
Costs are kept apart: `entry_costs_rs` (every entry fill's charges) and `exit_costs_rs`.

REALISED P&L (WF §16.3, long equity). Per exit fill, at the time:
    gross = (exit price − average entry) × q
    net   = gross − the fill's charges − the entry charges allocated to q (entry_costs × q / entry quantity)
At close the totals are set EXACTLY from the fill ledger:
    realized_gross_rs = exit proceeds − entry cost          (Σ exit values − Σ entry values)
    realized_net_rs   = realized_gross_rs − entry charges − exit charges
R MULTIPLE = net P&L / initial risk, initial risk = (average entry − the plan's initial stop) × entry quantity (the
price risk the plan accepted; costs not included). MFE / MAE: the best and worst executable price seen while open (the
live bid, else LTP, and every fill), in rupees on the entry quantity and in R.
Unrealised P&L is display only, from the live bid (else LTP): (price − average) × open quantity, and net of the entry
charges of the open shares and the estimated charges of selling them.

STATES (constants.POS_*): OPEN at the first fill → MONITORING once the monitor has looked at it → PARTIALLY_EXITED after
a partial exit fill → MONITORING → CLOSING while a full exit order is live → CLOSED at quantity 0. EXIT_PENDING: an exit
decided at the evening pass (trend, time, a stop breached without a live exit) waits for the next session's first live
quote. RECONCILIATION_REQUIRED: set by reconcile.py; no automatic exit orders, a manual exit is still allowed.

CLOSE AND THE ONE RELEASE. The close is set in the same conditional update as the last exit fill, with
`release: {state: "pending"}`. `release_once` then claims it (pending → claimed, conditional) and only the claimer calls
`paper_account.release(db, user_id, <the reservation's funding_rs, read from the account>, net_pnl=<realized_net_rs>,
trade_id=<the entry order id>)`, which unblocks the funding, credits the net P&L to cash and gives the risk budget back
in one update. `paper_account.release` re-applies funding and P&L when its reservation is already gone, so it must be
called once: a missing reservation is recorded (`missing_reservation`, for reconciliation) and never "fixed" here. A
claim left by a process that died is retried after RELEASE_CLAIM_GRACE_S, only while the reservation is still on the
account. Realised P&L of partial exits is credited at close, in that one call (the reservation is per trade).
"""
from __future__ import annotations

import logging
import math
import uuid
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from pymongo.errors import DuplicateKeyError

from services import paper_account as acct
from services.spt import constants as C
from services.spt import events as ev

from . import execution, store

logger = logging.getLogger(__name__)

RELEASE_CLAIM_GRACE_S = 600
MAX_RETRIES = 6
SERVICE_ACTOR = "spt-monitor"


def _f(x: Any) -> Optional[float]:
    return execution._num(x)


async def _emit(db, pos: Dict[str, Any], event_type: str, key: str, payload: Dict[str, Any],
                now: Optional[datetime] = None) -> None:
    await ev.emit(db, event_type, idempotency_key=key, source_service=store.SOURCE,
                  payload={"position_id": pos["_id"], "symbol": pos.get("symbol"), **payload},
                  occurred_at=store.iso(now), correlation_id=pos.get("correlation_id"), account_id=pos.get("user_id"),
                  instrument_id=pos.get("symbol"))


# ── pure: fills → position fields ────────────────────────────────────────────────────────────────────────────────────

def initial_risk(avg: Optional[float], stop: Optional[float], qty: int) -> Optional[float]:
    if avg is None or stop is None or qty <= 0 or stop >= avg:
        return None
    return round((avg - stop) * qty, 2)


def new_position(order: Dict[str, Any], rec: Dict[str, Any], now: datetime) -> Dict[str, Any]:
    """The position document of an ENTRY order's first fill, that fill applied."""
    plan = dict(order.get("exit_plan") or {})
    stop = _f(plan.get("stop_loss"))
    base: Dict[str, Any] = {
        "_id": str(uuid.uuid4()), "user_id": order["user_id"], "account_id": order["user_id"],
        "symbol": order["symbol"], "exchange": order.get("exchange") or "NSE", "direction": "long",
        "state": C.POS_OPEN, "is_open": True, "entry_order_id": order["_id"], "proposal_id": order.get("proposal_id"),
        "opportunity_id": order.get("opportunity_id"), "correlation_id": order.get("correlation_id"),
        "risk": dict(order.get("risk") or {}), "exit_plan": plan,
        "planned": {"entry": order.get("planned_entry_price"), "stop": stop, "quantity": order.get("quantity"),
                    "target_1": _f(plan.get("target_1")), "target_2": _f(plan.get("target_2"))},
        "stop_loss": stop, "initial_stop": stop, "target_1": _f(plan.get("target_1")), "target_2": _f(plan.get("target_2")),
        "t1_exit_fraction": float(plan.get("t1_exit_fraction") or 0.5),
        "move_stop_to_breakeven_at_t1": plan.get("move_stop_to_breakeven_at_t1", True) is not False,
        "trail": plan.get("trail") or None, "trend_exit": plan.get("trend_exit") or None,
        "max_hold_sessions": plan.get("max_hold_sessions"), "t1_done": False,
        "quantity": 0, "entry_qty": 0, "exit_qty": 0, "avg_entry_price": None, "entry_value_rs": 0.0,
        "entry_costs_rs": 0.0, "exit_value_rs": 0.0, "exit_costs_rs": 0.0, "realized_gross_rs": 0.0,
        "realized_net_rs": 0.0, "slippage_rs": 0.0, "initial_risk_rs": None, "max_price": None, "min_price": None,
        "mark": None, "fill_ids": [], "exit_fills": [], "exit_seq": 0, "live_exit_order_id": None, "pending_exit": None,
        "modifications": [], "stop_history": [{"at": store.iso(now), "stop": stop, "reason": "initial", "version": 1,
                                               "by": "exit_plan"}],
        "stop_version": 1, "sessions_held": 0, "evening_day": None, "opened_at": rec.get("at") or store.iso(now),
        "closed_at": None, "exit_reason": None, "release": None, "outcome": None, "reconciliation": None,
        "cost_model": order.get("cost_model"), "execution_version": C.EXECUTION_VERSION,
        "created_at": store.iso(now), "updated_at": store.iso(now), "version": 0,
    }
    base.update(entry_fill_fields(base, rec))
    base["fill_ids"] = [rec["fill_id"]]
    return base


def entry_fill_fields(pos: Dict[str, Any], rec: Dict[str, Any]) -> Dict[str, Any]:
    q, p = int(rec["quantity"]), float(rec["price"])
    eq = int(pos.get("entry_qty") or 0)
    avg = float(pos.get("avg_entry_price") or 0.0)
    new_eq = eq + q
    new_avg = (avg * eq + p * q) / new_eq
    out = {"entry_qty": new_eq, "quantity": int(pos.get("quantity") or 0) + q, "avg_entry_price": round(new_avg, 4),
           "entry_value_rs": round(float(pos.get("entry_value_rs") or 0) + float(rec["value_rs"]), 2),
           "entry_costs_rs": round(float(pos.get("entry_costs_rs") or 0) + float(rec["costs"]["total"]), 2),
           "slippage_rs": round(float(pos.get("slippage_rs") or 0) + float(rec.get("slippage_rs") or 0), 2),
           "initial_risk_rs": initial_risk(new_avg, _f(pos.get("initial_stop")), new_eq),
           "max_price": max(x for x in (pos.get("max_price"), p) if x is not None),
           "min_price": min(x for x in (pos.get("min_price"), p) if x is not None)}
    return out


def exit_fill_fields(pos: Dict[str, Any], rec: Dict[str, Any], order: Dict[str, Any], *, closable: bool,
                     now: datetime) -> Dict[str, Any]:
    q, p = int(rec["quantity"]), float(rec["price"])
    held = int(pos.get("quantity") or 0)
    q = min(q, held)
    eq = int(pos.get("entry_qty") or 0) or 1
    avg = float(pos.get("avg_entry_price") or 0.0)
    alloc = float(pos.get("entry_costs_rs") or 0.0) * q / eq
    gross = (p - avg) * q
    net = gross - float(rec["costs"]["total"]) - alloc
    left = held - q
    out: Dict[str, Any] = {
        "quantity": left, "exit_qty": int(pos.get("exit_qty") or 0) + q,
        "exit_value_rs": round(float(pos.get("exit_value_rs") or 0) + float(rec["value_rs"]), 2),
        "exit_costs_rs": round(float(pos.get("exit_costs_rs") or 0) + float(rec["costs"]["total"]), 2),
        "slippage_rs": round(float(pos.get("slippage_rs") or 0) + float(rec.get("slippage_rs") or 0), 2),
        "realized_gross_rs": round(float(pos.get("realized_gross_rs") or 0) + gross, 2),
        "realized_net_rs": round(float(pos.get("realized_net_rs") or 0) + net, 2),
        "max_price": max(x for x in (pos.get("max_price"), p) if x is not None),
        "min_price": min(x for x in (pos.get("min_price"), p) if x is not None),
    }
    if left <= 0 and closable:
        out["realized_gross_rs"] = round(out["exit_value_rs"] - float(pos.get("entry_value_rs") or 0), 2)
        out["realized_net_rs"] = round(out["realized_gross_rs"] - float(pos.get("entry_costs_rs") or 0)
                                       - out["exit_costs_rs"], 2)
        out.update(state=C.POS_CLOSED, is_open=False, closed_at=store.iso(now),
                   exit_reason=order.get("reason") or "manual", exit_gap=bool(order.get("gap")),
                   release={"state": "pending", "net_pnl_rs": out["realized_net_rs"], "at": store.iso(now)})
    elif pos.get("state") != C.POS_CLOSING:
        out["state"] = C.POS_PARTIALLY_EXITED
    return out


def exit_fill_summary(rec: Dict[str, Any], order: Dict[str, Any], gross: float, net: float) -> Dict[str, Any]:
    return {"fill_id": rec["fill_id"], "order_id": order["_id"], "reason": order.get("reason"), "quantity": rec["quantity"],
            "price": rec["price"], "gross_rs": round(gross, 2), "net_rs": round(net, 2), "gap": bool(order.get("gap")),
            "at": rec.get("at")}


# ── applying an order's fills ────────────────────────────────────────────────────────────────────────────────────────

async def apply_order_fills(db, order: Dict[str, Any], *, now: Optional[datetime] = None) -> Optional[Dict[str, Any]]:
    """Apply every recorded fill of `order` to its position once (see the module docstring). Returns the position."""
    moment = now or store.utcnow()
    fills = list(order.get("fills") or [])
    if not fills:
        return None
    pos: Optional[Dict[str, Any]] = None
    closed_now = False
    for _ in range(len(fills) * MAX_RETRIES + MAX_RETRIES):
        if order.get("purpose") == "ENTRY":
            pos = await db[store.POSITIONS].find_one({"entry_order_id": order["_id"]})
            if pos is None:
                doc = new_position(order, fills[0], moment)
                try:
                    await db[store.POSITIONS].insert_one(doc)
                except DuplicateKeyError:
                    if await db[store.POSITIONS].find_one({"entry_order_id": order["_id"]}) is None:
                        logger.error("spt paper: entry %s filled but %s already has another open position",
                                     order["_id"], order.get("symbol"))
                        await db[store.ORDERS].update_one({"_id": order["_id"]},
                                                          {"$set": {"exception": "open_position_exists"}})
                        return None
                    continue
                await _emit(db, doc, "POSITION_OPENED", f"position:{doc['_id']}:opened",
                            {"entry_order_id": order["_id"], "quantity": doc["quantity"],
                             "avg_entry_price": doc["avg_entry_price"], "stop_loss": doc["stop_loss"],
                             "target_1": doc["target_1"], "target_2": doc["target_2"]}, moment)
                continue
        else:
            pos = await store.get_position(db, order.get("position_id"))
            if pos is None:
                logger.error("spt paper: exit order %s has no position", order["_id"])
                return None
        applied = set(pos.get("fill_ids") or [])
        pending = [f for f in fills if f["fill_id"] not in applied]
        if not pending:
            break
        if pos.get("state") == C.POS_CLOSED:
            # never re-open or re-close a closed position (a second close would owe a second release): the fill stays
            # on its order and in spt_fills, and reconciliation reports it
            logger.error("spt paper: fill(s) of %s arrived for closed position %s; not applied", order["_id"], pos["_id"])
            await db[store.ORDERS].update_one({"_id": order["_id"]}, {"$set": {"exception": "fill_after_close"}})
            return pos
        rec = pending[0]
        if order.get("purpose") == "ENTRY":
            fields = entry_fill_fields(pos, rec)
            push: Dict[str, Any] = {"fill_ids": rec["fill_id"]}
        else:
            entry = await store.get_order(db, pos.get("entry_order_id"))
            closable = entry is None or entry.get("state") not in C.ORD_LIVE_STATES
            fields = exit_fill_fields(pos, rec, order, closable=closable, now=moment)
            q = min(int(rec["quantity"]), int(pos.get("quantity") or 0))
            avg = float(pos.get("avg_entry_price") or 0.0)
            alloc = float(pos.get("entry_costs_rs") or 0.0) * q / (int(pos.get("entry_qty") or 0) or 1)
            gross = (float(rec["price"]) - avg) * q
            push = {"fill_ids": rec["fill_id"],
                    "exit_fills": exit_fill_summary(rec, order, gross, gross - float(rec["costs"]["total"]) - alloc)}
        res = await db[store.POSITIONS].update_one(
            {"_id": pos["_id"], "version": pos["version"], "fill_ids": {"$ne": rec["fill_id"]}},
            {"$set": {**fields, "updated_at": store.iso(moment)}, "$push": push, "$inc": {"version": 1}})
        if res.matched_count and fields.get("state") == C.POS_CLOSED:
            closed_now = True
        if res.matched_count and order.get("purpose") == "EXIT" and fields.get("state") != C.POS_CLOSED:
            await _emit(db, pos, "POSITION_PARTIALLY_EXITED", f"position:{pos['_id']}:exit_fill:{rec['fill_id']}",
                        {"order_id": order["_id"], "reason": order.get("reason"), "quantity": rec["quantity"],
                         "price": rec["price"], "remaining_quantity": fields["quantity"]}, moment)
    else:
        logger.warning("spt paper: fills of %s not all applied (concurrent writers); the next sync finishes it",
                       order["_id"])
        return pos
    await db[store.ORDERS].update_one({"_id": order["_id"]}, {"$max": {"position_seq": len(fills)}})
    pos = await store.get_position(db, pos["_id"]) if pos else None
    if pos is not None and (closed_now or (pos.get("state") == C.POS_CLOSED and (pos.get("release") or {}).get("state") == "pending")):
        await close_followups(db, pos, now=moment)
        pos = await store.get_position(db, pos["_id"])
    return pos


# ── close: the one release, the event, the outcome ───────────────────────────────────────────────────────────────────

async def close_followups(db, pos: Dict[str, Any], *, now: Optional[datetime] = None) -> None:
    """Everything a CLOSED position still owes, each step idempotent: cancel its other live orders, the ONE release,
    POSITION_CLOSED, the trade outcome record (TRADE_ANALYTICS_COMPLETED)."""
    from . import orders                                    # orders imports this module
    moment = now or store.utcnow()
    for o in await store.live_orders(db, position_id=pos["_id"]):
        await orders.cancel_order(db, o["_id"], reason="position_closed", now=moment)
    entry = await store.get_order(db, pos.get("entry_order_id"))
    if entry is not None and entry.get("state") in C.ORD_LIVE_STATES:
        await orders.cancel_order(db, entry["_id"], reason="position_closed", now=moment)
    await release_once(db, pos, now=moment)
    pos = await store.get_position(db, pos["_id"]) or pos
    await _emit(db, pos, "POSITION_CLOSED", f"position:{pos['_id']}:closed",
                {"exit_reason": pos.get("exit_reason"), "quantity": pos.get("entry_qty"),
                 "avg_entry_price": pos.get("avg_entry_price"), "realized_net_rs": pos.get("realized_net_rs"),
                 "release": {k: (pos.get("release") or {}).get(k) for k in ("state", "amount_rs")}}, moment)
    await record_outcome(db, pos, now=moment)


async def release_once(db, pos: Dict[str, Any], *, now: Optional[datetime] = None) -> bool:
    """Claim the pending release and, as the claimer, call paper_account.release once. True when THIS call released."""
    token = str(uuid.uuid4())
    res = await db[store.POSITIONS].update_one(
        {"_id": pos["_id"], "state": C.POS_CLOSED, "release.state": "pending"},
        {"$set": {"release.state": "claimed", "release.claim": token, "release.claimed_at": store.iso(now)}})
    if not res.matched_count:
        return False
    return await _do_release(db, pos, token, now=now)


async def _do_release(db, pos: Dict[str, Any], token: str, *, now: Optional[datetime] = None) -> bool:
    pos = await store.get_position(db, pos["_id"]) or pos
    uid, trade_id = pos["user_id"], pos.get("entry_order_id")
    net = float(pos.get("realized_net_rs") or 0.0)
    account = await db[acct.ACCOUNTS].find_one({"user_id": uid})
    entries = [e for e in ((account or {}).get("reservations") or []) if e.get("trade_id") == trade_id]
    if not entries:
        ledger = await db[acct.LEDGER].find_one({"user_id": uid, "action": "release", "trade_id": trade_id})
        state = "done" if ledger is not None else "missing_reservation"
        if state == "missing_reservation":
            logger.error("spt paper: position %s closed but its reservation (trade %s) is not on the account; "
                         "nothing released (reconciliation)", pos["_id"], trade_id)
        await db[store.POSITIONS].update_one({"_id": pos["_id"], "release.claim": token},
                                             {"$set": {"release.state": state, "release.checked_at": store.iso(now)}})
        return False
    amount = float(entries[0].get("funding_rs") or 0.0)
    try:
        await acct.release(db, uid, amount, net_pnl=net, trade_id=trade_id, symbol=pos.get("symbol"))
    except Exception as e:  # noqa: BLE001 — the claim stays; recover_release retries while the reservation is there
        logger.warning("spt paper: release of %s failed (%s); retried after the grace", pos["_id"], type(e).__name__)
        return False
    await db[store.POSITIONS].update_one(
        {"_id": pos["_id"], "release.claim": token},
        {"$set": {"release.state": "done", "release.amount_rs": round(amount, 2), "release.net_pnl_rs": net,
                  "release.reservation_id": entries[0].get("id"), "release.released_at": store.iso(now)}})
    return True


async def recover_release(db, pos: Dict[str, Any], *, now: datetime) -> bool:
    """A release left `pending` (a crash after the close) or `claimed` longer than RELEASE_CLAIM_GRACE_S (a crash after
    the claim): finish it. The re-claim is conditional on the old claim, and _do_release calls paper_account.release
    only while the reservation is still on the account."""
    rel = pos.get("release") or {}
    if rel.get("state") == "pending":
        return await release_once(db, pos, now=now)
    if rel.get("state") != "claimed":
        return False
    at = store.parse_ts(rel.get("claimed_at"))
    if at is not None and (now - at) < timedelta(seconds=RELEASE_CLAIM_GRACE_S):
        return False
    token = str(uuid.uuid4())
    res = await db[store.POSITIONS].update_one(
        {"_id": pos["_id"], "release.state": "claimed", "release.claim": rel.get("claim")},
        {"$set": {"release.claim": token, "release.claimed_at": store.iso(now)}})
    if not res.matched_count:
        return False
    return await _do_release(db, pos, token, now=now)


# ── stop moves and exit bookkeeping ──────────────────────────────────────────────────────────────────────────────────

def modification_record(pos: Dict[str, Any], *, kind: str, field: str, previous: Any, new: Any, by: str, reason: str,
                        risk_class: str, risk_decision: Optional[Dict[str, Any]], market_ref: Optional[Dict[str, Any]],
                        now: datetime) -> Dict[str, Any]:
    """The WF §14.3 audit record (append-only on the position)."""
    return {"id": str(uuid.uuid4()), "position_id": pos["_id"], "kind": kind, "field": field, "previous": previous,
            "new": new, "requested_by": by, "at": store.iso(now), "reason": reason, "risk_class": risk_class,
            "risk_decision": risk_decision, "market_ref": market_ref, "position_version": pos.get("version")}


async def move_stop(db, pos_id: str, new_stop: float, *, reason: str, by: str, now: datetime,
                    raise_only: bool = True, market_ref: Optional[Dict[str, Any]] = None,
                    extra_set: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
    """A service stop move (breakeven, ATR trail): never lowers the stop when `raise_only`. Records stop_history and an
    audit record, emits STOP_MOVED. Returns the position after, or None when nothing moved."""
    for _ in range(MAX_RETRIES):
        pos = await store.get_position(db, pos_id)
        if pos is None or pos.get("state") not in C.POS_OPEN_STATES:
            return None
        cur = _f(pos.get("stop_loss"))
        new = round(float(new_stop), 2)
        if raise_only and cur is not None and new <= cur + 1e-9:
            if extra_set:
                await store.transition(db, store.POSITIONS, pos_id, expect_states=C.POS_OPEN_STATES,
                                       expect_version=pos["version"], set_=extra_set, now=now)
            return None
        sv = int(pos.get("stop_version") or 1) + 1
        rec = modification_record(pos, kind="stop_moved", field="stop_loss", previous=cur, new=new, by=by, reason=reason,
                                  risk_class="reducing", risk_decision=None, market_ref=market_ref, now=now)
        after = await store.transition(
            db, store.POSITIONS, pos_id, expect_states=C.POS_OPEN_STATES, expect_version=pos["version"],
            set_={"stop_loss": new, "stop_version": sv, **(extra_set or {})},
            push={"stop_history": {"at": store.iso(now), "stop": new, "reason": reason, "version": sv, "by": by},
                  "modifications": rec}, now=now)
        if after is not None:
            await _emit(db, after, "STOP_MOVED", f"position:{pos_id}:stop_v{sv}",
                        {"previous": cur, "new": new, "reason": reason, "by": by, "stop_version": sv}, now)
            return after
    return None


def breakeven_stop(pos: Dict[str, Any]) -> Optional[float]:
    """Average entry + the entry charges per share + the estimated charges per share of selling what is left, rounded
    UP to the paisa: a stop-out there loses about nothing (a stop is not a guaranteed fill)."""
    avg, eq, qty = _f(pos.get("avg_entry_price")), int(pos.get("entry_qty") or 0), int(pos.get("quantity") or 0)
    if avg is None or eq <= 0 or qty <= 0:
        return None
    per_share = float(pos.get("entry_costs_rs") or 0.0) / eq + execution.exit_costs_per_share(avg, qty, pos.get("cost_model"))
    return math.ceil((avg + per_share) * 100.0 - 1e-6) / 100.0


async def after_exit_terminal(db, order: Dict[str, Any], *, now: Optional[datetime] = None) -> None:
    """An EXIT order ended: free the position's exit slot; a full exit that ended with shares left goes back to
    MONITORING (or EXIT_PENDING when an evening exit is still owed); after a filled T1, the breakeven stop."""
    moment = now or store.utcnow()
    for _ in range(MAX_RETRIES):
        pos = await store.get_position(db, order.get("position_id"))
        if pos is None or pos.get("live_exit_order_id") != order["_id"]:
            break
        fields: Dict[str, Any] = {k: None for k in ("live_exit_order_id", "live_exit_reason", "live_exit_qty",
                                                    "live_exit_full", "live_exit_type", "live_exit_limit",
                                                    "live_exit_gap", "live_exit_trigger", "live_exit_actor")}
        to_state = None
        if pos.get("state") == C.POS_CLOSING and int(pos.get("quantity") or 0) > 0:
            to_state = C.POS_EXIT_PENDING if pos.get("pending_exit") else C.POS_MONITORING
        if pos.get("state") == C.POS_CLOSED:
            res = await db[store.POSITIONS].update_one({"_id": pos["_id"], "live_exit_order_id": order["_id"]},
                                                       {"$set": fields})
            if res.matched_count:
                break
            continue
        if await store.transition(db, store.POSITIONS, pos["_id"], expect_states=C.POS_OPEN_STATES,
                                  expect_version=pos["version"], to_state=to_state, set_=fields, now=moment):
            break
    if order.get("reason") == "target_1" and int(order.get("filled_quantity") or 0) > 0:
        pos = await store.get_position(db, order.get("position_id"))
        if pos is None or pos.get("t1_done") or pos.get("state") not in C.POS_OPEN_STATES:
            return
        be = breakeven_stop(pos) if pos.get("move_stop_to_breakeven_at_t1") else None
        if be is None:
            await store.transition(db, store.POSITIONS, pos["_id"], expect_states=C.POS_OPEN_STATES,
                                   expect_version=pos["version"], set_={"t1_done": True}, now=moment)
            return
        moved = await move_stop(db, pos["_id"], be, reason="breakeven_after_t1", by=SERVICE_ACTOR, now=moment,
                                extra_set={"t1_done": True})
        if moved is None:
            pos = await store.get_position(db, order.get("position_id"))
            if pos is not None and not pos.get("t1_done") and pos.get("state") in C.POS_OPEN_STATES:
                await store.transition(db, store.POSITIONS, pos["_id"], expect_states=C.POS_OPEN_STATES,
                                       expect_version=pos["version"], set_={"t1_done": True}, now=moment)


# ── marks (display) ──────────────────────────────────────────────────────────────────────────────────────────────────

def mark_fields(pos: Dict[str, Any], q: Dict[str, Any], now: datetime) -> Optional[Dict[str, Any]]:
    """The display mark from a usable live quote: the bid (what a sale would meet), else LTP, said which."""
    price = q.get("bid") or q.get("ltp")
    avg, qty = _f(pos.get("avg_entry_price")), int(pos.get("quantity") or 0)
    if price is None or avg is None:
        return None
    gross = (price - avg) * qty
    eq = int(pos.get("entry_qty") or 0) or 1
    open_entry_costs = float(pos.get("entry_costs_rs") or 0.0) * qty / eq
    exit_est = execution.exit_costs_per_share(price, qty, pos.get("cost_model")) * qty if qty else 0.0
    risk0 = _f(pos.get("initial_risk_rs"))
    unreal_net = gross - open_entry_costs - exit_est
    total = float(pos.get("realized_net_rs") or 0.0) + unreal_net
    return {"price": round(price, 2), "basis": "bid" if q.get("bid") else "ltp", "bid": q.get("bid"), "ask": q.get("ask"),
            "ltp": q.get("ltp"), "quote_at": q.get("received_at"), "at": store.iso(now),
            "unrealized_gross_rs": round(gross, 2), "unrealized_net_rs": round(unreal_net, 2),
            "r_multiple": round(total / risk0, 3) if risk0 else None}


async def mark(db, pos: Dict[str, Any], q: Dict[str, Any], now: datetime) -> None:
    """Write the display mark and widen the MFE/MAE price range. Not a state change: no version bump."""
    m = mark_fields(pos, q, now)
    if m is None:
        return
    await db[store.POSITIONS].update_one({"_id": pos["_id"], "state": {"$in": list(C.POS_OPEN_STATES)}},
                                         {"$set": {"mark": m}, "$max": {"max_price": m["price"]},
                                          "$min": {"min_price": m["price"]}})


def excursions(pos: Dict[str, Any]) -> Dict[str, Optional[float]]:
    avg, eq = _f(pos.get("avg_entry_price")), int(pos.get("entry_qty") or 0)
    hi, lo, risk0 = _f(pos.get("max_price")), _f(pos.get("min_price")), _f(pos.get("initial_risk_rs"))
    mfe = round((hi - avg) * eq, 2) if hi is not None and avg is not None else None
    mae = round((lo - avg) * eq, 2) if lo is not None and avg is not None else None
    return {"mfe_rs": mfe, "mae_rs": mae, "mfe_r": round(mfe / risk0, 3) if mfe is not None and risk0 else None,
            "mae_r": round(mae / risk0, 3) if mae is not None and risk0 else None,
            "max_price": hi, "min_price": lo}


# ── the trade outcome record (WF §17.2) ──────────────────────────────────────────────────────────────────────────────

async def record_outcome(db, pos: Dict[str, Any], *, now: Optional[datetime] = None) -> Optional[Dict[str, Any]]:
    """Written once at close (conditional on `outcome` being unset); TRADE_ANALYTICS_COMPLETED with it."""
    pos = await store.get_position(db, pos["_id"]) or pos
    if pos.get("state") != C.POS_CLOSED or pos.get("outcome"):
        return pos.get("outcome")
    fills = await db[store.FILLS].find({"$or": [{"order_id": pos.get("entry_order_id")}, {"position_id": pos["_id"]}]}) \
        .to_list(None)
    fills = sorted(fills, key=lambda f: (str(f.get("at") or ""), int(f.get("seq") or 0)))
    entry_f = [f for f in fills if f.get("purpose") == "ENTRY"]
    exit_f = [f for f in fills if f.get("purpose") == "EXIT"]
    planned = pos.get("planned") or {}
    avg = _f(pos.get("avg_entry_price"))
    p_entry = _f(planned.get("entry"))
    eq = int(pos.get("entry_qty") or 0)
    risk0 = _f(pos.get("initial_risk_rs"))
    p_stop = _f(planned.get("stop"))
    planned_risk = round((p_entry - p_stop) * int(planned.get("quantity") or eq), 2) if p_entry and p_stop and p_stop < p_entry else None
    opened, closed = store.parse_ts(pos.get("opened_at")), store.parse_ts(pos.get("closed_at"))
    net = float(pos.get("realized_net_rs") or 0.0)

    def brief(f: Dict[str, Any]) -> Dict[str, Any]:
        return {k: f.get(k) for k in ("_id", "order_id", "seq", "quantity", "price", "ref_price", "basis", "depth_unknown",
                                      "slippage_rs", "value_rs", "gap", "at", "reason")} | {"costs_rs": (f.get("costs") or {}).get("total")}

    out = {
        "version": C.OUTCOME_VERSION, "position_id": pos["_id"], "symbol": pos.get("symbol"),
        "proposal_id": pos.get("proposal_id"), "opportunity_id": pos.get("opportunity_id"),
        "entry_order_id": pos.get("entry_order_id"), "entry_fills": [brief(f) for f in entry_f],
        "exit_fills": [brief(f) for f in exit_f], "quantity": eq, "avg_entry_price": avg,
        "avg_exit_price": round(float(pos.get("exit_value_rs") or 0) / int(pos.get("exit_qty") or 1), 4) if pos.get("exit_qty") else None,
        "costs_rs": {"entry": pos.get("entry_costs_rs"), "exit": pos.get("exit_costs_rs"),
                     "total": round(float(pos.get("entry_costs_rs") or 0) + float(pos.get("exit_costs_rs") or 0), 2)},
        "slippage_rs": pos.get("slippage_rs"),
        "entry_vs_plan_rs": round((avg - p_entry) * eq, 2) if avg is not None and p_entry else None,
        "entry_vs_plan_pct": round((avg - p_entry) / p_entry * 100.0, 4) if avg is not None and p_entry else None,
        "planned_risk_rs": planned_risk, "initial_risk_rs": risk0, "realized_gross_rs": pos.get("realized_gross_rs"),
        "realized_net_rs": net, "r_multiple": round(net / risk0, 3) if risk0 else None,
        "holding_seconds": int((closed - opened).total_seconds()) if opened and closed else None,
        "sessions_held": pos.get("sessions_held"), **excursions(pos), "exit_reason": pos.get("exit_reason"),
        "exit_gap": pos.get("exit_gap"), "stop_history": pos.get("stop_history"),
        "versions": {"execution": C.EXECUTION_VERSION, "risk_policy": (pos.get("risk") or {}).get("policy_version"),
                     "risk_limits": (pos.get("risk") or {}).get("limits_version"),
                     "strategy": (pos.get("exit_plan") or {}).get("rules") or (pos.get("exit_plan") or {}).get("strategy_version"),
                     "cost_model": (pos.get("cost_model") or {}).get("version")},
        "at": store.iso(now),
    }
    res = await db[store.POSITIONS].update_one({"_id": pos["_id"], "outcome": None}, {"$set": {"outcome": out}})
    if res.matched_count:
        await _emit(db, pos, "TRADE_ANALYTICS_COMPLETED", f"position:{pos['_id']}:analytics", out, now)
    return out


def public(pos: Dict[str, Any]) -> Dict[str, Any]:
    """The position as the API shows it to its owner, with the derived figures."""
    out = {k: v for k, v in pos.items() if k not in ("fill_ids",)}
    out["position_id"] = pos["_id"]
    out.update(excursions(pos))
    avg, stop, qty = _f(pos.get("avg_entry_price")), _f(pos.get("stop_loss")), int(pos.get("quantity") or 0)
    out["invested_rs"] = round(avg * qty, 2) if avg is not None else None
    out["risk_at_stop_rs"] = round((avg - stop) * qty, 2) if avg is not None and stop is not None else None
    out["next_target"] = pos.get("target_2") if pos.get("t1_done") else pos.get("target_1")
    out["r_multiple"] = (pos.get("outcome") or {}).get("r_multiple") if pos.get("state") == C.POS_CLOSED \
        else (pos.get("mark") or {}).get("r_multiple")
    return out
