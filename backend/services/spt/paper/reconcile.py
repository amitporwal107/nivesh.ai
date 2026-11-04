"""Reconciliation of the SPT paper book: orders ↔ fills ↔ positions ↔ the paper account's reservations and ledger
(WF §20.3, PRD §25 #19). READ-ONLY: `report` reads and returns what does not add up; `startup_check` (run by the monitor
on a process's first pass, after it has finished its own leftovers) also MARKS what it found — an open position becomes
RECONCILIATION_REQUIRED (no automatic exit orders from then on; a manual exit is still allowed), a closed one gets a
`reconciliation` note — and never moves money. Corrections of an account go through services/paper_reconcile's
`paper_account.adjust`, by a person, not from here.

CHECKS (each mismatch: {code, user_id, order_id | position_id | reservation_id, detail}):
  order_fill_mismatch            order.filled_quantity ≠ Σ of its fills in spt_fills
  order_fills_not_logged         the order holds fills spt_fills does not (a sync is owed; the monitor finishes it)
  order_quantity_mismatch        filled + remaining + cancelled ≠ quantity
  fill_without_position          an ENTRY with fills and no position
  position_quantity_mismatch     position.quantity ≠ Σ entry fills − Σ exit fills
  duplicate_open_position        two open positions for one (user, symbol, direction)
  closed_without_release         a CLOSED position whose release is not `done`
  position_without_reservation   an open position whose reservation (trade_id = entry order id) is not on the account
  reservation_without_order_or_position   an account reservation of store spt_orders whose order is neither live nor
                                 holding an open position (a leak: its funding and risk are still blocked)
  double_release                 more than one `release` ledger row for one SPT trade
"""
from __future__ import annotations

import logging
from collections import defaultdict
from datetime import datetime
from typing import Any, Dict, List, Optional

from services import paper_account as acct
from services.spt import constants as C

from . import store

logger = logging.getLogger(__name__)

VERSION = "spt-reconcile-v1"
LIMIT = 20000


def _m(code: str, user_id: Any, **detail: Any) -> Dict[str, Any]:
    return {"code": code, "user_id": user_id, **detail}


