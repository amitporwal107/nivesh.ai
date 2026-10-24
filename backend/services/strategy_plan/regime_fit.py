"""Top ideas ranked by REGIME FIT, priced from the live end-of-day option chain.

The requirement (user, 2026-10-22): "the top 5 best trading strategy for nifty/banknifty options
and stock f/o and cash stocks", inside the desk Strategy Builder.

WHAT "BEST" MEANS HERE, AND WHAT IT DOES NOT
--------------------------------------------
"Best" is **fit to today's measured conditions**, priced from the real chain. It is not a
performance ranking, because this platform records no strategy performance to rank by:
`public.strategy_trades` holds 151 closed trades from three manually-triggered CASH backtests and
nothing for options; `strategy_signals`, `positional_outcomes` and `positional_backtest_labels`
hold no rows. It is also not an "IV rich/cheap" ranking in the usual sense: no option-IV history is
stored anywhere in this repository, so an IV percentile or IV rank cannot be computed. The
volatility axis therefore uses India VIX against the threshold the desk regime already defines
(`desk-regime-v1`, `vix_high`), which is a real, dated, versioned number rather than an invented one.

Nothing here is a forecast, a probability or an instruction to trade. `RANKING_NOTE` says so and
travels on every response.

WHY THIS MODULE EXISTS SEPARATELY FROM plan.py
-----------------------------------------------
`plan.py` builds one deeply-evidenced plan for ONE equity underlying: it collects eighteen snapshot
sources, most of which only exist for a listed security (indicators from `nidp.prices_eod_adjusted`,
candle patterns, scan rows, financials, shareholding, deals). An index has none of them —
`/api/research/chart/live/NIFTY/indicators` answers `404 no_bars_for_symbol`, and
`nidp.index_eod` carries `as_of_date` + `close_price` only, so an index has no ATR and no candles.
Bending that engine to indices would mean teaching eighteen equity sources to degrade. This module
instead reads the two things an index genuinely has — the option chain and the market regime — and
reuses `candidates.py`'s chain primitives and `payoff.py`'s pricing unchanged.
"""
from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional, Sequence, Tuple

from .candidates import _neighbour, _option_leg, condor_ok, iv_fences, leg_view, spread_strike

logger = logging.getLogger(__name__)

REGIME_FIT_VERSION = "regime-fit-v1 (2026-10-22)"

RANKING_NOTE = (
    "Ranked by fit to the market regime measured on the dates shown and by the live end-of-day "
    "option chain, then by reward : risk. This is not a forecast, not a probability, and not a "
    "ranking by past performance: no strategy performance is recorded for options in this system. "
    "Nothing here is an instruction to trade and nothing is sent to a broker."
)

CASH_RANKING_NOTE = (
    "The cash class is NOT ranked by regime fit: it is the desk's existing 'From AI opportunities' "
    "answer, kept unchanged, so it carries the scanner's own evidence rank and its ideas have no "
    "fit score. The two are shown side by side rather than merged into one ranking."
)

GAPS = [
    "No IV percentile or IV rank: no option-implied-volatility history is stored, so 'rich' and "
    "'cheap' volatility use India VIX against the desk-regime threshold (desk-regime-v1 vix_high), "
    "not a percentile of this underlying's own IV.",
    "No performance ranking: the only realised records are three manual cash backtests "
    "(public.strategy_trades); there is no options performance history, so no idea here can be "
    "ranked by what it earned.",
    "End of day only: the chain is the NSE F&O bhavcopy close. There is no intraday option data.",
    "An index has no cash leg: NIFTY and BANKNIFTY cannot be held, so covered calls, protective "
    "puts and collars are offered for stocks only.",
]

# ---------------------------------------------------------------------------
# The structures, and what each one is for.
#   view       the direction the structure needs to work
#   flow       debit = premium paid (favoured when volatility is low), credit = premium received
#   cash_leg   True when the structure holds the underlying, which an index cannot
# ---------------------------------------------------------------------------
FAMILY: Dict[str, Dict[str, Any]] = {
    "long_call":        {"label": "Long call",         "view": "up",      "flow": "debit",  "cash_leg": False},
    "long_put":         {"label": "Long put",          "view": "down",    "flow": "debit",  "cash_leg": False},
    "bull_call_spread": {"label": "Bull call spread",  "view": "up",      "flow": "debit",  "cash_leg": False},
    "bear_put_spread":  {"label": "Bear put spread",   "view": "down",    "flow": "debit",  "cash_leg": False},
    "bull_put_spread":  {"label": "Bull put spread",   "view": "up",      "flow": "credit", "cash_leg": False},
    "bear_call_spread": {"label": "Bear call spread",  "view": "down",    "flow": "credit", "cash_leg": False},
    "iron_condor":      {"label": "Iron condor",       "view": "flat",    "flow": "credit", "cash_leg": False},
}

