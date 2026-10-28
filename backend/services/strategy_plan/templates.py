"""Strategy templates as leg builders (PRD §16.4). Pure: a chain snapshot dict in, legs plus the engine's exact
numbers out. Strikes are arguments: strike SELECTION is not done here.

Chain snapshot (the shape routes/fno.py sends): {"as_of": "2026-10-19", "strikes": [{"strike": 1300.0,
"call": {"close", "oi", "volume"} | None, "put": {...} | None}, ...]}. A premium is the contract's close; a strike or
side with no close price raises TemplateError (code `no_premium`): a premium is never guessed.

Templates that hold the underlying (covered call, protective put, collar) hold it as CASH SHARES, lots × lot_size of
them so every short call is fully covered, bought at `spot`, the chain's underlying price (its `spot_source`, else the
bhavcopy underlying price on `as_of`). Not a long future: the risk gate's additional F&O check
(services/risk_gate/gate.defined_risk_failures) refuses a long future with a short call and no long put as
`unhedged_future`, and the owner's first wave is for pledged share portfolios (docs/AUTONOMOUS_PAPER_AGENTS_WORKFLOW.md §2).
"""
from __future__ import annotations

import functools
import inspect
import math
from datetime import date, timedelta
from typing import Any, Dict, List, Optional

from services import option_pricing as op

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


def _shares(chain, spot, lots, lot_size):
    """The underlying as cash shares, lots × lot_size of them, bought at the chain's spot (never a guessed price)."""
    if isinstance(spot, bool) or not isinstance(spot, (int, float)) or spot <= 0:
        raise TemplateError("no_spot", "The chain has no underlying price, so the shares cannot be priced.")
    return {"kind": "cash", "side": "buy", "quantity": lots * lot_size, "lot_size": 1, "entry_price": float(spot),
            "price_source": chain.get("spot_source") or f"NSE F&O bhavcopy underlying price, {chain.get('as_of')}"}


def _otm_call(name: str, strike: float, spot: float) -> None:
    if not strike > spot:
        raise TemplateError("strike_not_otm", f"{name}: the short call must be out of the money (strike above the spot {spot:g}).")


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


def bull_put_spread(chain, spot, lot_size, expiry, long_strike, short_strike, lots=1, underlying="X", today=None, costs=None):
    """A credit spread: sell the higher-strike put, buy the lower-strike put."""
    if not long_strike < short_strike:
        raise TemplateError("strike_order", "Bull put spread: sell the higher strike, buy the lower.")
    legs = [_opt(chain, "buy", "put", long_strike, lots, lot_size, expiry), _opt(chain, "sell", "put", short_strike, lots, lot_size, expiry)]
    return _result("bull_put_spread", legs, underlying, spot, today, costs, chain.get("as_of"))


def bear_call_spread(chain, spot, lot_size, expiry, short_strike, long_strike, lots=1, underlying="X", today=None, costs=None):
    """A credit spread: sell the lower-strike call, buy the higher-strike call."""
    if not short_strike < long_strike:
        raise TemplateError("strike_order", "Bear call spread: sell the lower strike, buy the higher.")
    legs = [_opt(chain, "sell", "call", short_strike, lots, lot_size, expiry), _opt(chain, "buy", "call", long_strike, lots, lot_size, expiry)]
    return _result("bear_call_spread", legs, underlying, spot, today, costs, chain.get("as_of"))


def covered_call(chain, spot, lot_size, expiry, call_strike, lots=1, underlying="X", today=None, costs=None):
    """Hold lots × lot_size shares and sell an out-of-the-money call on them."""
    _otm_call("Covered call", call_strike, spot)
    legs = [_shares(chain, spot, lots, lot_size), _opt(chain, "sell", "call", call_strike, lots, lot_size, expiry)]
    return _result("covered_call", legs, underlying, spot, today, costs, chain.get("as_of"))


def protective_put(chain, spot, lot_size, expiry, put_strike, lots=1, underlying="X", today=None, costs=None):
    """Hold lots × lot_size shares and buy a put on them."""
    legs = [_shares(chain, spot, lots, lot_size), _opt(chain, "buy", "put", put_strike, lots, lot_size, expiry)]
    return _result("protective_put", legs, underlying, spot, today, costs, chain.get("as_of"))


