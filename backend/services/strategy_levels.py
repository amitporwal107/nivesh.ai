"""Entry, stop-loss and target levels for an options structure, worked out from the payoff engine's own numbers (services.strategy_plan.compute_payoff).

RULE-BASED and HYPOTHETICAL: fixed research settings (version `strategy-levels-v1`, listed below), not predictions and not advice; no accuracy or hit rate is claimed. A stop is a theoretical level: a real stop
order can fill worse in a gap. The strategy's value at an underlying price is the engine's model estimate for the data date (T+0), not a quote. See test_reports/strategy_levels_TESTCASES.md."""
from __future__ import annotations

import math
from datetime import date
from functools import reduce
from typing import Any, Dict, List, Optional

from services.strategy_plan import compute_payoff

VERSION = "strategy-levels-v1"
S = {"debit_stop_keep": 0.70, "debit_t1": 0.30, "debit_t2": 0.60, "credit_stop_share_of_max_loss": 0.5, "credit_t1_keep": 0.50, "credit_t2_keep": 0.80,
     "delta_flat": 0.05, "delta_keep": 0.30, "neutral_delta_limit": 0.20, "expiry_week_days": 3}
# The scenario matrix: every leg repriced by the engine (Black-76) for a price move, an IV change and elapsed time. No probabilities are attached: we have none, so no "expected" P&L is computed.
SCENARIOS = [("Bullish", 2.0, -3.0, 1), ("Sideways", 0.0, -5.0, 1), ("Bearish", -2.0, 4.0, 1), ("Expiry day, small rise", 1.0, 0.0, None)]
CAVEATS = [
    "Rule-based, hypothetical levels from fixed research settings. They are not predictions or advice, and no accuracy or hit rate is claimed: tests of these signals found no skill beyond chance.",
    "A stop is a theoretical level, not an executable price: a stop order can fill worse in a sharp move or a liquidity gap.",
    "No entry range is given: bid and ask are not in end-of-day data. Values at a price are the engine's model estimate for the data date, not quotes.",
]


def _n(v: Any) -> Optional[float]:
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) else None


def _r(v: Optional[float], d: int = 2) -> Optional[float]:
    return None if v is None else round(v, d)


def _value_at(req: Dict[str, Any], price: float, today: date, base_gross_at_ref_unit: float, unit: float, credit: bool, entry: float) -> Optional[float]:
    """The structure's per-unit value (debit: what it would sell for; credit: what it would cost to buy back) at an underlying price on the data date, from a one-point engine run."""
    probe = {k: v for k, v in req.items() if k not in ("grid", "scenarios")}
    probe["grid"] = {"min": price, "max": price + 1e-6, "points": 5}
    out = compute_payoff(probe, today)
    pe = out.get("pre_expiry") or {}
    gross = pe.get("gross") or []
    if not out.get("valid") or not gross or _n(gross[0]) is None:
        return None
    pnl_unit = gross[0] / unit
    return entry + pnl_unit if not credit else entry - pnl_unit


