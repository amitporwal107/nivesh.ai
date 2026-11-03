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

Costs (payoff-v2, the desk cost card desk-cost-v2, services/desk_cost_card.py — the card the plan's sizing and every
paper trade use): each leg is charged per ORDER SIDE by its segment — a cash leg as equity delivery, a future as futures,
an option on its premium — brokerage, STT, exchange transaction charge, SEBI fee, stamp duty, GST and slippage, each
rounded to the paisa as a contract note adds them up. The entry side is the leg's own side (a buy or a sale) on
entry_price × units; the exit side is the opposite, on the price S × units (cash, future) or, for an option held to
expiry, its intrinsic value × units (the card's expiry convention: the option is priced as sold, or bought back, at its
settlement value, so a long in-the-money option pays the sell-side STT on its intrinsic value). An option that expires
worthless is not traded: no exit order and no exit cost (`worthless_exit_charged=True` charges that side's brokerage and
GST, used only for the conservative capital-at-risk, the desk's own convention for a worthless leg). A request's
`costs.slippage_pct` (percent) and `costs.brokerage_per_side` (₹) replace the card's two desk assumptions; the
statutory charges are always applied. Excluded: DP charges, IPFT and clearing charges, income tax on gains, dividends,
funding.

payoff-v1 (until 2026-10-27) charged slippage and a flat brokerage only, so its net figures left out STT, exchange, SEBI,
stamp duty and GST while the plan's sizing and the paper trades included them.
"""
from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from services import desk_cost_card as cost_card

from .model import slopes

EPS = 1e-7
COST_VERSION = cost_card.VERSION
#: The card segment each leg kind is priced as (the same mapping as services/desk_strategy_trades.LEG_SEGMENT).
SEGMENT = {"cash": "equity_delivery", "future": "futures", "option": "options"}
COST_MODEL = (f"the desk cost card {COST_VERSION} (services/desk_cost_card.py): brokerage, STT, exchange transaction charge, "
              "SEBI fee, stamp duty, GST and slippage, per leg and per order side, by segment (cash as equity delivery, "
              "futures, options on the premium)")
EXCLUDED = ["DP charges", "IPFT and clearing charges", "income tax on gains", "dividends", "funding"]


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

def cost_params(c: Dict[str, Any]) -> Tuple[Dict[str, Any], str]:
    """(the cost-model snapshot every side is priced with, where it came from): the desk cost card, with the request's
    slippage % and brokerage per side in place of the card's two desk assumptions where given."""
    model = dict(cost_card.SNAPSHOT)
    given = []
    if c.get("slippage_pct") is not None:
        model["slippage_pct_per_side"] = float(c["slippage_pct"])
        given.append("slippage_pct")
    if c.get("brokerage_per_side") is not None:
        model["brokerage_rs_per_side"] = float(c["brokerage_per_side"])
        given.append("brokerage_per_side")
    src = f"services/desk_cost_card.py ({COST_VERSION})"
    if given:
        src += f"; {' and '.join(given)} from the request"
    return model, src


def _side(leg: Dict[str, Any], entry: bool) -> str:
    """The order side: the entry is the leg's own side, the exit the opposite."""
    return "BUY" if (leg["sign"] > 0) == entry else "SELL"


def entry_side(leg: Dict[str, Any], model: Dict[str, Any]) -> Dict[str, float]:
    return cost_card.order_side(SEGMENT[leg["kind"]], _side(leg, True), leg["entry_price"] * leg["units"], model)


def entry_cost(leg: Dict[str, Any], model: Dict[str, Any]) -> float:
    return entry_side(leg, model)["total"]


def exit_value(leg: Dict[str, Any], s: float) -> float:
    """Traded value per unit on exit at expiry: the price (cash, future) or the intrinsic value (option)."""
    if leg["kind"] == "option":
        return max(s - leg["strike"], 0.0) if leg["option_type"] == "call" else max(leg["strike"] - s, 0.0)
    return s


def exit_side_for_value(leg: Dict[str, Any], value_per_unit: float, model: Dict[str, Any],
                        worthless_charged: bool = False) -> Optional[Dict[str, float]]:
    """The exit order side's charges at `value_per_unit`, or None when nothing is traded (a worthless exit, unless
    `worthless_charged`)."""
    if value_per_unit <= 0 and not worthless_charged:
        return None
    return cost_card.order_side(SEGMENT[leg["kind"]], _side(leg, False), max(value_per_unit, 0.0) * leg["units"], model)


def exit_cost_for_value(leg: Dict[str, Any], value_per_unit: float, model: Dict[str, Any],
                        worthless_charged: bool = False) -> float:
    side = exit_side_for_value(leg, value_per_unit, model, worthless_charged)
    return side["total"] if side else 0.0


def exit_cost(leg: Dict[str, Any], s: float, model: Dict[str, Any], worthless_charged: bool = False) -> float:
    return exit_cost_for_value(leg, exit_value(leg, s), model, worthless_charged)


def total_cost(legs: Sequence[Dict[str, Any]], s: float, model: Dict[str, Any], worthless_charged: bool = False) -> float:
    return sum(entry_cost(l, model) + exit_cost(l, s, model, worthless_charged) for l in legs)


def costs_block(legs: Sequence[Dict[str, Any]], ref: float, model: Dict[str, Any], source: str) -> Dict[str, Any]:
    per = []
    entries, exits = [], []
    for l in legs:
        e = entry_side(l, model)
        x = exit_side_for_value(l, exit_value(l, ref), model)
        entries.append(e)
        if x:
            exits.append(x)
        xt = x["total"] if x else 0.0
        per.append({"index": l["index"], "segment": SEGMENT[l["kind"]], "entry": r2(e["total"]), "exit_at_expiry": r2(xt),
                    "round_trip": r2(e["total"] + xt)})
    e_tot = sum(e["total"] for e in entries)
    x_tot = sum(x["total"] for x in exits)
    return {"model": COST_MODEL, "version": COST_VERSION,
            "slippage_pct": r2(float(model["slippage_pct_per_side"])), "brokerage_per_side": r2(float(model["brokerage_rs_per_side"])),
            "source": source,
            "entry": r2(e_tot), "exit_at_expiry": r2(x_tot), "round_trip": r2(e_tot + x_tot),
            "components": {"entry": cost_card.add(*entries) if entries else None,
                           "exit_at_expiry": cost_card.add(*exits) if exits else None},
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


def capital_at_risk(legs: Sequence[Dict[str, Any]], ext: Dict[str, Any], model: Dict[str, Any]) -> Optional[float]:
    """Worst net loss over all prices, every leg charged both sides (conservative); None when the loss is unbounded."""
    if ext["loss_unbounded"]:
        return None
    worst = min(gross(legs, s) - total_cost(legs, s, model, True) for s in ext["candidates"])
    return max(-worst, 0.0)


def net_premium(legs: Sequence[Dict[str, Any]]) -> float:
    """Debit negative, credit positive; options only."""
    return sum(-l["sign"] * l["entry_price"] * l["units"] for l in legs if l["kind"] == "option")
