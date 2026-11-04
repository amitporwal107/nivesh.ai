"""Market Recovery › strategies with downside protection (docs/market_recovery/DESIGN.md §8; owner, 4 Nov 2026).

For one scored stock: the owner's five strategies (Protective Put, Bull Call Spread, Collar, Bull Put Credit Spread, Put Ratio
Backspread), one lot each, on the nearest suitable monthly/weekly expiry, with strikes taken from the page's own plan for the
stock (close, entry zone, stop loss, targets). A stock without stock options gets a Nifty put hedge sized by its beta instead.

Every figure is at expiry from end-of-day prices (NSE F&O bhavcopy close, else settlement price) and reuses the desk's own maths:
services/strategy_plan/payoff.py for payoff, exact max profit / loss, breakevens and the desk cost card; candidates.leg_view for
each option leg's liquidity (the Strategy Builder's blockers and flags); rules.RULES for the reward : risk minimum; the Quick
Hedge's pick_put_strike for the Nifty strike. All five strategies are always returned (owner's choice); a strategy that fails a
check says why. Nothing is stored and nothing is sent to a broker. Leg words are Buy / Sell (owner's choice for this page).
"""
from __future__ import annotations

import logging
import math
import time
from datetime import date
from typing import Any, Awaitable, Callable, Dict, List, Optional, Sequence, Tuple

from fastapi import HTTPException, Request

from services.quick_hedge.calc import pick_put_strike
from services.strategy_plan import payoff as po
from services.strategy_plan.candidates import iv_fences, leg_view
from services.strategy_plan.rules import RULES

from .engine import fnum

logger = logging.getLogger(__name__)

MIN_DAYS_PREFERRED = 14          # the middle of the page's 5–20 session horizon, in calendar days
MIN_DAYS = int(RULES["options"]["min_days_to_expiry"])          # 5, the builder's options minimum
MAX_DAYS = int(RULES["options"]["max_days_to_expiry"])          # 60
MIN_RR = float(RULES["defaults"]["min_reward_risk"])            # 1.5, the plan default
CREDIT_MIN_WIDTH_FRACTION = 1.0 / 3.0
PAYOFF_POINTS = 41
PAYOFF_SPAN = 0.30               # 0.7× … 1.3× the close
NIFTY = "NIFTY"
NIFTY_MAX_FALL = 0.05          # protection starts within 5% of Nifty (a 10% cap picked ~8% OTM puts that pay little)
NIFTY_MIN_PUT_OI = 500           # the Quick Hedge's MIN_PUT_OI
CACHE_S = 900.0

LABEL = {
    "protective_put": "Protective Put", "bull_call_spread": "Bull Call Spread", "collar": "Collar",
    "bull_put_spread": "Bull Put Credit Spread", "put_ratio_backspread": "Put Ratio Backspread",
}
BEST_WHEN = {
    "protective_put": "Bullish, but concerned about a market correction: the put caps the loss on the shares.",
    "bull_call_spread": "Expecting a moderate rise: both the most it can make and the most it can lose are fixed.",
    "collar": "Protecting shares at low cost: the written call pays for part of the put, giving up gains above the call strike.",
    "bull_put_spread": "Moderately bullish or neutral-bullish: earns the premium while the stock stays above the short put strike.",
    "put_ratio_backspread": "Bullish but expecting volatility: the two long puts pay off in a sharp fall; there is a loss zone "
                            "between the strikes.",
}
ORDER = ("protective_put", "bull_call_spread", "collar", "bull_put_spread", "put_ratio_backspread")
NOTES = [
    "One lot each, figures at expiry from end-of-day prices; a leg that did not trade that day is priced at its settlement "
    "price and fails the liquidity check.",
    "Costs are the desk cost card (brokerage, STT, exchange charges, SEBI fee, stamp duty, GST, slippage); exchange margin for "
    "written options (credit spreads, the collar's call, the backspread) is not estimated here.",
    "Strikes come from this page's plan for the stock (entry zone, stop loss, Target 1). Rule-based and not back-tested; for "
    "research, not advice.",
]


# ── strike picks (pure) ───────────────────────────────────────────────────────────────────────────────────────────────

