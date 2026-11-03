"""Pre-expiry estimate: each option leg is repriced with Black-76 (services/option_pricing.py) at the evaluation date.
Never derived from the expiry payoff. Pure, no I/O.

Model, stated once:
  · Underlying price S on the grid; forward F = S × e^(r·T) ("carried spot": no dividends, no put-call-parity forward,
    because the request carries no chain). T = calendar days from the evaluation date to the expiry ÷ 365.
  · Volatility per option leg: `iv_pct` from the request, else solved (implied_vol) from the entry premium at as_of
    with F = reference_price × e^(r·T0); if that has no solution the leg is `unavailable`. No default volatility is
    ever substituted. `iv_shift_pct` is added to every leg's volatility (in volatility points).
  · Cash and future legs are linear in S and unchanged (delta only). The future's own carry/basis is not modelled.
  · Greeks are for the whole position at the reference price (units = sign × lots × lot_size):
      delta  position change per ₹1 of underlying (shares-equivalent);  gamma  change in that delta per ₹1
      theta  P&L change over one calendar day (repricing at T − 1 day, spot and volatility unchanged), INR/day
      vega   P&L change per volatility point, INR;   rho  P&L change per 1 percentage point of the rate, INR,
      with the carried-spot forward moving with the rate: ∂P/∂r = T·(Δ_F·F − P).
    They are None when the leg is at or past expiry (T ≤ 0): no time left, the formulas are undefined.
  · Exit costs: the position is closed at the modelled value on the evaluation date, same cost model as the expiry view
    (the desk cost card, payoff-v2: each leg's exit side priced by its segment on that value).
  · Scenarios (only when the request has both `pre_expiry` and `scenarios`): `scenarios` = [{name, underlying_price, gross,
    net, greeks}], each priced exactly as a grid point (same legs, volatilities, rate, date and costs) at that scenario's
    underlying price, and its greeks the whole position's at that price, worked out as `greeks` is at the reference price
    (per leg rounded to 4 places, then summed): at the reference price they equal `greeks`. gross / net / greeks are None
    when a leg cannot be priced (the reason is in `unavailable`); greeks alone are None when a leg is at or past expiry.
"""
from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Sequence

from services import option_pricing as op

from .payoff import entry_cost, exit_cost_for_value, leg_gross, r2

_KIND = {"call": "CE", "put": "PE"}
MODEL = "Black-76"


def _t(day_from, day_to) -> float:
    return op.year_fraction(op.days_between(day_from, day_to))


def _leg_vol(leg: Dict[str, Any], ref: float, as_of, rate: float, shift: float):
    """(volatility as a fraction incl. shift, source text, None) or (None, None, reason)."""
    if leg["iv_pct"] is not None:
        vol, src = leg["iv_pct"] / 100.0, "request iv_pct"
    else:
        t0 = _t(as_of, leg["expiry"])
        if t0 <= 0:
            return None, None, "No time to expiry at as_of: implied volatility cannot be solved from the premium; give iv_pct."
        f0 = ref * math.exp(rate * t0)
        iv = op.implied_vol(_KIND[leg["option_type"]], leg["entry_price"], f0, leg["strike"], t0, rate)
        if iv is None:
            return None, None, ("The entry premium has no valid Black-76 implied volatility "
                                "(below intrinsic value, above the maximum, or outside the search range); give iv_pct.")
        vol, src = iv, f"solved from the entry premium at {as_of.isoformat()} (carried-spot forward)"
    vol += shift / 100.0
    if vol <= 0:
        return None, None, "iv_shift_pct makes the volatility zero or negative."
    return vol, src, None


def _px(leg: Dict[str, Any], s: float, t: float, vol: float, rate: float) -> float:
    return op.price(_KIND[leg["option_type"]], s * math.exp(rate * max(t, 0.0)), leg["strike"], t, vol, rate)


def _leg_greeks(leg, ref, t, vol, rate):
    sgn_units = leg["sign"] * leg["units"]
    if leg["kind"] != "option":
        return {"delta": float(sgn_units), "gamma": 0.0, "theta": 0.0, "vega": 0.0, "rho": 0.0}
    if t <= 0:
        return None
    k = _KIND[leg["option_type"]]
    growth = math.exp(rate * t)
    f = ref * growth
    g = op.greeks(k, f, leg["strike"], t, vol, rate)
    if g is None:
        return None
    p = op.price(k, f, leg["strike"], t, vol, rate)
    one_day = op.year_fraction(1)
    p_next = _px(leg, ref, max(t - one_day, 0.0), vol, rate)
    rho = t * (g.delta * f - p) / 100.0
    return {"delta": g.delta * growth * sgn_units, "gamma": g.gamma * growth * growth * sgn_units,
            "theta": (p_next - p) * sgn_units, "vega": g.vega * sgn_units, "rho": rho * sgn_units}


def _position_greeks(legs: Sequence[Dict[str, Any]], prepared: Dict[int, Dict[str, Any]], s: float, rate: float):
    """(per-leg greeks rounded to 4 places, in leg order, each None when that leg has none) at underlying price `s`."""
    out = []
    for l in legs:
        if l["kind"] == "option" and l["index"] not in prepared:
            out.append(None)
            continue
        p = prepared.get(l["index"], {})
        g = _leg_greeks(l, s, p.get("t", 0.0), p.get("vol"), rate)
        out.append(None if g is None else {k: round(v + 0.0, 4) for k, v in g.items()})
    return out


