"""Opportunity validation `spt-validate-v1` (constants.VALIDATION_VERSION): Workflow §6 with the data that exists tonight,
the opportunity score, the decision, and expiry (PRD §7.3–§7.4; DESIGN.md §4, §5).

Steps (Workflow §6.2) and what each reads:
    1 market regime        the desk regime (inputs.regime: Nifty vs its 50-session average, India VIX 20, 52/48 breadth),
                           judged fresh by services/data_freshness (budget REGIME_BUDGET_SESSIONS)
    2 instrument trend     NSE end-of-day bars (inputs.bars) after the latest bonus/split break (exit_watch.rules.series_break,
                           extended over the whole read): last close vs EMA20 / EMA50 / EMA200, RSI(14) (Wilder), ATR(14) and
                           ATR % of the close. Freshness: the last bar within BARS_BUDGET_SESSIONS of the reference session.
    3 participation and    20-session average traded value in rupees (close × volume, as services/risk_gate/inputs.py), the
      liquidity            last session's volume against its 20-session average (relative volume of the LAST SESSION: today's
                           intraday volume is not recorded with a list mark), and whether a volume list flagged the stock
    4 derivatives          NOT checked tonight: `derivatives: null`, data_as_of.derivatives = {ok: false, reason: not_checked}
    5 quality              the opportunity score below

Opportunity score 0–100 (SCORE_LABEL: a rule-based measure of how complete the evidence is, NOT a probability of profit;
PRD §6.5, Workflow §6.2 step 5). Parts, each with its points, maximum and a note:
    confirmations 30   DISTINCT strategy families among the list signals (normalize.LIST_MAP; two lists of one family are
                       one confirmation; the strong signal is a score of the same lists, not a confirmation): 1 → 10,
                       2 → 18, 3 → 24, 4+ → 30
    trend 25           long: close > EMA20 (7), EMA20 > EMA50 (6), close > EMA200 (6), RSI 50–70 (6) or 70–80 (3);
                       short mirrored (close < EMA20, EMA20 < EMA50, close < EMA200, RSI 30–50 (6) or 20–30 (3))
    participation 15   last-session relative volume ≥ 2 (10), ≥ 1.5 (7), ≥ 1 (4); a volume-category list (5)
    liquidity 15       average traded value ≥ ₹50 cr (15), ≥ ₹10 cr (12), ≥ ₹5 cr (9), ≥ the minimum (5)
    regime fit 15      long: bullish 15, sideways 9, mixed 6, high volatility 3, bearish 0; short mirrored
    conflicts −10      when opposite-direction signals are open on the stock
Clamped to 0–100. A missing input scores 0 for its item and says so.

Decision (one of constants.OPP_*), in this order; reason_codes lists every finding, the decision follows the first that
applies:
    EXPIRED            window_ended (now past window_until); closed_below_stop (a daily close below the strong plan's stop on
                       or after the signal day); series_break_after_signal (a bonus/split since the signal: the plan's levels
                       are in the old price basis)
    DATA_INSUFFICIENT  bars_unavailable, bars_stale, regime_unavailable, regime_stale, adv_unknown (revalidated after
                       DATA_RETRY_S)
    REJECTED           liquidity_too_low (average traded value below SPT_MIN_ADV_RS, default ₹1 crore)
    WATCHLIST          not qualifiable tonight (DESIGN.md D5): no_strong_signal, plan_not_ok, direction_short,
                       horizon_intraday. Validated and kept for tracking; never QUALIFIED.
    CONDITIONAL        regime_risk_off (bearish or high volatility, for a long), conflicting_signals
    QUALIFIED          a strong signal with plan_ok, long, positional, fresh data, liquid enough, not risk-off, no conflicts
WATCHLIST and CONDITIONAL are revalidated at the next weekday 09:00 IST (the regime and the bars change with NSE's evening
file) or as soon as new evidence (a signal or a conflict) arrives. QUALIFIED, REJECTED and EXPIRED are not revalidated.

The validation record (Workflow §6.5) is stored on the opportunity (`validation`) and, whole, in the OPPORTUNITY_VALIDATED
event, so every decision can be reconstructed from its stored inputs and versioned policy (Workflow §25 item 21).
"""
from __future__ import annotations

import asyncio
import logging
import os
from datetime import date, datetime, time as dtime, timedelta, timezone
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np

from services import data_freshness as fresh
from services.exit_watch import rules
from services.scan_builder import signal_strength as SS

