"""One watched position as the screen and the watcher see it (docs/paper_pnl_dashboard/EXIT_WATCH.md "Status"). Pure.

The stop in force, first that applies:
    yours        the user's own stop or trail for the underlying (position_levels; positions.store.effective_stop)
    put_floor /  a hedged position: its option strike
    call_cap
    atr_trail    the stored (or, on a read before the watcher stored one, the in-memory) 2 × ATR trailing stop
    none         no level: the reason is in `why`
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from . import rules
from .book import Watched

HISTORY_SHOWN = 5


def stop_in_force(w: Watched, rule_stop: Optional[float], own: Optional[Dict[str, Any]],
                  price: Optional[float]) -> tuple:
    """(stop, method) by the order above."""
    from services.positions import store as positions_store
    if own and (own.get("stop") or own.get("trail_pct")):
        eff = positions_store.effective_stop(own, price, w.side)
        if eff:
            return rules.r2(float(eff)), rules.YOURS
    if w.kind == "hedged" and w.hedge:
        return float(w.hedge["strike"]), w.method
    if rule_stop is not None:
        return float(rule_stop), rules.ATR_TRAIL
    return None, rules.NONE


def position_view(w: Watched, lvl: Dict[str, Any], own: Optional[Dict[str, Any]], *, price: Optional[float],
                  source: Optional[str], as_of: Optional[str], stored: bool) -> Dict[str, Any]:
    """The GET body's position entry. `lvl` is `rules.advance_level`'s answer (or a stored level read the same way)."""
    rule_stop = lvl.get("stop")
    atr = lvl.get("atr")
    stop, method = stop_in_force(w, rule_stop, own, price)
    status, dpct, datr = rules.status_of(w.side, price, stop, atr, method)
    why = None
    if stop is None:
        why = lvl.get("why") or "no NSE end-of-day prices to work a stop loss out from"
    elif price is None:
        why = "no price for the stock yet"
    d1: List[Dict[str, Any]] = [{"type": l.type, "quantity": l.quantity, "avg": l.avg, "price": l.price} for l in w.delta_one]
    hedged = method in rules.HEDGE_METHODS
    loss, basis = rules.loss_at_stop("hedged" if hedged else w.kind, w.side, d1, stop, spot=price,
                                     hedge=w.hedge if hedged else None)
    note = w.note
    if method == rules.YOURS and w.kind == "hedged":
        note = "your stop loss is used; the option is left out of the loss at stop"
    return {
        "key": w.key, "account_id": w.account_id, "account": w.account, "underlying": w.underlying, "label": w.label,
        "kind": w.kind, "side": w.side, "legs": [l.public() for l in w.legs],
        "price": rules.r2(price), "price_source": source if price is not None else None, "price_as_of": as_of if price is not None else None,
        "stop": rules.r2(stop), "method": method, "stop_day": lvl.get("day"), "stored": stored,
        "rule_stop": rules.r2(rule_stop), "atr": lvl.get("atr"), "atr_pct": lvl.get("atr_pct"),
        "distance_pct": dpct, "distance_atr": datr, "status": status, "why": why,
        "loss_at_stop": loss, "loss_basis": basis, "support": lvl.get("support"), "note": note,
        "history": list(lvl.get("history") or [])[-HISTORY_SHOWN:],
        # The user's own levels for the underlying as stored (position_levels), so the screen can change the stop without
        # wiping a target or a trail: PUT /api/positions/{underlying}/levels replaces the whole document.
        "own": ({k: own.get(k) for k in ("stop", "target", "trail_pct")}
                if own and any(own.get(k) is not None for k in ("stop", "target", "trail_pct")) else None),
    }
