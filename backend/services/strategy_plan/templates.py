"""Strategy templates as leg builders (PRD §16.4). Pure: a chain snapshot dict in, legs plus the engine's exact
numbers out. Strikes are arguments: strike SELECTION is not done here.

Chain snapshot (the shape routes/fno.py sends): {"as_of": "2026-10-19", "strikes": [{"strike": 1300.0,
"call": {"close", "oi", "volume"} | None, "put": {...} | None}, ...]}. A premium is the contract's close; a strike or
side with no close price raises TemplateError (code `no_premium`): a premium is never guessed.
"""
from __future__ import annotations

import inspect
from datetime import date
from typing import Any, Dict, List, Optional

from .engine import CALCULATION_VERSION, compute_payoff


class TemplateError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code, self.message = code, message


def _premium(chain: Dict[str, Any], strike: float, side: str) -> float:
    for row in chain.get("strikes") or []:
        if isinstance(row, dict) and row.get("strike") == strike:
            c = (row.get(side) or {}).get("close")
            if isinstance(c, (int, float)) and not isinstance(c, bool) and c > 0:
                return float(c)
            raise TemplateError("no_premium", f"No close price for the {strike:g} {side} in the chain.")
    raise TemplateError("no_strike", f"Strike {strike:g} is not in the chain.")


def _src(chain: Dict[str, Any]) -> str:
    return chain.get("source") or f"NSE F&O bhavcopy close, {chain.get('as_of')}"


def _opt(chain, side, option_type, strike, lots, lot_size, expiry):
    return {"kind": "option", "side": side, "quantity": lots, "lot_size": lot_size,
            "entry_price": _premium(chain, strike, "call" if option_type == "call" else "put"),
            "expiry": expiry, "strike": strike, "option_type": option_type, "price_source": _src(chain)}


def _result(name: str, legs: List[Dict[str, Any]], underlying: str, spot: float, today: Optional[date],
            costs: Optional[dict], as_of: Optional[str]) -> Dict[str, Any]:
    prices = [spot] + [l["strike"] for l in legs if l.get("strike")] + [l["entry_price"] for l in legs if l["kind"] != "option"]
    body = {"underlying": underlying, "reference_price": spot, "legs": legs,
            "grid": {"min": min(prices) * 0.5, "max": max(prices) * 1.5, "points": 400}}
    if costs:
        body["costs"] = costs
    if as_of:
        body["as_of"] = as_of
    r = compute_payoff(body, today)
    if not r["valid"]:
        raise TemplateError("invalid_structure", "; ".join(p["code"] for p in r["problems"]))
    e = r["expiry"]
    return {"name": name, "legs": legs, "max_profit": e["max_profit"], "max_loss": e["max_loss"],
            "profit_unbounded": e["profit_unbounded"], "loss_unbounded": e["loss_unbounded"],
            "breakevens": e["breakevens"], "net_premium": e["net_premium"], "capital_at_risk": r["capital_at_risk"]}



def long_call(chain, spot, lot_size, expiry, strike, lots=1, underlying="X", today=None, costs=None):
    legs = [_opt(chain, "buy", "call", strike, lots, lot_size, expiry)]
    return _result("long_call", legs, underlying, spot, today, costs, chain.get("as_of"))


def long_put(chain, spot, lot_size, expiry, strike, lots=1, underlying="X", today=None, costs=None):
    legs = [_opt(chain, "buy", "put", strike, lots, lot_size, expiry)]
    return _result("long_put", legs, underlying, spot, today, costs, chain.get("as_of"))


def bull_call_spread(chain, spot, lot_size, expiry, long_strike, short_strike, lots=1, underlying="X", today=None, costs=None):
    if not long_strike < short_strike:
        raise TemplateError("strike_order", "Bull call spread: buy the lower strike, sell the higher.")
    legs = [_opt(chain, "buy", "call", long_strike, lots, lot_size, expiry), _opt(chain, "sell", "call", short_strike, lots, lot_size, expiry)]
    return _result("bull_call_spread", legs, underlying, spot, today, costs, chain.get("as_of"))


def bear_put_spread(chain, spot, lot_size, expiry, long_strike, short_strike, lots=1, underlying="X", today=None, costs=None):
    if not long_strike > short_strike:
        raise TemplateError("strike_order", "Bear put spread: buy the higher strike, sell the lower.")
    legs = [_opt(chain, "buy", "put", long_strike, lots, lot_size, expiry), _opt(chain, "sell", "put", short_strike, lots, lot_size, expiry)]
    return _result("bear_put_spread", legs, underlying, spot, today, costs, chain.get("as_of"))


