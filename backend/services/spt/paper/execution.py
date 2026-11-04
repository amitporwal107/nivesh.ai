"""The paper execution model `spt-exec-v1` (DESIGN.md §6, WF §12.2–§12.3, PRD §11.3).

PURE PART (no I/O, no clock): `simulate(order, quote, now, ...)` → {fills, reason, triggered_at, quote}.

  When          only in the NSE session (09:15–15:30 IST, weekdays; `store.in_session`). Out of session: no fill
                (`out_of_session`); the order waits for its time in force.
  Which quote   the live quote for the symbol, used only when it was received ≤ SPT_QUOTE_MAX_AGE_S (120 s) ago by its
                `received_at`. Missing → `quote_missing`; older (or unparseable stamp) → `quote_stale`. One quote (the
                same `received_at`) is consumed at most once per order (`quote_already_used`): its displayed quantity
                was already taken. NO PRICE IS EVER INVENTED (WF §20): no quote, no fill.
  Price         BUY executes against the asks, SELL against the bids, each level at its own price, then slippage
                (desk-cost-v2's 0.05 %) against the order: BUY × (1 + 0.05 %), SELL × (1 − 0.05 %), to the paisa.
                Book, best first:
                  `depth`            five levels {buy:[{price,quantity}], sell:[...]} when the quote carries them
                  `top_of_book`      bid/ask with their displayed quantity (what the live cache holds today)
                  `top_of_book_no_qty`  bid/ask without a quantity
                  `ltp_spread`       no bid/ask: LTP ± SPT_NO_DEPTH_SPREAD_PCT (0.05 %, the desk's spread allowance)
  Quantity      with a displayed quantity: up to it, level by level; the rest stays pending (a partial fill). Without
                one (the last two books): at most SPT_NO_DEPTH_MAX_QTY_FRACTION (0.25) of the ORDER per round (at least
                one share, never more than the remaining), flagged `depth_unknown: true`. Never the whole order on a
                guess (a 1–3 share order necessarily fills one share per round).
  Order types   MARKET: marketable. LIMIT: fills only at or better than the limit, never beyond it (a level whose price
                with slippage crosses the limit fills AT the limit when the level itself is within it). SL / SL_M: wait
                for LTP to cross the trigger (BUY: LTP ≥ trigger; SELL: LTP ≤ trigger), recorded once as
                `triggered_at`; then SL_M is marketable and SL is a limit order at its limit price.
  Entry guard   an ENTRY does not fill above the planned entry × (1 + SPT_ENTRY_MAX_DEVIATION_PCT %) (`price_beyond_plan`)
                nor at or below the plan's stop (`price_through_stop`): the reservation and the risk decision were made
                on the planned entry and stop. Exits have no guard: an exit is always allowed.

COSTS per fill: services/desk_cost_card.order_side for equity delivery (STT, exchange charge, SEBI fee, stamp duty on a
buy, GST), the card snapshotted on the order. The slippage is IN THE PRICE, so the card's slippage component is set to
0 here (it is not charged twice; each fill records `slippage_rs`, the price impact against the quote). Brokerage
(₹20, a desk assumption) is charged once per order, on its first fill.

ASYNC PART: `execute_order(db, order, quote, now, session_open=...)` runs one attempt for one order: catch up first
(orders.sync_order), simulate, then record the fills atomically on the order (orders.record_fills) and propagate them
(fills collection, position, events) through orders.sync_order.
"""
from __future__ import annotations

import math
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from services import desk_cost_card as cost_card
from services.spt import constants as C

from . import config, store

SEGMENT = "equity_delivery"
BOOK_KNOWN = ("depth", "top_of_book")


def _num(v: Any) -> Optional[float]:
    if isinstance(v, bool) or v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) and f > 0 else None


def _qty(v: Any) -> Optional[int]:
    f = _num(v)
    return int(f) if f is not None and f >= 1 else None


def _depth(d: Any) -> Optional[Dict[str, List[Tuple[float, int]]]]:
    if not isinstance(d, dict):
        return None
    out: Dict[str, List[Tuple[float, int]]] = {}
    for side in ("buy", "sell"):
        levels = []
        for lv in d.get(side) or []:
            if not isinstance(lv, dict):
                continue
            px, q = _num(lv.get("price")), _qty(lv.get("quantity"))
            if px is not None and q is not None:
                levels.append((px, q))
        out[side] = levels
    return out if out["buy"] or out["sell"] else None


