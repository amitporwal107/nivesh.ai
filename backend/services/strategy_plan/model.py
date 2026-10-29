"""Leg model and request validation for the strategy payoff calculator (PRD §16.6, §16.11 StrategyLeg).

Pure: no database, no network, no broker. `parse_request` turns the raw JSON body into normalised legs, a grid and
options, plus `problems` (field, code, message). It never raises on bad input: a bad request is a list of problems.

Units: cash `quantity` is shares; future and option `quantity` is LOTS and the position is quantity × lot_size units.
Side: buy = +1, sell = -1.
"""
from __future__ import annotations

import math
from datetime import date
from typing import Any, Dict, List, Optional, Tuple

MAX_LEGS = 8    # an ANALYSIS limit (what the payoff engine prices), not the strategy limit: services/strategy_limits
MIN_POINTS, MAX_POINTS = 5, 400
DEFAULT_GRID = {"from_pct": -20.0, "to_pct": 20.0, "points": 121}
MAX_IV_PCT = 500.0

KINDS = ("cash", "future", "option")
SIDES = ("buy", "sell")
OPTION_TYPES = ("call", "put")


def problem(field: str, code: str, message: str) -> Dict[str, str]:
    return {"field": field, "code": code, "message": message}


def num(x: Any) -> Optional[float]:
    """A finite number, or None. Booleans and strings are not numbers."""
    if isinstance(x, bool) or not isinstance(x, (int, float)):
        return None
    return float(x) if math.isfinite(x) else None


def whole(x: Any) -> Optional[int]:
    v = num(x)
    return int(v) if v is not None and v == int(v) else None


def parse_day(x: Any) -> Optional[date]:
    if not isinstance(x, str):
        return None
    try:
        return date.fromisoformat(x)
    except ValueError:
        return None


def _fmt(v: float) -> str:
    return f"{v:g}"


def leg_label(leg: Dict[str, Any]) -> str:
    verb = "Buy" if leg["sign"] > 0 else "Sell"
    if leg["kind"] == "cash":
        return f"{verb} {leg['quantity']} shares"
    lots = f"{leg['quantity']} lot" + ("" if leg["quantity"] == 1 else "s")
    if leg["kind"] == "future":
        return f"{verb} {lots} future"
    return f"{verb} {lots} {leg['option_type']} {_fmt(leg['strike'])}"


def _parse_leg(i: int, raw: Any, probs: List[Dict[str, str]]) -> Optional[Dict[str, Any]]:
    f = f"legs[{i}]"
    if not isinstance(raw, dict):
        probs.append(problem(f, "leg_not_object", "A leg must be an object."))
        return None
    n0 = len(probs)
    kind, side = raw.get("kind"), raw.get("side")
    if kind not in KINDS:
        probs.append(problem(f"{f}.kind", "bad_kind", "kind must be cash, future or option."))
    if side not in SIDES:
        probs.append(problem(f"{f}.side", "bad_side", "side must be buy or sell."))
    qty = whole(raw.get("quantity"))
    if qty is None or qty < 1:
        probs.append(problem(f"{f}.quantity", "bad_quantity",
                             "quantity must be a whole number of at least 1 (shares for cash, lots otherwise)."))
    lot = whole(raw.get("lot_size", 1 if kind == "cash" else None))
    if lot is None or lot < 1:
        probs.append(problem(f"{f}.lot_size", "bad_lot_size", "lot_size must be a whole number of at least 1."))
    elif kind == "cash" and lot != 1:
        probs.append(problem(f"{f}.lot_size", "cash_lot_size", "A cash leg has lot_size 1 (quantity is shares)."))
    entry = num(raw.get("entry_price"))
    if entry is None or entry <= 0:
        probs.append(problem(f"{f}.entry_price", "bad_price", "entry_price must be a positive number."))
    expiry = None
    if kind in ("future", "option"):
        expiry = parse_day(raw.get("expiry"))
        if expiry is None:
            probs.append(problem(f"{f}.expiry", "bad_expiry", "A future or option needs an expiry date (YYYY-MM-DD)."))
    strike, opt = None, None
    if kind == "option":
        strike = num(raw.get("strike"))
        if strike is None or strike <= 0:
            probs.append(problem(f"{f}.strike", "bad_strike", "An option needs a positive strike."))
        opt = raw.get("option_type")
        if opt not in OPTION_TYPES:
            probs.append(problem(f"{f}.option_type", "bad_option_type", "option_type must be call or put."))
    iv = None
    if raw.get("iv_pct") is not None:
        iv = num(raw.get("iv_pct"))
        if iv is None or not 0 < iv <= MAX_IV_PCT:
            probs.append(problem(f"{f}.iv_pct", "bad_iv", f"iv_pct must be a number above 0 and at most {MAX_IV_PCT:g}."))
            iv = None
    if len(probs) > n0:
        return None
    units = qty * (1 if kind == "cash" else lot)
    leg = {"index": i, "kind": kind, "side": side, "sign": 1 if side == "buy" else -1, "quantity": qty,
           "lot_size": lot, "units": units, "entry_price": entry, "expiry": expiry, "strike": strike,
           "option_type": opt, "iv_pct": iv, "price_source": raw.get("price_source")}
    leg["label"] = leg_label(leg)
    return leg


