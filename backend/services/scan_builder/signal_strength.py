"""Signal strength 0–100 for the Scan dashboard's signalled stocks — positional, long only (docs/scan_builder/DESIGN.md §11).

Owner, 4 Nov 2026 ~13:45 IST: process only the signals whose strength is above 70; the company must be fundamentally and
technically good with a solid reason for the move (a trend reversal from the 52-week low, momentum continuation, a market
event); classic pump-and-dump stocks score lower; blue chips weigh more; positional, not intraday. Decisions ~14:05: plan =
ATR stop + trend exit; below 70 = folded away (no alert, no plan); long only.

Score = quality (30) + trend (25) + reason (20) + size (15) + participation (10) − penalties, clamped to 0–100. The weights are
set by hand (rule-based; not fitted or back-tested) and every point is explained in `reasons` / `penalties`.

Inputs per stock (`StockInputs`): the EOD history to the last session and today's bar (live, Kite close or EOD), the NIDP
feature-store fundamentals (DaaS /stocks/screener), the feature-store snapshot (DaaS /features/scan-snapshot: ETF flag, NSE
price band, traded value, sector), exchange filings since the last session (DaaS /announcements, classified), index and F&O
membership, Kite trade sides, and the stock's list entries today.
"""
from __future__ import annotations

import asyncio
import logging
import math
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Awaitable, Callable, Dict, List, Optional, Sequence, Set, Tuple

import numpy as np

from . import early_movers as EM

logger = logging.getLogger(__name__)

THRESHOLD = 70
WEIGHTS = {"quality": 30, "trend": 25, "reason": 20, "size": 15, "participation": 10}
PLAN_RULES = "scan-plan-v3"
ATR_MULT = 2.0
R1, R2 = 2.0, 4.0

# Lists whose pattern is a positional setup (multi-day structure), as opposed to intraday-only conditions.
POSITIONAL_LISTS = {"dt_52w_high", "dt_52w_breakout", "dt_uptrend_52w", "dt_multiyear", "cup_handle", "tight_consolidation",
                    "triple_bottom", "long_buildup", "dt_swing_breakout", "dt_high_growth", "good_results", "rsi_dwm",
                    "supertrend_rsi", "dt_delivery_volume", "dt_vol_price_breakout"}
FINANCIAL_WORDS = ("bank", "financ", "nbfc", "insur", "housing finance", "capital market", "lending", "credit")
SMA_SET = (5, 10, 20, 30, 50, 100, 150, 200)
# Words this screen keeps out of everything but the plan block (owner, 3 Nov compliance rule): a filing subject carrying one
# is not quoted, only its category and time.
BARRED = re.compile(r"\b(buy\w*|sell\w*|recommend\w*|pick\w*|target\w*|stop\s*loss|entry|entries|exit\w*)\b", re.I)
QUERY_WORDS = re.compile(r"spurt in volume|price movement", re.I)   # the exchange's surveillance queries
EM_IST = timezone(timedelta(hours=5, minutes=30))
W52 = 250

RULES_TEXT = ("Signal strength 0–100 = quality 30 (ROCE/ROE, debt, margin, earnings consistency, holdings) + trend 25 (averages, "
              "52-week setup, RSI, 6-month return) + reason 20 (exchange filings since the last session, the 52-week setup, "
              "positional lists) + size 15 (Nifty 50 highest, then Nifty 100, 200 / Midcap 150, Nifty 500, F&O, market cap) + "
              "participation 10 (volume against its usual by now, trade sides, lists) − penalties for pump-and-dump traits "
              "(tiny market cap, penny price, NSE 5 % / 2 % price band, locked at the upper band, the exchange's volume / price "
              "queries, a negative filing, unexplained volume spike, parabolic run without earnings, losses, pledge, thin holdings, extreme "
              "volatility, chasing far above the 20-day average). Long only; "
              "ETFs are not scored. Weights set by hand, not back-tested.")
PLAN_TEXT = ("Strong signals (score ≥ 70) only: Entry = the live price when the score first reached 70; Stop loss = Entry − 2 × "
             "ATR(14), judged on daily closes; Target 1 = Entry + 2 × risk; Target 2 = Entry + 4 × risk; trend exit = a daily "
             "close below the 20-day average (it rises as the trend runs). Positional, not intraday.")
CAVEAT = ("A rule-based score and rule-based levels (scan-plan-v3), frozen when the stock first reached 70. Not investment advice; "
          "no accuracy or hit rate is claimed. Fundamentals are the feature store's latest and can lag a filing made today.")