def atm(ks: Sequence[float], x: float) -> Optional[float]:
    return min(ks, key=lambda k: (abs(k - x), k)) if ks else None


def nearest(ks: Sequence[float], x: Optional[float]) -> Optional[float]:
    return None if x is None or not ks else min(ks, key=lambda k: (abs(k - x), k))


def at_or_below(ks: Sequence[float], x: Optional[float]) -> Optional[float]:
    below = [k for k in ks if x is not None and k <= x + 1e-9]
    return max(below) if below else None


def next_below(ks: Sequence[float], k: float) -> Optional[float]:
    below = [x for x in ks if x < k - 1e-9]
    return max(below) if below else None


def next_above(ks: Sequence[float], k: float) -> Optional[float]:
    above = [x for x in ks if x > k + 1e-9]
    return min(above) if above else None


def pick_expiry(expiries: Sequence[Tuple[str, int]]) -> Optional[Tuple[str, int]]:
    """(expiry, days left): the nearest with MIN_DAYS_PREFERRED ≤ days ≤ MAX_DAYS, else the nearest with ≥ MIN_DAYS."""
    ok = sorted((d, e) for e, d in expiries if MIN_DAYS_PREFERRED <= d <= MAX_DAYS)
    if ok:
        return ok[0][1], ok[0][0]
    ok = sorted((d, e) for e, d in expiries if MIN_DAYS <= d <= MAX_DAYS)
    return (ok[0][1], ok[0][0]) if ok else None


def strikes_for(key: str, puts: Sequence[float], calls: Sequence[float],
                plan: Dict[str, Any]) -> Tuple[Optional[Dict[str, float]], Optional[str]]:
    """The strikes DESIGN §8 assigns to a strategy (from the listed put and call strikes), or (None, why)."""
    c, stop, t1, low = plan["close"], plan.get("stop_loss"), plan.get("target_1"), plan.get("entry_low")
    ks = calls if key == "bull_call_spread" else puts
    if key == "protective_put":
        k = at_or_below(ks, c)
        return ({"put": k}, None) if k else (None, "No put strike at or below the close is listed.")
    if key == "bull_call_spread":
        k1 = atm(ks, c)
        k2 = nearest(ks, t1)
        if k1 is not None and (k2 is None or k2 <= k1):
            k2 = next_above(ks, k1)
        return ({"long_call": k1, "short_call": k2}, None) if k1 and k2 else (None, "No call strike above the long call is listed.")
    if key == "collar":
        kp = nearest(puts, stop)
        if kp is not None and kp >= c:
            kp = next_below(puts, c)
        kc = nearest(calls, t1)
        if kc is not None and kc <= c:
            kc = next_above(calls, c)
        if not kp or not kc:
            return None, "The chain does not list a put below the close and a call above it."
        return {"long_put": kp, "short_call": kc}, None
    if key == "bull_put_spread":
        ks_ = at_or_below(ks, low if low is not None else c)
        kl = nearest(ks, stop)
        if ks_ is not None and (kl is None or kl >= ks_):
            kl = next_below(ks, ks_)
        return ({"short_put": ks_, "long_put": kl}, None) if ks_ and kl else (None, "No pair of put strikes below the entry zone is listed.")
    if key == "put_ratio_backspread":
        kh = atm(ks, c)
        kl = nearest(ks, stop)
        if kh is not None and (kl is None or kl >= kh):
            kl = next_below(ks, kh)
        return ({"short_put": kh, "long_put": kl}, None) if kh and kl else (None, "No put strike below the ATM strike is listed.")
    raise ValueError(key)


# ── legs and figures (pure) ───────────────────────────────────────────────────────────────────────────────────────────

def _row(rows: Dict[float, Dict[str, Any]], k: float) -> Optional[Dict[str, Any]]:
    return rows.get(k)


