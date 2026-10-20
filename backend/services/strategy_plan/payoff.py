"""Expiry payoff, breakevens, extremes and trading costs. Pure functions, no I/O.

Per-leg gross P&L at underlying price S (INR, whole position), sign = +1 buy / -1 sell, units = shares (cash) or
lots × lot_size (future, option):
    cash, future   sign × (S − entry) × units
    call           sign × (max(S − K, 0) − premium) × units
    put            sign × (max(K − S, 0) − premium) × units
The strategy payoff is the sum. It is piecewise linear in S with kinks only at the strikes.

Extremes: S ranges over [0, ∞). Candidate points are 0 and every strike; beyond the highest strike the payoff is a
straight line whose slope (`slopes`) says analytically whether the profit or the loss is unbounded. So max_profit and
max_loss are exact over all prices, not just over the plotted grid (`range_*` are over the plotted grid).

Costs (the strategy_engine backtest model, applied per leg, each side): slippage = DEFAULT_SLIPPAGE_PCT of the traded
value, plus a flat DEFAULT_BROKERAGE_INR. Entry: entry_price × units. Exit: the price S × units (cash, future) or, for an
option held to expiry, its intrinsic value × units. An option that expires worthless is not traded: no exit cost
(`worthless_exit_charged=True` charges it, used only for the conservative capital-at-risk). Excluded: taxes, STT,
exchange and statutory charges, dividends, funding.
"""
from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from services.strategy_engine.backtest import DEFAULT_BROKERAGE_INR, DEFAULT_SLIPPAGE_PCT

from .model import slopes

EPS = 1e-7
COST_MODEL = "slippage % of traded value + flat brokerage, each side, each leg"
EXCLUDED = ["taxes", "STT", "exchange and statutory charges", "dividends", "funding"]


def r2(x: Optional[float]) -> Optional[float]:
    return None if x is None else round(x + 0.0, 2)


def leg_gross(leg: Dict[str, Any], s: float) -> float:
    if leg["kind"] == "option":
        value = max(s - leg["strike"], 0.0) if leg["option_type"] == "call" else max(leg["strike"] - s, 0.0)
        return leg["sign"] * (value - leg["entry_price"]) * leg["units"]
    return leg["sign"] * (s - leg["entry_price"]) * leg["units"]


def gross(legs: Sequence[Dict[str, Any]], s: float) -> float:
    return sum(leg_gross(l, s) for l in legs)


# ── costs ────────────────────────────────────────────────────────────────────

def cost_params(c: Dict[str, Any]) -> Tuple[float, float, str]:
    """(slippage as a fraction, brokerage per side INR, where they came from)."""
    given = c.get("slippage_pct") is not None or c.get("brokerage_per_side") is not None
    slip = DEFAULT_SLIPPAGE_PCT if c.get("slippage_pct") is None else c["slippage_pct"] / 100.0
    brok = DEFAULT_BROKERAGE_INR if c.get("brokerage_per_side") is None else c["brokerage_per_side"]
    src = "request, defaults from services/strategy_engine/backtest.py for the rest" if given \
        else "services/strategy_engine/backtest.py defaults"
    return slip, brok, src


def entry_cost(leg: Dict[str, Any], slip: float, brok: float) -> float:
    return slip * leg["entry_price"] * leg["units"] + brok


def exit_value(leg: Dict[str, Any], s: float) -> float:
    """Traded value per unit on exit at expiry: the price (cash, future) or the intrinsic value (option)."""
    if leg["kind"] == "option":
        return max(s - leg["strike"], 0.0) if leg["option_type"] == "call" else max(leg["strike"] - s, 0.0)
    return s


def exit_cost_for_value(value_per_unit: float, units: int, slip: float, brok: float, worthless_charged: bool = False) -> float:
    if value_per_unit <= 0 and not worthless_charged:
        return 0.0
    return slip * max(value_per_unit, 0.0) * units + brok


def exit_cost(leg: Dict[str, Any], s: float, slip: float, brok: float, worthless_charged: bool = False) -> float:
    return exit_cost_for_value(exit_value(leg, s), leg["units"], slip, brok, worthless_charged)


def total_cost(legs: Sequence[Dict[str, Any]], s: float, slip: float, brok: float, worthless_charged: bool = False) -> float:
    return sum(entry_cost(l, slip, brok) + exit_cost(l, s, slip, brok, worthless_charged) for l in legs)


