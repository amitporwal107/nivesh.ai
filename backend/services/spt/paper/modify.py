"""Position modifications (WF §14, PRD §11.6, §18 rules 11–14, §8.5).

    change = {"kind": "stop_loss", "value": <price> | null}      a new stop (null removes it)
           | {"kind": "target_1" | "target_2", "value": <price>}
           | {"kind": "trailing", "enabled": true|false, "k": 2}  the ATR trail (trail-atr-v1) on / off
           | {"kind": "trend_exit", "enabled": true|false}         close below the 20-session average, on / off
           | {"kind": "reduce_quantity", "quantity": <shares>}      an EXIT order for that many shares (reason manual)
           | {"kind": "close"}                                      an EXIT order for the whole position (reason manual)

CLASSIFIED before anything is written:
  reducing    a tighter (higher) stop, turning the trail or the trend exit on, reducing, closing
  neutral     a target change (the loss at the stop is unchanged)
  increasing  a wider (lower) stop — a stop is never moved further away to fit a size (PRD §8.5): a wider stop is risk
              that must be approved again —, removing the stop, turning the trail or the trend exit off
Risk-increasing changes go to slice B's `services.spt.risk.check_modification(db, user_id=, position=, change=)` (imported
when needed); only its APPROVE applies the change. When B's module is not there the change is refused (503
risk_check_unavailable: fail closed). While the user's new entries are blocked (kill switch / halt / account block),
risk-increasing changes are refused (409 risk_increase_blocked) and reducing / neutral ones still apply (PRD §18 rules
12–14). RECONCILIATION_REQUIRED positions accept only reduce / close.

CONCURRENCY: the change is written with the position version the caller read (`expect_version`, else the one read
here). A target reached by the monitor while the stop is being modified bumps the version, so the stale change answers
409 position_changed and nothing is lost (PRD §23.3 #9).

AUDIT (WF §14.3): every change appends {position_id, kind, field, previous, new, requested_by, at, reason, risk_class,
risk_decision, market_ref} to `modifications` (append-only) and emits POSITION_MODIFIED (and STOP_MOVED for a stop).
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Awaitable, Callable, Dict, Optional, Tuple

from services.spt import constants as C
from services.spt import events as ev

from . import controls, execution, orders, positions, store

logger = logging.getLogger(__name__)

INCREASING, REDUCING, NEUTRAL = "increasing", "reducing", "neutral"
KINDS = ("stop_loss", "target_1", "target_2", "trailing", "trend_exit", "reduce_quantity", "close")
APPROVING = (C.RISK_APPROVE,)
DEFAULT_TRAIL = {"rule": "trail-atr-v1", "k": 2.0}


class ModifyRefused(RuntimeError):
    def __init__(self, code: str, status: int, **detail: Any) -> None:
        super().__init__(code)
        self.code, self.status, self.detail = code, status, detail


def classify(pos: Dict[str, Any], change: Dict[str, Any]) -> Tuple[str, str, Any, Any]:
    """(risk_class, field, previous, new) of a change. Raises ModifyRefused(422) for an invalid one. Pure."""
    kind = change.get("kind")
    if kind not in KINDS:
        raise ModifyRefused("modification_kind_invalid", 422, allowed=list(KINDS))
    num = execution._num
    stop = num(pos.get("stop_loss"))
    if kind == "stop_loss":
        raw = change.get("value")
        if raw is None:
            if stop is None:
                raise ModifyRefused("no_change", 422)
            return INCREASING, "stop_loss", stop, None
        new = num(raw)
        if new is None:
            raise ModifyRefused("stop_invalid", 422)
        new = round(new, 2)
        if stop is not None and abs(new - stop) < 1e-9:
            raise ModifyRefused("no_change", 422)
        t1 = num(pos.get("target_1")) if not pos.get("t1_done") else None
        t2 = num(pos.get("target_2"))
        if any(t is not None and new >= t for t in (t1, t2)):
            raise ModifyRefused("stop_not_below_target", 422)
        return (REDUCING if stop is not None and new > stop else INCREASING), "stop_loss", stop, new
    if kind in ("target_1", "target_2"):
        new = num(change.get("value"))
        if new is None:
            raise ModifyRefused("target_invalid", 422)
        new = round(new, 2)
        if stop is not None and new <= stop:
            raise ModifyRefused("target_not_above_stop", 422)
        other = num(pos.get("target_2" if kind == "target_1" else "target_1"))
        if other is not None and ((kind == "target_1" and new > other) or (kind == "target_2" and new < other)):
            raise ModifyRefused("targets_out_of_order", 422)
        prev = num(pos.get(kind))
        if prev is not None and abs(prev - new) < 1e-9:
            raise ModifyRefused("no_change", 422)
        return NEUTRAL, kind, prev, new
    if kind in ("trailing", "trend_exit"):
        on = change.get("enabled")
        if not isinstance(on, bool):
            raise ModifyRefused("enabled_required", 422)
        field = "trail" if kind == "trailing" else "trend_exit"
        prev = pos.get(field) or None
        if on:
            if kind == "trailing":
                k = num(change.get("k")) or DEFAULT_TRAIL["k"]
                if not 0 < k <= 10:
                    raise ModifyRefused("trail_k_invalid", 422)
                new: Any = {"rule": "trail-atr-v1", "k": k}
            else:
                new = {"rule": "close_below_sma20"}
            if prev == new:
                raise ModifyRefused("no_change", 422)
            return REDUCING, field, prev, new
        if prev is None:
            raise ModifyRefused("no_change", 422)
        return INCREASING, field, prev, None
    if kind == "reduce_quantity":
        q = orders._whole(change.get("quantity"))
        held = int(pos.get("quantity") or 0)
        if q is None or q > held:
            raise ModifyRefused("quantity_invalid", 422, held=held)
        return REDUCING, "quantity", held, held - q
    return REDUCING, "quantity", int(pos.get("quantity") or 0), 0           # close


async def _market_ref(reader: Optional[Callable[..., Awaitable[Dict[str, Any]]]], symbol: str,
                      now: datetime) -> Optional[Dict[str, Any]]:
    """The live quote the change was made against (WF §14.3), or a note why there is none. Never blocks the change."""
    if reader is None:
        return None
    try:
        got = await reader([symbol], now) or {}
    except Exception as e:  # noqa: BLE001
        logger.warning("spt modify: market reference unreadable (%s)", type(e).__name__)
        return {"available": False, "why": type(e).__name__}
    q, why = execution.check_quote((got.get("quotes") or {}).get(symbol), now)
    if q is None:
        return {"available": False, "why": got.get("why") or why}
    return {"available": True, "ltp": q["ltp"], "bid": q["bid"], "ask": q["ask"], "received_at": q["received_at"],
            "source": "kite_live"}


async def modify_position(db, *, user_id: str, position_id: str, change: Dict[str, Any], reason: str,
                          requested_by: str, expect_version: Optional[int] = None,
                          quotes: Optional[Callable[..., Awaitable[Dict[str, Any]]]] = None,
                          now: Optional[datetime] = None) -> Dict[str, Any]:
    """Apply one modification to the caller's own open position. Returns {position, order?, modification}. Raises
    ModifyRefused with a stable code and an HTTP status."""
    moment = now or store.utcnow()
    pos = await store.get_position(db, position_id)
    if pos is None or pos.get("user_id") != user_id:
        raise ModifyRefused("position_not_found", 404)
    if pos.get("state") not in C.POS_OPEN_STATES:
        raise ModifyRefused("position_not_open", 409, state=pos.get("state"))
    if expect_version is not None and int(expect_version) != int(pos.get("version") or 0):
        raise ModifyRefused("position_changed", 409, version=pos.get("version"))
    risk_class, field, previous, new = classify(pos, change)
    kind = change["kind"]
    if pos.get("state") == C.POS_RECONCILIATION_REQUIRED and kind not in ("reduce_quantity", "close"):
        raise ModifyRefused("position_needs_reconciliation", 409)
    market_ref = await _market_ref(quotes, pos["symbol"], moment)
    decision: Optional[Dict[str, Any]] = None
    if risk_class == INCREASING:
        block = await controls.entry_block(db, user_id)
        if block is not None:
            raise ModifyRefused("risk_increase_blocked", 409, control=block)
        try:
            from services.spt import risk as spt_risk          # slice B
            check = getattr(spt_risk, "check_modification")
        except (ImportError, AttributeError):
            raise ModifyRefused("risk_check_unavailable", 503)
        proposed = {"kind": kind, "field": field, "previous": previous, "new": new}
        try:
            decision = await check(db, user_id=user_id, position=positions.public(pos), change=proposed)
        except Exception as e:  # noqa: BLE001 — fail closed: an unanswered check is not an approval
            logger.warning("spt modify: risk check failed (%s)", type(e).__name__)
            raise ModifyRefused("risk_check_unavailable", 503)
        decision = dict(decision or {})
        if decision.get("decision") not in APPROVING:
            raise ModifyRefused("modification_rejected_by_risk", 409, decision=decision.get("decision"),
                                reason_codes=decision.get("reason_codes") or [], explanations=decision.get("explanations") or [],
                                decision_id=decision.get("decision_id"))
    rec = positions.modification_record(
        pos, kind=kind, field=field, previous=previous, new=new, by=requested_by, reason=reason or kind,
        risk_class=risk_class, now=moment, market_ref=market_ref,
        risk_decision=None if decision is None else {k: decision.get(k) for k in ("decision", "reason_codes", "decision_id")})
    if kind in ("reduce_quantity", "close"):
        qty = None if kind == "close" else int(change["quantity"])
        try:
            order = await orders.create_exit_order(db, position_id=position_id, reason="manual", quantity=qty,
                                                   actor_id=requested_by, now=moment,
                                                   trigger={"requested_by": requested_by, "kind": kind})
        except orders.ExitRefused as e:
            raise ModifyRefused(e.code, 409)
        rec["order_id"] = order["_id"]
        await db[store.POSITIONS].update_one({"_id": position_id}, {"$push": {"modifications": rec}})
        await _emit_modified(db, pos, rec, moment)
        return {"position": positions.public(await store.get_position(db, position_id) or pos),
                "order": orders.public(order), "modification": rec}
    sets: Dict[str, Any] = {field: new}
    push: Dict[str, Any] = {"modifications": rec}
    sv = None
    if field == "stop_loss":
        sv = int(pos.get("stop_version") or 1) + 1
        sets["stop_version"] = sv
        # `initial_stop` stays the plan's: it is the R denominator, and the evening trail (which only ever raises the
        # stop in force) replays from it
        push["stop_history"] = {"at": store.iso(moment), "stop": new, "reason": "manual", "version": sv, "by": requested_by}
    after = await store.transition(db, store.POSITIONS, position_id, expect_states=C.POS_OPEN_STATES,
                                   expect_version=pos["version"], set_=sets, push=push, now=moment)
    if after is None:
        raise ModifyRefused("position_changed", 409)
    await _emit_modified(db, after, rec, moment)
    if sv is not None:
        await ev.emit(db, "STOP_MOVED", idempotency_key=f"position:{position_id}:stop_v{sv}", source_service=store.SOURCE,
                      payload={"position_id": position_id, "previous": previous, "new": new, "reason": "manual",
                               "by": requested_by, "stop_version": sv},
                      occurred_at=store.iso(moment), correlation_id=pos.get("correlation_id"), account_id=user_id,
                      instrument_id=pos.get("symbol"))
    return {"position": positions.public(after), "modification": rec}


async def _emit_modified(db, pos: Dict[str, Any], rec: Dict[str, Any], now: datetime) -> None:
    await ev.emit(db, "POSITION_MODIFIED", idempotency_key=f"position:{pos['_id']}:mod:{rec['id']}",
                  source_service=store.SOURCE, payload=rec, occurred_at=store.iso(now),
                  correlation_id=pos.get("correlation_id"), account_id=pos.get("user_id"), instrument_id=pos.get("symbol"))