def collar(chain, spot, lot_size, expiry, put_strike, call_strike, lots=1, underlying="X", today=None, costs=None):
    """Hold lots × lot_size shares, buy a put below and sell an out-of-the-money call above."""
    if not put_strike < call_strike:
        raise TemplateError("strike_order", "Collar: the put strike must be below the call strike.")
    _otm_call("Collar", call_strike, spot)
    legs = [_shares(chain, spot, lots, lot_size), _opt(chain, "buy", "put", put_strike, lots, lot_size, expiry),
            _opt(chain, "sell", "call", call_strike, lots, lot_size, expiry)]
    return _result("collar", legs, underlying, spot, today, costs, chain.get("as_of"))


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
#
# Each leg names its `instrument` (option, future, cash). `kind` is the template's family as the UI groups it: an
# "option" template may also hold the underlying as cash shares (covered call, protective put, collar). `risk` says
# honestly how the maximum loss is bounded, the payoff engine's own result at expiry:
#   defined    fixed by the option legs (premium, net debit, or strike width less the net credit)
#   to_zero    the underlying's risk: the loss runs to a price of zero (bounded only there)
#   unbounded  no upper limit
#
# `intent` is the template's one-line market intent and `tags` the Strategy Lab's intent chips (bullish, bearish,
# neutral, income, hedging, volatility); no template here is a volatility trade (a long straddle or short strangle is not
# in the catalog), so no entry carries that tag. `direction` is the desk paper-trade direction the structure is recorded
# with (services/desk_strategy_trades.DIRECTIONS).


def _leg(side, option_type=None, strike_param=None, instrument=None):
    return {"side": side, "option_type": option_type, "strike_param": strike_param,
            "instrument": instrument or ("option" if option_type else None)}


_SHARES = _leg("buy", instrument="cash")

CATALOG: List[Dict[str, Any]] = [
    {"name": "long_call", "label": "Long call", "kind": "option",
     "intent": "Strongly bullish, limited risk", "tags": ["bullish"], "direction": "bullish",
     "legs": [_leg("buy", "call", "strike")],
     "risk": {"max_loss": "defined", "note": "The premium paid."}},
    {"name": "long_put", "label": "Long put", "kind": "option",
     "intent": "Bearish, or insurance on a fall", "tags": ["bearish", "hedging"], "direction": "bearish",
     "legs": [_leg("buy", "put", "strike")],
     "risk": {"max_loss": "defined", "note": "The premium paid."}},
    {"name": "bull_call_spread", "label": "Bull call spread", "kind": "option",
     "intent": "Moderately bullish", "tags": ["bullish"], "direction": "bullish",
     "legs": [_leg("buy", "call", "long_strike"), _leg("sell", "call", "short_strike")],
     "risk": {"max_loss": "defined", "note": "The net debit paid."}},
    {"name": "bear_put_spread", "label": "Bear put spread", "kind": "option",
     "intent": "Moderately bearish", "tags": ["bearish"], "direction": "bearish",
     "legs": [_leg("buy", "put", "long_strike"), _leg("sell", "put", "short_strike")],
     "risk": {"max_loss": "defined", "note": "The net debit paid."}},
    {"name": "bull_put_spread", "label": "Bull put spread", "kind": "option",
     "intent": "Mildly bullish, collect premium", "tags": ["bullish", "income"], "direction": "bullish",
     "legs": [_leg("buy", "put", "long_strike"), _leg("sell", "put", "short_strike")],
     "risk": {"max_loss": "defined", "note": "The strike width less the net credit received; the short put is covered "
                                             "by the long put below it."}},
    {"name": "bear_call_spread", "label": "Bear call spread", "kind": "option",
     "intent": "Mildly bearish, collect premium", "tags": ["bearish", "income"], "direction": "bearish",
     "legs": [_leg("sell", "call", "short_strike"), _leg("buy", "call", "long_strike")],
     "risk": {"max_loss": "defined", "note": "The strike width less the net credit received; the short call is covered "
                                             "by the long call above it."}},
    {"name": "iron_condor", "label": "Iron condor", "kind": "option",
     "intent": "Range-bound, collect premium", "tags": ["neutral", "income"], "direction": "neutral",
     "legs": [_leg("buy", "put", "long_put_strike"), _leg("sell", "put", "short_put_strike"),
              _leg("sell", "call", "short_call_strike"), _leg("buy", "call", "long_call_strike")],
     "risk": {"max_loss": "defined", "note": "The wider wing's strike width less the net credit received."}},
    {"name": "covered_call", "label": "Covered call", "kind": "option",
     "intent": "Hold the stock, earn premium", "tags": ["bullish", "income"], "direction": "bullish",
     "legs": [_SHARES, _leg("sell", "call", "call_strike")],
     "risk": {"max_loss": "to_zero", "note": "The shares' risk: the loss runs down to a share price of zero, less the "
                                             "call premium received. The short call is covered by the shares (lots × lot "
                                             "size), so the gain is capped at the call strike."}},
    {"name": "protective_put", "label": "Protective put", "kind": "option",
     "intent": "Hold the stock, insure the fall", "tags": ["bullish", "hedging"], "direction": "bullish",
     "legs": [_SHARES, _leg("buy", "put", "put_strike")],
     "risk": {"max_loss": "defined", "note": "The fall from the share price to the put strike, plus the put premium. "
                                             "The position holds the shares' full value; the gain is open."}},
    {"name": "collar", "label": "Collar", "kind": "option",
     "intent": "Hold the stock, low-cost insurance", "tags": ["neutral", "hedging"], "direction": "neutral",
     "legs": [_SHARES, _leg("buy", "put", "put_strike"), _leg("sell", "call", "call_strike")],
     "risk": {"max_loss": "defined", "note": "The fall from the share price to the put strike, plus the net premium paid "
                                             "(less a net credit). The position holds the shares' full value; the gain "
                                             "is capped at the call strike."}},
    {"name": "long_future", "label": "Long future", "kind": "future",
     "intent": "Bullish, full exposure", "tags": ["bullish"], "direction": "bullish",
     "legs": [_leg("buy", instrument="future")],
     "risk": {"max_loss": "to_zero", "note": "Down to a price of zero; marked to market daily, and the loss can exceed "
                                             "the margin."}},
    {"name": "short_future", "label": "Short future", "kind": "future",
     "intent": "Bearish, full exposure", "tags": ["bearish"], "direction": "bearish",
     "legs": [_leg("sell", instrument="future")],
     "risk": {"max_loss": "unbounded", "note": "The loss grows without limit as the price rises."}},
    {"name": "cash_long", "label": "Cash long", "kind": "cash",
     "intent": "Own the shares", "tags": ["bullish"], "direction": "bullish",
     "legs": [_leg("buy", instrument="cash")],
     "risk": {"max_loss": "to_zero", "note": "The shares' full value, down to a price of zero."}},
]

