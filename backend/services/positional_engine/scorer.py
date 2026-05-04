"""Scoring + stage classification.

Takes the feature pack from feature_calculator and produces:
  - Six sub-scores in [0, 1]: trend, momentum, structure, accumulation,
    sector, risk.
  - Final weighted score in [0, 1].
  - Stage classification: ACCUMULATION | EARLY_BREAKOUT | BREAKOUT |
    EXTENDED | WEAK.
  - Confidence: HIGH | MEDIUM | LOW.

Each band is a *linear ramp*: input → 0..1. Missing inputs collapse to
neutral 0.5 so a partially-observed stock isn't unfairly punished.
"""
from __future__ import annotations

from typing import Dict, List, Optional, Sequence

# Weights — sum to 1.0. Match the spec the user provided.
DEFAULT_WEIGHTS: Dict[str, float] = {
    "trend":        0.25,
    "structure":    0.20,
    "accumulation": 0.20,
    "momentum":     0.15,
    "sector":       0.10,
    "risk":         0.10,
}


# ── Bands ────────────────────────────────────────────────────────────────
def _ramp(v: Optional[float], lo: float, hi: float,
          *, good_is_high: bool = True) -> float:
    """Clamp+map v∈[lo,hi]→[0,1]. Missing→0.5 neutral."""
    if v is None:
        return 0.5
    if hi == lo:
        return 0.5
    pct = (v - lo) / (hi - lo)
    pct = max(0.0, min(1.0, pct))
    return pct if good_is_high else 1.0 - pct


# ── Sub-scorers ──────────────────────────────────────────────────────────
def score_trend(f: Dict[str, Optional[float]]) -> float:
    """Above 50 DMA + 50>200 + slope rising = bullish trend."""
    parts: List[float] = []
    close = f.get("close")
    s50 = f.get("sma_50")
    s200 = f.get("sma_200")

    if close is not None and s50 is not None:
        parts.append(1.0 if close > s50 else 0.0)
    if close is not None and s200 is not None:
        parts.append(1.0 if close > s200 else 0.0)
    if s50 is not None and s200 is not None:
        parts.append(1.0 if s50 > s200 else 0.0)

    # Slope strength: 0%/bar weak, 0.5%/bar strong
    parts.append(_ramp(f.get("slope_20_pct"), lo=0.0, hi=0.5))

    return sum(parts) / len(parts) if parts else 0.5


def score_momentum(f: Dict[str, Optional[float]]) -> float:
    """RSI 50–65 sweet spot for positional. MACD positive + rising hist."""
    parts: List[float] = []

    rsi_v = f.get("rsi_14")
    if rsi_v is not None:
        # Triangular: peaks at 57.5, drops off below 45 and above 75.
        if rsi_v < 45:
            r = 0.0
        elif rsi_v <= 57.5:
            r = (rsi_v - 45) / 12.5
        elif rsi_v <= 70:
            r = 1.0 - (rsi_v - 57.5) / 12.5
        else:
            r = max(0.0, 0.3 - (rsi_v - 70) / 15)   # late entry penalty
        parts.append(max(0.0, min(1.0, r)))

    macd_v = f.get("macd")
    sig_v = f.get("macd_signal")
    if macd_v is not None and sig_v is not None:
        parts.append(1.0 if macd_v > sig_v else 0.0)

    # 5-day return: 0% weak, 5% strong
    parts.append(_ramp(f.get("return_5d_pct"), lo=0.0, hi=5.0))

    return sum(parts) / len(parts) if parts else 0.5


def score_structure(f: Dict[str, Optional[float]]) -> float:
    """Tight range + breakout proximity = ready to move."""
    parts: List[float] = []

    # Tight range: ATR% low is good. 1% tight, 4% loose
    atr_pct = f.get("atr_pct")
    parts.append(_ramp(atr_pct, lo=1.0, hi=4.0, good_is_high=False))

    # Bollinger squeeze: lower width = tighter
    parts.append(_ramp(f.get("bb_width_20"), lo=0.05, hi=0.20, good_is_high=False))

    # Breakout proximity: at or just above 20-day high is best
    bp = f.get("breakout_proximity_pct")
    if bp is not None:
        if -2.0 <= bp <= 1.0:
            parts.append(1.0)
        elif bp > 1.0:
            # Already extended past breakout
            parts.append(max(0.0, 1.0 - (bp - 1.0) / 5.0))
        else:
            parts.append(max(0.0, 1.0 - (-bp) / 8.0))
    else:
        parts.append(0.5)

    return sum(parts) / len(parts) if parts else 0.5


def score_accumulation(f: Dict[str, Optional[float]]) -> float:
    """Rising delivery % + volume buildup."""
    parts: List[float] = []

    # Delivery trend: -10% weak, +20% strong accumulation
    parts.append(_ramp(f.get("delivery_trend_pct"), lo=-10.0, hi=20.0))

    # Volume z-score: 0 neutral, +2 strong buildup
    vz = f.get("volume_z_20")
    if vz is not None:
        if vz < 0:
            parts.append(0.4)
        else:
            parts.append(min(1.0, 0.5 + vz / 4.0))
    else:
        parts.append(0.5)

    return sum(parts) / len(parts) if parts else 0.5


