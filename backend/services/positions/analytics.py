"""Analytics for one group of positions on one underlying. Pure functions, no I/O.

A leg (built by services/positions/service.py):
    kind          "cash" | "future" | "option"
    option_type   "call" | "put" (options only)
    strike        option strike
    sign          +1 long, -1 short
    units         shares of the underlying (lots × lot size for F&O)
    entry_price   the broker's average price (or the paper trade's entry), per unit
    mark          the price the leg is valued at today, per unit (None when there is none)
    forward       the forward of the leg's expiry on the pricing day (options and futures), else None
    iv            implied volatility a year as a fraction (options), else None
    t             years to expiry on the pricing day (options), else None
    delta/gamma/theta/vega   per unit of the underlying, from the pricing day's chain (options)

Two valuations of a move of the underlying to S:
    expiry   the payoff at expiry (services/strategy_plan/payoff.py: options at intrinsic value)
    today    every option repriced with Black-76 at its own implied volatility and time left, its forward moved in
             proportion to S; a future moved the same way; shares at S. None when any option leg has no implied
             volatility (its price was not a market price), never a guess.
Both are GROSS: before brokerage, taxes and slippage.

Loss at the stop (owner rule, 30 Oct 2026): a group that holds shares or a long future with no long put under it, or
whose loss is unbounded, is never shown with a "to zero" maximum loss. Its risk figure is the loss if the underlying
reaches the stop the user set; with no stop it has none and says so. A defined-risk option structure keeps its
expiry maximum loss.
"""
from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Sequence

from services import option_pricing
from services.strategy_plan import payoff

NEAR_STOP_PCT = 2.0           # within 2% of the stop (or the target): "near"
EXPIRY_SOON_DAYS = 2          # expires today, tomorrow or the day after
SCENARIO_MOVES = (-10.0, -5.0, -3.0, -2.0, -1.0, 0.0, 1.0, 2.0, 3.0, 5.0, 10.0)
CURVE_POINTS = 41
CURVE_SPAN = 0.15             # the payoff curve spans ±15% of the spot (stretched to include strikes and levels)


def r2(x: Optional[float]) -> Optional[float]:
    return None if x is None or not math.isfinite(x) else round(x + 0.0, 2)


def _payoff_leg(leg: Dict[str, Any]) -> Dict[str, Any]:
    return {"kind": leg["kind"], "option_type": leg.get("option_type"), "strike": leg.get("strike"),
            "sign": leg["sign"], "units": leg["units"], "entry_price": leg["entry_price"]}


def expiry_pnl(legs: Sequence[Dict[str, Any]], s: float) -> float:
    return payoff.gross([_payoff_leg(l) for l in legs], s)


def _leg_value_today(leg: Dict[str, Any], s: float, spot: float, iv_shift: float = 0.0, days_forward: int = 0) -> Optional[float]:
    if leg["kind"] == "cash":
        return s
    ratio = s / spot
    if leg["kind"] == "future":
        base = leg.get("forward") or leg.get("mark")
        return None if base is None else base * ratio
    if leg.get("iv") is None or leg.get("forward") is None or leg.get("t") is None:
        return None
    t = max(leg["t"] - days_forward / option_pricing.DAYS_PER_YEAR, 0.0)
    vol = max(leg["iv"] + iv_shift / 100.0, option_pricing.MIN_VOL)
    kind = "CE" if leg["option_type"] == "call" else "PE"
    return option_pricing.price(kind, leg["forward"] * ratio, leg["strike"], t, vol)


def today_pnl(legs: Sequence[Dict[str, Any]], s: float, spot: Optional[float], iv_shift: float = 0.0,
              days_forward: int = 0) -> Optional[float]:
    """Gross P&L if the underlying were at S on the pricing day (or `days_forward` days later), every option at its
    own implied volatility (+ `iv_shift` volatility points). None when any leg cannot be valued."""
    if not spot or spot <= 0:
        return None
    total = 0.0
    for leg in legs:
        v = _leg_value_today(leg, s, spot, iv_shift, days_forward)
        if v is None:
            return None
        total += leg["sign"] * (v - leg["entry_price"]) * leg["units"]
    return total