# Arguments every template takes from its context (the chain, the market, the call), not a choice of the template.
_CONTEXT_ARGS = {"chain", "spot", "lot_size", "expiry", "underlying", "today", "costs", "as_of", "source"}


# ── illustrations ───────────────────────────────────────────────────────────
# Each card's mini payoff is the template's OWN payoff: its function above is called on a synthetic chain and the
# payoff engine draws the curve. Nothing here is a price, a quote or a forecast; the basis says so.
_ILLUSTRATION_SPOT = 100.0
_ILLUSTRATION_VOL = 0.20
_ILLUSTRATION_DAYS = 30
_ILLUSTRATION_DAY = date(2026, 1, 5)            # fixed, so the curve is the same on every call and every day
_ILLUSTRATION_GRID = (70.0, 130.0, 41)
_ILLUSTRATION_BASIS = ("Illustrative only: spot 100, the strikes listed, premiums priced with Black-76 at 20% volatility "
                       "and 30 days to expiry, gross profit or loss at expiry for one unit; not a price or a forecast.")

#: The example strikes (or entry) each card is drawn at; every key is an argument of the template's function.
_ILLUSTRATION_PARAMS: Dict[str, Dict[str, float]] = {
    "long_call": {"strike": 100.0},
    "long_put": {"strike": 100.0},
    "bull_call_spread": {"long_strike": 100.0, "short_strike": 110.0},
    "bear_put_spread": {"long_strike": 100.0, "short_strike": 90.0},
    "bull_put_spread": {"long_strike": 90.0, "short_strike": 100.0},
    "bear_call_spread": {"short_strike": 100.0, "long_strike": 110.0},
    "iron_condor": {"long_put_strike": 85.0, "short_put_strike": 95.0, "short_call_strike": 105.0, "long_call_strike": 115.0},
    "covered_call": {"call_strike": 110.0},
    "protective_put": {"put_strike": 95.0},
    "collar": {"put_strike": 95.0, "call_strike": 110.0},
    "long_future": {"entry_price": 100.0},
    "short_future": {"entry_price": 100.0},
    "cash_long": {"shares": 1},
}