def option_leg(i: int, action: str, side: str, k: float, lots: int, lot: int, rows: Dict[float, Dict[str, Any]],
               strikes: List[Dict[str, Any]], fences) -> Dict[str, Any]:
    row = _row(rows, k)
    view = leg_view(row, side, strikes, fences)
    s = (row or {}).get(side) or {}
    close, settle = fnum(s.get("close")), fnum(s.get("settle"))
    price, basis = (close, "close") if close and close > 0 else ((settle, "settlement") if settle and settle > 0 else (None, None))
    return {"index": i, "kind": "option", "option_type": side, "sign": 1 if action == "Buy" else -1, "strike": k,
            "units": lots * lot, "entry_price": price,
            "_view": {"action": action, "instrument": "Call" if side == "call" else "Put", "strike": k, "lots": lots,
                      "units": lots * lot, "price": None if price is None else round(price, 2), "price_basis": basis,
                      "oi": view.get("oi"), "volume": view.get("volume"), "flags": list(view.get("flags") or []),
                      "blockers": list(view.get("blockers") or [])}}


def share_leg(i: int, close: float, lot: int) -> Dict[str, Any]:
    return {"index": i, "kind": "cash", "sign": 1, "units": lot, "entry_price": close, "strike": None,
            "_view": {"action": "Buy", "instrument": "Shares", "strike": None, "lots": 1, "units": lot, "price": round(close, 2),
                      "price_basis": "close", "oi": None, "volume": None, "flags": [], "blockers": []}}


def legs_for(key: str, k: Dict[str, float], plan: Dict[str, Any], lot: int, rows, strikes, fences) -> List[Dict[str, Any]]:
    c = plan["close"]
    if key == "protective_put":
        return [share_leg(0, c, lot), option_leg(1, "Buy", "put", k["put"], 1, lot, rows, strikes, fences)]
    if key == "bull_call_spread":
        return [option_leg(0, "Buy", "call", k["long_call"], 1, lot, rows, strikes, fences),
                option_leg(1, "Sell", "call", k["short_call"], 1, lot, rows, strikes, fences)]
    if key == "collar":
        return [share_leg(0, c, lot), option_leg(1, "Buy", "put", k["long_put"], 1, lot, rows, strikes, fences),
                option_leg(2, "Sell", "call", k["short_call"], 1, lot, rows, strikes, fences)]
    if key == "bull_put_spread":
        return [option_leg(0, "Sell", "put", k["short_put"], 1, lot, rows, strikes, fences),
                option_leg(1, "Buy", "put", k["long_put"], 1, lot, rows, strikes, fences)]
    if key == "put_ratio_backspread":
        return [option_leg(0, "Sell", "put", k["short_put"], 1, lot, rows, strikes, fences),
                option_leg(1, "Buy", "put", k["long_put"], 2, lot, rows, strikes, fences)]
    raise ValueError(key)


def _r(x: Optional[float], dp: int = 2) -> Optional[float]:
    return None if x is None else round(x + 0.0, dp)


def figures(key: str, legs: List[Dict[str, Any]], plan: Dict[str, Any], model: Dict[str, Any], lot: int) -> Dict[str, Any]:
    """Payoff figures at expiry, whole position (payoff.py)."""
    c = plan["close"]
    lo, hi = c * (1 - PAYOFF_SPAN), c * (1 + PAYOFF_SPAN)
    grid = [lo + (hi - lo) * i / (PAYOFF_POINTS - 1) for i in range(PAYOFF_POINTS)]
    ext = po.extremes(legs, lo, hi, grid)
    be = po.breakevens(legs, lo, hi, grid)
    car = po.capital_at_risk(legs, ext, model)
    net = po.net_premium(legs)
    share_units = sum(l["units"] for l in legs if l["kind"] == "cash")
    outlay = net - sum(l["entry_price"] * l["units"] for l in legs if l["kind"] == "cash")
    max_loss = ext["max_loss"]
    t1 = plan.get("target_1")
    if key == "put_ratio_backspread":
        rr = None                    # its "max profit" needs the stock to collapse; judged by its loss zone instead
    elif ext["max_profit"] is not None and max_loss is not None and max_loss < 0:
        rr = ext["max_profit"] / -max_loss
    elif ext["profit_unbounded"] and t1 is not None and max_loss is not None and max_loss < 0:
        rr = po.gross(legs, t1) / -max_loss
    else:
        rr = None
    scen = []
    for label, price in (("At the Stop loss", plan.get("stop_loss")), ("Unchanged at the close", c),
                         ("At Target 1", t1), ("At Target 2", plan.get("target_2"))):
        if price is None:
            continue
        row = {"label": label, "price": _r(price), "pnl": _r(po.gross(legs, price))}
        if share_units:
            row["pnl_unhedged"] = _r((price - c) * share_units)
        scen.append(row)
    costs = po.costs_block(legs, c, model, "desk cost card")
    return {
        "net_premium": _r(net), "net_premium_per_share": _r(net / lot) if lot else None,
        "outlay": _r(outlay),
        "max_profit": _r(ext["max_profit"]), "profit_unbounded": bool(ext["profit_unbounded"]),
        "max_loss": _r(max_loss), "loss_unbounded": bool(ext["loss_unbounded"]),
        "max_loss_with_costs": None if car is None else _r(-car),
        "breakevens": [_r(x) for x in be["all"]], "reward_risk": _r(rr),
        "costs_round_trip": costs.get("round_trip"),
        "scenarios": scen,
        "payoff": [[_r(s), _r(po.gross(legs, s))] for s in grid],
    }


