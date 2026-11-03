"""compute_payoff: the whole POST /api/desk/strategy/payoff calculation, pure (no I/O, no broker, no database)."""
from __future__ import annotations

from datetime import date
from typing import Any, Dict, List, Optional

from services.option_pricing import RISK_FREE_RATE

from . import payoff as po
from .model import parse_request, slopes
from .pre_expiry import pre_expiry

# payoff-v2 (2026-10-27): net figures and capital at risk are priced with the desk cost card desk-cost-v2 (statutory charges
# included), the card the plan's sizing and the paper trades use. payoff-v1 charged slippage and a flat brokerage only.
CALCULATION_VERSION = "payoff-v2"

MARGIN_REASON = ("This payoff calculation does not estimate margin. The margin for a structure comes only from Zerodha's margin calculator "
                 "(the F&O builder's funds and margin strip), which needs the platform's daily Kite login and is unavailable without it.")


def _empty(parsed: Dict[str, Any]) -> Dict[str, Any]:
    return {"valid": False, "problems": parsed["problems"], "warnings": parsed["warnings"],
            "calculation_version": CALCULATION_VERSION, "expiry": None, "pre_expiry": None, "costs": None,
            "margin": None, "margin_reason": MARGIN_REASON, "capital_at_risk": None,
            "loss_can_exceed_margin": False, "caveats": [], "sent_to_broker": False}


def compute_payoff(body: Any, today: Optional[date] = None) -> Dict[str, Any]:
    """Validate and calculate. Never raises on bad input: problems come back in the result with valid=false."""
    parsed = parse_request(body, today or date.today())
    if parsed["problems"] or parsed["legs"] is None or parsed["grid"] is None:
        return _empty(parsed)
    legs, ref = parsed["legs"], parsed["reference_price"]
    lo, hi, n = parsed["grid"]
    grid = [lo + (hi - lo) * i / (n - 1) for i in range(n)]
    model, src = po.cost_params(parsed["costs"])
    warns: List[Dict[str, str]] = parsed["warnings"]

    ext = po.extremes(legs, lo, hi, grid)
    be = po.breakevens(legs, lo, hi, grid)
    if be["flat_at_zero"]:
        warns.append({"code": "payoff_flat_at_zero", "message": "The payoff is exactly zero over a stretch of prices: it has no single breakeven there."})
    if len(be["all"]) > len(be["in_grid"]):
        warns.append({"code": "breakeven_outside_grid", "message": "A breakeven lies outside the plotted price range: widen the grid to see it."})

    gross_arr = [po.r2(po.gross(legs, s)) for s in grid]
    net_arr = [po.r2(po.gross(legs, s) - po.total_cost(legs, s, model)) for s in grid]
    scenarios = [{"name": s["name"], "underlying_price": po.r2(s["underlying_price"]),
                  "gross": po.r2(po.gross(legs, s["underlying_price"])),
                  "net": po.r2(po.gross(legs, s["underlying_price"]) - po.total_cost(legs, s["underlying_price"], model))}
                 for s in parsed["scenarios"]]
    expiry = {
        "grid": [po.r2(s) for s in grid], "gross": gross_arr, "net": net_arr,
        "per_leg": [{"index": l["index"], "label": l["label"], "gross": [po.r2(po.leg_gross(l, s)) for s in grid]} for l in legs],
        "breakevens": [po.r2(b) for b in be["in_grid"]],
        "max_profit": po.r2(ext["max_profit"]), "max_loss": po.r2(ext["max_loss"]),
        "profit_unbounded": ext["profit_unbounded"], "loss_unbounded": ext["loss_unbounded"],
        "range_max_profit": po.r2(ext["range_max_profit"]), "range_max_loss": po.r2(ext["range_max_loss"]),
        "net_premium": po.r2(po.net_premium(legs)), "scenarios": scenarios,
        "extremes_basis": "gross, all prices from 0 to infinity (exact: payoff is piecewise linear); range_* are over the plotted grid",
    }
    pre = None
    if parsed["pre_expiry"] is not None:
        pre = pre_expiry(legs, ref, grid, parsed["as_of"], parsed["pre_expiry"], model, RISK_FREE_RATE,
                         scenarios=parsed["scenarios"])

    has_future = any(l["kind"] == "future" for l in legs)
    caveats = [
        "Margin is not the maximum loss.",
        "Estimated P&L is a calculation at the prices shown, not a forecast. Net figures include brokerage, STT, exchange and SEBI charges, "
        "stamp duty, GST and slippage (desk cost card); they exclude DP charges, income tax, dividends and funding.",
        "Nothing is sent to a broker.",
    ]
    if has_future:
        caveats.insert(0, "Futures losses can exceed the initial margin; a future's loss is limited only by the price reaching zero.")
    if ext["loss_unbounded"]:
        caveats.insert(0, "The loss on this position has no upper limit.")
    car = po.capital_at_risk(legs, ext, model)
    return {"valid": True, "problems": [], "warnings": warns, "calculation_version": CALCULATION_VERSION,
            "underlying": parsed["underlying"], "reference_price": po.r2(ref), "as_of": parsed["as_of"].isoformat(),
            "expiry": expiry, "pre_expiry": pre,
            "costs": po.costs_block(legs, ref, model, src),
            "margin": None, "margin_reason": MARGIN_REASON,
            "capital_at_risk": po.r2(car),
            "capital_at_risk_basis": "worst net loss over all prices, every leg charged entry and exit costs; null when the loss is unbounded",
            "loss_can_exceed_margin": has_future, "caveats": caveats, "sent_to_broker": False}