# ── inputs ──────────────────────────────────────────────────────────────────────────────────────────────────────────

@dataclass
class StockInputs:
    symbol: str
    name: str = ""
    price: Optional[float] = None                     # today's price (live / Kite close / EOD)
    volume_today: Optional[float] = None
    closes: np.ndarray = field(default_factory=lambda: np.zeros(0))      # history BEFORE today, oldest first
    highs: np.ndarray = field(default_factory=lambda: np.zeros(0))
    lows: np.ndarray = field(default_factory=lambda: np.zeros(0))
    volumes: np.ndarray = field(default_factory=lambda: np.zeros(0))
    fundamentals: Dict[str, Optional[float]] = field(default_factory=dict)
    snapshot: Dict[str, Any] = field(default_factory=dict)
    members: Set[str] = field(default_factory=set)
    fno: bool = False
    filings: List[Dict[str, Any]] = field(default_factory=list)
    lists: List[Dict[str, Any]] = field(default_factory=list)          # [{id, title, direction}]
    usual_share: Optional[float] = 1.0                # share of a day's volume usually traded by now (1.0 = whole day)
    ask_trades: Optional[float] = None
    bid_trades: Optional[float] = None
    exchange_queries: List[Dict[str, Any]] = field(default_factory=list)   # the exchange's volume/price queries, 30 days


def _f(v: Any) -> Optional[float]:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) else None


def _band(v: Optional[float], steps: Sequence[Tuple[float, int]]) -> int:
    if v is None:
        return 0
    for t, p in steps:
        if v >= t:
            return p
    return 0


def _pct(v: Optional[float], dp: int = 1) -> str:
    return "no data" if v is None else f"{v:.{dp}f} %"


def _money(v: float) -> str:
    return f"₹{v:,.2f}"


def is_financial(inp: StockInputs) -> bool:
    text = " ".join(str(inp.snapshot.get(k) or "") for k in ("sector", "industry")).lower() or inp.name.lower()
    return any(w in text for w in FINANCIAL_WORDS)


def rsi14(closes: np.ndarray, price: Optional[float]) -> Optional[float]:
    """Wilder's RSI(14) on the history plus today's price."""
    c = np.asarray(closes, dtype=float)
    if price is not None:
        c = np.append(c, price)
    if len(c) < 15:
        return None
    d = np.diff(c)
    up, dn = np.clip(d, 0, None), np.clip(-d, 0, None)
    au, ad = up[:14].mean(), dn[:14].mean()
    for u, w in zip(up[14:], dn[14:]):
        au, ad = (au * 13 + u) / 14, (ad * 13 + w) / 14
    if ad == 0:
        return 100.0
    return 100.0 - 100.0 / (1.0 + au / ad)


def atr14(highs: np.ndarray, lows: np.ndarray, closes: np.ndarray) -> Optional[float]:
    """Wilder's ATR(14) to the last session (history only)."""
    if len(closes) < 15:
        return None
    h, l, c = np.asarray(highs, float), np.asarray(lows, float), np.asarray(closes, float)
    tr = np.maximum(h[1:] - l[1:], np.maximum(np.abs(h[1:] - c[:-1]), np.abs(l[1:] - c[:-1])))
    a = tr[:14].mean()
    for x in tr[14:]:
        a = (a * 13 + x) / 14
    return float(a) if math.isfinite(a) else None


@dataclass
class Tech:
    smas: Dict[int, float]
    hi52: Optional[float]
    lo52: Optional[float]
    rsi: Optional[float]
    ret21: Optional[float]
    ret63: Optional[float]
    ret125: Optional[float]
    adv20: Optional[float]
    traded_cr: Optional[float]
    atr: Optional[float]


def technicals(inp: StockInputs) -> Tech:
    c, p = inp.closes, inp.price
    n = len(c)
    smas = {k: float(np.mean(c[-k:])) for k in SMA_SET if n >= k}
    hi52 = float(np.max(inp.highs[-W52:])) if n else None
    lo52 = float(np.min(inp.lows[-W52:])) if n else None

    def ret(k: int) -> Optional[float]:
        return (p / c[-k] - 1.0) * 100.0 if p and n >= k and c[-k] > 0 else None
    adv20 = float(np.mean(inp.volumes[-20:])) if n >= 20 else None
    traded = _f(inp.snapshot.get("traded_value_cr_20d"))
    if traded is None and adv20 is not None and n:
        traded = adv20 * float(c[-1]) / 1e7
    return Tech(smas=smas, hi52=hi52, lo52=lo52, rsi=rsi14(c, p), ret21=ret(21), ret63=ret(63), ret125=ret(125),
                adv20=adv20, traded_cr=traded, atr=atr14(inp.highs, inp.lows, c))