from .. import constants as C
from .. import events
from ..signals import clock, normalize
from . import inputs as inputs_mod
from . import store

logger = logging.getLogger(__name__)

SOURCE = "spt-opportunity-engine"
VERSION = C.VALIDATION_VERSION
DEFAULT_MIN_ADV_RS = 10_000_000.0             # ₹1 crore a day
BARS_BUDGET_SESSIONS = 2
REGIME_BUDGET_SESSIONS = 2
RISK_OFF = ("bearish", "high_volatility")
DATA_RETRY_S = 600
VALIDATING_STALE_S = 300
REVALIDATE_AT = dtime(9, 0)
MAX_PER_ROUND = 60
DUE_SCAN_MAX = 5000
EVENING_FROM = dtime(19, 30)                 # NSE's end-of-day file is expected in the bars from here
REFERENCE_SYMBOL = "RELIANCE"
REVALIDATABLE = (C.OPP_CREATED, C.OPP_CONDITIONAL, C.OPP_WATCHLIST, C.OPP_DATA_INSUFFICIENT)
SCORE_LABEL = ("Opportunity score 0–100: a rule-based, versioned measure of how complete the setup's evidence is. It is not "
               "a probability of profit, and a higher score is not a forecast.")
CR = 10_000_000.0

EXPLAIN = {
    "window_ended": "The consolidation window ended at {window_until}.",
    "closed_below_stop": "A daily close ({close} on {day}) is below the plan's stop loss ({stop}).",
    "series_break_after_signal": "The price series breaks on {break_day} (a bonus or split) after the signal: the plan's "
                                 "levels are in the old price basis.",
    "bars_unavailable": "NSE end-of-day bars could not be read: {why}.",
    "bars_stale": "NSE end-of-day bars are stale: {why}.",
    "regime_unavailable": "The market regime could not be read: {why}.",
    "regime_stale": "The market regime is stale: {why}.",
    "adv_unknown": "No traded value in the last 20 sessions, so liquidity cannot be judged.",
    "liquidity_too_low": "Average traded value ₹{adv_cr} cr a day is below the minimum ₹{min_cr} cr.",
    "no_strong_signal": "No strong signal (strength ≥ 70 with a scan-plan-v3 plan) yet.",
    "plan_not_ok": "The strong signal has no usable plan ({plan_note}).",
    "direction_short": "Bearish opportunities are tracked, not qualified, tonight.",
    "horizon_intraday": "Intraday opportunities are tracked, not qualified, tonight.",
    "regime_risk_off": "The market regime is {regime} (risk-off for a long).",
    "conflicting_signals": "{n} opposite-direction signal(s) are open on this stock.",
    "validation_error": "The validation failed ({why}); it is retried.",
}


