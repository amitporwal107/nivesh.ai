"""Position sizing for an SPT proposal (PRD §8.3-§8.5, WF §8): pure, every step recorded.

    allowed risk     = equity × risk %                                     (PRD §8.3; risk % = policy.effective_risk_pct)
    risk per share   = |entry − stop| + estimated cost per share           (WF §8.3)
    quantity         = floor(allowed risk / risk per share)                (PRD §8.4)

EQUITY: `risk_book.read(...)["equity"]["equity_rs"]` — paper cash plus the net unrealised P&L of the open desk
positions at their end-of-day marks (services/risk_profile.CAPITAL_BASIS_TEXT), the same equity the universal risk
service measures every limit against. Unknown equity sizes nothing (blocked `equity_unknown`), never a guess.

COST PER SHARE: when the caller gives one (the PRD's worked example: ₹0.50) the formula uses it as given. Otherwise the
desk cost card desk-cost-v2 prices the round trip entry → stop exactly (`desk_trading.max_units_within_budget`, the same
function that books realised costs): the largest quantity whose loss at the stop INCLUDING the round-trip costs fits the
allowed risk; the cost per share reported is that round trip ÷ quantity.

THE CAPS, IN ORDER (each a step {cap, before, after, limit, reason}; a cap never raises the quantity):
    risk_budget             the formula above
    risk_profile_per_trade  the risk profile's own per-trade definition: stop loss + costs + the gap stress
                            (risk_gate.estimate.cash_risk, GAP_STRESS_PCT) within equity × profile per_trade_risk_pct —
                            the check the risk service applies, by the same function (estimate.max_cash_qty), so a size
                            sent to it is not cut again (TESTCASES DB-3). Only when the profile's % is given.
    liquidity               ≤ max_adv_participation_pct of the 20-session average daily traded value (risk_gate.inputs
                            ADV); ADV unknown → 0 (liquidity_unknown); ADV below min_adv_rs → 0 (liquidity_below_floor);
                            skipped only when no liquidity input at all is given (a pure calculation)
    position_exposure       quantity × entry ≤ equity × the profile's max_position_pct
    available_capital       quantity × entry ≤ the paper account's available capital minus the reserve bucket
    lot_size                whole lots (1 share for cash)

RESULT: {inputs, steps, quantity, capital_required, planned_risk, stressed_risk, cost_per_share, blocked[], version}
    planned_risk   quantity × |entry − stop| + costs (given per share, or the cost card's round trip)    PRD §9.2
    stressed_risk  planned_risk + quantity × stop × stressed_gap_pct / 100 (a gap of that % through the stop)
A stop is never moved to fit a size (PRD §8.5): the stop is an input here, never an output.
"""
from __future__ import annotations

import hashlib
import json
import math
from typing import Any, Dict, List, Optional

from services import desk_trading as desk
from services.risk_gate import estimate as est

from . import constants as C

EQUITY_BASIS = ("risk_book equity: paper cash + net unrealised P&L of the open desk positions at end-of-day marks "
                "(services/risk_profile.CAPITAL_BASIS_TEXT), the equity the universal risk service measures limits on")


def _f(x: Any) -> Optional[float]:
    if isinstance(x, bool) or not isinstance(x, (int, float)) or not math.isfinite(float(x)):
        return None
    return float(x)


