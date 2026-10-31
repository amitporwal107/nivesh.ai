"""Quick Hedge core: pure functions, no I/O, no LLM. Owner decisions 2026-10-31 (docs/RISK_AND_HEDGE_GAP_AND_PLAN_20261031.md §4a):

    SIZE        beta-adjusted exposure E = hedgeable value x beta. Required lots = E / (spot x lot). Executed lots are
                ROUNDED DOWN to whole exchange lots, so the hedge never exceeds 100% of E. The protected and residual
                shares are always reported. Under one lot there is no idea ("smaller_than_one_lot"), never a forced lot.
    STRIKE      from the user's tolerable loss T (rupees the portfolio may lose before protection starts): the Nifty fall
                at which the portfolio has lost T is d = T / E, and the long put is the LOWEST listed strike at or above
                spot x (1 - d), so the deductible never exceeds T. A strike with no traded premium is not a candidate: a
                premium is never guessed. The user is never asked for a strike.
    MODES       maximum (deductible T/2), balanced (T), lowest_cost (T, as a put spread whose short put sits at the
                user's expected fall, so the protected band is the fall they said they fear).
    STRUCTURES  long put and put spread only. No short call, no futures (they need cover from outside the structure).
    SUITABILITY hedge confidence from R-squared against Nifty. Poor or unknown confidence shows the scenarios but blocks
                placing a paper hedge. THRESHOLDS ARE PLACEHOLDERS to calibrate on real portfolios.
    PAYOFF      at expiry, European and cash-settled: intrinsic value. The portfolio is assumed to move with Nifty by its
                beta (E x move); that is an estimate, not an outcome.

`charges(legs, underlying_at_expiry)` is an injected cost model: called with None for the entry, with the Nifty level for
the expiry settlement. It returns rupees. Without one, charges are 0 and `charges_included` is false.
"""
from __future__ import annotations

import math
from typing import Any, Callable, Dict, List, Optional, Sequence

POLICY_VERSION = "quick-hedge-v1"
MODES = ("maximum", "balanced", "lowest_cost")
DEFAULT_MOVES_PCT = (10, 5, 0, -5, -10, -15, -20)
R2_HIGH = 0.7        # placeholder: calibrate on staged portfolios
R2_MEDIUM = 0.4      # placeholder
EPS = 1e-9

DISCLOSURES = (
    "Estimated scenario, not guaranteed future performance.",
    "A hedge reduces the size of a possible loss but does not eliminate it; the premium is a cost whether or not it pays.",
    "The portfolio is assumed to move with Nifty by its beta. If it does not track Nifty closely, the hedge will protect less (or more) than shown.",
    "Option premiums are the last exchange closing prices, not live quotes. Figures are before income tax.",
    "Nifty options are European-style and cash-settled at expiry; the hedge protects only if Nifty is below the strike at expiry.",
)


def _num(x: Any) -> Optional[float]:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


def lots_for(exposure_rs: float, spot: float, lot: int) -> Dict[str, float]:
    """Required (fractional) and executed (whole, rounded down) lots, and the protected / residual share of the exposure."""
    notional = spot * lot
    required = exposure_rs / notional
    executed = int(math.floor(required + EPS))
    protected = executed * notional / exposure_rs * 100.0 if exposure_rs > 0 else 0.0
    return {"lot_notional_rs": notional, "required_lots": required, "executed_lots": executed,
            "protected_pct": protected, "residual_pct": 100.0 - protected}


def confidence(r2: Optional[float], corr: Optional[float] = None) -> Dict[str, Any]:
    r2 = _num(r2)
    if r2 is None:
        return {"level": "unknown", "r2": None, "correlation": _num(corr),
                "message": "The portfolio's fit to Nifty could not be measured, so the hedge cannot be placed."}
    level = "high" if r2 >= R2_HIGH else "medium" if r2 >= R2_MEDIUM else "poor"
    msg = {"high": "Nifty explains most of this portfolio's moves.",
           "medium": "Nifty explains part of this portfolio's moves; expect a looser hedge.",
           "poor": "Nifty may be a poor hedge for this portfolio."}[level]
    return {"level": level, "r2": r2, "correlation": _num(corr), "message": msg}


def _put_strikes(puts: Dict[float, float]) -> List[float]:
    return sorted(float(k) for k, p in puts.items() if _num(p) is not None and float(p) > 0)