def _parse_grid(raw: Any, ref: Optional[float], probs: List[Dict[str, str]], warns: List[Dict[str, str]]
                ) -> Optional[Tuple[float, float, int]]:
    if raw is None:
        raw = dict(DEFAULT_GRID)
        warns.append({"code": "grid_defaulted",
                      "message": "No grid given: using -20% to +20% of the reference price, 121 points."})
    if not isinstance(raw, dict):
        probs.append(problem("grid", "bad_grid", "grid must be an object."))
        return None
    pts = whole(raw.get("points"))
    if pts is None or not MIN_POINTS <= pts <= MAX_POINTS:
        probs.append(problem("grid.points", "bad_grid_points", f"points must be a whole number from {MIN_POINTS} to {MAX_POINTS}."))
        return None
    lo, hi = num(raw.get("min")), num(raw.get("max"))
    if lo is None and hi is None and raw.get("from_pct") is not None:
        a, b = num(raw.get("from_pct")), num(raw.get("to_pct"))
        if a is None or b is None or ref is None:
            probs.append(problem("grid", "bad_grid", "from_pct and to_pct must be numbers and need a valid reference_price."))
            return None
        lo, hi = ref * (1 + a / 100), ref * (1 + b / 100)
    if lo is None or hi is None:
        probs.append(problem("grid", "bad_grid", "grid needs min and max, or from_pct and to_pct."))
        return None
    if lo <= 0 or hi <= 0:
        probs.append(problem("grid", "grid_not_positive", "Grid prices must be positive."))
        return None
    if lo >= hi:
        probs.append(problem("grid", "grid_order", "Grid min must be below max."))
        return None
    return lo, hi, pts