def costs_block(legs: Sequence[Dict[str, Any]], ref: float, slip: float, brok: float, source: str) -> Dict[str, Any]:
    per = []
    for l in legs:
        e, x = entry_cost(l, slip, brok), exit_cost(l, ref, slip, brok)
        per.append({"index": l["index"], "entry": r2(e), "exit_at_expiry": r2(x), "round_trip": r2(e + x)})
    e_tot = sum(entry_cost(l, slip, brok) for l in legs)
    x_tot = sum(exit_cost(l, ref, slip, brok) for l in legs)
    return {"model": COST_MODEL, "slippage_pct": r2(slip * 100), "brokerage_per_side": r2(brok), "source": source,
            "entry": r2(e_tot), "exit_at_expiry": r2(x_tot), "round_trip": r2(e_tot + x_tot),
            "exit_basis": "expiry settlement with the underlying at reference_price; an option expiring worthless has no exit cost",
            "per_leg": per, "excluded": list(EXCLUDED)}


# ── breakevens ───────────────────────────────────────────────────────────────

def zeros(xs: Sequence[float], f: Callable[[float], float], tail_slope: Optional[float] = None) -> Tuple[List[float], bool]:
    """Every price where the piecewise-linear f crosses or touches zero, with f linear between consecutive `xs`
    (which must include every kink). Sign changes are solved exactly by linear interpolation; a node at zero is
    included (a payoff that touches zero counts); a flat stretch at zero has no single price and is skipped, with
    the flag set. `tail_slope` extends the line beyond the last node."""
    xs = sorted(set(xs))
    ys = [f(x) for x in xs]
    z = [abs(y) < EPS for y in ys]
    out: List[float] = []
    flat = False
    for i, x in enumerate(xs):
        if z[i]:
            if (i > 0 and z[i - 1]) or (i + 1 < len(xs) and z[i + 1]):
                flat = True
            else:
                out.append(x)
        if i + 1 < len(xs) and not z[i] and not z[i + 1] and ys[i] * ys[i + 1] < 0:
            out.append(xs[i] + (xs[i + 1] - xs[i]) * (-ys[i]) / (ys[i + 1] - ys[i]))
    if tail_slope and not z[-1] and ys[-1] * tail_slope < 0:
        out.append(xs[-1] - ys[-1] / tail_slope)
    return sorted(out), flat


def breakevens(legs: Sequence[Dict[str, Any]], lo: float, hi: float, grid: Sequence[float]) -> Dict[str, Any]:
    """Breakevens inside the grid range, and every breakeven at any price (to warn when some lie outside)."""
    strikes = sorted({l["strike"] for l in legs if l["kind"] == "option"})
    f = lambda s: gross(legs, s)
    inside, flat = zeros(list(grid) + [k for k in strikes if lo < k < hi], f)
    up, _, _ = slopes(legs)
    every, flat2 = zeros([0.0] + strikes + [max(strikes + [hi])], f, up)
    return {"in_grid": inside, "all": every, "flat_at_zero": flat or flat2}


# ── extremes ─────────────────────────────────────────────────────────────────

def extremes(legs: Sequence[Dict[str, Any]], lo: float, hi: float, grid: Sequence[float]) -> Dict[str, Any]:
    up, _, _ = slopes(legs)
    strikes = sorted({l["strike"] for l in legs if l["kind"] == "option"})
    cand = [0.0] + strikes + [max(strikes + [hi])]
    vals = [gross(legs, s) for s in cand]
    in_range = [gross(legs, s) for s in list(grid) + [k for k in strikes if lo < k < hi]]
    profit_unb, loss_unb = up > 0, up < 0
    return {
        "profit_unbounded": profit_unb, "loss_unbounded": loss_unb,
        "max_profit": None if profit_unb else max(vals), "max_loss": None if loss_unb else min(vals),
        "range_max_profit": max(in_range), "range_max_loss": min(in_range),
        "candidates": cand,
    }


def capital_at_risk(legs: Sequence[Dict[str, Any]], ext: Dict[str, Any], slip: float, brok: float) -> Optional[float]:
    """Worst net loss over all prices, every leg charged both sides (conservative); None when the loss is unbounded."""
    if ext["loss_unbounded"]:
        return None
    worst = min(gross(legs, s) - total_cost(legs, s, slip, brok, True) for s in ext["candidates"])
    return max(-worst, 0.0)


def net_premium(legs: Sequence[Dict[str, Any]]) -> float:
    """Debit negative, credit positive; options only."""
    return sum(-l["sign"] * l["entry_price"] * l["units"] for l in legs if l["kind"] == "option")