def checks_for(key: str, legs: List[Dict[str, Any]], fig: Dict[str, Any], as_of: str) -> List[Dict[str, Any]]:
    out = []
    bad = [l["_view"] for l in legs if l["kind"] == "option" and l["_view"]["blockers"]]
    flagged = [l["_view"] for l in legs if l["kind"] == "option" and l["_view"]["flags"]]
    day = _day_text(as_of)
    if bad:
        txt = "; ".join(f"{v['instrument']} {v['strike']:g}: {', '.join(b.replace('_', ' ') for b in v['blockers'])}" for v in bad)
        out.append({"id": "liquid", "label": f"Every option leg traded on {day}", "pass": False,
                    "detail": f"{txt} — its price is not a market price."})
    else:
        note = ("; flagged " + "; ".join(f"{v['instrument']} {v['strike']:g}: {', '.join(f.replace('_', ' ') for f in v['flags'])}"
                                         for v in flagged)) if flagged else ""
        out.append({"id": "liquid", "label": f"Every option leg traded on {day}", "pass": True,
                    "detail": f"Each leg has a premium, open interest and trades{note}."})
    if key == "put_ratio_backspread":
        out.append({"id": "reward_risk", "label": "Reward : risk", "pass": None,
                    "detail": "Not applied: a volatility hedge, judged by its loss zone between the strikes."})
    else:
        rr = fig["reward_risk"]
        out.append({"id": "reward_risk", "label": f"Reward : risk at least {MIN_RR:g}",
                    "pass": None if rr is None else rr >= MIN_RR,
                    "detail": "Not measurable." if rr is None else f"{rr:.2f} : 1"
                              + (" (P&L at Target 1 ÷ max loss; the gain above it is open)" if fig["profit_unbounded"] else "")})
    if key == "bull_put_spread":
        ks = sorted(l["strike"] for l in legs if l["kind"] == "option")
        units = legs[0]["units"]
        width = (ks[-1] - ks[0]) * units
        credit = fig["net_premium"] or 0.0
        ok = width > 0 and credit >= CREDIT_MIN_WIDTH_FRACTION * width
        out.append({"id": "credit", "label": "Credit at least a third of the strike width", "pass": ok,
                    "detail": f"credit ₹{credit:,.0f} vs width ₹{width:,.0f}"})
    return out


def inr(x: float) -> str:
    """₹ amount in Indian digit grouping: 2188807 -> '21,88,807'."""
    n = int(round(abs(x)))
    t = str(n)
    if len(t) > 3:
        head, tail = t[:-3], t[-3:]
        parts = []
        while len(head) > 2:
            parts.insert(0, head[-2:])
            head = head[:-2]
        if head:
            parts.insert(0, head)
        t = ",".join(parts + [tail])
    return ("-" if x < 0 else "") + t