async def report(db, *, user_id: Optional[str] = None, now: Optional[datetime] = None) -> Dict[str, Any]:
    q: Dict[str, Any] = {"user_id": user_id} if user_id else {}
    orders = await db[store.ORDERS].find(q).to_list(LIMIT)
    fills = await db[store.FILLS].find(q).to_list(LIMIT)
    positions = await db[store.POSITIONS].find(q).to_list(LIMIT)
    out: List[Dict[str, Any]] = []
    by_order: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for f in fills:
        by_order[f.get("order_id")].append(f)
    pos_by_entry = {p.get("entry_order_id"): p for p in positions}
    orders_by_id = {o["_id"]: o for o in orders}

    for o in orders:
        logged = sum(int(f.get("quantity") or 0) for f in by_order.get(o["_id"], []))
        embedded = sum(int(f.get("quantity") or 0) for f in o.get("fills") or [])
        filled = int(o.get("filled_quantity") or 0)
        if embedded != filled:
            out.append(_m("order_fill_mismatch", o.get("user_id"), order_id=o["_id"], filled_quantity=filled,
                          fills_on_order=embedded, fills_logged=logged))
        elif logged != filled:
            out.append(_m("order_fills_not_logged" if logged < filled else "order_fill_mismatch", o.get("user_id"),
                          order_id=o["_id"], filled_quantity=filled, fills_logged=logged))
        if filled + int(o.get("remaining_quantity") or 0) + int(o.get("cancelled_quantity") or 0) != int(o.get("quantity") or 0):
            out.append(_m("order_quantity_mismatch", o.get("user_id"), order_id=o["_id"], quantity=o.get("quantity"),
                          filled=filled, remaining=o.get("remaining_quantity"), cancelled=o.get("cancelled_quantity")))
        if o.get("purpose") == "ENTRY" and filled > 0 and o["_id"] not in pos_by_entry:
            out.append(_m("fill_without_position", o.get("user_id"), order_id=o["_id"], filled_quantity=filled))

    open_keys: Dict[tuple, List[str]] = defaultdict(list)
    for p in positions:
        entry_q = sum(int(f.get("quantity") or 0) for f in by_order.get(p.get("entry_order_id"), []))
        exit_q = sum(int(f.get("quantity") or 0) for f in fills
                     if f.get("purpose") == "EXIT" and f.get("position_id") == p["_id"])
        if int(p.get("quantity") or 0) != entry_q - exit_q:
            out.append(_m("position_quantity_mismatch", p.get("user_id"), position_id=p["_id"],
                          quantity=p.get("quantity"), entry_fills=entry_q, exit_fills=exit_q))
        if p.get("is_open"):
            open_keys[(p.get("user_id"), p.get("symbol"), p.get("direction"))].append(p["_id"])
        if p.get("state") == C.POS_CLOSED and (p.get("release") or {}).get("state") != "done":
            out.append(_m("closed_without_release", p.get("user_id"), position_id=p["_id"],
                          release_state=(p.get("release") or {}).get("state")))
    for (uid, sym, _), ids in open_keys.items():
        if len(ids) > 1:
            out.append(_m("duplicate_open_position", uid, symbol=sym, position_ids=ids))

    users = sorted({u for u in [user_id] + [o.get("user_id") for o in orders] + [p.get("user_id") for p in positions] if u})
    for uid in users:
        account = await db[acct.ACCOUNTS].find_one({"user_id": uid}) or {}
        held = {e.get("trade_id"): e for e in account.get("reservations") or [] if e.get("store") == C.ORDERS}
        for trade_id, e in held.items():
            o = orders_by_id.get(trade_id)
            p = pos_by_entry.get(trade_id)
            live = o is not None and o.get("state") in C.ORD_LIVE_STATES
            holding = p is not None and p.get("state") in C.POS_OPEN_STATES
            if not live and not holding:
                out.append(_m("reservation_without_order_or_position", uid, reservation_id=e.get("id"), trade_id=trade_id,
                              order_state=(o or {}).get("state"), position_state=(p or {}).get("state"),
                              funding_rs=e.get("funding_rs"), risk_rs=e.get("risk_rs")))
        for p in positions:
            if p.get("user_id") == uid and p.get("state") in C.POS_OPEN_STATES and p.get("entry_order_id") not in held:
                out.append(_m("position_without_reservation", uid, position_id=p["_id"], trade_id=p.get("entry_order_id")))
        trade_ids = {o["_id"] for o in orders if o.get("user_id") == uid and o.get("purpose") == "ENTRY"}
        if trade_ids:
            rows = await db[acct.LEDGER].find({"user_id": uid, "action": "release"}).to_list(LIMIT)
            counts: Dict[str, int] = defaultdict(int)
            for row in rows:
                if row.get("trade_id") in trade_ids:
                    counts[row["trade_id"]] += 1
            for tid, n in counts.items():
                if n > 1:
                    out.append(_m("double_release", uid, trade_id=tid, releases=n))

    codes: Dict[str, int] = defaultdict(int)
    for m in out:
        codes[m["code"]] += 1
    return {"version": VERSION, "at": store.iso(now), "ok": not out, "user_id": user_id,
            "counts": {"orders": len(orders), "fills": len(fills), "positions": len(positions),
                       "mismatches": len(out), "by_code": dict(codes)},
            "mismatches": out}


async def startup_check(db, *, now: Optional[datetime] = None) -> Dict[str, Any]:
    """`report` over every user, then mark: open positions → RECONCILIATION_REQUIRED (with the codes and the state
    before), closed positions → a `reconciliation` note. Never moves money."""
    rep = await report(db, now=now)
    by_pos: Dict[str, List[str]] = defaultdict(list)
    for m in rep["mismatches"]:
        if m.get("position_id"):
            by_pos[m["position_id"]].append(m["code"])
    for pid, codes in by_pos.items():
        pos = await store.get_position(db, pid)
        if pos is None:
            continue
        note = {"required": True, "codes": sorted(set(codes)), "at": store.iso(now), "state_before": pos.get("state")}
        if pos.get("state") in C.POS_OPEN_STATES and pos.get("state") != C.POS_RECONCILIATION_REQUIRED:
            await store.transition(db, store.POSITIONS, pid, expect_states=[pos["state"]], expect_version=pos["version"],
                                   to_state=C.POS_RECONCILIATION_REQUIRED, set_={"reconciliation": note}, now=now)
        elif pos.get("state") == C.POS_CLOSED:
            await db[store.POSITIONS].update_one({"_id": pid}, {"$set": {"reconciliation": note}})
        logger.error("spt reconcile: position %s needs reconciliation: %s", pid, ",".join(note["codes"]))
    if rep["mismatches"]:
        logger.error("spt reconcile: %d mismatch(es): %s", len(rep["mismatches"]), rep["counts"]["by_code"])
    return rep
