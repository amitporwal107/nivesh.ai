"""Estimated risk of an entry, in rupees: what the universal risk service sizes and limits on (Phase 1 item 1.3).

    estimated_risk_rs = {gross, costs, gap_stress, total, stop_based, ...}

SHARES (long; the desk records no short cash trades)
    gross       quantity x (entry - stop)                                   the loss AT the stop
    costs       round-trip costs of entering at the entry and leaving at the stop, priced by the desk cost card
                desk-cost-v2 (services/desk_cost_card.py through desk_trading.round_trip_cost: brokerage, STT,
                exchange, SEBI, stamp, GST, 0.05% slippage a side) — the same function that books realised costs
    gap_stress  quantity x stop x GAP_STRESS_PCT / 100                      the extra loss if the price gaps
                GAP_STRESS_PCT through the stop and the exit fills there instead of at the stop
    stop_based  gross + costs                                               stop-based risk (reported separately)
    total       gross + costs + gap_stress                                  what the per-trade and open-risk limits use

STRUCTURES (futures / options legs)
    options only        gross = the MAXIMUM LOSS AT EXPIRY from the full multi-leg payoff (services/risk_gate/gate.
                        structure_capital_at_risk, exact over the strike kinks); gap_stress = 0, because no gap can
                        lose more than the payoff's maximum; costs = entry sides at the leg prices + exit sides at the
                        intrinsic values where that maximum loss occurs.
    with a futures leg  the loss at the underlying stop (stop_underlying): the structure's payoff at the stop, every
                        leg at its value there (futures at the stop price, options at intrinsic value; a SHORT option
                        at no less than its entry premium, because before expiry it is worth at least its intrinsic
                        value and selling it back costs more, never less); gap_stress = the extra payoff loss between
                        the stop and the stop moved GAP_STRESS_PCT further; capped, gross and gap together, at the
                        maximum loss at expiry when the payoff has one. A futures leg with no stop has no estimate.
    Futures are valued at the underlying price (basis ignored, both at the entry and at the stop).

SIZING (services/risk_gate/service.py)
    the largest whole quantity (shares) or lot multiple (structure: every leg scaled together, only when every leg has
    the same lot count) whose `total` stays within a budget, found exactly by bisection on the pricing function. When
    the smallest valid quantity already exceeds the budget the entry is refused, never rounded up.

CREDIT STRUCTURES (credit_terms): whether a structure is a defined-risk credit structure, its net credit and its
strike width, for the credit rule of the reward_risk check (service.py, universal-risk-v2). The rule itself reads the
round-trip costs from the risk estimate above, so the credit after costs and the risk use the same costs.

GAP_STRESS_PCT is a named research constant, NOT calibrated: 1% of the stop price, about one typical overnight gap of
a large-cap NSE share; event days and small caps gap more. Changing it is a policy change: bump ESTIMATE_VERSION.
"""
from __future__ import annotations

import math
from typing import Any, Callable, Dict, List, Optional, Tuple

from services import desk_cost_card as cost_card
from services import desk_strategy_trades as strat
from services import desk_trading as desk

from . import gate

ESTIMATE_VERSION = "est-risk-v1"
GAP_STRESS_PCT = 1.0
GAP_STRESS_TEXT = (f"a gap of {GAP_STRESS_PCT:g}% of the stop price through the stop (research constant, not "
                   f"calibrated; {ESTIMATE_VERSION})")


def _r(x: float) -> float:
    return round(float(x), 2)