# ── the five parts ──────────────────────────────────────────────────────────────────────────────────────────────────

def quality(inp: StockInputs) -> Tuple[int, str]:
    g = inp.fundamentals.get
    fin = is_financial(inp)
    roce, roe, de, pm = _f(g("roce_pct")), _f(g("roe_pct")), _f(g("debt_to_equity")), _f(g("profit_margin_pct"))
    cons, prom = _f(g("earnings_consistency_score")), _f(g("promoter_pct"))
    fii, dii = _f(g("fii_pct")), _f(g("dii_pct"))
    inst = None if fii is None and dii is None else (fii or 0.0) + (dii or 0.0)
    pts = _band(roe if fin else roce, [(20, 8), (15, 6), (10, 3)])
    pts += _band(roe, [(18, 5), (12, 3), (8, 1)])
    if fin:
        pts += 3
    elif de is not None:
        pts += 5 if de <= 0.3 else 3 if de <= 1 else 1 if de <= 2 else 0
    pts += 3 if pm is not None and pm >= 10 else 1 if pm is not None and pm > 0 else 0
    pts += _band(cons, [(75, 4), (50, 2)])
    pts += _band(prom, [(50, 3), (30, 2)])
    pts += 2 if inst is not None and inst >= 15 else 1 if inst is not None and inst >= 5 else 0
    first = f"ROE {_pct(roe)}" if fin else f"ROCE {_pct(roce)}, ROE {_pct(roe)}"
    debt = "" if fin else f", debt/equity {'no data' if de is None else f'{de:.2f}'}"
    text = f"Quality {pts}/30: {first}{debt}, margin {_pct(pm)}, promoter {_pct(prom)}"
    return min(pts, WEIGHTS["quality"]), text


def setup_of(inp: StockInputs, t: Tech) -> Optional[str]:
    p = inp.price
    if p is None or t.hi52 is None or t.lo52 is None:
        return None
    if p >= t.hi52:
        return "breakout"
    if p >= 0.95 * t.hi52:
        return "near_high"
    c = inp.closes
    s20_rising = len(c) >= 25 and float(np.mean(c[-20:])) > float(np.mean(c[-25:-5]))
    if p <= 1.30 * t.lo52 and t.smas.get(50) is not None and p > t.smas[50] and s20_rising:
        return "reversal"
    return None


def trend(inp: StockInputs, t: Tech, setup: Optional[str]) -> Tuple[int, List[str]]:
    p = inp.price or 0.0
    above = sum(1 for m in t.smas.values() if p > m)
    pts = above
    notes = [f"Above {above} of {len(t.smas)} daily averages (5 to 200 day)"]
    if t.smas.get(50) is not None and t.smas.get(200) is not None and t.smas[50] > t.smas[200]:
        pts += 4
        notes.append("50-day average above the 200-day")
    if setup == "breakout":
        pts += 6
        notes.append(f"52-week-high breakout (prior high {_money(t.hi52)})")
    elif setup == "near_high":
        pts += 4
        notes.append(f"Within 5 % of the 52-week high ({_money(t.hi52)})")
    elif setup == "reversal":
        pts += 6
        notes.append(f"Turning up from the 52-week low ({_money(t.lo52)}), above its 50-day average")
    r = t.rsi
    pts += 4 if r is not None and 50 <= r <= 72 else 2 if r is not None and 72 < r <= 80 else 1 if r is not None and r < 50 else 0
    if r is not None:
        notes.append(f"RSI(14) {r:.0f}")
    pts += 3 if t.ret125 is not None and t.ret125 > 10 else 1 if t.ret125 is not None and t.ret125 > 0 else 0
    return min(pts, WEIGHTS["trend"]), notes


EVENT_LABEL = {"earnings": "Results", "orders": "Order", "mna": "Merger / acquisition", "capex": "Capacity / capex",
               "buyback": "Share repurchase", "dividend": "Dividend", "rating": "Credit rating", "qip": "Fund raise",
               "management": "Management", "litigation": "Litigation", "regulatory": "Regulatory", "other": "Exchange"}