def greeks(legs: Sequence[Dict[str, Any]]) -> Optional[Dict[str, float]]:
    """Position Greeks in underlying units: delta (shares), gamma, theta (₹ a day), vega (₹ per volatility point).
    None when any option leg has no Greeks."""
    out = {"delta": 0.0, "gamma": 0.0, "theta": 0.0, "vega": 0.0}
    for leg in legs:
        q = leg["sign"] * leg["units"]
        if leg["kind"] in ("cash", "future"):
            out["delta"] += q
            continue
        if any(leg.get(g) is None for g in out):
            return None
        for g in out:
            out[g] += q * leg[g]
    return {"delta": round(out["delta"], 2), "gamma": round(out["gamma"], 6), "theta": round(out["theta"], 2),
            "vega": round(out["vega"], 2)}


def direction(legs: Sequence[Dict[str, Any]], spot: float, g: Optional[Dict[str, float]]) -> int:
    """+1 when the group gains as the underlying rises, -1 when it loses, 0 when flat at the spot."""
    if g is not None and abs(g["delta"]) > 1e-9:
        return 1 if g["delta"] > 0 else -1
    up, down = expiry_pnl(legs, spot * 1.001), expiry_pnl(legs, spot * 0.999)
    return 1 if up > down + 1e-9 else -1 if down > up + 1e-9 else 0


def _risk_basis(legs: Sequence[Dict[str, Any]], loss_unbounded: bool) -> str:
    long_underlying = any(l["kind"] in ("cash", "future") and l["sign"] > 0 for l in legs)
    long_put = any(l["kind"] == "option" and l.get("option_type") == "put" and l["sign"] > 0 for l in legs)
    return "stop" if loss_unbounded or (long_underlying and not long_put) else "expiry"


def _at_level(legs: Sequence[Dict[str, Any]], level: Optional[float], spot: float):
    """(gross P&L with the underlying at `level`, "today" | "expiry"): today's valuation when every leg can be
    valued, else the expiry payoff. (None, None) with no level."""
    if not level:
        return None, None
    v = today_pnl(legs, level, spot)
    return (v, "today") if v is not None else (expiry_pnl(legs, level), "expiry")


def curve(legs: Sequence[Dict[str, Any]], spot: float, extra: Sequence[float] = ()) -> List[List[Optional[float]]]:
    """[[price, expiry P&L, today P&L], …] over ±15% of the spot, widened to include strikes and levels."""
    lo, hi = spot * (1 - CURVE_SPAN), spot * (1 + CURVE_SPAN)
    marks = [k for k in [*(l.get("strike") for l in legs if l["kind"] == "option"), *extra] if k]
    if marks:
        lo, hi = min(lo, min(marks) * 0.98), max(hi, max(marks) * 1.02)
    step = (hi - lo) / (CURVE_POINTS - 1)
    xs = sorted({round(lo + i * step, 2) for i in range(CURVE_POINTS)} | {round(m, 2) for m in marks} | {round(spot, 2)})
    return [[x, r2(expiry_pnl(legs, x)), r2(today_pnl(legs, x, spot))] for x in xs if x > 0]


def scenario(legs: Sequence[Dict[str, Any]], spot: float, moves: Sequence[float] = SCENARIO_MOVES,
             iv_shift: float = 0.0, days_forward: int = 0) -> List[Dict[str, Any]]:
    rows = []
    for m in moves:
        s = spot * (1 + m / 100.0)
        rows.append({"move_pct": m, "price": r2(s), "expiry_pnl_rs": r2(expiry_pnl(legs, s)),
                     "today_pnl_rs": r2(today_pnl(legs, s, spot, iv_shift, days_forward))})
    return rows