def pick_put_strike(strikes: Sequence[float], spot: float, fall_fraction: float) -> Optional[float]:
    """The lowest listed strike in [spot x (1 - fall), spot]; None when there is none (never a wider deductible)."""
    target = spot * (1.0 - fall_fraction)
    inside = [k for k in strikes if target - EPS <= k <= spot + EPS]
    return min(inside) if inside else None


def pick_short_strike(strikes: Sequence[float], spot: float, expected_fall_pct: float, long_strike: float) -> Optional[float]:
    """The highest listed strike at or below spot x (1 - expected fall) and below the long strike; None when none."""
    target = spot * (1.0 - expected_fall_pct / 100.0)
    below = [k for k in strikes if k <= target + EPS and k < long_strike - EPS]
    return max(below) if below else None


def _payoff(legs: Sequence[Dict[str, Any]], s_t: float) -> float:
    return sum((1 if l["side"] == "buy" else -1) * l["qty"] * max(0.0, l["strike"] - s_t) for l in legs)


def _fmt_level(x: float) -> str:
    return f"{x:,.0f}"


def _moves(expected_fall_pct: float) -> List[int]:
    moves = list(DEFAULT_MOVES_PCT)
    ef = -int(round(abs(expected_fall_pct)))
    if ef not in moves:
        moves.append(ef)
    return sorted(set(moves), reverse=True)


def _mode(name: str, *, exposure: Dict[str, float], hedgeable_value: float, portfolio_value: float, beta_exposure: float,
          spot: float, lot: int, puts: Dict[float, float], strikes: List[float], tolerance_rs: float,
          expected_fall_pct: float, conf: Dict[str, Any], charges: Optional[Callable[[List[Dict[str, Any]], Optional[float]], float]]
          ) -> Dict[str, Any]:
    out: Dict[str, Any] = {"mode": name, "available": False, "place_allowed": False, "reason": None, "structure": None,
                           "legs": [], "scenario_rows": []}
    d = tolerance_rs / beta_exposure if beta_exposure > 0 else 0.0
    fall = d / 2.0 if name == "maximum" else d
    k_long = pick_put_strike(strikes, spot, fall)
    if k_long is None:
        out["reason"] = {"code": "no_strike_within_tolerance",
                         "message": "No listed index put with a traded price starts protection within your tolerable loss for this expiry."}
        return out
    lots = int(exposure["executed_lots"])
    qty = lots * lot
    legs = [{"side": "buy", "type": "put", "strike": k_long, "qty": qty, "premium": float(puts[k_long])}]
    structure = "long_put"
    if name == "lowest_cost":
        # The spread covers the band from the long strike down to the fall the user fears; if that fall does not reach
        # below the long strike there is no band, and a spread just under the strike would not be what they asked for.
        k_short = None if spot * (1.0 - expected_fall_pct / 100.0) >= k_long - EPS \
            else pick_short_strike(strikes, spot, expected_fall_pct, k_long)
        if k_short is None:
            out["reason"] = {"code": "expected_fall_within_tolerance",
                             "message": "The fall you are worried about is within the loss you said you can tolerate, so a put spread has no band to cover."}
            return out
        legs.append({"side": "sell", "type": "put", "strike": k_short, "qty": qty, "premium": float(puts[k_short])})
        structure = "put_spread"
    debit_per_unit = sum((1 if l["side"] == "buy" else -1) * l["premium"] for l in legs)
    if debit_per_unit <= 0:
        out["reason"] = {"code": "no_net_cost", "message": "The quoted prices give no net cost for this structure, so it is not offered."}
        return out
    premium_rs = debit_per_unit * qty
    entry_charges = float(charges(legs, None)) if charges else 0.0
    cost = {"premium_rs": premium_rs, "charges_rs": entry_charges, "total_rs": premium_rs + entry_charges,
            "pct_of_portfolio": (premium_rs + entry_charges) / portfolio_value * 100.0, "charges_included": charges is not None}

    rows: List[Dict[str, Any]] = []
    for m in _moves(expected_fall_pct):
        s_t = spot * (1.0 + m / 100.0)
        gross = _payoff(legs, s_t)
        exit_charges = float(charges(legs, s_t)) if charges else 0.0
        hedge_pnl = gross - premium_rs - entry_charges - exit_charges
        without = beta_exposure * m / 100.0
        rows.append({"move_pct": m, "nifty_level": s_t, "without_hedge_rs": without, "hedge_pnl_rs": hedge_pnl,
                     "with_hedge_rs": without + hedge_pnl, "is_expected_fall": m == -int(round(abs(expected_fall_pct)))})
    fall_level = spot * (1.0 - expected_fall_pct / 100.0)
    out.update({
        "available": True, "structure": structure, "legs": legs,
        "deductible_rs": beta_exposure * (spot - k_long) / spot,
        "deductible_pct": (spot - k_long) / spot * 100.0,
        "protection_starts_at": k_long,
        "protection_at_expected_fall_rs": _payoff(legs, fall_level),
        "max_protection_rs": (k_long - legs[1]["strike"]) * qty if structure == "put_spread" else None,
        "break_even_level": k_long - debit_per_unit,
        "cost": cost, "scenario_rows": rows,
        "worst_scenario_shown_rs": min(r["with_hedge_rs"] for r in rows),
        "place_allowed": conf["level"] in ("high", "medium"),
        "reason": None if conf["level"] in ("high", "medium") else
        {"code": "hedge_confidence_" + conf["level"], "message": conf["message"]},
    })
    return out


