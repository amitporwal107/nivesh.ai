"""Results signal in the AI scanner (docs/EARNINGS_SURPRISE_TRACKER.md §4d; owner, 27 Oct 2026).

"Show extra strength signal for strong-results candidate stocks in the AI scanner." The engine's stored scores
(positional_signals, stock_technical_features) stay purely technical and auditable: this adjustment is applied at READ
time by GET /api/positional/picks and /watchlist, before their sort, min-score filter and limit. Each row gains
`results_signal` ({strength, points, basis, reasons, filed_at, sessions_since} or null) and `base_final_score`;
`final_score` becomes clamp(base + points / 100, 0, 1), so every merge that ranks by final_score uses it unchanged.
Stage and actionability are untouched.

Every constant below is a provisional research setting, not validated; the adjustment has not been tested (RULE_TEXT).
A source failure means no adjustment and a gap, never a crash and never a guessed signal.
"""
from __future__ import annotations

import asyncio
import logging
import time
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Sequence, Tuple

from . import loaders, scoring as sc

logger = logging.getLogger(__name__)

RULE_TEXT = "Strong results add up to +10 points, weak results subtract up to 10; this adjustment has not been tested yet."

# Window and decay: a results filing counts for WINDOW_SESSIONS sessions, counted from the first session that can react
# to it (§4a: filed before the 15:30 IST close on a session day → that session, else the next). That session is 0 (full
# points); points × (1 − sessions_since / 5), so session 4 keeps a fifth and session 5 nothing.
WINDOW_SESSIONS = 5

# STRONG on the figures (+10): the quarter's figures are stored and at least STRONG_MIN_MET of these hold —
PAT_YOY_STRONG_PCT = 20.0          # PAT YoY ≥ +20 % (a loss a year ago turned into a profit counts as met)
REVENUE_YOY_STRONG_PCT = 10.0      # revenue YoY ≥ +10 %
MARGIN_YOY_STRONG_BPS = 50.0       # EBITDA margin YoY ≥ +50 bps
STRONG_MIN_MET = 2                 # … or a RATED §4a metric verdict "above" as one of them
# — and no red flag (exceptional items > 20 % of PBT, other income > 30 % of PBT; §4b's thresholds) and no rated
# "below". WEAK on the figures (−10): PAT YoY ≤ −10 % with revenue YoY < +5 %, or a rated verdict below / well below.
PAT_YOY_WEAK_PCT = -10.0
REVENUE_YOY_WEAK_BELOW_PCT = 5.0
FIGURES_POINTS = {"strong": 10.0, "weak": -10.0}
RED_FLAGS = ("exceptional_items", "other_income")

# Figures not stored yet: the filing analysis (Mongo event_ai_analysis) at confidence ≥ 75 — moderately positive or
# better → +5, moderately negative or worse → −5.
FILING_MIN_CONFIDENCE = 75.0
POSITIVE_BANDS = ("moderately_positive", "strongly_positive", "extremely_positive")
NEGATIVE_BANDS = ("moderately_negative", "strongly_negative", "extremely_negative")
FILING_POINTS = {"strong": 5.0, "weak": -5.0}

CACHE_S = 600.0                    # ≤ 10 minutes
FAIL_CACHE_S = 60.0                # a failure is retried after a minute, not on every scanner request
TIMEOUT_S = 25.0                   # the scanner routes never wait longer than this for the signal
CALENDAR_BACK_DAYS, CALENDAR_AHEAD_DAYS = 21, 10
FIN_QUARTERS = 8

_state: Dict[str, Any] = {"at": None, "ttl": 0.0, "value": None}
_lock: Optional[asyncio.Lock] = None


# ── pure rules ────────────────────────────────────────────────────────────────────────────────────────────────────

def sessions_since(filed_at: datetime, sessions: Sequence[date], today: date) -> Optional[int]:
    """Sessions after the first reacting session, up to today (0 = today is that session, or it is still ahead)."""
    fs = sc.first_session(filed_at, sessions)
    if fs is None:
        return None
    if fs >= today:
        return 0
    return sum(1 for s in sessions if fs < s <= today)


def decayed(points: float, since: int) -> float:
    if since < 0 or since >= WINDOW_SESSIONS:
        return 0.0
    return points * (1.0 - since / WINDOW_SESSIONS)


def _day(t: Optional[datetime]) -> str:
    return t.astimezone(sc.IST).strftime("%d %b").lstrip("0") if t else "date unknown"