# Families an index can hold (no cash leg) — used to gate the index classes.
OPTION_ONLY = [k for k, v in FAMILY.items() if not v["cash_leg"]]

# Scoring weights. Same shape as picks.py: every factor earns weight x credit, credit is
# 1 (supports) / 0.5 (neutral) / 0 (conflicts), and the score is the weighted percentage.
WEIGHTS = {"direction": 40.0, "volatility": 30.0, "breadth": 15.0, "positioning": 15.0}


def _credit(state: str) -> float:
    return {"supports": 1.0, "neutral": 0.5, "conflicts": 0.0}.get(state, 0.5)


def factor(key: str, state: str, text: str) -> Dict[str, Any]:
    return {"factor": key, "state": state, "text": text}


# ---------------------------------------------------------------------------
# Regime
# ---------------------------------------------------------------------------
async def read_regime() -> Dict[str, Any]:
    """The desk regime as macro_engine classifies it. Returns {available, ...} and never raises:
    without it the endpoint still answers, with the regime marked unavailable and no ideas invented."""
    try:
        from routes import macro
        from services import macro_engine

        st = await macro_engine.latest_state()
        if not st:
            return {"available": False, "reason": "macro_state is empty",
                    "source": "macro_engine.classify_desk_regime"}
        reg = await macro._desk_regime(st)
    except Exception as e:  # noqa: BLE001 — an unreadable regime is reported, never guessed
        logger.warning("regime_fit: desk regime unavailable: %s", e)
        return {"available": False, "reason": f"{type(e).__name__}: {str(e)[:160]}",
                "source": "macro_engine.classify_desk_regime"}

    inp = reg.get("inputs") or {}
    rule = reg.get("rule") or {}
    vix, vix_high = inp.get("india_vix"), rule.get("vix_high")
    return {
        "available": True,
        "key": reg.get("key"),
        "label": reg.get("label"),
        "as_of": reg.get("date"),
        "trend": inp.get("trend"),
        "nifty_close": inp.get("nifty_close"),
        "nifty_average": inp.get("nifty_average"),
        "nifty_vs_average_pct": inp.get("nifty_vs_average_pct"),
        "india_vix": vix,
        "vix_high_threshold": vix_high,
        "volatility": ("high" if inp.get("volatility_high") else "low") if vix is not None else None,
        "breadth": inp.get("breadth"),
        "advancing_share_pct": inp.get("advancing_share_pct"),
        "rule_version": rule.get("version"),
        "source": "macro_engine.classify_desk_regime (routes/macro._desk_regime)",
    }


def direction_of(regime: Dict[str, Any]) -> str:
    """up / down / flat, from the regime's own trend. 'flat' when the trend is unreadable."""
    t = (regime.get("trend") or "").lower()
    return {"up": "up", "down": "down"}.get(t, "flat")