def iron_condor(chain, spot, lot_size, expiry, long_put_strike, short_put_strike, short_call_strike, long_call_strike,
                lots=1, underlying="X", today=None, costs=None):
    if not long_put_strike < short_put_strike < short_call_strike < long_call_strike:
        raise TemplateError("strike_order", "Iron condor: long put < short put < short call < long call.")
    legs = [_opt(chain, "buy", "put", long_put_strike, lots, lot_size, expiry), _opt(chain, "sell", "put", short_put_strike, lots, lot_size, expiry),
            _opt(chain, "sell", "call", short_call_strike, lots, lot_size, expiry), _opt(chain, "buy", "call", long_call_strike, lots, lot_size, expiry)]
    return _result("iron_condor", legs, underlying, spot, today, costs, chain.get("as_of"))


def _future(side, name, spot, lot_size, expiry, entry_price, lots, underlying, today, costs, as_of, source):
    legs = [{"kind": "future", "side": side, "quantity": lots, "lot_size": lot_size, "entry_price": entry_price,
             "expiry": expiry, "price_source": source}]
    return _result(name, legs, underlying, spot, today, costs, as_of)


def long_future(spot, lot_size, expiry, entry_price, lots=1, underlying="X", today=None, costs=None, as_of=None, source=None):
    return _future("buy", "long_future", spot, lot_size, expiry, entry_price, lots, underlying, today, costs, as_of, source)


def short_future(spot, lot_size, expiry, entry_price, lots=1, underlying="X", today=None, costs=None, as_of=None, source=None):
    return _future("sell", "short_future", spot, lot_size, expiry, entry_price, lots, underlying, today, costs, as_of, source)


def cash_long(spot, shares, entry_price=None, underlying="X", today=None, costs=None, as_of=None, source=None):
    legs = [{"kind": "cash", "side": "buy", "quantity": shares, "lot_size": 1,
             "entry_price": entry_price if entry_price is not None else spot, "price_source": source}]
    return _result("cash_long", legs, underlying, spot, today, costs, as_of)


# ── catalog ──────────────────────────────────────────────────────────────────
# The templates as the F&O lab's program library lists them (GET /api/desk/strategy/templates). One entry per public
# template function above; tests/test_strategy_plan_templates_route.py checks the names, and that every leg's
# strike_param is an argument of its function, so the catalog cannot drift from the code. `params` is not written here:
# catalog() reads it from each function's own signature.

CATALOG: List[Dict[str, Any]] = [
    {"name": "long_call", "label": "Long call", "kind": "option",
     "legs": [{"side": "buy", "option_type": "call", "strike_param": "strike"}]},
    {"name": "long_put", "label": "Long put", "kind": "option",
     "legs": [{"side": "buy", "option_type": "put", "strike_param": "strike"}]},
    {"name": "bull_call_spread", "label": "Bull call spread", "kind": "option",
     "legs": [{"side": "buy", "option_type": "call", "strike_param": "long_strike"},
              {"side": "sell", "option_type": "call", "strike_param": "short_strike"}]},
    {"name": "bear_put_spread", "label": "Bear put spread", "kind": "option",
     "legs": [{"side": "buy", "option_type": "put", "strike_param": "long_strike"},
              {"side": "sell", "option_type": "put", "strike_param": "short_strike"}]},
    {"name": "iron_condor", "label": "Iron condor", "kind": "option",
     "legs": [{"side": "buy", "option_type": "put", "strike_param": "long_put_strike"},
              {"side": "sell", "option_type": "put", "strike_param": "short_put_strike"},
              {"side": "sell", "option_type": "call", "strike_param": "short_call_strike"},
              {"side": "buy", "option_type": "call", "strike_param": "long_call_strike"}]},
    {"name": "long_future", "label": "Long future", "kind": "future",
     "legs": [{"side": "buy", "option_type": None, "strike_param": None}]},
    {"name": "short_future", "label": "Short future", "kind": "future",
     "legs": [{"side": "sell", "option_type": None, "strike_param": None}]},
    {"name": "cash_long", "label": "Cash long", "kind": "cash",
     "legs": [{"side": "buy", "option_type": None, "strike_param": None}]},
]

# Arguments every template takes from its context (the chain, the market, the call), not a choice of the template.
_CONTEXT_ARGS = {"chain", "spot", "lot_size", "expiry", "underlying", "today", "costs", "as_of", "source"}


def catalog() -> List[Dict[str, Any]]:
    """CATALOG with each template's own parameters (read from its signature) and the payoff engine's version."""
    out: List[Dict[str, Any]] = []
    for entry in CATALOG:
        fn = globals()[entry["name"]]
        params = [p for p in inspect.signature(fn).parameters if p not in _CONTEXT_ARGS]
        out.append({**entry, "legs": [dict(leg) for leg in entry["legs"]], "params": params,
                    "calculation_version": CALCULATION_VERSION})
    return out
