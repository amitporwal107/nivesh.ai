"""Market context as Evidence (PRD F2): regime, trend, India VIX and breadth, all from research/charting/regime.py.
No rule is re-implemented here; this only wraps the existing point-in-time features into the shared record."""
from __future__ import annotations

from typing import Any, Dict, List

from . import _research
from .evidence import UNCALIBRATED_CONFIDENCE, Evidence, unavailable

SKILL = "market_intelligence"
BENCHMARK = "NIFTY 500"


def _src(name: str, as_of: str) -> List[Dict[str, Any]]:
    return [{"name": name, "timestamp": as_of}]


def _fv(fv) -> Dict[str, Any]:
    return {"value": fv.value, "status": fv.status, "reason": fv.reason}


def market_context(as_of: str) -> List[Evidence]:
    ctx, regime, _rw, _rs = _research.load()
    import pandas as pd

    ts = pd.Timestamp(as_of).normalize()
    out: List[Evidence] = []

    bench = ctx.load_index_history(BENCHMARK)
    reg = regime.market_regime(bench, ts)
    label = reg["regime"]
    src = _src(f"research/index_history/data/NIFTY_500.csv (regime.market_regime v{regime.FEATURE_VERSION})", as_of)
    if label.status != "OK":
        out.append(unavailable(SKILL, None, as_of, "market", f"{BENCHMARK} regime", label.reason, src))
    else:
        impact = {"BULL": "supports", "BEAR": "opposes"}.get(label.value, "neutral")
        out.append(Evidence(
            skill=SKILL, symbol=None, as_of=as_of, horizon="market",
            observation=f"{BENCHMARK} regime is {label.value} (close vs SMA200 and its slope).",
            interpretation={"BULL": "Market backdrop favours long positions.",
                            "BEAR": "Market backdrop opposes new long positions.",
                            "SIDEWAYS": "No directional market backdrop."}[label.value],
            confidence=UNCALIBRATED_CONFIDENCE, decision_impact=impact, sources=src,
            conditions=[f"Regime changes if {BENCHMARK} closes on the other side of its SMA200."],
            data={k: _fv(v) for k, v in reg.items()},
        ))

    tc = regime.trend_classification(bench, ts)
    cls = tc["class"]
    if cls.status != "OK":
        out.append(unavailable(SKILL, None, as_of, "market", f"{BENCHMARK} trend class", cls.reason, src))
    else:
        impact = ("supports" if cls.value in ("BULL", "STRONG_BULL")
                  else "opposes" if cls.value in ("BEAR", "STRONG_BEAR") else "neutral")
        out.append(Evidence(
            skill=SKILL, symbol=None, as_of=as_of, horizon="market",
            observation=f"{BENCHMARK} 20-session trend is {cls.value} (OLS slope and ADX 14).",
            interpretation="Short-term direction and strength of the market.",
            confidence=UNCALIBRATED_CONFIDENCE, decision_impact=impact, sources=src,
            conditions=["Re-evaluate each session; the class uses only the last 20 sessions."],
            data={k: _fv(v) for k, v in tc.items()},
        ))

    vix = regime.india_vix_at(ts)
    vsrc = _src("research/index_history/data/INDIA_VIX.csv", as_of)
    if vix.status != "OK":
        out.append(unavailable(SKILL, None, as_of, "market", "India VIX", vix.reason, vsrc))
    else:
        out.append(Evidence(
            skill=SKILL, symbol=None, as_of=as_of, horizon="market",
            observation=f"India VIX closed at {vix.value:.2f}.",
            interpretation="Level of expected market volatility; read with the regime, not alone.",
            confidence=UNCALIBRATED_CONFIDENCE, decision_impact="neutral", sources=vsrc,
            data={"india_vix": vix.value},
        ))

    br = regime.breadth_at(ts)
    bsrc = _src("research/index_history/data/BREADTH_UNIVERSE.csv", as_of)
    adr = br.get("advance_decline_ratio")
    if adr is None or adr.status != "OK":
        reason = adr.reason if adr is not None else "NO_DATA_FOR_DATE"
        out.append(unavailable(SKILL, None, as_of, "market", "market breadth", reason, bsrc))
    else:
        out.append(Evidence(
            skill=SKILL, symbol=None, as_of=as_of, horizon="market",
            observation=f"Advance/decline ratio {adr.value:.2f} across the breadth universe.",
            interpretation="Participation behind the index move; above 1 means more advancers than decliners.",
            confidence=UNCALIBRATED_CONFIDENCE,
            decision_impact="supports" if adr.value > 1 else "opposes" if adr.value < 1 else "neutral",
            sources=bsrc, data={k: _fv(v) for k, v in br.items()},
        ))
    return out