# ── shares ───────────────────────────────────────────────────────────────────
def cash_risk(quantity: int, entry: float, stop: float, model: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    q = int(quantity)
    gross = q * (entry - stop)
    costs = desk.round_trip_cost(q, entry, stop, model or desk.COST_MODEL) if q > 0 else 0.0
    gap = q * stop * GAP_STRESS_PCT / 100.0
    return {"gross": _r(gross), "costs": _r(costs), "gap_stress": _r(gap), "stop_based": _r(gross + costs),
            "total": _r(gross + costs + gap), "basis": "shares: qty x (entry - stop) + round-trip costs + gap stress",
            "gap_stress_pct": GAP_STRESS_PCT, "version": ESTIMATE_VERSION}


def cash_reward(quantity: int, entry: float, target: float, model: Optional[Dict[str, Any]] = None) -> float:
    """Gain at the target net of the round-trip costs of leaving there."""
    q = int(quantity)
    return _r(q * (target - entry) - desk.round_trip_cost(q, entry, target, model or desk.COST_MODEL))


def _largest(limit: int, fits: Callable[[int], bool]) -> int:
    """The largest n in [0, limit] with fits(n), for a `fits` that is true up to some n and false after."""
    if limit < 1 or not fits(1):
        return 0
    lo, hi = 1, limit
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if fits(mid):
            lo = mid
        else:
            hi = mid - 1
    return lo


def max_cash_qty(budget: float, entry: float, stop: float, upper: int, model: Optional[Dict[str, Any]] = None) -> int:
    """The most shares (<= upper) whose estimated `total` stays within `budget`; 0 when not even one share does."""
    if budget <= 0 or entry <= stop:
        return 0
    per_share = (entry - stop) + stop * GAP_STRESS_PCT / 100.0
    limit = min(int(upper), int(math.floor(budget / per_share)) + 1)
    return _largest(limit, lambda n: cash_risk(n, entry, stop, model)["total"] <= budget + 1e-9)


# ── structures ───────────────────────────────────────────────────────────────
def _value(leg: Dict[str, Any], spot: float, *, floor_short_at_entry: bool) -> float:
    """A leg's value per unit when the underlying is at `spot`: futures and cash at spot, options at intrinsic; a short
    option no lower than its entry premium when `floor_short_at_entry`."""
    if leg["kind"] in ("future", "cash"):
        return spot
    intrinsic = max(spot - leg["strike"], 0.0) if leg["option_type"] == "call" else max(leg["strike"] - spot, 0.0)
    if floor_short_at_entry and leg["side"] == "sell":
        return max(intrinsic, leg["entry_price"])
    return intrinsic


def _payoff(legs: List[Dict[str, Any]], spot: float, *, floor_short_at_entry: bool = False) -> float:
    return sum(leg["sign"] * leg["qty"] * (_value(leg, spot, floor_short_at_entry=floor_short_at_entry) - leg["entry_price"])
               for leg in legs)


def _costs(legs: List[Dict[str, Any]], spot: float, model: Optional[Dict[str, Any]], *, floor_short_at_entry: bool) -> float:
    """Entry sides at the leg prices + exit sides at the legs' values at `spot`, every leg, desk-cost-v2 by segment."""
    marks = [_value(leg, spot, floor_short_at_entry=floor_short_at_entry) for leg in legs]
    doc = {"legs": [{"kind": leg["kind"], "side": leg["side"], "lots": leg["lots"], "lot_size": leg["lot_size"],
                     "entry_price": leg["entry_price"]} for leg in legs], "cost_model": model or desk.COST_MODEL}
    breakdown = strat.strategy_cost_breakdown(doc, marks)
    return float(breakdown["total"]) if breakdown else 0.0


def _worst_point(legs: List[Dict[str, Any]]) -> float:
    points = [0.0] + sorted({leg["strike"] for leg in legs if leg["kind"] == "option"})
    return min(points, key=lambda s: _payoff(legs, s))


def scale_legs(legs: List[Dict[str, Any]], multiple: int, base: int) -> List[Dict[str, Any]]:
    """The legs with every lot count multiplied by multiple / base (all legs share `base` lots)."""
    out = []
    for leg in legs:
        lots = int(leg["lots"]) * multiple // base
        out.append({**leg, "lots": lots, "qty": lots * leg["lot_size"]})
    return out


def structure_risk(raw_legs: List[Dict[str, Any]], *, direction: Optional[str], stop_underlying: Optional[float],
                   model: Optional[Dict[str, Any]] = None) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """(estimate, None) or (None, why it cannot be estimated)."""
    legs, failures = gate.clean_legs(raw_legs)
    if failures or not legs:
        return None, "the legs are not valid"
    has_future = any(leg["kind"] == "future" for leg in legs)
    bounded = gate.structure_capital_at_risk(legs)            # None: unbounded upside or more than one expiry
    if not has_future:
        if bounded is None:
            return None, "the structure has no bounded maximum loss"
        spot = _worst_point(legs)
        costs = _costs(legs, spot, model, floor_short_at_entry=False)
        return {"gross": _r(bounded), "costs": _r(costs), "gap_stress": 0.0, "stop_based": _r(bounded + costs),
                "total": _r(bounded + costs), "max_loss_at_expiry": _r(bounded),
                "basis": "options: maximum loss at expiry from the payoff + round-trip costs; no gap stress (the "
                         "maximum loss already bounds any gap)",
                "gap_stress_pct": 0.0, "version": ESTIMATE_VERSION}, None
    if stop_underlying is None or stop_underlying <= 0:
        return None, "a structure with a futures leg needs a stop on the underlying to estimate its risk"
    down = direction != "bearish"
    stressed = stop_underlying * (1 - GAP_STRESS_PCT / 100.0) if down else stop_underlying * (1 + GAP_STRESS_PCT / 100.0)
    at_stop = -_payoff(legs, stop_underlying, floor_short_at_entry=True)
    at_gap = -_payoff(legs, stressed, floor_short_at_entry=True)
    gross = max(at_stop, 0.0)
    gap = max(at_gap - gross, 0.0)
    capped = False
    if bounded is not None and gross + gap > bounded:
        capped = True
        gross = min(gross, bounded)
        gap = max(bounded - gross, 0.0)
    costs = _costs(legs, stop_underlying, model, floor_short_at_entry=True)
    return {"gross": _r(gross), "costs": _r(costs), "gap_stress": _r(gap), "stop_based": _r(gross + costs),
            "total": _r(gross + costs + gap), "max_loss_at_expiry": None if bounded is None else _r(bounded),
            "capped_at_max_loss": capped,
            "basis": "futures: payoff loss at the underlying stop (futures at the stop, options at intrinsic, short "
                     "options at least at their entry premium) + round-trip costs + gap stress",
            "gap_stress_pct": GAP_STRESS_PCT, "version": ESTIMATE_VERSION}, None


def structure_reward(raw_legs: List[Dict[str, Any]], *, direction: Optional[str], target_underlying: Optional[float],
                     model: Optional[Dict[str, Any]] = None) -> Tuple[Optional[float], str]:
    """(net reward, basis) for the reward:risk check. Options only: the maximum gain at expiry over the strikes, None when
    it is unbounded (an unbounded gain passes the check). With a futures leg: the payoff at target_underlying, less
    costs; None and a reason when there is no target."""
    legs, failures = gate.clean_legs(raw_legs)
    if failures or not legs:
        return None, "invalid legs"
    has_future = any(leg["kind"] == "future" for leg in legs)
    if has_future:
        if target_underlying is None:
            return None, "no target"
        gain = _payoff(legs, target_underlying)
        return _r(gain - _costs(legs, target_underlying, model, floor_short_at_entry=False)), "payoff at the target"
    up_slope = sum(leg["sign"] * leg["qty"] for leg in legs if leg["kind"] == "cash" or leg["option_type"] == "call")
    if up_slope > 0:
        return None, "unbounded gain (net long calls)"
    # The payoff is piecewise linear with kinks at the strikes and a non-positive slope beyond the last one, so its
    # maximum over S >= 0 is at S = 0 or at a strike (long puts gain most at S = 0, which is still bounded).
    points = [0.0] + sorted({leg["strike"] for leg in legs if leg["kind"] == "option"})
    best = max(points, key=lambda s: _payoff(legs, s))
    gain = _payoff(legs, best)
    return _r(gain - _costs(legs, best, model, floor_short_at_entry=False)), "maximum gain at expiry"


def credit_terms(raw_legs: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """The terms of a DEFINED-RISK CREDIT STRUCTURE, or None when the legs are not one (owner decision 2026-10-28; the
    rule itself is in service.py, policy universal-risk-v2). Decided from the legs and the payoff, never a template name:

      1. no futures leg (a futures leg is not defined risk under the desk rule);
      2. at least one option leg, every option leg one expiry;
      3. the payoff at expiry is FLAT beyond the outermost strikes on both sides: slope 0 as the underlying rises without
         limit (cash, futures and calls) and as it falls to 0 (cash and futures less puts). The loss is then bounded by
         long options, not by a share price of zero: a covered call (loss runs to zero) and a long call or protective
         put (open upside) are not credit structures;
      4. the option legs open for a NET CREDIT: premium of the sold options x quantity - premium of the bought ones > 0.

    Bull put and bear call spreads, iron condors (and other flat-winged credit structures) and a collar whose options
    open for a credit qualify; debit spreads, long options, a collar opened for a debit and a covered call do not.

    width_rs is the maximum loss at expiry BEFORE the premiums (the payoff with every option premium set to 0): the
    strike difference x lots x lot size for a vertical spread; the wider wing for an iron condor (only one wing can be in
    the money at expiry); for a collar, the fall from the share price to the put strike x shares."""
    legs, failures = gate.clean_legs(raw_legs)
    if failures or not legs:
        return None
    options = [leg for leg in legs if leg["kind"] == "option"]
    if not options or any(leg["kind"] == "future" for leg in legs):
        return None
    if len({leg["expiry"] for leg in options}) > 1:
        return None
    up = sum(leg["sign"] * leg["qty"] for leg in legs if leg["kind"] == "cash" or leg["option_type"] == "call")
    down = (sum(leg["sign"] * leg["qty"] for leg in legs if leg["kind"] == "cash")
            - sum(leg["sign"] * leg["qty"] for leg in options if leg["option_type"] == "put"))
    if up != 0 or down != 0:
        return None
    net_credit = sum(-leg["sign"] * leg["qty"] * leg["entry_price"] for leg in options)
    if net_credit <= 0:
        return None
    unpriced = [{**leg, "entry_price": 0.0} if leg["kind"] == "option" else leg for leg in legs]
    points = [0.0] + sorted({leg["strike"] for leg in options})
    width = max(0.0, -min(_payoff(unpriced, s) for s in points))
    max_loss = max(0.0, -min(_payoff(legs, s) for s in points))
    return {"net_credit_rs": _r(net_credit), "width_rs": _r(width), "max_loss_at_expiry_rs": _r(max_loss),
            "basis": "options net credit (sold premium - bought premium, x quantity); width = the maximum loss at "
                     "expiry before the premiums"}


def common_lots(raw_legs: List[Dict[str, Any]]) -> Optional[int]:
    """The lot count every derivative leg shares, or None when they differ (then a structure cannot be scaled down)."""
    lots = {int(leg.get("lots") or 0) for leg in raw_legs if isinstance(leg, dict) and leg.get("kind") != "cash"}
    return lots.pop() if len(lots) == 1 else None


def max_structure_multiple(raw_legs: List[Dict[str, Any]], budget: float, *, direction: Optional[str],
                           stop_underlying: Optional[float], model: Optional[Dict[str, Any]] = None) -> int:
    """The most lots per leg (<= the requested common lot count) whose estimated `total` stays within `budget`;
    0 when not even one lot per leg does, or the legs cannot be scaled together."""
    base = common_lots(raw_legs)
    if not base or any(leg.get("kind") == "cash" for leg in raw_legs if isinstance(leg, dict)):
        if base:
            est, _ = structure_risk(raw_legs, direction=direction, stop_underlying=stop_underlying, model=model)
            return base if est and est["total"] <= budget + 1e-9 else 0
        return 0

    def fits(m: int) -> bool:
        legs = [{**leg, "lots": m} for leg in raw_legs]
        est, _ = structure_risk(legs, direction=direction, stop_underlying=stop_underlying, model=model)
        return est is not None and est["total"] <= budget + 1e-9

    return _largest(base, fits)


def segment_note() -> Dict[str, Any]:
    return {"version": ESTIMATE_VERSION, "gap_stress_pct": GAP_STRESS_PCT, "gap_stress_text": GAP_STRESS_TEXT,
            "cost_model": cost_card.VERSION}