def normalize_quote(q: Any) -> Optional[Dict[str, Any]]:
    """A quote from the cache (nested `ohlc`) or the snapshot (flat) in one shape. Absent values are None, never 0."""
    if not isinstance(q, dict):
        return None
    ohlc = q.get("ohlc") if isinstance(q.get("ohlc"), dict) else {}
    return {"ltp": _num(q.get("ltp")), "bid": _num(q.get("bid")), "ask": _num(q.get("ask")),
            "bid_qty": _qty(q.get("bid_qty")), "ask_qty": _qty(q.get("ask_qty")),
            "open": _num(q.get("open") if q.get("open") is not None else ohlc.get("open")),
            "received_at": q.get("received_at"), "depth": _depth(q.get("depth"))}


def check_quote(q: Any, now: datetime, max_age_s: Optional[float] = None) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """(the normalized quote with its age, None) or (None, quote_missing | quote_stale)."""
    nq = normalize_quote(q)
    if nq is None or nq["ltp"] is None:
        return None, "quote_missing"
    t = store.parse_ts(nq["received_at"])
    if t is None:
        return None, "quote_stale"
    limit = config.quote_max_age_s() if max_age_s is None else max_age_s
    age = (now - t).total_seconds()
    if age > limit or age < -limit:
        return None, "quote_stale"
    nq["age_s"] = round(age, 1)
    return nq, None


def executable_price(q: Dict[str, Any], side: str) -> Optional[float]:
    """The price a market order of `side` would meet first, before slippage: the bid for a SELL, the ask for a BUY; None
    without one (the monitor then judges on LTP and says so)."""
    return q.get("ask") if side == "BUY" else q.get("bid")


def book_side(q: Dict[str, Any], side: str, spread_pct: float) -> Tuple[List[Tuple[float, Optional[int]]], str]:
    """The levels an order of `side` executes against, best first, and which book they are (see the module docstring)."""
    depth = q.get("depth") or {}
    key = "sell" if side == "BUY" else "buy"
    if depth.get(key):
        levels = sorted(depth[key], key=lambda lv: lv[0], reverse=(side == "SELL"))
        return [(p, qn) for p, qn in levels], "depth"
    px = executable_price(q, side)
    qty = q.get("ask_qty") if side == "BUY" else q.get("bid_qty")
    if px is not None:
        return [(px, qty)], ("top_of_book" if qty else "top_of_book_no_qty")
    ltp = q["ltp"]
    px = ltp * (1 + spread_pct / 100.0) if side == "BUY" else ltp * (1 - spread_pct / 100.0)
    return [(px, None)], "ltp_spread"


def slippage_pct(order: Dict[str, Any]) -> float:
    model = order.get("cost_model") or cost_card.SNAPSHOT
    try:
        return float(model.get("slippage_pct_per_side", cost_card.SLIPPAGE_PCT_PER_SIDE))
    except (TypeError, ValueError):
        return cost_card.SLIPPAGE_PCT_PER_SIDE


def simulate(order: Dict[str, Any], quote: Any, now: datetime, *, session_open: bool,
             max_qty: Optional[int] = None) -> Dict[str, Any]:
    """One fill attempt (the module docstring). Pure. `max_qty`: an EXIT can never sell more than the position holds."""
    out: Dict[str, Any] = {"fills": [], "reason": None, "triggered_at": None, "quote": None}
    if not session_open:
        out["reason"] = "out_of_session"
        return out
    q, why = check_quote(quote, now)
    if why:
        out["reason"] = why
        return out
    side, otype = order["side"], order["order_type"]
    remaining = int(order.get("remaining_quantity") or 0)
    if max_qty is not None:
        remaining = min(remaining, max(0, int(max_qty)))
    out["quote"] = {"ltp": q["ltp"], "bid": q["bid"], "ask": q["ask"], "bid_qty": q["bid_qty"], "ask_qty": q["ask_qty"],
                    "open": q["open"], "received_at": q["received_at"], "age_s": q["age_s"]}
    if order.get("last_quote_at") and str(order["last_quote_at"]) == str(q["received_at"]):
        out["reason"] = "quote_already_used"
        return out
    if remaining <= 0:
        out["reason"] = "nothing_to_fill"
        return out
    if otype in ("SL", "SL_M") and not order.get("triggered_at"):
        trig = _num(order.get("trigger_price"))
        hit = trig is not None and (q["ltp"] >= trig if side == "BUY" else q["ltp"] <= trig)
        if not hit:
            out["reason"] = "not_triggered"
            return out
        out["triggered_at"] = store.iso(now)
    limit = _num(order.get("limit_price")) if otype in ("LIMIT", "SL") else None
    levels, basis = book_side(q, side, config.no_depth_spread_pct())
    known = basis in BOOK_KNOWN
    slip = slippage_pct(order)
    cap = remaining if known else min(remaining, max(1, int(math.floor(int(order["quantity"]) * config.no_depth_fraction()))))
    guard = order.get("purpose") == "ENTRY" and side == "BUY"
    planned = _num(order.get("planned_entry_price")) if guard else None
    plan_stop = _num((order.get("exit_plan") or {}).get("stop_loss")) if guard else None
    dev = config.entry_max_deviation_pct()
    left = cap
    for i, (ref, avail) in enumerate(levels):
        if left <= 0:
            break
        px = cost_card.paisa(ref * (1 + slip / 100.0) if side == "BUY" else ref * (1 - slip / 100.0))
        if limit is not None:
            if side == "BUY" and px > limit + 1e-9:
                if ref > limit + 1e-9:
                    out["reason"] = out["reason"] or ("limit_not_marketable" if i == 0 else None)
                    break
                px = limit
            if side == "SELL" and px < limit - 1e-9:
                if ref < limit - 1e-9:
                    out["reason"] = out["reason"] or ("limit_not_marketable" if i == 0 else None)
                    break
                px = limit
        if guard and planned is not None and px > planned * (1 + dev / 100.0) + 1e-9:
            out["reason"] = out["reason"] or ("price_beyond_plan" if i == 0 else None)
            break
        if guard and plan_stop is not None and px <= plan_stop + 1e-9:
            out["reason"] = out["reason"] or ("price_through_stop" if i == 0 else None)
            break
        take = left if avail is None else min(left, int(avail))
        if take <= 0:
            continue
        out["fills"].append({"quantity": take, "price": px, "ref_price": round(ref, 4), "level": i,
                             "depth_unknown": not known, "basis": basis,
                             "slippage_rs": cost_card.paisa(abs(px - ref) * take)})
        left -= take
    if out["fills"]:
        out["reason"] = None
    elif out["reason"] is None:
        out["reason"] = "no_liquidity"
    return out