def _illustration_chain() -> Dict[str, Any]:
    """Strikes 50 to 150 in steps of 5, each call and put closed at its Black-76 price (forward = spot × e^(rT))."""
    t = op.year_fraction(_ILLUSTRATION_DAYS)
    fwd = _ILLUSTRATION_SPOT * math.exp(op.RISK_FREE_RATE * t)
    rows = []
    for k in range(50, 155, 5):
        px = {side: round(op.price(code, fwd, float(k), t, _ILLUSTRATION_VOL, op.RISK_FREE_RATE), 4)
              for side, code in (("call", "CE"), ("put", "PE"))}
        rows.append({"strike": float(k), **{side: ({"close": v} if v > 0 else None) for side, v in px.items()}})
    return {"as_of": _ILLUSTRATION_DAY.isoformat(), "strikes": rows,
            "source": "illustration: Black-76 at 20% volatility", "spot_source": "illustration: spot 100"}


def _illustration(name: str) -> Dict[str, Any]:
    params = _ILLUSTRATION_PARAMS[name]
    fn = globals()[name]
    expiry = (_ILLUSTRATION_DAY + timedelta(days=_ILLUSTRATION_DAYS)).isoformat()
    ctx: Dict[str, Any] = {"spot": _ILLUSTRATION_SPOT, "underlying": "ILLUSTRATION", "today": _ILLUSTRATION_DAY}
    if name in ("long_future", "short_future"):
        ctx.update(lot_size=1, expiry=expiry, as_of=_ILLUSTRATION_DAY.isoformat(), source="illustration: entry 100")
    elif name == "cash_long":
        ctx.update(as_of=_ILLUSTRATION_DAY.isoformat(), source="illustration: entry 100")
    else:
        ctx.update(chain=_illustration_chain(), lot_size=1, expiry=expiry)
    built = fn(**ctx, **params)
    lo, hi, n = _ILLUSTRATION_GRID
    r = compute_payoff({"underlying": "ILLUSTRATION", "reference_price": _ILLUSTRATION_SPOT, "legs": built["legs"],
                        "as_of": _ILLUSTRATION_DAY.isoformat(), "grid": {"min": lo, "max": hi, "points": n}},
                       _ILLUSTRATION_DAY)
    if not r["valid"]:
        raise TemplateError("invalid_structure", "; ".join(p["code"] for p in r["problems"]))
    e = r["expiry"]
    return {"spot": _ILLUSTRATION_SPOT, "params": dict(params),
            "points": [[x, y] for x, y in zip(e["grid"], e["gross"])],
            "max_profit": built["max_profit"], "max_loss": built["max_loss"],
            "profit_unbounded": built["profit_unbounded"], "loss_unbounded": built["loss_unbounded"],
            "breakevens": built["breakevens"], "basis": _ILLUSTRATION_BASIS}


@functools.lru_cache(maxsize=1)
def _illustrations() -> Dict[str, Dict[str, Any]]:
    """{name: {"illustration": ...} or {"illustration": None, "illustration_error": why}}, worked out once."""
    out: Dict[str, Dict[str, Any]] = {}
    for entry in CATALOG:
        try:
            out[entry["name"]] = {"illustration": _illustration(entry["name"])}
        except (TemplateError, KeyError, TypeError, ValueError) as exc:     # never a made-up curve: the card says why
            out[entry["name"]] = {"illustration": None, "illustration_error": f"{type(exc).__name__}: {exc}"[:200]}
    return out


def catalog() -> List[Dict[str, Any]]:
    """CATALOG with each template's own parameters (read from its signature), the payoff engine's version and its
    illustration (the template's own payoff on a synthetic chain, `_illustration`)."""
    out: List[Dict[str, Any]] = []
    shown = _illustrations()
    for entry in CATALOG:
        fn = globals()[entry["name"]]
        params = [p for p in inspect.signature(fn).parameters if p not in _CONTEXT_ARGS]
        ill = shown[entry["name"]]
        extra = {"illustration": None if ill["illustration"] is None else
                 {**ill["illustration"], "params": dict(ill["illustration"]["params"]),
                  "points": [list(p) for p in ill["illustration"]["points"]],
                  "breakevens": list(ill["illustration"]["breakevens"])}}
        if "illustration_error" in ill:
            extra["illustration_error"] = ill["illustration_error"]
        out.append({**entry, "legs": [dict(leg) for leg in entry["legs"]], "risk": dict(entry["risk"]),
                    "tags": list(entry["tags"]), "params": params, "calculation_version": CALCULATION_VERSION, **extra})
    return out