def cap_warnings(strategies: List[Dict[str, Any]], plan: Dict[str, Any], chain: Dict[str, Any]) -> List[str]:
    """A written call capped at the highest listed strike, below Target 1: the gain stops there (3 Nov: LAURUSLABS lists
    calls only up to 2,680 against a Target 1 of 2,775.72)."""
    t1 = plan.get("target_1")
    calls = [float(r["strike"]) for r in chain.get("strikes") or [] if r.get("call")]
    if t1 is None or not calls:
        return []
    top = max(calls)
    hit = [s["label"] for s in strategies
           if any(l["action"] == "Sell" and l["instrument"] == "Call" and l["strike"] == top for l in s.get("legs") or [])]
    if not hit or top >= t1:
        return []
    return [f"Target 1 ({t1:,.2f}) is above the highest listed call ({top:,.0f}): the {' and the '.join(hit)} write the "
            f"{top:,.0f} call, so their gains stop there."]


def _day_text(iso: str) -> str:
    try:
        return date.fromisoformat(str(iso)[:10]).strftime("%-d %b")
    except ValueError:
        return str(iso)


def build_options(plan: Dict[str, Any], chain: Dict[str, Any]) -> List[Dict[str, Any]]:
    """The five strategies for a stock with options. `plan` = {close, entry_low, stop_loss, target_1, target_2};
    `chain` = routes/fno.chain's answer (strikes rows, lot_size, summary)."""
    strikes = chain.get("strikes") or []
    rows = {float(r["strike"]): r for r in strikes}
    lot = int(chain.get("lot_size") or 0)
    as_of = (chain.get("summary") or {}).get("as_of") or ""
    fences = iv_fences(strikes)
    model, _ = po.cost_params({})
    out = []
    puts = sorted(k for k, r in rows.items() if r.get("put"))
    calls = sorted(k for k, r in rows.items() if r.get("call"))
    for key in ORDER:
        base = {"key": key, "label": LABEL[key], "best_when": BEST_WHEN[key]}
        if lot <= 0:
            out.append({**base, "status": "unavailable", "why": "The chain gives no lot size.", "legs": [], "checks": []})
            continue
        k, why = strikes_for(key, puts, calls, plan)
        if not k:
            out.append({**base, "status": "unavailable", "why": why, "legs": [],
                        "checks": [{"id": "strikes", "label": "The strikes the rule needs are listed", "pass": False, "detail": why}]})
            continue
        legs = legs_for(key, k, plan, lot, rows, strikes, fences)
        missing = [l["_view"] for l in legs if l["entry_price"] is None]
        if missing:
            why = "; ".join(f"{v['instrument']} {v['strike']:g} has no price on {_day_text(as_of)}" for v in missing)
            out.append({**base, "status": "unavailable", "why": why, "legs": [l["_view"] for l in legs],
                        "checks": [{"id": "liquid", "label": "Every option leg has a price", "pass": False, "detail": why}]})
            continue
        fig = figures(key, legs, plan, model, lot)
        checks = checks_for(key, legs, fig, as_of)
        fails = [c for c in checks if c["pass"] is False]
        out.append({**base, "status": "fails" if fails else "passes",
                    "why": "; ".join(f"{c['label']}: {c['detail']}" for c in fails) or None,
                    "legs": [{k2: v for k2, v in l["_view"].items() if k2 != "blockers"} for l in legs],
                    **fig, "checks": checks})
    return out