def compute(body: Dict[str, Any], refs: Optional[Dict[str, Any]] = None, today: Optional[date] = None) -> Dict[str, Any]:
    today = today or date.today()
    refs = refs or {}
    req = {k: v for k, v in body.items() if k not in ("pre_expiry",)}
    legs = [l for l in (req.get("legs") or []) if isinstance(l, dict)]
    base = {"version": VERSION, "settings": S, "caveats": CAVEATS, "sent_to_broker": False}
    if not legs or not req.get("as_of"):
        return {**base, "valid": False, "problems": [{"code": "bad_request", "message": "legs and as_of are required"}]}
    req["pre_expiry"] = {"date": req["as_of"]}
    ref = _n(req.get("reference_price"))
    grid = req.get("grid") or ({"from_pct": -15, "to_pct": 15, "points": 61} if ref else None)
    req["grid"] = grid
    out = compute_payoff(req, today)
    if not out.get("valid"):
        return {**base, "valid": False, "problems": out.get("problems") or []}
    ex, pe = out["expiry"], out.get("pre_expiry") or {}
    lots = [int(l["quantity"]) for l in legs if isinstance(l.get("quantity"), (int, float)) and l["quantity"] > 0]
    lot_sizes = {int(l.get("lot_size") or 1) for l in legs}
    g = reduce(math.gcd, lots) if lots else 1
    unit = (lot_sizes.pop() if len(lot_sizes) == 1 else 1) * g
    net = _n(ex.get("net_premium")) or 0.0
    credit = net > 0
    entry = abs(net) / unit
    mp = _n(ex.get("max_profit")); ml = _n(ex.get("max_loss"))
    mp_u = None if ex.get("profit_unbounded") or mp is None else mp / unit
    ml_u = None if ex.get("loss_unbounded") or ml is None else -ml / unit
    greeks = (pe.get("greeks") or {}) if pe else {}
    d_total = _n(greeks.get("delta"))
    d0 = None if d_total is None else d_total / unit
    # premium levels (per unit)
    if not credit:
        stop = entry * S["debit_stop_keep"]
        t1, t2 = entry * (1 + S["debit_t1"]), entry * (1 + S["debit_t2"])
        cap = None if mp_u is None else entry + mp_u
        if cap is not None:
            t1, t2 = min(t1, cap), min(t2, cap)
        boundary = {"value": 0.0 if ml_u is None or ml_u >= entry else entry - ml_u, "meaning": "the structure's value at its worst: the whole debit is lost"}
        prem = {"kind": "debit", "entry": entry, "planned_stop": stop, "risk_boundary": boundary, "target_1": t1, "target_2": t2,
                "planned_stop_loss_per_unit": entry - stop, "max_loss_per_unit": ml_u}
    else:
        if ml_u is None:
            return {**base, "valid": False, "problems": [{"code": "undefined_risk", "message": "A credit structure with no maximum loss is not supported: only defined-risk structures get levels."}]}
        stop = entry + min(entry, S["credit_stop_share_of_max_loss"] * ml_u)
        boundary = {"value": entry + ml_u, "meaning": "buyback cost at the maximum loss"}
        prem = {"kind": "credit", "entry": entry, "planned_stop": stop, "risk_boundary": boundary, "target_1": entry * (1 - S["credit_t1_keep"]), "target_2": entry * (1 - S["credit_t2_keep"]),
                "planned_stop_loss_per_unit": stop - entry, "max_loss_per_unit": ml_u}
    # underlying levels
    spot = ref
    em = _n(refs.get("expected_move")); pw = _n(refs.get("put_wall")); cw = _n(refs.get("call_wall"))
    view = "neutral" if d0 is None or abs(d0) <= S["delta_flat"] else ("bullish" if d0 > 0 else "bearish")
    def below() -> Optional[float]:
        return pw if (pw is not None and spot is not None and pw < spot) else (spot - em if spot is not None and em is not None else None)
    def above() -> Optional[float]:
        return cw if (cw is not None and spot is not None and cw > spot) else (spot + em if spot is not None and em is not None else None)
    lo, hi = below(), above()
    und: Dict[str, Any] = {"view": view, "entry": spot}
    if view == "bullish":
        und.update(stop=lo, target=hi)
    elif view == "bearish":
        und.update(stop=hi, target=lo)
    else:
        und.update(range_low=lo, range_high=hi)
    def val(p: Optional[float]) -> Optional[float]:
        return None if p is None else _r(_value_at(req, p, today, 0.0, unit, credit, entry))
    und["value_at_stop"] = val(und.get("stop")) if "stop" in und else None
    und["value_at_target"] = val(und.get("target")) if "target" in und else None
    if view == "neutral":
        und["value_at_range_low"], und["value_at_range_high"] = val(lo), val(hi)
    # Greek rule
    greek: Dict[str, Any] = {"net_delta_per_share": _r(d0, 3), "gamma": _r(_n(greeks.get("gamma")) and greeks["gamma"] / unit, 4) if greeks else None,
                             "theta_per_day_per_share": _r(_n(greeks.get("theta")) and greeks["theta"] / unit, 3) if greeks else None, "vega_per_point_per_share": _r(_n(greeks.get("vega")) and greeks["vega"] / unit, 3) if greeks else None}
    if d0 is not None and view in ("bullish", "bearish"):
        greek["review_when"] = f"net delta falls below {_r(S['delta_keep'] * d0, 3)} (30% of the entry delta {_r(d0, 3)})" if view == "bullish" else f"net delta rises above {_r(S['delta_keep'] * d0, 3)} (30% of the entry delta {_r(d0, 3)})"
    elif d0 is not None:
        greek["review_when"] = f"|net delta| exceeds {S['neutral_delta_limit']} (entry {_r(d0, 3)})"
    else:
        greek["review_when"] = None
    expiry = next((l.get("expiry") for l in legs if l.get("expiry")), None)
    scen: List[Dict[str, Any]] = []
    if spot is not None and expiry:
        d0 = date.fromisoformat(req["as_of"])
        for name, move, ivs, days_on in SCENARIOS:
            when = date.fromisoformat(expiry) if days_on is None else min(date.fromordinal(d0.toordinal() + days_on), date.fromisoformat(expiry))
            price = spot * (1 + move / 100.0)
            probe = {k: v for k, v in req.items() if k not in ("grid", "scenarios")}
            probe["grid"] = {"min": price, "max": price + 1e-6, "points": 5}
            probe["pre_expiry"] = {"date": when.isoformat(), "iv_shift_pct": ivs}
            o = compute_payoff(probe, today)
            gross = ((o.get("pre_expiry") or {}).get("gross") or [None])[0] if o.get("valid") else None
            scen.append({"name": name, "underlying_move_pct": move, "underlying": _r(price), "iv_change_points": ivs, "date": when.isoformat(),
                         "pnl_per_unit": None if _n(gross) is None else _r(gross / unit), "pnl_total": None if _n(gross) is None else _r(gross)})

    days = (date.fromisoformat(expiry) - date.fromisoformat(req["as_of"])).days if expiry else None
    flags = []
    if days is not None and days <= S["expiry_week_days"]:
        flags.append({"code": "expiry_week", "message": f"{days} days to expiry: gamma can change quickly, so the levels can be overtaken fast."})
    rr = None if mp_u is None or not ml_u else mp_u / ml_u
    rnd = lambda d: {k: (_r(v, 2) if isinstance(v, float) else v) for k, v in d.items()}
    prem = {**{k: (_r(v) if isinstance(v, float) else v) for k, v in prem.items() if k != "risk_boundary"}, "risk_boundary": rnd(prem["risk_boundary"])}
    return {**base, "valid": True, "unit": {"shares": unit, "note": "figures per share (per unit of the position's lot multiple)"}, "premium": prem, "underlying": {k: (_r(v) if isinstance(v, float) else v) for k, v in und.items()},
            "greeks": greek, "scenarios": scen, "iv_rank": None, "iv_percentile": None, "iv_note": "IV rank and percentile need an IV history we do not store; they are not shown.", "max_profit_per_unit": _r(mp_u), "max_loss_per_unit": _r(ml_u), "risk_reward": _r(rr), "max_profit_total": _r(mp), "max_loss_total": _r(ml),
            "capital_at_risk": _n(out.get("capital_at_risk")), "days_to_expiry": days, "flags": flags, "expiry": expiry}