def figures_facts(ev: Dict[str, Any], rows: Sequence[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """The declared quarter's YoY facts from the stored quarters, or None when that quarter is not stored."""
    q = sc.period_end_of(ev.get("period_label"))
    by = sc._rows_by_end(rows)
    if q is None or q not in by:
        return None
    t, t4 = by[q], by.get(sc.shift_quarters(q, 4))
    pat, pat4 = sc._fig(t, "pat"), sc._fig(t4, "pat")
    m, m4 = sc._margin(t), sc._margin(t4)
    qual = sc.quality(rows, q)
    rated = sc.surprise(ev.get("metrics") or [])["metrics"]
    return {
        "quarter": q, "pat_yoy": sc.growth_pct(pat, pat4),
        "loss_to_profit": pat is not None and pat4 is not None and pat4 <= 0 < pat,
        "revenue_yoy": sc.growth_pct(sc._fig(t, "revenue"), sc._fig(t4, "revenue")),
        "margin_bps": (m - m4) * 100.0 if m is not None and m4 is not None else None,
        "red_flags": [f for f in qual["flags"] if f["code"] in RED_FLAGS],
        "above": [k for k in sc.METRICS if rated[k].get("verdict") == "above"],
        "below": [k for k in sc.METRICS if rated[k].get("verdict") == "below"],
    }


def _facts_text(ev: Dict[str, Any], f: Dict[str, Any], filed_at: Optional[datetime]) -> str:
    q = str(ev.get("period_label") or "").split(" (")[0] or f["quarter"].isoformat()
    bits = []
    if f["loss_to_profit"]:
        bits.append("PAT turned to a profit from a loss a year earlier")
    elif f["pat_yoy"] is not None:
        bits.append(f"PAT {f['pat_yoy']:+.1f} % YoY")
    if f["revenue_yoy"] is not None:
        bits.append(f"revenue {f['revenue_yoy']:+.1f} %")
    if f["margin_bps"] is not None:
        bits.append(f"EBITDA margin {f['margin_bps']:+.0f} bps")
    return f"{q} {', '.join(bits) or 'figures stored'} (filed {_day(filed_at)})"


def classify_figures(f: Dict[str, Any]) -> Tuple[Optional[str], List[str]]:
    """(strong | weak | None, extra reasons). Weak is checked first."""
    names = {"pat": "PAT", "revenue": "revenue"}
    weak_pat = f["pat_yoy"] is not None and f["revenue_yoy"] is not None and f["pat_yoy"] <= PAT_YOY_WEAK_PCT \
        and f["revenue_yoy"] < REVENUE_YOY_WEAK_BELOW_PCT
    if f["below"] or weak_pat:
        extra = [f"{names[k]} below historical trend" for k in f["below"]]
        return "weak", extra
    met = []
    if f["loss_to_profit"] or (f["pat_yoy"] is not None and f["pat_yoy"] >= PAT_YOY_STRONG_PCT):
        met.append("pat")
    if f["revenue_yoy"] is not None and f["revenue_yoy"] >= REVENUE_YOY_STRONG_PCT:
        met.append("revenue")
    if f["margin_bps"] is not None and f["margin_bps"] >= MARGIN_YOY_STRONG_BPS:
        met.append("margin")
    if f["above"]:
        met.append("above")
    if len(met) < STRONG_MIN_MET:
        return None, []
    if f["red_flags"]:
        return None, []                    # vetoed: the quality red flag outweighs the growth
    return "strong", [f"{names[k]} above historical trend" for k in f["above"]]


def classify_filing(doc: Optional[Dict[str, Any]]) -> Optional[str]:
    if not doc:
        return None
    conf = sc.num(doc.get("confidence_score"))
    if conf is None or conf < FILING_MIN_CONFIDENCE:
        return None
    band = doc.get("net_band")
    return "strong" if band in POSITIVE_BANDS else "weak" if band in NEGATIVE_BANDS else None


def signal_for(ev: Dict[str, Any], fin_rows: Optional[Sequence[Dict[str, Any]]], docs: Sequence[Dict[str, Any]],
               sessions: Sequence[date], now: datetime) -> Optional[Dict[str, Any]]:
    """One results meeting's signal at `now`, or None (outside the window, not yet broadcast, or nothing to say)."""
    from .build import filed_at_of, pick_analysis, status_of

    today = now.astimezone(sc.IST).date()
    status = status_of(ev)
    if status == "upcoming":
        return None
    try:
        ev_d = date.fromisoformat(str(ev.get("event_date"))[:10])
    except ValueError:
        return None
    filed_at = filed_at_of(ev)
    facts = figures_facts(ev, fin_rows or []) if status == "declared" and filed_at is not None and filed_at <= now else None
    if facts is not None:
        strength, extra = classify_figures(facts)
        if strength is None:
            return None
        basis, base_points = "figures", FIGURES_POINTS[strength]
        reasons = [_facts_text(ev, facts, filed_at), *extra]
    else:
        doc = pick_analysis(docs, ev_d, now)
        strength = classify_filing(doc)
        if strength is None:
            return None
        ts = sc.parse_ts(doc.get("event_ts"))
        filed_at = min(x for x in (filed_at, ts) if x is not None) if (filed_at or ts) else None
        if filed_at is None or filed_at > now:
            return None
        basis, base_points = "filing_analysis", FILING_POINTS[strength]
        band = str(doc.get("net_band")).replace("_", " ")
        reasons = [f"Filing analysis: {band}, confidence {sc.num(doc.get('confidence_score')):.0f} % (figures not filed yet)"]
    since = sessions_since(filed_at, sessions, today)
    if since is None:
        return None
    pts = decayed(base_points, since)
    if pts == 0:
        return None
    return {"strength": strength, "points": round(pts, 1), "basis": basis, "reasons": reasons,
            "filed_at": filed_at.isoformat(), "sessions_since": since}


def apply(rows: List[Dict[str, Any]], signals: Dict[str, Dict[str, Any]], key: str = "final_score",
          symbol_key: str = "nse_symbol") -> List[Dict[str, Any]]:
    """Adds results_signal and base_final_score to each row and sets final_score = clamp(base + points / 100, 0, 1)."""
    for r in rows:
        base = sc.num(r.get(key))
        sig = signals.get(str(r.get(symbol_key) or "").upper())
        r["base_final_score"] = base
        r["results_signal"] = sig
        if base is not None:
            r[key] = round(sc.clamp(base + (sig["points"] / 100.0 if sig else 0.0), 0.0, 1.0), 4)
    return rows


def meta(signals: Dict[str, Dict[str, Any]], gap: Optional[str], applied: int) -> Dict[str, Any]:
    return {"rule": RULE_TEXT, "tested": False, "signals": len(signals), "applied": applied, "gap": gap,
            "source": "results meetings in the last 5 sessions (DaaS expectations), stored quarters (DaaS financials), "
                      "filing analysis (Mongo event_ai_analysis)"}


# ── loading ───────────────────────────────────────────────────────────────────────────────────────────────────────

async def compute(now: datetime, db=None) -> Tuple[Dict[str, Dict[str, Any]], List[str]]:
    """{symbol: signal} at `now`, and gaps. Raises when the results calendar cannot be read."""
    from services.copilot_tools import daas_client

    if not daas_client.is_configured():
        raise loaders.SourceUnavailable("DaaS is not configured")
    async with loaders.pooled():
        return await _compute(now, db)


async def _compute(now: datetime, db=None) -> Tuple[Dict[str, Dict[str, Any]], List[str]]:
    if db is None:
        from deps import db as _db
        db = _db
    today = now.astimezone(sc.IST).date()
    sess, cal_gap = await loaders.sessions(today - timedelta(days=CALENDAR_BACK_DAYS), today + timedelta(days=CALENDAR_AHEAD_DAYS))
    past = [s for s in sess if s <= today]
    if len(past) < WINDOW_SESSIONS + 1:
        raise loaders.SourceUnavailable("the session calendar is too short")
    start = past[-(WINDOW_SESSIONS + 1)]          # a filing after that session's close reacts in the window's first session
    events, _meta, _first, exp_gaps = await loaders.expectations(loaders.windows(start, today))
    evs = [e for e in events if e.get("status") == "declared"]
    gaps = [g for g in (cal_gap, *exp_gaps) if g]
    figs = {str(e["symbol"]).upper(): e.get("basis") != "standalone" for e in evs if e.get("filed_state") == "figures"}
    fin, fin_gaps, fin_src = await loaders.quarterly(figs)
    if fin_src:
        gaps.append(fin_src)
    syms = [str(e["symbol"]).upper() for e in evs]
    an, an_gap = await loaders.filing_analysis(db, syms, datetime.combine(start - timedelta(days=1), datetime.min.time(), sc.IST), now)
    if an_gap:
        gaps.append(an_gap)
    latest: Dict[str, Dict[str, Any]] = {}
    for e in sorted(evs, key=lambda e: str(e.get("event_date"))):       # a symbol's latest declared meeting decides
        latest[str(e["symbol"]).upper()] = e
    out: Dict[str, Dict[str, Any]] = {}
    for sym, e in latest.items():
        sig = signal_for(e, fin.get(sym), an.get(sym) or [], sess, now)
        if sig is not None:
            out[sym] = sig
    return out, gaps


async def current(now: Optional[datetime] = None, db=None) -> Tuple[Dict[str, Dict[str, Any]], Optional[str]]:
    """({symbol: signal}, gap) for the scanner routes: cached ≤ 10 minutes, one computation at a time, bounded by
    TIMEOUT_S. Any failure → ({}, gap): no adjustment, never a crash."""
    global _lock
    t = time.monotonic()
    if _state["at"] is not None and t - _state["at"] < _state["ttl"]:
        return _state["value"]
    if _lock is None:
        _lock = asyncio.Lock()
    async with _lock:
        t = time.monotonic()
        if _state["at"] is not None and t - _state["at"] < _state["ttl"]:
            return _state["value"]
        try:
            sigs, gaps = await asyncio.wait_for(compute(now or datetime.now(timezone.utc), db), TIMEOUT_S)
            value, ttl = (sigs, "; ".join(gaps) or None), CACHE_S
        except asyncio.TimeoutError:
            value, ttl = ({}, f"results signal not applied: it took longer than {TIMEOUT_S:g} s"), FAIL_CACHE_S
        except Exception as e:  # noqa: BLE001 — never break the scanner
            logger.warning("results signal unavailable: %s: %s", type(e).__name__, str(e)[:200])
            value, ttl = ({}, f"results signal not applied: {type(e).__name__}: {str(e)[:160]}"), FAIL_CACHE_S
        _state.update(at=time.monotonic(), ttl=ttl, value=value)
        return value


def clear_cache() -> None:
    _state.update(at=None, ttl=0.0, value=None)