# ---------------------------------------------------------------------------
# Fit scoring
# ---------------------------------------------------------------------------
def score_fit(family: str, regime: Dict[str, Any], chain_summary: Dict[str, Any],
              short_strike_at_wall: Optional[bool]) -> Dict[str, Any]:
    """Deterministic 0-100 fit, with the real reason for every factor. No probability is implied."""
    meta = FAMILY[family]
    direction, vol = direction_of(regime), regime.get("volatility")
    because: List[Dict[str, Any]] = []

    # Direction: does the structure's view match the measured trend?
    if meta["view"] == "flat":
        d_state = "supports" if direction == "flat" else "conflicts"
        d_text = (f"The structure needs a range and the trend is {direction}."
                  if d_state == "conflicts" else "The structure needs a range and no trend is measured.")
    elif direction == "flat":
        d_state, d_text = "neutral", f"No trend is measured, so a {meta['view']} view is neither supported nor contradicted."
    else:
        d_state = "supports" if meta["view"] == direction else "conflicts"
        pct = regime.get("nifty_vs_average_pct")
        move = f" (Nifty {pct:+.2f}% against its {50}-session average)" if isinstance(pct, (int, float)) else ""
        d_text = (f"The measured trend is {direction} and the structure needs {meta['view']}{move}."
                  if d_state == "supports"
                  else f"The measured trend is {direction} but the structure needs {meta['view']}{move}.")
    because.append(factor("direction", d_state, d_text))

    # Volatility: premium paid is favoured when volatility is low, premium received when it is high.
    if vol is None:
        v_state, v_text = "neutral", "India VIX is unavailable, so the premium side cannot be judged."
    else:
        want = "debit" if vol == "low" else "credit"
        v_state = "supports" if meta["flow"] == want else "conflicts"
        vix, thr = regime.get("india_vix"), regime.get("vix_high_threshold")
        where = f"India VIX {vix} is {'below' if vol == 'low' else 'at or above'} the {thr} threshold"
        v_text = (f"{where}, so {'buying' if meta['flow'] == 'debit' else 'selling'} premium is the favoured side."
                  if v_state == "supports"
                  else f"{where}, which favours {'selling' if want == 'credit' else 'buying'} premium, "
                       f"not {'buying' if meta['flow'] == 'debit' else 'selling'} it.")
    because.append(factor("volatility", v_state, v_text))

    # Breadth: agreement between the market's breadth and the structure's view.
    b = (regime.get("breadth") or "").lower()
    if b not in ("up", "down"):
        b_state, b_text = "neutral", "Market breadth is unavailable."
    elif meta["view"] == "flat":
        b_state, b_text = "neutral", f"Breadth is {b}; a range structure takes no side."
    else:
        b_state = "supports" if b == meta["view"] else "conflicts"
        share = regime.get("advancing_share_pct")
        s = f" ({share}% of the universe advancing)" if share is not None else ""
        b_text = f"Breadth is {b}{s} and the structure needs {meta['view']}."
    because.append(factor("breadth", b_state, b_text))

    # Positioning: a short strike sitting on the open-interest wall is the structure's own evidence.
    if short_strike_at_wall is None:
        p_state, p_text = "neutral", "The structure has no short strike to place against a wall."
    elif short_strike_at_wall:
        p_state, p_text = "supports", "The short strike sits on the open-interest wall from the same chain."
        pcr = chain_summary.get("pcr")
        if pcr is not None:
            p_text += f" Chain put/call OI ratio {pcr}."
    else:
        p_state, p_text = "neutral", "The short strike is placed by the expected move, not on an open-interest wall."
    because.append(factor("positioning", p_state, p_text))

    total = sum(WEIGHTS[f["factor"]] * _credit(f["state"]) for f in because)
    return {"score": round(total, 1), "because": because}


# ---------------------------------------------------------------------------
# Strike plans and legs
# ---------------------------------------------------------------------------
def _rows(chain: Dict[str, Any]) -> Tuple[Dict[float, Dict[str, Any]], List[float]]:
    rowmap = {r["strike"]: r for r in chain["strikes"]}
    return rowmap, sorted(rowmap)