def filing_points(r: Dict[str, Any]) -> int:
    cat, imp, sen = r.get("event_category"), r.get("impact_score"), r.get("sentiment")
    if cat == "earnings" and sen == "positive":
        return 16
    if cat in ("orders", "mna", "capex", "buyback") and sen == "positive":
        return 12 if imp in ("high", "medium") else 8
    if sen == "positive" and imp in ("high", "medium"):
        return 8
    if cat == "earnings":
        return 6
    if sen == "negative" and imp in ("high", "medium"):
        return -8
    return 0


def _filed_ist(r: Dict[str, Any]) -> Optional[datetime]:
    v = r.get("filed_at") or r.get("broadcast_at")
    if not v:
        return None
    try:
        d = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    except ValueError:
        return None
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)            # the platform stores filing times in UTC
    return d.astimezone(EM_IST)



def event(inp: StockInputs) -> Tuple[int, Optional[str]]:
    """The strongest filing (largest |points|; positive wins a tie) and its text."""
    best, text = 0, None
    for r in inp.filings:
        pts = filing_points(r)
        if pts == 0 or (abs(pts) < abs(best)) or (abs(pts) == abs(best) and pts < best):
            continue
        when = _filed_ist(r)
        label = EVENT_LABEL.get(str(r.get("event_category")), "Exchange")
        tone = r.get("sentiment") or "unclassified"
        stamp = when.strftime("%d %b %H:%M") if when else "recently"
        subj = str(r.get("subject") or "").strip()[:80]
        best, text = pts, f"{label} filing {stamp} IST ({tone})" + ("" if not subj or BARRED.search(subj) else f": {subj}")
    return best, text


def reason(inp: StockInputs, setup: Optional[str], ev: int, ev_text: Optional[str]) -> Tuple[int, List[str]]:
    notes: List[str] = []
    st = 10 if setup in ("breakout", "reversal") else 6 if setup == "near_high" else 0
    pos = sorted({x["id"] for x in inp.lists} & POSITIONAL_LISTS)
    if pos:
        st += 4
        notes.append(f"In {len(pos)} positional-pattern list(s) today")
    if ev_text:
        notes.insert(0, ev_text)
    pts = st + ev
    return max(0, min(WEIGHTS["reason"], pts)), notes


def size(inp: StockInputs, t: Tech) -> Tuple[int, str]:
    m = inp.members
    mcap = _f(inp.fundamentals.get("market_cap_cr"))
    if "nifty50" in m:
        pts, label = 15, "Nifty 50"
    elif "nifty100" in m:
        pts, label = 13, "Nifty 100"
    elif "nifty200" in m or "midcap150" in m:
        pts, label = 10, "Nifty 200" if "nifty200" in m else "Nifty Midcap 150"
    elif "nifty500" in m:
        pts, label = 7, "Nifty 500"
    else:
        pts, label = 0, "outside Nifty 500"
    if inp.fno and pts < 9:
        pts, label = 9, f"{label}, F&O stock"
    if pts == 0:
        pts = 5 if mcap is not None and mcap >= 5000 else 3 if mcap is not None and mcap >= 2000 else 0
    if t.traded_cr is not None and t.traded_cr < 5:
        pts = min(pts, 2)
        label += f", thinly traded (₹{t.traded_cr:.1f} cr a day)"
    cap = "" if mcap is None else f", market cap ₹{mcap:,.0f} cr"
    return pts, f"Size {pts}/15: {label}{cap}"


def volume_ratio(inp: StockInputs, t: Tech) -> Optional[float]:
    if inp.volume_today is None or not t.adv20 or not inp.usual_share:
        return None
    return inp.volume_today / (t.adv20 * inp.usual_share)


def participation(inp: StockInputs, t: Tech, rv: Optional[float], ev: int) -> Tuple[int, List[str]]:
    pts, notes = 0, []
    if rv is not None:
        if 1.5 <= rv <= 8:
            pts += 6
        elif 8 < rv <= 20:
            pts += 4 if ev > 0 else 2
        elif rv > 20:
            pts += 3 if ev > 0 else 0
        else:
            pts += 2
        notes.append(f"Volume {rv:.1f}× its usual by now")
    a, b = _f(inp.ask_trades), _f(inp.bid_trades)
    if a and b:
        if a / b > 1.1:
            pts += 2
        notes.append(f"Trades at the ask ÷ at the bid {a / b:.2f}")
    if len({x["id"] for x in inp.lists} & POSITIONAL_LISTS) >= 2:
        pts += 2
    return min(pts, WEIGHTS["participation"]), notes