def inputs_hash(inputs: Dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(inputs, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()


def size(*, equity_rs: Any, risk_pct: Any, entry: Any, stop: Any, cost_per_share: Any = None, adv_rs: Any = None,
         min_adv_rs: Any = None, max_adv_participation_pct: Any = None, max_position_pct: Any = None,
         available_rs: Any = None, reserve_rs: Any = 0.0, profile_per_trade_pct: Any = None,
         stressed_gap_pct: Any = est.GAP_STRESS_PCT, lot_size: int = 1, model: Optional[Dict[str, Any]] = None,
         equity_basis: str = EQUITY_BASIS) -> Dict[str, Any]:
    """The size (module docstring). Pure. A cap whose input is None is skipped and said so in its step, except
    liquidity (ADV None → 0: an unknown ADV is never read as liquid)."""
    model = model or desk.COST_MODEL
    inputs = {"equity_rs": equity_rs, "equity_basis": equity_basis, "risk_pct": risk_pct, "entry": entry, "stop": stop,
              "cost_per_share": cost_per_share, "cost_model": (model or {}).get("version"), "adv_rs": adv_rs,
              "min_adv_rs": min_adv_rs, "max_adv_participation_pct": max_adv_participation_pct,
              "max_position_pct": max_position_pct, "available_rs": available_rs, "reserve_rs": reserve_rs,
              "profile_per_trade_pct": profile_per_trade_pct, "stressed_gap_pct": stressed_gap_pct,
              "gap_stress_pct_risk_service": est.GAP_STRESS_PCT, "lot_size": lot_size}
    out: Dict[str, Any] = {"inputs": inputs, "steps": [], "quantity": 0, "capital_required": 0.0, "planned_risk": 0.0,
                           "stressed_risk": 0.0, "cost_per_share": None, "allowed_risk": None, "blocked": [],
                           "version": C.SIZING_VERSION, "inputs_hash": inputs_hash(inputs)}
    eq, pct, e, s = _f(equity_rs), _f(risk_pct), _f(entry), _f(stop)
    if eq is None or eq <= 0:
        out["blocked"].append({"code": "equity_unknown", "message": "Paper equity is unknown, so nothing can be sized."})
    if pct is None or pct <= 0:
        out["blocked"].append({"code": "risk_pct_invalid", "message": "The risk percentage must be a positive number."})
    if e is None or s is None or e <= 0 or s <= 0:
        out["blocked"].append({"code": "levels_invalid", "message": "Entry and stop must be positive prices."})
    elif s >= e:
        out["blocked"].append({"code": "stop_not_below_entry", "message": "The stop must be below the entry for a long."})
    lot = int(lot_size) if isinstance(lot_size, int) and lot_size >= 1 else 1
    cps_given = _f(cost_per_share)
    if cost_per_share is not None and (cps_given is None or cps_given < 0):
        out["blocked"].append({"code": "cost_invalid", "message": "The cost per share must be 0 or more."})
    if out["blocked"]:
        return out

    allowed = eq * pct / 100.0
    out["allowed_risk"] = round(allowed, 2)
    dist = e - s
    steps: List[Dict[str, Any]] = out["steps"]

    def step(cap: str, before: int, after: int, reason: str, limit: Any = None) -> int:
        after = max(0, min(before, after))
        steps.append({"cap": cap, "before": before, "after": after, "limit": limit, "binding": after < before,
                      "reason": reason})
        return after

    if cps_given is not None:
        q = int(math.floor(allowed / (dist + cps_given) + 1e-9))
        steps.append({"cap": "risk_budget", "before": None, "after": q, "limit": round(allowed, 2), "binding": True,
                      "reason": f"floor(₹{allowed:,.2f} / (₹{dist:,.2f} stop distance + ₹{cps_given:,.2f} cost per share))"})
    else:
        q = desk.max_units_within_budget(allowed, e, s, lot_units=1, model=model)
        steps.append({"cap": "risk_budget", "before": None, "after": q, "limit": round(allowed, 2), "binding": True,
                      "reason": f"the most shares whose loss at the stop plus the {model.get('version')} round-trip costs "
                                f"stays within ₹{allowed:,.2f}"})

    ppt = _f(profile_per_trade_pct)
    if ppt is not None and ppt > 0:
        budget = eq * ppt / 100.0
        fit = est.max_cash_qty(budget, e, s, max(q, 1), model) if q > 0 else 0
        q = step("risk_profile_per_trade", q, fit,
                 f"the risk profile's per-trade limit {ppt:g}% (₹{budget:,.2f}) on its own measure: stop loss + costs + a "
                 f"{est.GAP_STRESS_PCT:g}% gap stress ({est.ESTIMATE_VERSION}), as the risk service checks it", round(budget, 2))
    else:
        steps.append({"cap": "risk_profile_per_trade", "before": q, "after": q, "limit": None, "binding": False,
                      "reason": "not applied: no risk-profile limit given (a pure calculation)"})

    adv, floor_rs, part = _f(adv_rs), _f(min_adv_rs), _f(max_adv_participation_pct)
    if adv is None and floor_rs is None and part is None:
        steps.append({"cap": "liquidity", "before": q, "after": q, "limit": None, "binding": False,
                      "reason": "not applied: no liquidity inputs given (a pure calculation)"})
    elif adv is None:
        q = step("liquidity", q, 0, "the average daily traded value is unknown, so the liquidity limit cannot be checked "
                                    "(liquidity_unknown)")
        out["blocked"].append({"code": "liquidity_unknown", "message": "The average daily traded value is unknown."})
    elif floor_rs is not None and adv < floor_rs:
        q = step("liquidity", q, 0, f"average daily traded value ₹{adv:,.0f} is below the floor ₹{floor_rs:,.0f} "
                                    f"(liquidity_below_floor)", floor_rs)
        out["blocked"].append({"code": "liquidity_below_floor",
                               "message": f"Average daily traded value ₹{adv:,.0f} is below the ₹{floor_rs:,.0f} floor."})
    elif part is not None:
        cap = int(math.floor(adv * part / 100.0 / e + 1e-9))
        q = step("liquidity", q, cap, f"at most {part:g}% of the 20-session average daily traded value ₹{adv:,.0f}", part)
    else:
        steps.append({"cap": "liquidity", "before": q, "after": q, "limit": None, "binding": False,
                      "reason": "no participation limit given"})

    mpp = _f(max_position_pct)
    if mpp is not None:
        cap_rs = eq * mpp / 100.0
        q = step("position_exposure", q, int(math.floor(cap_rs / e + 1e-9)),
                 f"position value within the profile's {mpp:g}% of equity (₹{cap_rs:,.2f})", round(cap_rs, 2))
    else:
        steps.append({"cap": "position_exposure", "before": q, "after": q, "limit": None, "binding": False,
                      "reason": "no position limit given"})

    avail, reserve = _f(available_rs), _f(reserve_rs) or 0.0
    if avail is not None:
        room = max(0.0, avail - reserve)
        q = step("available_capital", q, int(math.floor(room / e + 1e-9)),
                 f"available capital ₹{avail:,.2f} less the reserve bucket ₹{reserve:,.2f} = ₹{room:,.2f}", round(room, 2))
    else:
        steps.append({"cap": "available_capital", "before": q, "after": q, "limit": None, "binding": False,
                      "reason": "no available capital given (a pure calculation)"})

    q = step("lot_size", q, (q // lot) * lot, f"whole lots of {lot}", lot)

    out["quantity"] = q
    if q > 0:
        costs = round(cps_given * q, 2) if cps_given is not None else desk.round_trip_cost(q, e, s, model)
        planned = round(q * dist + costs, 2)
        out["cost_per_share"] = round(costs / q, 4)
        out["planned_risk"] = planned
        out["stressed_risk"] = round(planned + q * s * float(_f(stressed_gap_pct) or 0.0) / 100.0, 2)
        out["capital_required"] = round(q * e, 2)
        out["costs_rs"] = costs
    elif not out["blocked"]:
        binding = next((st for st in reversed(steps) if st["binding"]), None)
        out["blocked"].append({"code": f"{binding['cap']}_leaves_zero" if binding else "zero_quantity",
                               "message": "No whole share fits: " + (binding["reason"] if binding else "zero quantity")})
    return out


def stressed_per_share(entry: float, stop: float, cost_per_share: float, gap_pct: float) -> float:
    """Stressed risk of one share: the stop distance, its costs and a gap of `gap_pct` % of the stop through it."""
    return (float(entry) - float(stop)) + float(cost_per_share or 0.0) + float(stop) * float(gap_pct) / 100.0