def build_index_hedge(plan: Dict[str, Any], beta: Optional[float], chain: Dict[str, Any], expiry: str, days: int,
                      symbol: str) -> Dict[str, Any]:
    """One Nifty put lot as the hedge for a stock without stock options (DESIGN §8)."""
    summary = chain.get("summary") or {}
    spot = fnum(summary.get("spot"))
    lot = int(chain.get("lot_size") or 0)
    rows = {float(r["strike"]): r for r in chain.get("strikes") or []}
    checks: List[Dict[str, Any]] = []
    caveat = (f"A Nifty put protects against a market-wide fall only. A fall in {symbol} alone is not covered; its Stop loss level is "
              f"the stock-level protection.")
    base = {"index": NIFTY, "expiry": expiry, "days_to_expiry": days, "lot_size": lot or None, "spot": _r(spot),
            "beta": _r(beta), "caveat": caveat}
    if beta is None or beta <= 0.1:
        return {**base, "status": "unavailable", "why": "The stock's 1-year beta to Nifty is not available or too low to size a hedge.",
                "checks": checks}
    if spot is None or lot <= 0:
        return {**base, "status": "unavailable", "why": "The Nifty chain gives no spot or lot size.", "checks": checks}
    c, stop = plan["close"], plan.get("stop_loss")
    stock_fall = (c - stop) / c if stop is not None and stop < c else 0.05
    fall = min(stock_fall / beta, NIFTY_MAX_FALL)
    why_fall = (f"the stock's {100 * stock_fall:.1f}% distance to its Stop loss ÷ beta {beta:.2f}"
                + (f" = {100 * stock_fall / beta:.1f}%, capped at {100 * NIFTY_MAX_FALL:.0f}%" if stock_fall / beta > NIFTY_MAX_FALL else ""))
    puts = {k: fnum(((r.get("put") or {}).get("close")) or ((r.get("put") or {}).get("settle"))) for k, r in rows.items() if r.get("put")}
    priced = sorted(k for k, p in puts.items() if p and p > 0)
    k = pick_put_strike(priced, spot, fall)
    if k is None:
        return {**base, "status": "unavailable", "why": f"No Nifty put is listed between {spot * (1 - fall):,.0f} and {spot:,.0f}.",
                "checks": checks}
    side = rows[k]["put"]
    close, settle = fnum(side.get("close")), fnum(side.get("settle"))
    prem, basis = (close, "close") if close and close > 0 else (settle, "settlement")
    oi, vol = side.get("oi"), side.get("volume")
    cost = prem * lot
    hedged = spot * lot / beta
    scen = []
    for m in (-5, -10, -15):
        s_t = spot * (1 + m / 100.0)
        put_pnl = (max(k - s_t, 0.0) - prem) * lot
        scen.append({"label": f"Nifty {m}%", "nifty_move_pct": m, "put_pnl": _r(put_pnl),
                     "stock_loss": _r(hedged * beta * m / 100.0)})
    liquid = bool(close and close > 0 and vol and oi and oi >= NIFTY_MIN_PUT_OI)
    checks.append({"id": "liquid", "label": f"The put traded with open interest of at least {NIFTY_MIN_PUT_OI}",
                   "pass": liquid, "detail": f"open interest {oi or 0:,}, volume {vol or 0:,}, priced at its {basis}"})
    return {**base, "status": "passes" if liquid else "fails",
            "why": None if liquid else "The Nifty put did not trade enough to be a market price.",
            "put_strike": k, "premium": _r(prem), "price_basis": basis, "oi": oi, "volume": vol,
            "cost_per_lot": _r(cost), "hedged_value": _r(hedged, 0), "cost_pct": _r(100.0 * cost / hedged),
            "fall_used_pct": _r(100.0 * fall, 1), "scenarios": scen, "checks": checks,
            "sizing": (f"One Nifty lot ({lot} × {spot:,.0f}) hedges about ₹{inr(hedged)} of {symbol} at a beta of {beta:.2f}; "
                       f"the put strike is the lowest within {100 * fall:.1f}% of Nifty ({why_fall}).")}


# ── I/O: chains through routes/fno.py, one cached answer per stock ───────────────────────────────────────────────────

class ChainUnavailable(Exception):
    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


ChainReader = Callable[[Request, str, Optional[date]], Awaitable[Dict[str, Any]]]
ExpiryReader = Callable[[Request, str], Awaitable[Dict[str, Any]]]


async def _fno_expiries(request: Request, sym: str) -> Dict[str, Any]:
    from routes import fno
    return await fno.expiries(request, symbol=sym)


async def _fno_chain(request: Request, sym: str, expiry: Optional[date]) -> Dict[str, Any]:
    from routes import fno
    return await fno.chain(request, symbol=sym, expiry=expiry, around=fno.DEFAULT_AROUND)


def _days_left(expiry: str, as_of: str) -> int:
    return (date.fromisoformat(expiry[:10]) - date.fromisoformat(as_of[:10])).days