def penalties(inp: StockInputs, t: Tech, rv: Optional[float], ev: int) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    g = inp.fundamentals.get
    p = inp.price
    mcap = _f(g("market_cap_cr"))
    if mcap is not None and mcap < 500:
        out.append({"text": f"Market cap under ₹500 cr (₹{mcap:,.0f} cr)", "points": 25})
    elif mcap is not None and mcap < 1000:
        out.append({"text": f"Market cap under ₹1,000 cr (₹{mcap:,.0f} cr)", "points": 15})
    if mcap is None and not inp.members:
        out.append({"text": "No market cap on record and in no index", "points": 10})
    if p is not None and p < 20:
        out.append({"text": f"Price under ₹20 ({_money(p)})", "points": 10})
    band = _f(inp.snapshot.get("price_band_pct"))
    if band is not None and band <= 2:
        out.append({"text": "NSE price band 2 % (surveillance-level band)", "points": 30})
    elif band is not None and band <= 5:
        out.append({"text": "NSE price band 5 % (a band surveillance and illiquid stocks get)", "points": 15})
    elif band is not None and band <= 10:
        out.append({"text": "NSE price band 10 %", "points": 5})
    if rv is not None and rv > 10 and ev <= 0 and "nifty500" not in inp.members:
        out.append({"text": f"Volume {rv:.0f}× usual with no filing, outside Nifty 500", "points": 15})
    prev = float(inp.closes[-1]) if len(inp.closes) else None
    if band is not None and band <= 10 and p is not None and prev and p >= prev * (1 + band / 100.0) * 0.999:
        out.append({"text": f"Locked at the upper {band:g} % price band today", "points": 10})
    asked = [q for q in inp.exchange_queries if QUERY_WORDS.search(str(q.get("title") or q.get("subject") or ""))]
    if asked:
        out.append({"text": f"The exchange queried the company about its price or volume in the last 30 days ({len(asked)} "
                            "repl" + ("y" if len(asked) == 1 else "ies") + " filed)", "points": 10})
    if ev < 0:
        out.append({"text": "A negative filing since the last session (see the reasons)", "points": 10})
    patg = _f(g("pat_growth_yoy_pct"))
    if ((t.ret21 or 0) > 50 or (t.ret63 or 0) > 100) and not (patg is not None and patg > 25) and ev <= 0:
        out.append({"text": f"Parabolic run ({t.ret21 or 0:.0f} % in 21 sessions, {t.ret63 or 0:.0f} % in 63) without "
                            "earnings growth or a filing", "points": 15})
    pm = _f(g("profit_margin_pct"))
    if pm is not None and pm < 0:
        out.append({"text": "Loss-making (negative profit margin)", "points": 10})
    pledge = _f(g("promoter_pledged_pct"))
    if pledge is not None and pledge > 50:
        out.append({"text": f"Promoter pledge {pledge:.0f} %", "points": 20})
    elif pledge is not None and pledge > 25:
        out.append({"text": f"Promoter pledge {pledge:.0f} %", "points": 10})
    prom = _f(g("promoter_pct"))
    fii, dii = _f(g("fii_pct")), _f(g("dii_pct"))
    inst = (fii or 0.0) + (dii or 0.0)
    if prom is not None and prom < 25 and inst < 5:
        out.append({"text": f"Low promoter ({prom:.0f} %) and institutional ({inst:.0f} %) holding", "points": 5})
    vol = _f(g("volatility_1y_pct"))
    if vol is not None and vol > 70:
        out.append({"text": f"1-year volatility {vol:.0f} %", "points": 5})
    s20 = t.smas.get(20)
    if p is not None and s20:
        ext = (p / s20 - 1.0) * 100.0
        if ext > 25:
            out.append({"text": f"{ext:.0f} % above its 20-day average (chasing)", "points": 5})
    return out


# ── the score ───────────────────────────────────────────────────────────────────────────────────────────────────────

def not_scored(inp: StockInputs) -> Optional[str]:
    if inp.snapshot.get("is_etf"):
        return "Not scored: an ETF, not a company"
    if inp.lists and all(x.get("direction") == "short" for x in inp.lists):
        return "Not scored: long only — this stock is in today's lists as a falling stock"
    if inp.price is None or inp.price <= 0:
        return "Not scored: no price today"
    if len(inp.closes) < 60:
        return "Not scored: under 60 sessions of history"
    return None


