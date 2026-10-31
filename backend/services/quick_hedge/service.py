"""Quick Hedge: one answer for the Smart Trading Desk and for Copilot chat. Reads the inputs on the server (inputs.py), runs the
deterministic core (calc.py) with the desk cost card's charges (costs.py), and returns the result with the data's dates and
what was left out. The language model never touches a number here. Nothing is stored and no order is placed."""
from __future__ import annotations

from typing import Any, Dict, Optional

from . import calc, costs, inputs

NO_FIT = {"r2": None, "correlation": None, "regression_beta": None, "observations": 0, "coverage": 0.0, "series_used": 0,
          "window_start": None, "window_end": None, "reason": None}


class Readers:
    """The three reads; tests replace them."""
    portfolio = staticmethod(inputs.load_portfolio)
    market = staticmethod(inputs.nifty_market)
    fit = staticmethod(inputs.load_fit)


async def run(db, user_id: str, *, expected_fall_pct: float, tenor: str = "1m", tolerance_rs: Optional[float] = None,
              tolerance_pct: Optional[float] = None, readers: Any = None) -> Dict[str, Any]:
    r = readers or Readers
    pf = await r.portfolio(db, user_id)
    market = await r.market(tenor)
    fit = dict(NO_FIT)
    if pf["beta"] is not None and pf["hedgeable_value_rs"] > 0:
        fit = await r.fit(pf)
    if tolerance_rs is None and tolerance_pct is not None:
        tolerance_rs = tolerance_pct / 100.0 * pf["hedgeable_value_rs"]
    res = calc.build(
        portfolio_value=pf["portfolio_value_rs"], hedgeable_value=pf["hedgeable_value_rs"], beta=pf["beta"],
        spot=market.get("spot"), lot=market.get("lot"), expiry=market.get("expiry") or "", puts=market.get("puts") or {},
        tolerance_rs=tolerance_rs if tolerance_rs is not None else float("nan"), expected_fall_pct=expected_fall_pct,
        r2=fit.get("r2"), corr=fit.get("correlation"), charges=costs.make_charges())
    pre = list(pf["reasons"]) + ([] if market.get("ok") else [market["reason"]])
    if pre:                                    # the real cause first, then whatever the core also found missing
        seen = {p["code"] for p in pre}
        res["status"], res["modes"] = "incomplete", []
        res["reasons"] = pre + [x for x in res["reasons"] if x["code"] not in seen]
    if fit.get("reason"):
        res["reasons"].append(fit["reason"])
    res["tenor"] = tenor
    res["data"] = {
        "portfolio": {"portfolio_value_rs": pf["portfolio_value_rs"], "hedgeable_value_rs": pf["hedgeable_value_rs"],
                      "excluded_rs": pf["excluded_rs"], "beta": pf["beta"], "beta_coverage": pf["beta_coverage"],
                      "holdings_counted": len(pf["holdings"]), "as_of": pf.get("as_of")},
        "market": {"as_of": market.get("as_of"), "expiry": market.get("expiry"), "days_to_expiry": market.get("days_to_expiry"),
                   "expiries": market.get("expiries") or [], "puts_traded": len(market.get("puts") or {}),
                   "source": market.get("source")},
        "fit": {k: fit.get(k) for k in NO_FIT},
    }
    return res