async def read_chain(request: Request, sym: str, *, expiries: ExpiryReader = _fno_expiries,
                     chain: ChainReader = _fno_chain) -> Tuple[Dict[str, Any], str, int]:
    try:
        ex = await expiries(request, sym)
        as_of = str(ex.get("as_of") or "")[:10]
        pick = pick_expiry([(str(r.get("expiry"))[:10], _days_left(str(r.get("expiry")), as_of))
                            for r in ex.get("expiries") or [] if r.get("expiry")])
        if not pick:
            raise ChainUnavailable(f"No {sym} option expiry between {MIN_DAYS} and {MAX_DAYS} days out is listed on {as_of}.")
        body = await chain(request, sym, date.fromisoformat(pick[0]))
    except HTTPException as e:
        detail = e.detail if isinstance(e.detail, str) else (e.detail or {}).get("message") if isinstance(e.detail, dict) else None
        raise ChainUnavailable(detail or f"The {sym} option chain could not be read (HTTP {e.status_code}).") from e
    return body, pick[0], pick[1]


class StrategyService:
    def __init__(self, *, expiries: ExpiryReader = _fno_expiries, chain: ChainReader = _fno_chain,
                 clock: Callable[[], float] = time.monotonic):
        self._expiries, self._chain, self._clock = expiries, chain, clock
        self._cache: Dict[str, Tuple[float, Dict[str, Any]]] = {}

    async def for_stock(self, request: Request, symbol: str, ctx: Dict[str, Any], has_options: bool,
                        eod: str) -> Dict[str, Any]:
        key = f"{symbol}:{eod}"
        hit = self._cache.get(key)
        if hit and self._clock() - hit[0] < CACHE_S:
            return hit[1]
        plan_src = ctx.get("plan") or {}
        if not plan_src:
            raise ChainUnavailable(f"{symbol} has no plan on this page (no ATR), so the strategies cannot be placed.")
        plan = {"close": ctx["close"], "entry_low": plan_src.get("entry_low"), "stop_loss": plan_src.get("stop_loss"),
                "target_1": plan_src.get("target_1"), "target_2": plan_src.get("target_2")}
        if has_options:
            body, expiry, days = await read_chain(request, symbol, expiries=self._expiries, chain=self._chain)
            summary = body.get("summary") or {}
            out = {"symbol": symbol, "kind": "options", "as_of": summary.get("as_of"), "expiry": expiry, "days_to_expiry": days,
                   "lot_size": body.get("lot_size"), "spot": fnum(summary.get("spot")), "plan": plan,
                   "strategies": build_options(plan, body), "index_hedge": None}
            src = f"NSE F&O bhavcopy via /api/fno/{symbol}/chain"
        else:
            body, expiry, days = await read_chain(request, NIFTY, expiries=self._expiries, chain=self._chain)
            summary = body.get("summary") or {}
            out = {"symbol": symbol, "kind": "index_hedge", "as_of": summary.get("as_of"), "expiry": expiry,
                   "days_to_expiry": days, "lot_size": body.get("lot_size"), "spot": fnum(summary.get("spot")), "plan": plan,
                   "strategies": [],
                   "index_hedge": build_index_hedge(plan, ctx.get("beta"), body, expiry, days, symbol)}
            src = "NSE F&O bhavcopy via /api/fno/NIFTY/chain"
        out["notes"] = NOTES if has_options else [NOTES[0], NOTES[2]]
        out["sources"] = [{"what": "Option prices, open interest, volume, lot size", "source": src, "as_of": out["as_of"]},
                          {"what": "Close, Entry zone, Stop loss, Target 1 and Target 2", "source": "this page's plan (recovery-plan-v1)",
                           "as_of": eod}]
        if not has_options:
            out["sources"].append({"what": "Beta", "source": "NIDP feature store beta_1y (1-year daily returns vs Nifty)",
                                   "as_of": eod})
        out["warnings"] = cap_warnings(out["strategies"], plan, body) if has_options else []
        if out["as_of"] and out["as_of"] != eod:
            out["warnings"].append(f"Option prices are from {out['as_of']}; the plan levels are from the close of {eod}.")
        self._cache[key] = (self._clock(), out)
        return out


_service: Optional[StrategyService] = None


def get_service() -> StrategyService:
    global _service
    if _service is None:
        _service = StrategyService()
    return _service
