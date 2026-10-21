"""Multi-timeframe trend and conflicts as Evidence (PRD F4).

Weekly and monthly bars come from research.charting.resample on the daily bars cut at `as_of`, so nothing later than
`as_of` is seen. The trailing weekly/monthly bar is always flagged incomplete by the resampler and is DROPPED here: an
unfinished bar is never used as confirmation. Trend class is research.charting.regime.trend_classification."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from . import _research
from .evidence import UNCALIBRATED_CONFIDENCE, Evidence, unavailable

SKILL = "technical"
BULLISH = ("BULL", "STRONG_BULL")
BEARISH = ("BEAR", "STRONG_BEAR")
ORDER = ("daily", "weekly", "monthly")


def _direction(cls: str) -> str:
    return "bullish" if cls in BULLISH else "bearish" if cls in BEARISH else "flat"


def trend_by_timeframe(symbol: str, bars, as_of: str) -> Dict[str, Dict[str, Any]]:
    """{timeframe: {"class", "status", "reason"}} for daily, weekly, monthly. `bars` is the symbol's daily frame."""
    _ctx, regime, rw, resample = _research.load()
    import pandas as pd

    ts = pd.Timestamp(as_of).normalize()
    daily = bars.copy()
    daily["date"] = pd.to_datetime(daily["date"]).dt.normalize()
    daily = daily[daily["date"] <= ts].sort_values("date").reset_index(drop=True)

    # as_of must be a session of this symbol. Otherwise weekly/monthly would quietly answer from an older bar while
    # claiming to be as of `as_of` (e.g. a date inside the sealed block, or a holiday), so every timeframe is withheld.
    if rw.is_sealed_gap(ts):
        reason = "SEALED_GAP"
    elif daily.empty or not (daily["date"] == ts).any():
        reason = "NO_DATA_FOR_DATE"
    else:
        reason = None
    if reason:
        return {tf: {"class": None, "status": "UNAVAILABLE", "reason": reason} for tf in ORDER}

    frames = {"daily": (daily, ts)}
    for name, fn in (("weekly", resample.resample_weekly), ("monthly", resample.resample_monthly)):
        rs = fn(daily) if not daily.empty else daily
        done = rs[~rs["incomplete"]].reset_index(drop=True) if len(rs) else rs
        frames[name] = (done, done["date"].iloc[-1] if len(done) else None)

    out: Dict[str, Dict[str, Any]] = {}
    for name, (frame, t) in frames.items():
        if t is None or frame.empty:
            out[name] = {"class": None, "status": "UNAVAILABLE", "reason": "NO_DATA_FOR_DATE"}
            continue
        cls = regime.trend_classification(frame, t)["class"]
        out[name] = {"class": cls.value, "status": cls.status, "reason": cls.reason, "bar_date": str(pd.Timestamp(t).date())}
    return out


def timeframe_evidence(symbol: str, bars, as_of: str) -> List[Evidence]:
    trends = trend_by_timeframe(symbol, bars, as_of)
    src = [{"name": f"Kite daily bars for {symbol}, resampled (research.charting.resample)", "timestamp": as_of}]
    out: List[Evidence] = []
    ok: Dict[str, str] = {}
    for tf in ORDER:
        t = trends[tf]
        if t["status"] != "OK":
            out.append(unavailable(SKILL, symbol, as_of, tf, f"{symbol} {tf} trend", t["reason"], src))
            continue
        d = _direction(t["class"])
        ok[tf] = d
        out.append(Evidence(
            skill=SKILL, symbol=symbol, as_of=as_of, horizon=tf,
            observation=f"{symbol} {tf} trend is {t['class']}.",
            interpretation={"bullish": "Trend favours longs on this timeframe.",
                            "bearish": "Trend opposes longs on this timeframe.",
                            "flat": "No clear trend on this timeframe."}[d],
            confidence=UNCALIBRATED_CONFIDENCE,
            decision_impact={"bullish": "supports", "bearish": "opposes", "flat": "neutral"}[d],
            sources=src, conditions=[f"Trend class is recomputed when the next {tf} bar completes."],
            data=t,
        ))

    out.extend(_conflicts(symbol, as_of, ok, src))
    return out


def _conflicts(symbol: str, as_of: str, ok: Dict[str, str], src) -> List[Evidence]:
    """A contradiction record whenever a higher timeframe points the other way from a lower one."""
    found: List[Evidence] = []
    for i, low in enumerate(ORDER):
        for high in ORDER[i + 1:]:
            a, b = ok.get(low), ok.get(high)
            if a and b and {a, b} == {"bullish", "bearish"}:
                msg = f"{high} trend is {b} while {low} trend is {a}."
                found.append(Evidence(
                    skill=SKILL, symbol=symbol, as_of=as_of, horizon=f"{low}/{high}",
                    observation=f"{symbol}: {msg}",
                    interpretation=f"The higher timeframe ({high}) outweighs the {low}; a {a} trade runs against it.",
                    confidence=UNCALIBRATED_CONFIDENCE, decision_impact="opposes",
                    contradictions=[msg], sources=src,
                    conditions=[f"Conflict clears when the {low} and {high} trends agree."],
                    data={low: a, high: b},
                ))
    return found