def strike_plans(family: str, chain: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Concrete strike sets to price for one family. More than one is offered where the placement is a
    real choice (at the money, or one strike out), so five ideas are five priced variants, not five labels."""
    S = chain["summary"]
    atm = S.get("atm_strike")
    _, ks = _rows(chain)
    if atm is None or atm not in ks:
        return []
    out: List[Dict[str, Any]] = []

    if family in ("long_call", "long_put"):
        otm = _neighbour(ks, atm, 1 if family == "long_call" else -1)
        out.append({"k": atm, "placement": "at the money"})
        if otm is not None:
            out.append({"k": otm, "placement": "one strike out of the money"})
        return out

    if family in ("bull_call_spread", "bear_put_spread"):
        up = family == "bull_call_spread"
        sh = spread_strike(chain, up)
        if sh is None or sh["strike"] not in ks:
            return []
        out.append({"long": atm, "short": sh["strike"], "short_from": sh["from"],
                    "placement": f"short strike from the {sh['from']}"})
        return out

    if family in ("bull_put_spread", "bear_call_spread"):
        # Credit spread: the SHORT strike is the one that must hold, so it is placed the same way a
        # debit spread's short strike is (wall when the wall is inside the expected move, else the move).
        up = family == "bull_put_spread"          # a bull put spread wants the price to stay ABOVE the short put
        sh = spread_strike(chain, not up)          # short put below spot / short call above spot
        if sh is None or sh["strike"] not in ks:
            return []
        wing = _neighbour(ks, sh["strike"], -1 if up else 1)
        if wing is None:
            return []
        out.append({"short": sh["strike"], "long": wing, "short_from": sh["from"],
                    "placement": f"short strike from the {sh['from']}"})
        return out

    if family == "iron_condor":
        ok, _why, put_wall, call_wall = condor_ok(chain)
        if not ok or put_wall not in ks or call_wall not in ks:
            return []
        lp, lc = _neighbour(ks, put_wall, -1), _neighbour(ks, call_wall, 1)
        if lp is None or lc is None:
            return []
        out.append({"short_put": put_wall, "short_call": call_wall, "long_put": lp, "long_call": lc,
                    "short_from": "wall", "placement": "short strikes on the open-interest walls"})
        return out

    return out


def leg_spec(family: str, plan: Dict[str, Any]) -> Optional[List[Tuple[float, str, str]]]:
    """[(strike, option_type, side)] for the family. Mirrors candidates.structure_legs and adds the two
    credit spreads, which that function does not build."""
    if family == "long_call":
        return [(plan["k"], "call", "buy")]
    if family == "long_put":
        return [(plan["k"], "put", "buy")]
    if family == "bull_call_spread":
        return [(plan["long"], "call", "buy"), (plan["short"], "call", "sell")]
    if family == "bear_put_spread":
        return [(plan["long"], "put", "buy"), (plan["short"], "put", "sell")]
    if family == "bull_put_spread":
        return [(plan["short"], "put", "sell"), (plan["long"], "put", "buy")]
    if family == "bear_call_spread":
        return [(plan["short"], "call", "sell"), (plan["long"], "call", "buy")]
    if family == "iron_condor":
        return [(plan["long_put"], "put", "buy"), (plan["short_put"], "put", "sell"),
                (plan["short_call"], "call", "sell"), (plan["long_call"], "call", "buy")]
    return None


def price_variant(chain: Dict[str, Any], family: str, plan: Dict[str, Any],
                  lot: Optional[int]) -> Dict[str, Any]:
    """Price one strike set from the chain. Returns {ok, legs, blockers} — a variant whose strikes are
    illiquid or unlisted comes back with blockers and is dropped by the caller, never silently repaired."""
    rowmap, ks = _rows(chain)
    rows = chain["strikes"]
    fences = iv_fences(rows)
    spec = leg_spec(family, plan)
    if spec is None or any(k is None or k not in rowmap for k, _, _ in spec):
        return {"ok": False, "blockers": ["strike_not_listed"], "legs": [], "views": []}
    if not lot:
        return {"ok": False, "blockers": ["lot_size_unknown"], "legs": [], "views": []}

    views, blockers = [], []
    for k, otype, side in spec:
        v = leg_view(rowmap[k], otype, rows, fences)
        v.update(strike=k, option_type=otype, side=side)
        views.append(v)
        blockers += [f"{b}@{k:g}{otype[0].upper()}E" for b in v["blockers"]]
    if blockers:
        return {"ok": False, "blockers": blockers, "legs": [], "views": views}

    legs = [_option_leg(chain["asof"], chain["summary"]["expiry"], int(lot), rowmap,
                        v["strike"], v["option_type"], v["side"], 1, v) for v in views]

    # A debit spread must cost something and less than its width; a credit spread must pay something
    # and less than its width. Either failure means the two closes disagree, so the variant is dropped.
    if family in ("bull_call_spread", "bear_put_spread"):
        width = abs(plan["short"] - plan["long"])
        debit = views[0]["close"] - views[1]["close"]
        if not 0 < debit < width:
            return {"ok": False, "blockers": ["spread_price_inconsistent"], "legs": [], "views": views}
    if family in ("bull_put_spread", "bear_call_spread"):
        width = abs(plan["short"] - plan["long"])
        credit = views[0]["close"] - views[1]["close"]
        if not 0 < credit < width:
            return {"ok": False, "blockers": ["spread_price_inconsistent"], "legs": [], "views": views}

    return {"ok": True, "blockers": [], "legs": legs, "views": views}


# ---------------------------------------------------------------------------
# Payoff metrics
# ---------------------------------------------------------------------------
def metrics_for(underlying: str, legs: Sequence[Dict[str, Any]], spot: float,
                as_of: str, costs: Optional[Dict[str, Any]] = None,
                scenario_price: Optional[float] = None) -> Dict[str, Any]:
    """Max profit, max loss, breakevens and capital at risk, from engine.compute_payoff — the same
    calculation POST /api/desk/strategy/payoff runs, so a structure priced here and in the shipped
    plan engine cannot disagree. Returns {ok: False, ...} when the request does not validate.

    Margin is deliberately absent: engine.MARGIN_REASON records that the payoff calculation does not
    estimate margin (only Zerodha's margin calculator gives it, through the platform's Kite login).
    For the defined-risk structures offered here, max loss IS the capital at risk."""
    from .engine import compute_payoff

    body: Dict[str, Any] = {"underlying": underlying, "reference_price": spot, "as_of": as_of,
                            "legs": list(legs)}
    if costs:
        body["costs"] = costs
    if scenario_price is not None:
        body["scenarios"] = [{"name": "expected_move", "underlying_price": scenario_price}]
    res = compute_payoff(body)
    if not res.get("valid"):
        return {"ok": False, "problems": res.get("problems") or []}

    ex = res["expiry"]
    max_profit, max_loss = ex.get("max_profit"), ex.get("max_loss")

    # Theoretical reward : risk, which for a bought option measures the payoff at an underlying price
    # of ZERO. It is reported because it is the true bound, but it is NOT what the ranking uses: a long
    # put would otherwise score a reward : risk in the hundreds and beat every spread on the tiebreak.
    rr_theoretical = None
    if max_profit is not None and max_loss is not None:
        risk = abs(max_loss)
        if risk > 0 and max_profit > 0:
            rr_theoretical = round(max_profit / risk, 2)

    # The ranking number: net P&L at the chain's OWN expected move, over the capital at risk. Both
    # sides come from real figures — the expected move is derived from the ATM option's implied
    # volatility by routes/fno.py, and the P&L is net of the engine's cost model.
    rr_expected, net_at_move = None, None
    scen = (ex.get("scenarios") or [])
    if scen:
        net_at_move = scen[0].get("net")
        risk = abs(max_loss) if max_loss is not None else res.get("capital_at_risk")
        if net_at_move is not None and risk and risk > 0 and net_at_move > 0:
            rr_expected = round(net_at_move / risk, 2)

    return {
        "ok": True,
        "max_profit": max_profit,
        "max_loss": max_loss,
        "net_at_expected_move": net_at_move,
        "reward_risk_at_expected_move": rr_expected,
        "reward_risk_theoretical": rr_theoretical,
        "reward_risk_basis": ("net P&L at the chain's expected move over the capital at risk; the "
                              "theoretical figure measures the payoff at an underlying price of zero "
                              "and is shown for reference only"),
        "profit_unbounded": ex.get("profit_unbounded"),
        "loss_unbounded": ex.get("loss_unbounded"),
        "breakevens": ex.get("breakevens") or [],
        "net_premium": ex.get("net_premium"),
        "capital_at_risk": res.get("capital_at_risk"),
        "capital_at_risk_basis": res.get("capital_at_risk_basis"),
        "margin": None,
        "margin_reason": res.get("margin_reason"),
        "caveats": res.get("caveats") or [],
        "calculation_version": res.get("calculation_version"),
    }


def _net_greeks(views: Sequence[Dict[str, Any]], chain: Dict[str, Any], lot: int) -> Dict[str, Any]:
    """Signed sum of the legs' own Greeks, read from the chain rows (leg_view carries only delta, so the
    Greeks are taken from the same row the leg was priced off). Missing on any leg means the total is
    not reported: a partial sum would read as a position Greek it is not."""
    rowmap, _ = _rows(chain)
    out: Dict[str, Any] = {}
    for g in ("delta", "gamma", "theta", "vega"):
        vals: Optional[List[float]] = []
        for v in views:
            side_row = (rowmap.get(v["strike"]) or {}).get(v["option_type"]) or {}
            raw = side_row.get(g)
            if raw is None:
                vals = None
                break
            vals.append((1.0 if v["side"] == "buy" else -1.0) * float(raw) * lot)
        out[g] = round(sum(vals), 4) if vals else None
    return out


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------
_ISO_DAY = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _newest_day(value: Any) -> Optional[str]:
    """A single comparable ISO day from a value that may be a day, an object of per-source days, or
    neither. Returns None rather than something uncomparable or something that merely looks like a
    string.

    Two live defects shaped this. The ideas engine's `data_as_of` is an OBJECT of per-source dates,
    and comparing it to the regime's date raised TypeError: '>' not supported between 'dict' and
    'str'. That object also carries `mode: "end_of_day"`, which is not a date at all -- taking the
    max of its values lexicographically preferred "end_of_day" over "2026-10-21" and printed
    "The option chain is from end_of_day". Only YYYY-MM-DD values are considered."""
    if isinstance(value, str):
        return value if _ISO_DAY.match(value) else None
    if isinstance(value, dict):
        days = [v for v in value.values() if isinstance(v, str) and _ISO_DAY.match(v)]
        return max(days) if days else None
    return None


def _why(e: BaseException) -> str:
    return f"{type(e).__name__}: {str(e)[:160]}"


async def _chain_for(request: Any, symbol: str, expiry: Optional[str]) -> Dict[str, Any]:
    """The chain for one underlying, shaped the way candidates.py shapes it (`asof` alongside `summary`).
    Raises LookupError when the underlying lists no option expiries — which is also how a non-F&O
    symbol is detected, without a second reference lookup."""
    from datetime import date as _date

    from routes import fno

    ex = await fno.expiries(request, symbol=symbol)
    rows = ex.get("expiries") or []
    if not rows:
        raise LookupError(f"{symbol} lists no option expiries on the latest trading day")
    chosen = expiry or rows[0]["expiry"]
    ch = dict(await fno.chain(request, symbol=symbol, expiry=_date.fromisoformat(chosen),
                              around=fno.DEFAULT_AROUND))
    ch["asof"] = (ch.get("summary") or {}).get("as_of")
    ch["expiries_listed"] = [r["expiry"] for r in rows]
    return ch


def _expected_move_price(view: str, summary: Dict[str, Any]) -> Optional[float]:
    """The price the structure is judged at: one expected move in the direction it needs, or the spot
    itself for a range structure. The expected move is the chain's own, derived by routes/fno.py from
    the at-the-money option's implied volatility — not a number invented here. Returns None when the
    chain does not publish one, and the ranking then falls back to fit alone."""
    spot, move = summary.get("spot"), summary.get("expected_move")
    if spot is None:
        return None
    if view == "flat":
        return float(spot)
    if move is None:
        return None
    return float(spot) + (float(move) if view == "up" else -float(move))


def _short_at_wall(plan: Dict[str, Any]) -> Optional[bool]:
    """True/False when the structure has a short strike, None when it has none to place."""
    if "short_from" not in plan:
        return None
    return plan["short_from"] == "wall"


async def ideas_for_underlying(request: Any, symbol: str, regime: Dict[str, Any], *,
                               expiry: Optional[str] = None, limit: int = 5) -> Dict[str, Any]:
    """Every defined-risk option structure that prices on this underlying's chain, scored for regime fit
    and returned best-first. A structure whose strikes are unlisted or illiquid is dropped with its
    blocker recorded, never repaired into something that prices."""
    try:
        chain = await _chain_for(request, symbol, expiry)
    except Exception as e:  # noqa: BLE001 — an unreadable chain is reported per underlying
        logger.info("regime_fit: no chain for %s: %s", symbol, _why(e))
        return {"underlying": symbol, "available": False, "reason": _why(e), "ideas": [], "dropped": []}

    S, lot, asof = chain["summary"], chain.get("lot_size"), chain.get("asof")
    spot = S.get("spot")
    if spot is None or not lot:
        return {"underlying": symbol, "available": False,
                "reason": "the chain has no spot price" if spot is None else "the chain has no lot size",
                "ideas": [], "dropped": []}

    built: List[Dict[str, Any]] = []
    dropped: List[Dict[str, Any]] = []
    for family in OPTION_ONLY:
        for plan in strike_plans(family, chain):
            priced = price_variant(chain, family, plan, lot)
            if not priced["ok"]:
                dropped.append({"structure": family, "placement": plan.get("placement"),
                                "blockers": priced["blockers"]})
                continue
            m = metrics_for(symbol, priced["legs"], spot, asof,
                            scenario_price=_expected_move_price(FAMILY[family]["view"], S))
            if not m.get("ok"):
                dropped.append({"structure": family, "placement": plan.get("placement"),
                                "blockers": ["payoff_invalid"], "problems": m.get("problems")})
                continue
            fit = score_fit(family, regime, S, _short_at_wall(plan))
            meta = FAMILY[family]
            strikes = sorted({float(l["strike"]) for l in priced["legs"]})
            built.append({
                "underlying": symbol,
                # The spot the legs were priced against. Carried on the idea so a caller can build a
                # payoff request or a paper trade from the idea alone, without joining back to the
                # class's `underlyings` list.
                "reference_price": spot,
                "structure": family,
                "name": f"{meta['label']} {'/'.join(f'{k:g}' for k in strikes)}",
                "view": meta["view"],
                "premium_flow": meta["flow"],
                "expiry": S.get("expiry"),
                "days_to_expiry": S.get("days_to_expiry"),
                "placement": plan.get("placement"),
                "legs": priced["legs"],
                "net_greeks": _net_greeks(priced["views"], chain, int(lot)),
                "max_profit": m["max_profit"], "max_loss": m["max_loss"],
                "profit_unbounded": m["profit_unbounded"], "loss_unbounded": m["loss_unbounded"],
                "breakevens": m["breakevens"], "net_premium": m["net_premium"],
                "capital_at_risk": m["capital_at_risk"],
                "capital_at_risk_basis": m["capital_at_risk_basis"],
                "reward_risk": m["reward_risk_at_expected_move"],
                "reward_risk_theoretical": m["reward_risk_theoretical"],
                "reward_risk_basis": m["reward_risk_basis"],
                "net_at_expected_move": m["net_at_expected_move"],
                "margin": None, "margin_reason": m["margin_reason"],
                "caveats": m["caveats"],
                "fit": fit,
                "data_as_of": {"chain": asof, "regime": regime.get("as_of")},
                "price_source": f"NSE F&O bhavcopy close, {asof}",
            })

    # Best fit first; reward : risk breaks a tie. An idea with no reward:risk (unbounded profit) sorts
    # last within its fit band rather than being treated as infinitely good.
    built.sort(key=lambda i: (-(i["fit"]["score"]), -(i["reward_risk"] or 0.0)))
    top = built[:limit]
    for i, it in enumerate(top, 1):
        it["rank"] = i
    return {
        "underlying": symbol, "available": True, "as_of": asof,
        "expiry": S.get("expiry"), "expiries_listed": chain.get("expiries_listed"),
        "spot": spot, "lot_size": lot,
        "chain_context": {"atm_strike": S.get("atm_strike"), "atm_iv": S.get("atm_iv"),
                          "pcr": S.get("pcr"), "max_pain": S.get("max_pain"),
                          "expected_move": S.get("expected_move"),
                          "expected_move_pct": S.get("expected_move_pct")},
        "ideas": top, "considered": len(built), "dropped": dropped,
    }


INDEX_UNDERLYINGS = ["NIFTY", "BANKNIFTY"]

# How many scanner names to try for the stock F&O class. The ideas are pooled across the symbols and
# the best `limit` are kept, so this bounds the chain reads, not the answer.
STOCK_FNO_SCAN = 8


async def _pooled(request: Any, symbols: Sequence[str], regime: Dict[str, Any],
                  expiry: Optional[str], limit: int) -> Dict[str, Any]:
    """Build every underlying in the list, pool the ideas and keep the best `limit` overall."""
    import asyncio

    results = await asyncio.gather(
        *[ideas_for_underlying(request, s, regime, expiry=expiry, limit=limit) for s in symbols],
        return_exceptions=True,
    )
    pool: List[Dict[str, Any]] = []
    unavailable: List[Dict[str, Any]] = []
    as_of: Optional[str] = None
    context: List[Dict[str, Any]] = []
    for sym, r in zip(symbols, results):
        if isinstance(r, BaseException):
            unavailable.append({"underlying": sym, "reason": _why(r)})
            continue
        if not r.get("available"):
            unavailable.append({"underlying": sym, "reason": r.get("reason")})
            continue
        as_of = as_of or r.get("as_of")
        context.append({"underlying": sym, "spot": r.get("spot"), "expiry": r.get("expiry"),
                        **(r.get("chain_context") or {})})
        pool.extend(r["ideas"])
    pool.sort(key=lambda i: (-(i["fit"]["score"]), -(i["reward_risk"] or 0.0)))
    top = pool[:limit]
    for i, it in enumerate(top, 1):
        it["rank"] = i
    return {"as_of": as_of, "ideas": top, "considered": len(pool),
            "underlyings": context, "unavailable": unavailable}


async def _stock_fno_symbols(request: Any, want: int) -> Tuple[List[str], Optional[str]]:
    """The scanner's own ranked names, which is the universe the desk already uses. Returns
    ([], reason) when the scanner cannot be read — never a made-up list."""
    try:
        from .selection import select_opportunities

        sel = await select_opportunities(request, want)
        syms = [str(s["symbol"]).upper() for s in (sel.get("setups") or []) if s.get("symbol")]
        return syms[:want], None
    except Exception as e:  # noqa: BLE001
        logger.warning("regime_fit: scanner selection unavailable: %s", _why(e))
        return [], _why(e)


async def build_top(request: Any, user_id: str, *, limit: int = 5,
                    classes: Optional[Sequence[str]] = None,
                    expiry: Optional[str] = None) -> Dict[str, Any]:
    """The whole answer: the regime, then the best `limit` ideas in each asset class.

    Reads only. Nothing is written and nothing is sent to a broker."""
    from datetime import datetime, timezone

    wanted = list(classes) if classes else ["index_options", "stock_fno", "cash"]
    regime = await read_regime()
    out_classes: Dict[str, Any] = {}

    if "index_options" in wanted:
        if regime.get("available"):
            out_classes["index_options"] = await _pooled(request, INDEX_UNDERLYINGS, regime, expiry, limit)
        else:
            out_classes["index_options"] = {"ideas": [], "considered": 0, "underlyings": [],
                                            "unavailable": [{"underlying": s, "reason": "the market regime is unavailable, so fit cannot be scored"} for s in INDEX_UNDERLYINGS]}

    if "stock_fno" in wanted:
        if regime.get("available"):
            syms, why = await _stock_fno_symbols(request, STOCK_FNO_SCAN)
            if syms:
                out_classes["stock_fno"] = await _pooled(request, syms, regime, expiry, limit)
                out_classes["stock_fno"]["universe"] = {
                    "source": "the AI scanner's merged setup list (services/strategy_plan/selection.select_opportunities)",
                    "symbols_tried": syms}
            else:
                out_classes["stock_fno"] = {"ideas": [], "considered": 0, "underlyings": [],
                                            "unavailable": [{"underlying": None, "reason": why or "the scanner returned no setups"}]}
        else:
            out_classes["stock_fno"] = {"ideas": [], "considered": 0, "underlyings": [],
                                        "unavailable": [{"underlying": None, "reason": "the market regime is unavailable, so fit cannot be scored"}]}

    if "cash" in wanted:
        out_classes["cash"] = await _cash_class(request, user_id, limit)

    gap = None
    if regime.get("available"):
        # Only ISO day strings are comparable. The cash class's `as_of` comes from the ideas engine,
        # whose `data_as_of` is an OBJECT of per-source dates, not a day — comparing it against the
        # regime's date raised TypeError: '>' not supported between 'dict' and 'str'.
        chain_days = [d for d in (_newest_day(c.get("as_of")) for c in out_classes.values()
                                  if isinstance(c, dict)) if d]
        newest = max(chain_days) if chain_days else None
        regime_day = _newest_day(regime.get("as_of"))
        if newest and regime_day and newest > regime_day:
            gap = (f"The option chain is from {newest} but the market regime was last classified on "
                   f"{regime_day}: the fit is scored against the older regime.")

    return {
        "schema": "desk.strategy.top.v1",
        "rules_version": REGIME_FIT_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "limit": limit,
        "regime": regime,
        "staleness_note": gap,
        "classes": out_classes,
        "ranking_note": RANKING_NOTE,
        "ranking_note_cash": CASH_RANKING_NOTE,
        "gaps": GAPS,
        "sent_to_broker": False,
    }


async def _cash_class(request: Any, user_id: str, limit: int) -> Dict[str, Any]:
    """The cash class is the desk's existing 'From AI opportunities' answer, unchanged: the same
    scanner selection and the same evidence ranking that `POST /api/desk/strategy/ideas` returns.
    It is reused rather than re-ranked so the two views cannot disagree about the same stocks."""
    from datetime import date as _date, datetime as _dt, timezone as _tz

    from . import ideas as ideas_mod

    try:
        _limit, passed, problems, applied = ideas_mod.parse_body({})
        if problems:
            return {"ideas": [], "considered": 0, "unavailable": [{"underlying": None, "reason": str(problems)}]}
        body = await ideas_mod.build_ideas(request, user_id, limit, passed or {}, applied,
                                           _dt.now(_tz.utc), _date.today())
    except Exception as e:  # noqa: BLE001
        logger.warning("regime_fit: cash class unavailable: %s", _why(e))
        return {"ideas": [], "considered": 0, "unavailable": [{"underlying": None, "reason": _why(e)}]}

    ideas = (body.get("ideas") or [])[:limit]
    # The ideas engine's `data_as_of` is an object of per-source dates. It is kept whole under
    # `data_as_of`, and `as_of` carries a single comparable day (the newest of them) or None.
    raw_as_of = body.get("data_as_of") or body.get("as_of")
    return {
        "as_of": _newest_day(raw_as_of),
        "data_as_of": raw_as_of,
        "ideas": ideas,
        "considered": len(body.get("ideas") or []),
        "unavailable": [],
        "ranking": body.get("ranking_note") or body.get("selection_rule"),
        "source": "POST /api/desk/strategy/ideas (services/strategy_plan/ideas.build_ideas), unchanged",
    }