def score(inp: StockInputs) -> Dict[str, Any]:
    """{score (int | None), parts, reasons, penalties, lists, note, setup} for one stock."""
    lists = [{"id": x["id"], "title": x.get("title")} for x in inp.lists]
    why = not_scored(inp)
    if why:
        return {"score": None, "parts": None, "reasons": [], "penalties": [], "lists": lists, "note": why, "setup": None}
    t = technicals(inp)
    setup = setup_of(inp, t)
    ev, ev_text = event(inp)
    rv = volume_ratio(inp, t)
    q, q_text = quality(inp)
    tr, tr_notes = trend(inp, t, setup)
    rs, rs_notes = reason(inp, setup, ev, ev_text)
    sz, sz_text = size(inp, t)
    pa, pa_notes = participation(inp, t, rv, ev)
    pen = penalties(inp, t, rv, ev)
    pen_total = sum(x["points"] for x in pen)
    total = max(0, min(100, q + tr + rs + sz + pa - pen_total))
    reasons = ([ev_text] if ev_text else []) + tr_notes[1:3] + [tr_notes[0], q_text, sz_text] + pa_notes[:1] + \
              [n for n in rs_notes if n != ev_text]
    if ev < 0 and ev_text:
        reasons[0] = f"Negative: {ev_text}"
    return {"score": int(round(total)),
            "parts": {"quality": q, "trend": tr, "reason": rs, "size": sz, "participation": pa, "penalty": -pen_total},
            "reasons": reasons[:7], "penalties": pen, "lists": lists, "note": None, "setup": setup,
            "atr": None if t.atr is None else round(t.atr, 2), "sma20": None if t.smas.get(20) is None else round(t.smas[20], 2)}


# ── the positional plan (scan-plan-v3) ──────────────────────────────────────────────────────────────────────────────

def positional_plan(entry: Any, atr: Any, sma20: Any, eod_day: Optional[str] = None) -> Dict[str, Any]:
    """Entry − 2 × ATR(14) stop on daily closes, targets 2 and 4 × risk, trend exit on a daily close below the 20-day
    average. Never raises; without a price or ATR, plan_ok is False with a plan_note."""
    e, a, s20 = _f(entry), _f(atr), _f(sma20)
    out: Dict[str, Any] = {"rules": PLAN_RULES, "entry": None if e is None else round(e, 2), "stop_loss": None,
                           "target_1": None, "target_2": None, "risk_per_share": None, "rr_1": R1, "rr_2": R2,
                           "atr": None if a is None else round(a, 2), "sma20": None if s20 is None else round(s20, 2),
                           "trend_exit": None, "plan_ok": False, "plan_note": None}
    if e is None or e <= 0:
        out["plan_note"] = "No price when the stock reached 70, so no plan."
        return out
    if a is None or a <= 0:
        out["plan_note"] = "No ATR(14) for this stock (too little history), so no plan."
        return out
    risk = ATR_MULT * a
    if e - risk <= 0:
        out["plan_note"] = "Two ATRs exceed the price, so no stop level is possible."
        return out
    when = f" on {eod_day}" if eod_day else ""
    out.update(stop_loss=round(e - risk, 2), target_1=round(e + R1 * risk, 2), target_2=round(e + R2 * risk, 2),
               risk_per_share=round(risk, 2), plan_ok=True,
               trend_exit=(f"A daily close below the 20-day average ({_money(s20)}{when}; it rises as the trend runs)"
                           if s20 is not None else "A daily close below the 20-day average"))
    return out


# ── loaders (DaaS), cached per process ──────────────────────────────────────────────────────────────────────────────

SNAPSHOT_TTL_S = 1800
FILINGS_TTL_S = 120
FILINGS_PAGE = 500
FILINGS_MAX_PAGES = 10
_cache: Dict[str, Tuple[float, Any]] = {}
_locks: Dict[str, asyncio.Lock] = {}


async def _cached(key: str, ttl: float, load: Callable[[], Awaitable[Any]], clock: Callable[[], float] = time.monotonic) -> Any:
    hit = _cache.get(key)
    if hit and clock() - hit[0] < ttl:
        return hit[1]
    lock = _locks.setdefault(key, asyncio.Lock())
    async with lock:
        hit = _cache.get(key)
        if hit and clock() - hit[0] < ttl:
            return hit[1]
        val = await load()
        _cache[key] = (clock(), val)
        return val


def reset_caches() -> None:
    _cache.clear()


async def load_snapshot(get: Callable[..., Awaitable[Any]]) -> Tuple[Dict[str, Dict[str, Any]], Optional[str]]:
    """{SYMBOL: snapshot row} from DaaS /features/scan-snapshot, and its as-of day."""
    async def load():
        body = await get("/features/scan-snapshot", {}, timeout=60.0)
        rows = (body or {}).get("rows") or (body or {}).get("data") or []
        return {str(r["symbol"]).upper(): r for r in rows if r.get("symbol")}, (body or {}).get("as_of")
    return await _cached("snapshot", SNAPSHOT_TTL_S, load)