def score_sector(rs_vs_nifty_pct: Optional[float]) -> float:
    """Sector relative strength vs Nifty over ~20 bars.
    >0 means sector outperforming. -5%→0, +5%→1."""
    return _ramp(rs_vs_nifty_pct, lo=-5.0, hi=5.0)


def score_risk(f: Dict[str, Optional[float]]) -> float:
    """Higher = lower risk (better)."""
    parts: List[float] = []

    # Distance to support: too far = high risk; ideal 1-5%
    d = f.get("dist_to_support_pct")
    if d is not None:
        if d <= 0:
            parts.append(0.0)
        elif d <= 5:
            parts.append(1.0)
        elif d <= 12:
            parts.append(1.0 - (d - 5) / 7)
        else:
            parts.append(0.0)
    else:
        parts.append(0.5)

    # Volatility: ATR% low is safer
    parts.append(_ramp(f.get("atr_pct"), lo=1.5, hi=5.0, good_is_high=False))

    return sum(parts) / len(parts) if parts else 0.5


# ── Stage classifier ─────────────────────────────────────────────────────
def classify_stage(f: Dict[str, Optional[float]],
                   trend: float, momentum: float, structure: float,
                   ) -> str:
    bp = f.get("breakout_proximity_pct")     # vs 20-day high
    rsi_v = f.get("rsi_14") or 50.0
    s50 = f.get("sma_50")
    s200 = f.get("sma_200")
    close = f.get("close")

    weak = (close is not None and s50 is not None and close < s50) or trend < 0.3
    if weak and (s200 is None or (close is not None and close < s200)):
        return "WEAK"

    extended = rsi_v > 72 or (bp is not None and bp > 5.0)
    if extended:
        return "EXTENDED"

    breaking = bp is not None and -1.5 <= bp <= 2.0 and momentum > 0.55
    early_breaking = bp is not None and -5.0 <= bp <= -1.5 and structure > 0.55
    accumulating = (bp is not None and bp < -5.0
                    and trend > 0.55
                    and structure > 0.55)

    if breaking and bp >= 0:
        return "BREAKOUT"
    if breaking or early_breaking:
        return "EARLY_BREAKOUT"
    if accumulating:
        return "ACCUMULATION"
    if trend < 0.4:
        return "WEAK"
    return "ACCUMULATION"


# ── Confidence ───────────────────────────────────────────────────────────
def classify_confidence(final_score: float, scan_hits: int) -> str:
    """Confidence boosts when multiple scans agree (signal clustering)."""
    base = "LOW"
    if final_score >= 0.70:
        base = "HIGH"
    elif final_score >= 0.55:
        base = "MEDIUM"

    if scan_hits >= 3 and base == "MEDIUM":
        base = "HIGH"
    if scan_hits == 0 and base == "HIGH":
        base = "MEDIUM"
    return base


# ── Top-level scoring ────────────────────────────────────────────────────
def score(features: Dict[str, Optional[float]],
          *,
          rs_vs_nifty_pct: Optional[float] = None,
          scan_hits: Sequence[str] = (),
          weights: Optional[Dict[str, float]] = None,
          macro_multiplier: Optional[float] = None,
          sector_modifier: Optional[float] = None,
          ) -> Dict[str, object]:
    """Compute all sub-scores, final score, stage, confidence, and a
    breakdown blob suitable for storing as `components` JSONB.

    Macro layer (PR-2):
      • macro_multiplier — scalar in {0.8, 1.0, 1.1} from macro_state.risk
      • sector_modifier  — -10..+10 from macro_sector for this stock's sector

    The base score (the existing 6-component weighted sum) is multiplied
    by macro_multiplier and then nudged by sector_modifier / 100.0 so a
    +5 sector tilt adds 0.05 to a 0..1 score. Both inputs are optional —
    when None, scoring behaves exactly like PR-1.
    """
    w = weights or DEFAULT_WEIGHTS

    sub = {
        "trend":        score_trend(features),
        "momentum":     score_momentum(features),
        "structure":    score_structure(features),
        "accumulation": score_accumulation(features),
        "sector":       score_sector(rs_vs_nifty_pct),
        "risk":         score_risk(features),
    }

    base_score = sum(sub[k] * w.get(k, 0.0) for k in sub)

    # Macro adjustment — multiplicative on the base, additive sector tilt.
    # Final clamped to [0, 1] so downstream gates don't see weird values.
    mult = float(macro_multiplier) if macro_multiplier is not None else 1.0
    sect_mod = float(sector_modifier) if sector_modifier is not None else 0.0
    macro_adjusted = base_score * mult + (sect_mod / 100.0)
    final = max(0.0, min(1.0, macro_adjusted))

    stage = classify_stage(features, sub["trend"], sub["momentum"], sub["structure"])
    conf = classify_confidence(final, len(scan_hits))

    return {
        "sub_scores": sub,
        "base_score": round(base_score, 4),
        "macro_multiplier": mult,
        "sector_modifier": sect_mod,
        "final_score": final,
        "stage": stage,
        "confidence": conf,
        "weights": dict(w),
        "scan_hits": list(scan_hits),
    }