_GREEK_KEYS = ("delta", "gamma", "theta", "vega", "rho")


def _sum_greeks(per_leg: Sequence[Optional[Dict[str, float]]]) -> Optional[Dict[str, float]]:
    """The whole position's greeks: the sum of the legs' (rounded) greeks, or None when any leg has none."""
    if not all(g is not None for g in per_leg):
        return None
    return {k: round(sum(g[k] for g in per_leg) + 0.0, 4) for k in _GREEK_KEYS}


def _value_at(legs: Sequence[Dict[str, Any]], prepared: Dict[int, Dict[str, Any]], s: float, rate: float,
              model: Dict[str, Any]):
    """(gross, net) of the whole position at underlying price `s` on the evaluation date, unrounded."""
    gsum = csum = 0.0
    for l in legs:
        if l["kind"] == "option":
            p = prepared[l["index"]]
            px = _px(l, s, p["t"], p["vol"], rate)
            gsum += l["sign"] * (px - l["entry_price"]) * l["units"]
            exit_c = exit_cost_for_value(l, px, model)
        else:
            gsum += leg_gross(l, s)
            exit_c = exit_cost_for_value(l, s, model)
        csum += entry_cost(l, model) + exit_c
    return gsum, gsum - csum


def pre_expiry(legs: Sequence[Dict[str, Any]], ref: float, grid: Sequence[float], as_of, spec: Dict[str, Any],
               model: Dict[str, Any], default_rate: float,
               scenarios: Optional[Sequence[Dict[str, Any]]] = None) -> Dict[str, Any]:
    day = spec["date"]
    rate = default_rate if spec.get("rate_pct") is None else spec["rate_pct"] / 100.0
    shift = spec["iv_shift_pct"]
    unavailable: List[Dict[str, Any]] = []
    prepared: Dict[int, Dict[str, Any]] = {}
    legs_assump = []
    for l in legs:
        if l["kind"] != "option":
            continue
        t = _t(day, l["expiry"])
        vol, src, why = _leg_vol(l, ref, as_of, rate, shift)
        if why:
            unavailable.append({"leg": l["index"], "reason": why})
            legs_assump.append({"leg": l["index"], "time_to_expiry_days": op.days_between(day, l["expiry"]),
                                "iv_pct": None, "iv_source": None})
            continue
        prepared[l["index"]] = {"t": t, "vol": vol}
        legs_assump.append({"leg": l["index"], "time_to_expiry_days": op.days_between(day, l["expiry"]),
                            "iv_pct": round(vol * 100, 4), "iv_source": src})
    assumptions = {"model": MODEL, "rate_pct": round(rate * 100, 4),
                   "rate_source": "request rate_pct" if spec.get("rate_pct") is not None
                   else "services/option_pricing.RISK_FREE_RATE",
                   "time": "calendar days from the evaluation date to expiry / 365",
                   "forward_basis": "carried spot: S x exp(r T); no dividends, no put-call-parity forward",
                   "iv_shift_pct": shift, "as_of": as_of.isoformat(), "legs": legs_assump,
                   "greeks_units": "whole position at reference_price: delta per Rs 1, theta per day, vega per vol point, "
                                   "rho per 1 pp of rate, all in INR except delta/gamma in shares-equivalent"}
    out: Dict[str, Any] = {"date": day.isoformat(), "model": MODEL, "assumptions": assumptions, "grid": None,
                           "gross": None, "net": None, "greeks": None, "per_leg_greeks": [], "unavailable": unavailable}
    # Greeks per leg (available legs only)
    for l, g in zip(legs, _position_greeks(legs, prepared, ref, rate)):
        out["per_leg_greeks"].append({"leg": l["index"], "label": l["label"], "greeks": g})
    if scenarios:
        # Every figure null when a leg cannot be priced: the reason is already in `unavailable`.
        out["scenarios"] = [{"name": sc["name"], "underlying_price": r2(sc["underlying_price"]), "gross": None, "net": None,
                             "greeks": None} for sc in scenarios]
    if unavailable:
        return out
    out["greeks"] = _sum_greeks([e["greeks"] for e in out["per_leg_greeks"]])
    if out["greeks"] is None:
        assumptions["greeks_unavailable"] = "an option leg is at or past expiry on the evaluation date: no time value left"
    gross_arr, net_arr = [], []
    for s in grid:
        g_, n_ = _value_at(legs, prepared, s, rate, model)
        gross_arr.append(r2(g_))
        net_arr.append(r2(n_))
    out.update({"grid": [r2(s) for s in grid], "gross": gross_arr, "net": net_arr})
    for row, sc in zip(out.get("scenarios") or [], scenarios or []):
        g_, n_ = _value_at(legs, prepared, sc["underlying_price"], rate, model)
        row.update(gross=r2(g_), net=r2(n_), greeks=_sum_greeks(_position_greeks(legs, prepared, sc["underlying_price"], rate)))
    return out