def analyse(legs: Sequence[Dict[str, Any]], spot: Optional[float], levels: Optional[Dict[str, Any]] = None,
            days_to_expiry: Optional[int] = None, physically_settled: bool = False) -> Dict[str, Any]:
    """Every figure of one group. `levels` = {stop, target} (an effective stop already worked out)."""
    levels = levels or {}
    stop, target = levels.get("stop"), levels.get("target")
    out: Dict[str, Any] = {"greeks": None, "delta_exposure_rs": None, "exposure_rs": None, "payoff": None,
                           "scenario": [], "curve": [], "distance_to_stop_pct": None, "distance_to_target_pct": None,
                           "direction": None, "warnings": []}
    if not legs:
        return out
    exposure = [abs(l["units"] * (l["mark"] if l.get("mark") is not None else l["entry_price"]))
                for l in legs if l["kind"] in ("cash", "future")]
    out["exposure_rs"] = r2(sum(exposure)) if exposure else None
    if not spot or spot <= 0:
        return out
    g = greeks(legs)
    out["greeks"] = g
    out["delta_exposure_rs"] = r2(g["delta"] * spot) if g else None
    d = direction(legs, spot, g)
    out["direction"] = {1: "long", -1: "short", 0: "flat"}[d]

    pl = [_payoff_leg(l) for l in legs]
    strikes = sorted({l["strike"] for l in pl if l["kind"] == "option"})
    hi = max([spot * 2] + strikes)
    grid = [hi * i / 200 for i in range(201)]
    ext = payoff.extremes(pl, 0.0, hi, grid)
    be = payoff.breakevens(pl, 0.0, hi, grid)
    basis = _risk_basis(legs, ext["loss_unbounded"])
    at_stop, at_stop_basis = _at_level(legs, stop, spot)
    at_target, _ = _at_level(legs, target, spot)
    # "Risk left" (the owner's Trader design): what the group would lose from the current price to the stop, on the
    # same valuation as the figure at the stop.
    now = None
    if at_stop is not None:
        now = today_pnl(legs, spot, spot) if at_stop_basis == "today" else expiry_pnl(legs, spot)
    out["payoff"] = {
        "breakevens": [r2(x) for x in be["all"]],
        "max_profit": None if ext["profit_unbounded"] else r2(ext["max_profit"]),
        "profit_unbounded": ext["profit_unbounded"],
        # A to-zero figure is never the headline for shares or a future held long (owner rule); see the module docstring.
        "max_loss": r2(ext["max_loss"]) if basis == "expiry" and not ext["loss_unbounded"] else None,
        "loss_unbounded": ext["loss_unbounded"],
        "risk_basis": basis,
        "pnl_at_stop_rs": r2(at_stop),
        "loss_at_stop_rs": r2(max(-at_stop, 0.0)) if at_stop is not None else None,
        "pnl_at_stop_basis": at_stop_basis,
        "risk_to_stop_rs": r2(max(now - at_stop, 0.0)) if now is not None else None,
        "pnl_at_target_rs": r2(at_target),
        "gross": True,
    }
    out["scenario"] = scenario(legs, spot)
    out["curve"] = curve(legs, spot, [x for x in (stop, target) if x])

    w: List[Dict[str, str]] = []
    if stop and d:
        dist = (spot - stop) / spot * 100 * d
        out["distance_to_stop_pct"] = r2(dist)
        if dist < 0:
            w.append({"code": "stop_breached", "tone": "danger",
                      "text": f"The price ({spot:,.2f}) is past your stop ({stop:,.2f})."})
        elif dist <= NEAR_STOP_PCT:
            w.append({"code": "near_stop", "tone": "amber", "text": f"{dist:.2f}% from your stop ({stop:,.2f})."})
    elif not stop:
        w.append({"code": "no_stop", "tone": "ink", "text": "No stop set: the loss at a stop cannot be shown."})
    if target and d:
        dist_t = (target - spot) / spot * 100 * d
        out["distance_to_target_pct"] = r2(dist_t)
        if dist_t <= 0:
            w.append({"code": "target_reached", "tone": "mint", "text": f"The price has reached your target ({target:,.2f})."})
    if days_to_expiry is not None and 0 <= days_to_expiry <= EXPIRY_SOON_DAYS:
        when = "today" if days_to_expiry == 0 else "tomorrow" if days_to_expiry == 1 else f"in {days_to_expiry} days"
        w.append({"code": "expiry_soon", "tone": "amber", "text": f"The nearest contract expires {when}."})
        if physically_settled and any(l["kind"] in ("future", "option") for l in legs):
            w.append({"code": "physical_settlement", "tone": "amber",
                      "text": "Stock F&O is settled by delivery: a future, or an option in the money at expiry, "
                              "becomes a delivery of shares."})
    out["warnings"] = w
    return out