# ── costs ────────────────────────────────────────────────────────────────────────────────────────────────────────────

def card_snapshot() -> Dict[str, Any]:
    """What an order snapshots (`cost_model`): the desk card, plus how SPT applies it."""
    return {**cost_card.SNAPSHOT, "segment": SEGMENT, "slippage_in_price": True,
            "slippage_basis_spt": "applied to the fill price against the bid/ask, so not charged again as a cost",
            "brokerage_basis_spt": "once per order, on its first fill", "execution_version": C.EXECUTION_VERSION}


def fill_costs(side: str, value: float, *, first_fill: bool, model: Optional[Dict[str, Any]] = None) -> Dict[str, float]:
    """The charges on one fill: desk-cost-v2 equity delivery, slippage 0 (it is in the price), brokerage on the first
    fill of the order only."""
    m = dict(model or cost_card.SNAPSHOT)
    brokerage = float(m.get("brokerage_rs_per_side", cost_card.BROKERAGE_RS_PER_SIDE))
    m.update(slippage_pct_per_side=0.0, brokerage_rs_per_side=brokerage if first_fill else 0.0)
    return cost_card.order_side(SEGMENT, side, value, m)


def exit_costs_per_share(price: float, quantity: int, model: Optional[Dict[str, Any]] = None) -> float:
    """The estimated charges per share of selling `quantity` at `price` as one order (brokerage included), for the
    breakeven stop."""
    if quantity <= 0 or price <= 0:
        return 0.0
    return fill_costs("SELL", price * quantity, first_fill=True, model=model)["total"] / quantity


# ── one attempt for one order ────────────────────────────────────────────────────────────────────────────────────────

async def execute_order(db, order: Dict[str, Any], quote: Any, now: datetime, *, session_open: bool) -> Dict[str, Any]:
    """One fill attempt: {"order_id", "filled": shares filled now, "reason"}. Never fills a non-live order, never more
    than an EXIT's position holds. Restart-safe: a fill is recorded on the order in the same conditional update that
    advances its version and state, so a replay or a second worker records nothing twice."""
    from . import orders                                    # orders imports this module

    order = await orders.sync_order(db, order["_id"])
    if order is None or order.get("state") not in C.ORD_LIVE_STATES:
        return {"order_id": (order or {}).get("_id"), "filled": 0, "reason": "not_live"}
    max_qty = None
    if order.get("purpose") == "EXIT":
        pos = await store.get_position(db, order.get("position_id"))
        max_qty = int((pos or {}).get("quantity") or 0)
    sim = simulate(order, quote, now, session_open=session_open, max_qty=max_qty)
    if not sim["fills"]:
        await orders.record_attempt(db, order, sim["reason"], now, triggered_at=sim["triggered_at"], quote=sim["quote"])
        return {"order_id": order["_id"], "filled": 0, "reason": sim["reason"]}
    after = await orders.record_fills(db, order, sim, now)
    if after is None:
        return {"order_id": order["_id"], "filled": 0, "reason": "changed_concurrently"}
    await orders.sync_order(db, order["_id"])
    return {"order_id": order["_id"], "filled": sum(f["quantity"] for f in sim["fills"]), "reason": None}