def policy(env: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    env = os.environ if env is None else env
    try:
        min_adv = float(env.get("SPT_MIN_ADV_RS") or DEFAULT_MIN_ADV_RS)
    except ValueError:
        min_adv = DEFAULT_MIN_ADV_RS
    return {"version": VERSION, "min_adv_rs": min_adv if min_adv > 0 else DEFAULT_MIN_ADV_RS,
            "bars_budget_sessions": BARS_BUDGET_SESSIONS, "regime_budget_sessions": REGIME_BUDGET_SESSIONS,
            "risk_off_regimes": list(RISK_OFF), "window_sessions": clock.window_sessions(env),
            "qualified_rule": "strong signal with plan_ok, long, positional, fresh data, liquid, not risk-off, no conflicts",
            "freshness": fresh.FRESHNESS_VERSION}


def _r(v: Optional[float], dp: int = 2) -> Optional[float]:
    return None if v is None else round(float(v), dp)


def _day(b: Dict[str, Any]) -> str:
    d = b.get("date")
    return d.isoformat() if isinstance(d, date) else str(d)[:10]


# ── stock metrics (pure) ──────────────────────────────────────────────────────────────────────────────────────────────

def cut_at_breaks(bars: List[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], Optional[str]]:
    """rules.series_break over the whole read: its own look-back is the last BREAK_LOOKBACK sessions, and EMA200 reads ~290,
    so an older break is found with the same thresholds (rules.BREAK_LOW / BREAK_HIGH)."""
    used, day = rules.series_break(bars)
    if day is not None:
        return used, day
    cut, brk = 0, None
    for i in range(1, len(bars)):
        ratio = float(bars[i]["close"]) / float(bars[i - 1]["close"])
        if ratio < rules.BREAK_LOW or ratio > rules.BREAK_HIGH:
            cut, brk = i, _day(bars[i])
    return bars[cut:], brk


def stock_metrics(bars: List[Dict[str, Any]], direction: str) -> Dict[str, Any]:
    """Trend, volatility and volume metrics from NSE end-of-day bars (oldest first)."""
    clean = rules.clean_bars(bars)
    used, brk = cut_at_breaks(clean)
    closes = [float(b["close"]) for b in used]
    out: Dict[str, Any] = {"bars_read": len(clean), "bars_used": len(used), "series_break_day": brk,
                           "last_close": None, "last_close_as_of": None, "ema20": None, "ema50": None, "ema200": None,
                           "rsi14": None, "atr14": None, "atr_pct": None, "checks": {}, "notes": []}
    if not used:
        out["notes"].append("no bars")
        return out
    last = used[-1]
    c = closes[-1]
    out["last_close"], out["last_close_as_of"] = _r(c), _day(last)
    for n in (20, 50, 200):
        e = rules.ema_series(closes, n)[-1] if len(closes) >= n else None
        out[f"ema{n}"] = _r(e)
        if e is None:
            out["notes"].append(f"EMA{n} needs {n} sessions; {len(closes)} since " + (f"the break on {brk}" if brk else "the first bar"))
    rsi = SS.rsi14(np.asarray(closes, dtype=float), None)
    out["rsi14"] = _r(rsi, 1)
    a = rules.atr(used)
    out["atr14"] = _r(a)
    out["atr_pct"] = _r(a / c * 100) if a is not None and c else None
    e20, e50, e200 = out["ema20"], out["ema50"], out["ema200"]
    sign = 1 if direction == normalize.LONG else -1
    chk = out["checks"]
    chk["close_vs_ema20"] = None if e20 is None else sign * (c - e20) > 0
    chk["ema20_vs_ema50"] = None if e20 is None or e50 is None else sign * (e20 - e50) > 0
    chk["close_vs_ema200"] = None if e200 is None else sign * (c - e200) > 0
    chk["trend_aligned"] = None if None in (chk["close_vs_ema20"], chk["ema20_vs_ema50"]) else \
        bool(chk["close_vs_ema20"] and chk["ema20_vs_ema50"] and chk["close_vs_ema200"] is not False)
    vols = [float(b["volume"]) for b in used if isinstance(b.get("volume"), (int, float)) and b["volume"] is not None]
    if len(vols) >= 21 and used[-1].get("volume") is not None:
        avg = sum(vols[-21:-1]) / 20
        out["volume_last_session"] = vols[-1]
        out["avg_volume_20"] = _r(avg, 0)
        out["rvol_last_session"] = _r(vols[-1] / avg) if avg > 0 else None
    else:
        out["volume_last_session"] = out["avg_volume_20"] = out["rvol_last_session"] = None
        out["notes"].append("relative volume needs 21 sessions with volume")
    return out


def liquidity(bars: List[Dict[str, Any]], min_adv_rs: float) -> Dict[str, Any]:
    """20-session average traded value (close × volume) in rupees: traded value does not jump at a bonus or split, so the
    clean bars are used whole (services/risk_gate/inputs.instrument does the same)."""
    traded = [float(b["close"]) * float(b["volume"]) for b in rules.clean_bars(bars)
              if b.get("volume") not in (None, 0)][-20:]
    adv = sum(traded) / len(traded) if traded else None
    return {"adv_rs": _r(adv), "adv_sessions": len(traded), "min_adv_rs": min_adv_rs,
            "ok": None if adv is None else adv >= min_adv_rs}


# ── the score (pure) ──────────────────────────────────────────────────────────────────────────────────────────────────

def _part(points: int, mx: int, note: str) -> Dict[str, Any]:
    return {"points": points, "max": mx, "note": note}


def score(opp: Dict[str, Any], stock: Dict[str, Any], liq: Dict[str, Any], market: Dict[str, Any]) -> Dict[str, Any]:
    direction = opp.get("direction")
    fams = [f for f in dict.fromkeys(s.get("family") for s in opp.get("signals") or [] if s.get("kind") != "strong")
            if f and f != normalize.STRONG_FAMILY]
    n = len(fams)
    conf = {0: 0, 1: 10, 2: 18, 3: 24}.get(n, 30)
    parts: Dict[str, Dict[str, Any]] = {
        "confirmations": _part(conf, 30, f"{n} distinct famil{'y' if n == 1 else 'ies'}: {', '.join(fams) or 'none'}")}
    chk = stock.get("checks") or {}
    rsi = stock.get("rsi14")
    t, notes = 0, []
    for key, pts, text in (("close_vs_ema20", 7, "close vs EMA20"), ("ema20_vs_ema50", 6, "EMA20 vs EMA50"),
                           ("close_vs_ema200", 6, "close vs EMA200")):
        v = chk.get(key)
        t += pts if v else 0
        notes.append(f"{text} {'aligned' if v else 'not known' if v is None else 'against'}")
    if rsi is not None:
        lo, hi = (50, 70) if direction == normalize.LONG else (30, 50)
        ext_lo, ext_hi = (70, 80) if direction == normalize.LONG else (20, 30)
        rp = 6 if lo <= rsi <= hi else 3 if ext_lo <= rsi <= ext_hi else 0
        t += rp
        notes.append(f"RSI {rsi} ({rp})")
    else:
        notes.append("RSI not known")
    parts["trend"] = _part(t, 25, "; ".join(notes))
    rv = stock.get("rvol_last_session")
    p = 10 if rv is not None and rv >= 2 else 7 if rv is not None and rv >= 1.5 else 4 if rv is not None and rv >= 1 else 0
    vol_list = any(s.get("category") == "volume" for s in opp.get("signals") or [])
    p += 5 if vol_list else 0
    parts["participation"] = _part(p, 15, (f"last-session volume {rv}× its 20-session average" if rv is not None
                                           else "last-session relative volume not known")
                                   + ("; a volume list flagged it" if vol_list else ""))
    adv = liq.get("adv_rs")
    mn = liq.get("min_adv_rs") or DEFAULT_MIN_ADV_RS
    lp = 0 if adv is None or adv < mn else 15 if adv >= 50 * CR else 12 if adv >= 10 * CR else 9 if adv >= 5 * CR else 5
    parts["liquidity"] = _part(lp, 15, "average traded value not known" if adv is None
                               else f"average traded value ₹{adv / CR:,.2f} cr a day")
    key = market.get("key")
    table = ({"bullish": 15, "sideways": 9, "mixed": 6, "high_volatility": 3, "bearish": 0} if direction == normalize.LONG
             else {"bearish": 15, "sideways": 9, "mixed": 6, "high_volatility": 3, "bullish": 0})
    parts["regime_fit"] = _part(table.get(key, 0), 15, f"regime {key}" if key else "regime not known")
    nconf = len(opp.get("conflicts") or [])
    parts["conflicts"] = _part(-10 if nconf else 0, 0, f"{nconf} opposite-direction signal(s)" if nconf else "none")
    total = max(0, min(100, sum(x["points"] for x in parts.values())))
    return {"score": total, "parts": parts, "label": SCORE_LABEL, "version": VERSION, "families": fams}


# ── the decision (pure) ───────────────────────────────────────────────────────────────────────────────────────────────

def next_revalidation(now: datetime) -> datetime:
    """The next weekday 09:00 IST strictly after `now`."""
    ist = now.astimezone(clock.IST)
    d = ist.date()
    cand = datetime.combine(d, REVALIDATE_AT, tzinfo=clock.IST)
    while cand <= now or cand.weekday() >= 5:
        d += timedelta(days=1)
        cand = datetime.combine(d, REVALIDATE_AT, tzinfo=clock.IST)
    return cand


def _plan_check(opp: Dict[str, Any], bars: List[Dict[str, Any]]) -> Dict[str, Any]:
    """For a strong plan: the closes on or after the signal day against its stop, and a series break since the signal."""
    st = opp.get("strong") or {}
    plan = st.get("plan") or {}
    det = clock.parse_ts(st.get("detected_at"))
    out: Dict[str, Any] = {"stop_loss": plan.get("stop_loss"), "target_1": plan.get("target_1"), "entry": plan.get("entry"),
                           "closes_checked": 0, "below_stop": None, "break_day": None, "last_close": None}
    if not plan.get("plan_ok") or det is None:
        return out
    sday = clock.ist_day(det).isoformat()
    clean = rules.clean_bars(bars)
    idx = next((i for i, b in enumerate(clean) if _day(b) >= sday), None)
    if idx is None:
        out["below_stop"] = False
        return out
    for i in range(max(idx, 1), len(clean)):
        ratio = float(clean[i]["close"]) / float(clean[i - 1]["close"])
        if ratio < rules.BREAK_LOW or ratio > rules.BREAK_HIGH:
            out["break_day"] = _day(clean[i])
    after = clean[idx:]
    stop = plan.get("stop_loss")
    out["closes_checked"] = len(after)
    out["last_close"] = _r(float(after[-1]["close"])) if after else None
    hit = next((b for b in after if stop is not None and float(b["close"]) < float(stop)), None)
    out["below_stop"] = hit is not None
    if hit is not None:
        out["below_stop_day"], out["below_stop_close"] = _day(hit), _r(float(hit["close"]))
    return out


def _market(reg: Dict[str, Any], now: datetime) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    keep = ("available", "key", "label", "as_of", "trend", "nifty_close", "nifty_average", "nifty_vs_average_pct", "india_vix",
            "vix_high_threshold", "volatility", "breadth", "advancing_share_pct", "rule_version", "source", "reason")
    m = {k: reg.get(k) for k in keep}
    if not reg.get("available"):
        f = fresh.unavailable(reg.get("source") or inputs_mod.REGIME_SOURCE, reg.get("reason") or "unavailable",
                              budget_sessions=REGIME_BUDGET_SESSIONS)
    else:
        f = fresh.assess(reg.get("source") or inputs_mod.REGIME_SOURCE, reg.get("as_of"), budget_sessions=REGIME_BUDGET_SESSIONS,
                         now=now, have_value=bool(reg.get("key")))
    return m, f


def assess(opp: Dict[str, Any], bars_read: Dict[str, Any], reg: Dict[str, Any], now: datetime,
           pol: Dict[str, Any]) -> Dict[str, Any]:
    """The validation record of `opp` from what was read (pure)."""
    at = clock.utc_iso(now)
    bars = bars_read.get("bars") or []
    direction = opp.get("direction")
    stock = stock_metrics(bars, direction)
    liq = liquidity(bars, pol["min_adv_rs"])
    liq["rvol_last_session"] = stock.get("rvol_last_session")
    market, reg_f = _market(reg, now)
    if bars_read.get("error"):
        bars_f = fresh.unavailable(bars_read.get("source") or inputs_mod.BARS_SOURCE, bars_read["error"],
                                   budget_sessions=BARS_BUDGET_SESSIONS)
    else:
        bars_f = fresh.assess(bars_read.get("source") or inputs_mod.BARS_SOURCE, stock.get("last_close_as_of"),
                              budget_sessions=BARS_BUDGET_SESSIONS, now=now, have_value=bool(bars))
        if not bars:
            bars_f["reason"] = "the data platform has no end-of-day bars for this symbol"
    plan_chk = _plan_check(opp, bars) if opp.get("strong") else None
    stock["plan_check"] = plan_chk
    sc = score(opp, stock, liq, market)
    st = opp.get("strong") or {}
    plan = st.get("plan") or {}

    codes: List[str] = []
    expl: List[str] = []

    def add(code: str, **kw: Any) -> None:
        if code not in codes:
            codes.append(code)
            try:
                expl.append(EXPLAIN[code].format(**kw))
            except (KeyError, IndexError, ValueError):
                expl.append(code)

    until = clock.parse_ts(opp.get("window_until"))
    if until is not None and now > until:
        add("window_ended", window_until=opp.get("window_until"))
    if plan_chk and plan_chk.get("break_day"):
        add("series_break_after_signal", break_day=plan_chk["break_day"])
    elif plan_chk and plan_chk.get("below_stop"):
        add("closed_below_stop", close=plan_chk.get("below_stop_close"), day=plan_chk.get("below_stop_day"),
            stop=plan.get("stop_loss"))
    if bars_read.get("error") or not bars:
        add("bars_unavailable", why=bars_read.get("error") or bars_f.get("reason"))
    elif not bars_f["ok"]:
        add("bars_stale", why=bars_f.get("reason"))
    if not reg.get("available"):
        add("regime_unavailable", why=reg.get("reason") or "unavailable")
    elif not reg_f["ok"]:
        add("regime_stale", why=reg_f.get("reason"))
    if bars and not bars_read.get("error") and liq["adv_rs"] is None:
        add("adv_unknown")
    elif liq["adv_rs"] is not None and liq["adv_rs"] < pol["min_adv_rs"]:
        add("liquidity_too_low", adv_cr=f"{liq['adv_rs'] / CR:,.2f}", min_cr=f"{pol['min_adv_rs'] / CR:,.2f}")
    if not st:
        add("no_strong_signal")
    elif not plan.get("plan_ok"):
        add("plan_not_ok", plan_note=plan.get("plan_note") or "no plan")
    if direction == normalize.SHORT:
        add("direction_short")
    if opp.get("horizon") == normalize.INTRADAY:
        add("horizon_intraday")
    if direction == normalize.LONG and market.get("key") in RISK_OFF:
        add("regime_risk_off", regime=market.get("label") or market.get("key"))
    if opp.get("conflicts"):
        add("conflicting_signals", n=len(opp["conflicts"]))

    s = set(codes)
    if s & {"window_ended", "closed_below_stop", "series_break_after_signal"}:
        decision = C.OPP_EXPIRED
    elif s & {"bars_unavailable", "bars_stale", "regime_unavailable", "regime_stale", "adv_unknown"}:
        decision = C.OPP_DATA_INSUFFICIENT
    elif "liquidity_too_low" in s:
        decision = C.OPP_REJECTED
    elif s & {"no_strong_signal", "plan_not_ok", "direction_short", "horizon_intraday"}:
        decision = C.OPP_WATCHLIST
    elif s & {"regime_risk_off", "conflicting_signals"}:
        decision = C.OPP_CONDITIONAL
    else:
        decision = C.OPP_QUALIFIED
    if decision == C.OPP_DATA_INSUFFICIENT:
        reval: Optional[str] = clock.utc_iso(now + timedelta(seconds=DATA_RETRY_S))
    elif decision in (C.OPP_WATCHLIST, C.OPP_CONDITIONAL):
        reval = clock.utc_iso(next_revalidation(now))
    else:
        reval = None
    return {
        "opportunity_id": opp.get("_id"), "at": at, "version": VERSION, "decision": decision, "reason_codes": codes,
        "explanations": expl, "opportunity_score": sc["score"], "score_parts": sc["parts"], "score_label": sc["label"],
        "families": sc["families"], "signal_count": len(opp.get("signals") or []),
        "evidence_version": opp.get("evidence_version"),
        "market": market, "stock": stock, "liquidity": liq, "derivatives": None,
        "data_as_of": {"bars": bars_f, "regime": reg_f,
                       "derivatives": {"ok": False, "reason": "not_checked",
                                       "note": "derivatives validation (Workflow §6.2 step 4) is not built tonight"},
                       "bars_read_at": bars_read.get("read_at")},
        "revalidate_at": reval, "policy": pol,
    }


def error_record(opp: Dict[str, Any], now: datetime, why: str, pol: Dict[str, Any]) -> Dict[str, Any]:
    return {"opportunity_id": opp.get("_id"), "at": clock.utc_iso(now), "version": VERSION,
            "decision": C.OPP_DATA_INSUFFICIENT, "reason_codes": ["validation_error"],
            "explanations": [EXPLAIN["validation_error"].format(why=why)], "opportunity_score": None, "score_parts": None,
            "score_label": SCORE_LABEL, "families": [], "signal_count": len(opp.get("signals") or []),
            "evidence_version": opp.get("evidence_version"), "market": None, "stock": None, "liquidity": None,
            "derivatives": None, "data_as_of": None,
            "revalidate_at": clock.utc_iso(now + timedelta(seconds=DATA_RETRY_S)), "policy": pol}


# ── running it ────────────────────────────────────────────────────────────────────────────────────────────────────────

async def validate(db, opp_id: str, *, inputs: Optional[inputs_mod.MarketInputs] = None, now: Optional[datetime] = None,
                   env: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """Validate (or revalidate) one opportunity: → VALIDATING → the decision, the record on the opportunity and in
    OPPORTUNITY_VALIDATED. Returns {ok, opportunity_id, state, validation} or {ok: False, error, state}:
    error ∈ opportunity_not_found | opportunity_not_revalidatable | validation_in_progress | state_changed."""
    inputs = inputs or inputs_mod.get_inputs()
    now = now or datetime.now(timezone.utc)
    pol = policy(env)
    opp = await store.get(db, opp_id)
    if opp is None:
        return {"ok": False, "error": "opportunity_not_found", "state": None}
    st = opp.get("state")
    if st == C.OPP_VALIDATING:
        since = clock.parse_ts(opp.get("validating_since") or opp.get("updated_at"))
        if since is not None and (now - since).total_seconds() < VALIDATING_STALE_S:
            return {"ok": False, "error": "validation_in_progress", "state": st}
    elif st not in REVALIDATABLE:
        return {"ok": False, "error": "opportunity_not_revalidatable", "state": st}
    else:
        moved = await store.transition(db, opp_id, expect_states=[st], to_state=C.OPP_VALIDATING,
                                       reason="validation_started", extra={"validating_since": clock.utc_iso(now)},
                                       now=clock.utc_iso(now))
        if moved is None:
            cur = await store.get(db, opp_id)
            return {"ok": False, "error": "state_changed", "state": (cur or {}).get("state")}
        opp = moved
    try:
        bars_read = await inputs.bars(opp["symbol"], now)
        reg = await inputs.regime()
        rec = assess(opp, bars_read, reg, now, pol)
    except Exception as e:  # noqa: BLE001 — never left in VALIDATING: recorded as DATA_INSUFFICIENT and retried
        logger.warning("spt validate: %s failed (%s)", opp_id, type(e).__name__)
        rec = error_record(opp, now, type(e).__name__, pol)
    done = None
    for _ in range(3):              # a signal attached meanwhile bumps `version`: retry while it is still VALIDATING
        done = await store.transition(
            db, opp_id, expect_states=[C.OPP_VALIDATING], to_state=rec["decision"],
            reason=",".join(rec["reason_codes"]) or "passed",
            extra={"validation": rec, "opportunity_score": rec["opportunity_score"], "revalidate_at": rec["revalidate_at"],
                   "validated_evidence_version": opp.get("evidence_version") or 0, "validating_since": None},
            now=clock.utc_iso(now))
        if done is not None or ((await store.get(db, opp_id)) or {}).get("state") != C.OPP_VALIDATING:
            break
    if done is None:
        cur = await store.get(db, opp_id)
        return {"ok": False, "error": "state_changed", "state": (cur or {}).get("state")}
    await events.emit(db, "OPPORTUNITY_VALIDATED", idempotency_key=f"opp:{opp_id}:validated:{done.get('version')}",
                      source_service=SOURCE, occurred_at=rec["at"], correlation_id=opp_id, instrument_id=done.get("symbol"),
                      payload={"opportunity_id": opp_id, "decision": rec["decision"], "reason_codes": rec["reason_codes"],
                               "opportunity_score": rec["opportunity_score"], "validation": rec})
    return {"ok": True, "opportunity_id": opp_id, "state": done.get("state"), "validation": rec}


def _due_query(now: datetime) -> Dict[str, Any]:
    at = clock.utc_iso(now)
    stale = clock.utc_iso(now - timedelta(seconds=VALIDATING_STALE_S))
    return {"state": {"$in": list(REVALIDATABLE) + [C.OPP_VALIDATING]},
            "$or": [{"state": C.OPP_CREATED},
                    {"state": C.OPP_VALIDATING, "validating_since": {"$lte": stale}},
                    {"state": {"$ne": C.OPP_VALIDATING},
                     "$expr": {"$gt": ["$evidence_version", {"$ifNull": ["$validated_evidence_version", 0]}]}},
                    {"state": {"$ne": C.OPP_VALIDATING}, "revalidate_at": {"$lte": at}}]}


def _priority(o: Dict[str, Any]) -> Tuple[int, int, str]:
    return (0 if o.get("strong") else 1, 0 if o.get("horizon") == normalize.POSITIONAL else 1, o.get("first_seen_at") or "")


async def validate_due(db, *, now: Optional[datetime] = None, inputs: Optional[inputs_mod.MarketInputs] = None,
                       limit: int = MAX_PER_ROUND, env: Optional[Dict[str, str]] = None) -> Dict[str, int]:
    """Validate the opportunities that are due (new, new evidence, revalidate_at passed, stuck in VALIDATING), strong and
    positional first, at most `limit` per call. Returns counts per resulting state plus skipped/errors."""
    now = now or datetime.now(timezone.utc)
    inputs = inputs or inputs_mod.get_inputs()
    due = await db[store.COLL].find(_due_query(now), {"strong.signal_id": 1, "horizon": 1, "first_seen_at": 1,
                                                      "state": 1}).limit(DUE_SCAN_MAX).to_list(length=None)
    due.sort(key=_priority)
    counts: Dict[str, int] = {"due": len(due), "validated": 0, "skipped": 0, "errors": 0}
    batch = due[:max(0, int(limit))]

    async def one(o: Dict[str, Any]) -> None:
        try:
            r = await validate(db, o["_id"], inputs=inputs, now=now, env=env)
        except Exception as e:  # noqa: BLE001 — one opportunity never stops the round
            logger.warning("spt validate: %s failed (%s)", o.get("_id"), type(e).__name__)
            counts["errors"] += 1
            return
        if r.get("ok"):
            counts["validated"] += 1
            counts[r["state"]] = counts.get(r["state"], 0) + 1
        else:
            counts["skipped"] += 1

    for i in range(0, len(batch), inputs_mod.FETCH_CONCURRENCY):
        await asyncio.gather(*(one(o) for o in batch[i:i + inputs_mod.FETCH_CONCURRENCY]))
    return counts


def expected_bar_day(now: datetime) -> str:
    """The newest NSE session whose end-of-day bar should be in: today from EVENING_FROM on a weekday, else the weekday
    before today (data_freshness.previous_session)."""
    ist = now.astimezone(clock.IST)
    if ist.weekday() < 5 and ist.time() >= EVENING_FROM:
        return ist.date().isoformat()
    return fresh.previous_session(ist.date()).isoformat()


async def expire(db, *, now: Optional[datetime] = None, inputs: Optional[inputs_mod.MarketInputs] = None) -> Dict[str, Any]:
    """EXPIRED for every open opportunity past its window, and every open one whose strong plan's stop was closed below
    (or whose price series broke) since the signal. The stop check reads bars only for opportunities not yet checked
    through the newest session that should be in (`stop_checked_through` < expected_bar_day): once per opportunity per
    NSE session, not every round. Returns counts."""
    now = now or datetime.now(timezone.utc)
    inputs = inputs or inputs_mod.get_inputs()
    at = clock.utc_iso(now)
    expected = expected_bar_day(now)
    counts: Dict[str, Any] = {"window_ended": 0, "closed_below_stop": 0, "series_break_after_signal": 0, "checked": 0,
                              "errors": 0, "expected_bar_day": expected}
    ended = await db[store.COLL].find({"state": {"$in": list(C.OPP_OPEN_STATES)}, "window_until": {"$lt": at}}).to_list(length=None)
    for o in ended:
        if await store.transition(db, o["_id"], expect_states=[o["state"]], to_state=C.OPP_EXPIRED, reason="window_ended",
                                  extra={"expiry": {"reason": "window_ended", "window_until": o.get("window_until")}},
                                  now=at):
            counts["window_ended"] += 1
    withplan = await db[store.COLL].find({"state": {"$in": list(C.OPP_OPEN_STATES)}, "strong.plan.plan_ok": True,
                                          "$or": [{"stop_checked_through": None},
                                                  {"stop_checked_through": {"$lt": expected}}]}).to_list(length=None)
    if withplan and expected == clock.ist_day(now).isoformat():
        ref = await inputs.bars(REFERENCE_SYMBOL, now)        # this evening's file not in yet: check after it lands
        last = (ref.get("bars") or [{}])[-1].get("date") if ref.get("bars") else None
        if last is None or str(last)[:10] < expected:
            counts["stop_check"] = "waiting_for_nse_file"
            return counts
    for o in withplan:
        try:
            got = await inputs.bars(o["symbol"], now)
        except Exception as e:  # noqa: BLE001
            logger.warning("spt expire: bars for %s failed (%s)", o.get("symbol"), type(e).__name__)
            counts["errors"] += 1
            continue
        if got.get("error"):
            continue
        counts["checked"] += 1
        chk = _plan_check(o, got.get("bars") or [])
        reason = ("series_break_after_signal" if chk.get("break_day") else "closed_below_stop" if chk.get("below_stop")
                  else None)
        if reason:
            if await store.transition(db, o["_id"], expect_states=[o["state"]], to_state=C.OPP_EXPIRED,
                                      reason=reason, extra={"expiry": {"reason": reason, **chk}}, now=at):
                counts[reason] += 1
            continue
        last_bar = rules.clean_bars(got.get("bars") or [])
        if last_bar:
            await db[store.COLL].update_one({"_id": o["_id"]}, {"$set": {"stop_checked_through": _day(last_bar[-1])}})
    return counts