def parse_request(body: Any, today: date) -> Dict[str, Any]:
    """Normalise and validate. Returns {problems, warnings, legs, grid, costs, scenarios, pre_expiry, as_of,
    reference_price, underlying}. Legs/grid are None when invalid."""
    probs: List[Dict[str, str]] = []
    warns: List[Dict[str, str]] = []
    out: Dict[str, Any] = {"problems": probs, "warnings": warns, "legs": None, "grid": None, "costs": None,
                           "scenarios": [], "pre_expiry": None, "as_of": today, "reference_price": None,
                           "underlying": None}
    if not isinstance(body, dict):
        probs.append(problem("body", "bad_body", "The request must be a JSON object."))
        return out
    und = body.get("underlying")
    if not isinstance(und, str) or not und.strip():
        probs.append(problem("underlying", "bad_underlying", "underlying is required."))
    out["underlying"] = und.strip().upper() if isinstance(und, str) else None
    ref = num(body.get("reference_price"))
    if ref is None or ref <= 0:
        probs.append(problem("reference_price", "bad_price", "reference_price must be a positive number."))
        ref = None
    out["reference_price"] = ref
    if body.get("as_of") is not None:
        d = parse_day(body.get("as_of"))
        if d is None:
            probs.append(problem("as_of", "bad_date", "as_of must be YYYY-MM-DD."))
        else:
            out["as_of"] = d
    raw_legs = body.get("legs")
    legs: List[Dict[str, Any]] = []
    if not isinstance(raw_legs, list) or not raw_legs:
        probs.append(problem("legs", "no_legs", "At least one leg is required."))
    elif len(raw_legs) > MAX_LEGS:
        probs.append(problem("legs", "too_many_legs", f"At most {MAX_LEGS} legs."))
    else:
        for i, r in enumerate(raw_legs):
            leg = _parse_leg(i, r, probs)
            if leg:
                legs.append(leg)
            if isinstance(r, dict) and r.get("underlying") not in (None, "") and out["underlying"] \
                    and str(r.get("underlying")).strip().upper() != out["underlying"]:
                probs.append(problem(f"legs[{i}].underlying", "mixed_underlyings", "All legs must be on one underlying."))
    fno_expiries = {l["expiry"] for l in legs if l["expiry"]}
    if len(fno_expiries) > 1:
        probs.append(problem("legs", "mixed_expiries_not_supported",
                             "All futures and options legs must share one expiry; calendar structures are not supported."))
    for l in legs:
        if l["expiry"] and l["expiry"] < out["as_of"]:
            probs.append(problem(f"legs[{l['index']}].expiry", "expiry_in_past",
                                 f"Expiry {l['expiry']} is before the evaluation date {out['as_of']}."))
    grid = _parse_grid(body.get("grid"), ref, probs, warns)

    costs = body.get("costs")
    c_out = {"slippage_pct": None, "brokerage_per_side": None}
    if costs is not None and not isinstance(costs, dict):
        probs.append(problem("costs", "bad_costs", "costs must be an object."))
    else:
        for key, hi in (("slippage_pct", 5.0), ("brokerage_per_side", 100_000.0)):
            v = (costs or {}).get(key)
            if v is None:
                continue
            n = num(v)
            if n is None or n < 0 or n > hi:
                probs.append(problem(f"costs.{key}", "bad_cost", f"{key} must be a number from 0 to {hi:g}."))
            else:
                c_out[key] = n
    out["costs"] = c_out

    scen = body.get("scenarios")
    if scen is not None:
        if not isinstance(scen, list) or len(scen) > 20:
            probs.append(problem("scenarios", "bad_scenarios", "scenarios must be a list of at most 20."))
        else:
            for j, s in enumerate(scen):
                p = num(s.get("underlying_price")) if isinstance(s, dict) else None
                if p is None or p <= 0:
                    probs.append(problem(f"scenarios[{j}].underlying_price", "bad_price", "A scenario price must be positive."))
                else:
                    out["scenarios"].append({"name": str(s.get("name") or f"Scenario {j + 1}")[:60], "underlying_price": p})

    pre = body.get("pre_expiry")
    if pre is not None:
        if not isinstance(pre, dict):
            probs.append(problem("pre_expiry", "bad_pre_expiry", "pre_expiry must be an object."))
        else:
            d = parse_day(pre.get("date"))
            shift = num(pre.get("iv_shift_pct", 0)) if pre.get("iv_shift_pct") is not None else 0.0
            rate = num(pre.get("rate_pct")) if pre.get("rate_pct") is not None else None
            if d is None:
                probs.append(problem("pre_expiry.date", "bad_date", "pre_expiry.date must be YYYY-MM-DD."))
            elif d < out["as_of"]:
                probs.append(problem("pre_expiry.date", "pre_expiry_before_as_of", "The evaluation date is before as_of."))
            elif fno_expiries and d > min(fno_expiries):
                probs.append(problem("pre_expiry.date", "pre_expiry_after_expiry", "The evaluation date is after the expiry."))
            if shift is None or abs(shift) > 200:
                probs.append(problem("pre_expiry.iv_shift_pct", "bad_iv_shift", "iv_shift_pct must be a number from -200 to 200."))
            if pre.get("rate_pct") is not None and (rate is None or not 0 <= rate <= 50):
                probs.append(problem("pre_expiry.rate_pct", "bad_rate", "rate_pct must be from 0 to 50."))
            out["pre_expiry"] = {"date": d, "iv_shift_pct": shift or 0.0, "rate_pct": rate}

    out["grid"] = grid
    out["legs"] = legs if legs else None
    if not probs:
        _guard_risk(legs, probs)
    return out


def slopes(legs: List[Dict[str, Any]]) -> Tuple[float, float, float]:
    """(slope as the price goes to +infinity, slope below every strike, the puts' share of the latter).
    Slope = payoff change in INR per ₹1 of underlying move; exact because the payoff is piecewise linear."""
    up = down = put_down = 0.0
    for l in legs:
        u = l["sign"] * l["units"]
        if l["kind"] in ("cash", "future"):
            up += u
            down += u
        elif l["option_type"] == "call":
            up += u
        else:
            down -= u
            put_down -= u
    return up, down, put_down


def _guard_risk(legs: List[Dict[str, Any]], probs: List[Dict[str, str]]) -> None:
    """Undefined-risk guard (release scope: defined-risk options only).

    Rule, exact: the payoff is piecewise linear with kinks only at the strikes, so its behaviour at +infinity is
    its slope beyond the highest strike (calls +units for a bought call, -units for a sold call, puts 0, cash and
    futures ±units). A structure containing at least one option leg is rejected with `undefined_risk_not_supported` when
      (a) that upside slope is negative: a net short call (a short call not covered by a long call, a long future or
          held shares, or a call spread with more short than long units): loss grows without limit as price rises;
      (b) the puts alone have a net short position (short put units exceed long put units): a naked short put,
          whose loss runs to the strike when price falls.
    Plain cash and futures positions (no option leg) are linear and allowed long or short."""
    if not any(l["kind"] == "option" for l in legs):
        return
    up, _, put_down = slopes(legs)
    if up < 0:
        probs.append(problem("legs", "undefined_risk_not_supported",
                             "This structure has a net short call: its loss is unlimited. Only defined-risk option structures are supported."))
    elif put_down > 0:
        probs.append(problem("legs", "undefined_risk_not_supported",
                             "This structure has a short put without a covering long put. Only defined-risk option structures are supported."))