def build(*, portfolio_value: Optional[float], hedgeable_value: Optional[float], beta: Optional[float], spot: Optional[float],
          lot: Optional[int], expiry: str, puts: Dict[float, float], tolerance_rs: float, expected_fall_pct: float,
          r2: Optional[float] = None, corr: Optional[float] = None,
          charges: Optional[Callable[[List[Dict[str, Any]], Optional[float]], float]] = None) -> Dict[str, Any]:
    """The whole Quick Hedge answer for one expiry. status: ok | not_hedgeable | no_hedge_needed | incomplete."""
    res: Dict[str, Any] = {"policy_version": POLICY_VERSION, "status": "ok", "reasons": [], "expiry": expiry, "modes": [],
                           "exposure": None, "confidence": confidence(r2, corr), "disclosures": list(DISCLOSURES),
                           "inputs": {"tolerance_rs": tolerance_rs, "expected_fall_pct": expected_fall_pct}}

    def stop(status: str, code: str, message: str) -> Dict[str, Any]:
        res["status"] = status
        res["reasons"].append({"code": code, "message": message})
        return res

    pv, hv, b, s, lt = _num(portfolio_value), _num(hedgeable_value), _num(beta), _num(spot), _num(lot)
    for name, v in (("beta", b), ("spot", s), ("lot", lt)):
        if v is None or v <= 0:
            return stop("incomplete", f"missing_{name}", f"The {name} needed to size a hedge is not available, so no hedge is shown.")
    if pv is None or pv <= 0 or hv is None or hv <= 0:
        return stop("incomplete", "missing_portfolio", "There is no equity-linked portfolio value to hedge.")
    strikes = _put_strikes(puts)
    if not strikes:
        return stop("incomplete", "missing_premiums", "No traded index put prices are available for this expiry.")
    tol = _num(tolerance_rs)
    ef = _num(expected_fall_pct)
    if tol is None or tol < 0 or ef is None or ef <= 0:
        return stop("incomplete", "bad_inputs", "Tolerable loss must be zero or more and the expected fall must be above zero.")

    e = hv * b
    sizing = lots_for(e, s, int(lt))
    res["exposure"] = {"portfolio_value_rs": pv, "hedgeable_value_rs": hv, "beta": b, "beta_adjusted_exposure_rs": e, **sizing,
                       "spot": s, "lot": int(lt)}
    if tol >= e:
        return stop("no_hedge_needed", "tolerance_at_or_above_exposure",
                    "The loss you can tolerate is at least your whole market exposure, so a hedge cannot reduce your loss below it.")
    if sizing["executed_lots"] < 1:
        return stop("not_hedgeable", "smaller_than_one_lot",
                    "Your portfolio is smaller than one efficient index-option hedge lot. A full lot may over-hedge your portfolio.")
    res["modes"] = [_mode(m, exposure=res["exposure"], hedgeable_value=hv, portfolio_value=pv, beta_exposure=e, spot=s, lot=int(lt),
                          puts=puts, strikes=strikes, tolerance_rs=tol, expected_fall_pct=ef, conf=res["confidence"], charges=charges)
                    for m in MODES]
    return res