async def load_filings(get: Callable[..., Awaitable[Any]], since_day: str) -> Tuple[Dict[str, List[Dict[str, Any]]], str]:
    """{SYMBOL: filings} filed since `since_day` (ISO, the last session's day), all pages; and when they were read."""
    async def load():
        rows: List[Dict[str, Any]] = []
        for page in range(FILINGS_MAX_PAGES):
            body = await get("/announcements", {"filed_from": since_day, "limit": FILINGS_PAGE,
                                                "offset": page * FILINGS_PAGE}, timeout=60.0)
            got = (body or {}).get("data") or []
            rows += got
            if len(got) < FILINGS_PAGE:
                break
        out: Dict[str, List[Dict[str, Any]]] = {}
        for r in rows:
            sym = str(r.get("ticker_symbol") or "").upper()
            if sym:
                out.setdefault(sym, []).append(r)
        return out, datetime.now(timezone.utc).isoformat(timespec="seconds")
    return await _cached(f"filings:{since_day}", FILINGS_TTL_S, load)


def usual_share_now(at: datetime, live: bool) -> float:
    """Share of a day's volume usually traded by `at` (the Early-movers curve), from 09:15; 1.0 when not live."""
    if not live:
        return 1.0
    ist = at.astimezone(EM_IST)
    m = ist.hour * 60 + ist.minute + ist.second / 60.0 - EM.OPEN_MIN
    if m <= 0:
        return EM.VOLUME_CURVE[0]
    slot = min(len(EM.VOLUME_CURVE) - 1, int(m // 5))
    prev = EM.VOLUME_CURVE[slot - 1] if slot > 0 else 0.0
    frac = min(1.0, max(0.0, (m - 5 * slot) / 5.0))
    return max(EM.VOLUME_CURVE[0], prev + (EM.VOLUME_CURVE[slot] - prev) * frac)   # floor: the first 5 minutes' share


QUERIES_TTL_S = 1800
QUERIES_PAGE = 120                      # the route's cap


async def load_exchange_queries(get: Callable[..., Awaitable[Any]]) -> Dict[str, List[Dict[str, Any]]]:
    """{SYMBOL: filings} — the company's replies to the exchange's surveillance queries in the last 30 days
    (DaaS /desk/filings?family=exchange, paged)."""
    async def load():
        rows: List[Dict[str, Any]] = []
        for page in range(FILINGS_MAX_PAGES):
            body = await get("/desk/filings", {"family": "exchange", "days": 30, "limit": QUERIES_PAGE,
                                               "offset": page * QUERIES_PAGE}, timeout=60.0)
            got = (body or {}).get("articles") or []
            rows += got
            if len(got) < QUERIES_PAGE:
                break
        out: Dict[str, List[Dict[str, Any]]] = {}
        for r in rows:
            sym = str(r.get("symbol") or "").upper()
            if sym:
                out.setdefault(sym, []).append(r)
        return out
    return await _cached("exchange_queries", QUERIES_TTL_S, load)


FUND_KEYS = ("roce_pct", "roe_pct", "debt_to_equity", "profit_margin_pct", "earnings_consistency_score", "promoter_pct",
             "fii_pct", "dii_pct", "market_cap_cr", "promoter_pledged_pct", "pat_growth_yoy_pct", "volatility_1y_pct")


async def build_scores(get: Callable[..., Awaitable[Any]], panel: Any, ref: Any, entries: Sequence[Dict[str, Any]],
                       at: datetime, *, live: bool, eod_day: str,
                       side_reader: Optional[Callable[[List[str]], Awaitable[Any]]] = None
                       ) -> Tuple[Dict[str, Dict[str, Any]], Dict[str, Any]]:
    """Score every stock with a list entry today. `panel` = the dashboard's panel (history + today's bar as the last row),
    `entries` = today's list entries (signals.today). Returns ({SYMBOL: score result + name}, meta). A source that cannot be
    read leaves its part without that input and says so in meta['warnings']; never raises for a source."""
    warnings: List[str] = []
    lists: Dict[str, List[Dict[str, Any]]] = {}
    for e in entries:
        sym = e.get("symbol")
        if sym:
            lists.setdefault(sym, []).append({"id": e.get("widget_id"), "title": e.get("widget_title"),
                                              "direction": e.get("direction")})
    pos = {s: i for i, s in enumerate(panel.symbols)}
    syms = [s for s in lists if s in pos]
    snap, snap_as_of, fil, fil_at, queries, sides = {}, None, {}, None, {}, {}
    try:
        snap, snap_as_of = await load_snapshot(get)
    except Exception as e:  # noqa: BLE001
        warnings.append(f"The feature-store snapshot could not be read ({type(e).__name__}): no ETF flag or price band.")
    try:
        fil, fil_at = await load_filings(get, eod_day)
    except Exception as e:  # noqa: BLE001
        warnings.append(f"Exchange filings could not be read ({type(e).__name__}): the reason part has no events.")
    try:
        queries = await load_exchange_queries(get)
    except Exception as e:  # noqa: BLE001
        warnings.append(f"The exchange's queries could not be read ({type(e).__name__}): that penalty is not applied.")
    if live and side_reader is not None and syms:
        try:
            sides = (await side_reader(syms)) or {}
        except Exception as e:  # noqa: BLE001
            warnings.append(f"Kite trade sides could not be read ({type(e).__name__}).")
    share = usual_share_now(at, live)
    F = getattr(ref, "fundamentals", {}) or {}
    members = getattr(ref, "members", {}) or {}
    names = getattr(ref, "names", {}) or {}
    fno = getattr(ref, "fno", set()) or set()
    out: Dict[str, Dict[str, Any]] = {}
    for sym in lists:
        if sym not in pos:
            out[sym] = {"score": None, "parts": None, "reasons": [], "penalties": [], "note": "Not scored: no price history",
                        "lists": [{"id": x["id"], "title": x["title"]} for x in lists[sym]], "name": names.get(sym, "")}
            continue
        j = pos[sym]
        hc, hh, hl, hv = panel.close[:-1, j], panel.high[:-1, j], panel.low[:-1, j], panel.volume[:-1, j]
        ok = np.isfinite(hc) & np.isfinite(hh) & np.isfinite(hl)
        q = sides.get(sym) or {}
        inp = StockInputs(symbol=sym, name=names.get(sym, ""), price=_f(panel.close[-1, j]),
                          volume_today=_f(panel.volume[-1, j]), closes=hc[ok], highs=hh[ok], lows=hl[ok],
                          volumes=np.nan_to_num(hv[ok]),
                          fundamentals={k: _f((F.get(k) or {}).get(sym)) for k in FUND_KEYS},
                          snapshot=snap.get(sym) or {}, members={k for k, v in members.items() if sym in v},
                          fno=sym in fno, filings=fil.get(sym, []), lists=lists[sym], usual_share=share,
                          ask_trades=q.get("ask_trades"), bid_trades=q.get("bid_trades"),
                          exchange_queries=queries.get(sym, []))
        try:
            res = score(inp)
        except Exception:  # noqa: BLE001 — one stock failing never blanks the rest; logged with its trace
            logger.exception("signal strength: scoring %s failed", sym)
            res = {"score": None, "parts": None, "reasons": [], "penalties": [], "note": "Not scored: an error",
                   "lists": [{"id": x["id"], "title": x["title"]} for x in lists[sym]]}
        res["name"] = inp.name
        out[sym] = res
    scored = [r for r in out.values() if r.get("score") is not None]
    meta = {"threshold": THRESHOLD, "weights": dict(WEIGHTS), "rules": RULES_TEXT, "plan_rules": PLAN_TEXT,
            "caveat": CAVEAT, "warnings": warnings,
            "as_of": {"fundamentals": getattr(ref, "fundamentals_as_of", None), "eod": eod_day, "snapshot": snap_as_of,
                      "filings": fil_at},
            "counts": {"scored": len(scored), "strong": sum(1 for r in scored if r["score"] >= THRESHOLD),
                       "below": sum(1 for r in scored if r["score"] < THRESHOLD),
                       "not_scored": len(out) - len(scored)}}
    return out, meta


def strong_candidate(sym: str, res: Dict[str, Any], price: Any, eod_day: str) -> Dict[str, Any]:
    """The frozen record of a stock that reached the threshold: its score now and the scan-plan-v3 levels at `price`."""
    return {"symbol": sym, "name": res.get("name", ""), "score_at": res.get("score"), "parts_at": res.get("parts"),
            "reasons_at": res.get("reasons"), "penalties_at": res.get("penalties"), "lists_at": res.get("lists"),
            **positional_plan(price, res.get("atr"), res.get("sma20"), eod_day)}
