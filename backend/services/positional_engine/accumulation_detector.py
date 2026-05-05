"""Pre-breakout accumulation detector.

The screening engine ([scorer.py]) tells you whether a stock IS in
breakout. This module tells you whether it's about to be — *before*
the breakout fires. That edge is where positional alpha actually lives.

Four named signals, each pure-Python, deterministic, fed by the existing
feature pack:

  • vol_divergence   — Volume rising while price stays flat. Smart
                        money quietly accumulating without driving price.
  • delivery_spike   — Delivery-% trending up. Real positional buyers
                        (not intraday flippers) taking shares off the
                        market. India-specific edge — most non-Indian
                        markets don't publish per-stock delivery.
  • bb_squeeze       — Bollinger bandwidth at multi-week low + ATR
                        falling. Volatility compression always precedes
                        expansion. Energy building.
  • sector_lag       — Stock is lagging while its sector index is
                        rising. Mean-reversion catch-up trade. (Stub
                        until sector_index OHLC is ingested — currently
                        approximated via stock_ret_20d − bench_ret_20d.)

Each detector returns a tuple `(fired: bool, strength: 0..1)`. The
composite `accumulation_score` is the average strength of *fired*
signals, weighted toward count (you want multiple signals confirming,
not one strong signal alone).
"""
from __future__ import annotations

from typing import Dict, List, Optional, Tuple

# A signal "fires" only when both the boolean condition is met AND its
# strength is above this floor. Keeps weak random hits out.
STRENGTH_FLOOR = 0.30

# Composite threshold — accumulation_score above this = "Early Opportunity"
EARLY_OPPORTUNITY_FLOOR = 0.55


def _ramp(v: Optional[float], lo: float, hi: float,
          *, good_is_high: bool = True) -> float:
    """Clamp v∈[lo,hi]→[0,1]. None → 0."""
    if v is None or hi == lo:
        return 0.0
    pct = (v - lo) / (hi - lo)
    pct = max(0.0, min(1.0, pct))
    return pct if good_is_high else 1.0 - pct


# ── Signal 1: Volume vs price divergence ─────────────────────────────────
def detect_vol_divergence(features: Dict[str, Optional[float]]
                           ) -> Tuple[bool, float]:
    """Volume Z > +1 AND |slope_20_pct| < 0.1% per bar.

    Smart-money tell: order book absorbing supply at flat prices.
    Strength is dominated by volume Z; flatness is the gate.
    """
    vz = features.get("volume_z_20")
    slope = features.get("slope_20_pct")
    if vz is None or slope is None:
        return False, 0.0
    if vz < 1.0:
        return False, 0.0
    if abs(slope) >= 0.1:    # not flat enough — price already moving
        return False, 0.0
    # Strength: 1.0 std → 0.4, 3.0 std → 1.0
    strength = min(1.0, 0.4 + (vz - 1.0) * 0.3)
    return strength >= STRENGTH_FLOOR, strength


# ── Signal 2: Delivery % spike ───────────────────────────────────────────
def detect_delivery_spike(features: Dict[str, Optional[float]]
                           ) -> Tuple[bool, float]:
    """Delivery-trend > +15% AND price slope flat-to-mildly-up.

    The flat-price gate is what makes this an *accumulation* signal vs
    an "already running" signal. Rising delivery during a price rally
    is just confirmation; rising delivery during sideways action is
    where the edge is.
    """
    dt = features.get("delivery_trend_pct")
    slope = features.get("slope_20_pct")
    if dt is None or slope is None:
        return False, 0.0
    if dt < 15.0:
        return False, 0.0
    if slope > 0.3:           # already running — not pre-breakout
        return False, 0.0
    # Strength: +15% → 0.4, +50% → 1.0
    strength = min(1.0, 0.4 + (dt - 15.0) / 35.0 * 0.6)
    return strength >= STRENGTH_FLOOR, strength


# ── Signal 3: Bollinger / ATR compression ────────────────────────────────
def detect_bb_squeeze(features: Dict[str, Optional[float]]
                      ) -> Tuple[bool, float]:
    """BB width < 8% AND ATR% < 2.5%.

    Volatility compression always precedes expansion. The tighter the
    range, the bigger the eventual move. Pure structural signal —
    doesn't care about direction yet.
    """
    bb = features.get("bb_width_20")
    atr_pct = features.get("atr_pct")
    if bb is None or atr_pct is None:
        return False, 0.0
    if bb >= 0.08 or atr_pct >= 2.5:
        return False, 0.0
    # Both compression dimensions contribute. Tighter = stronger.
    bb_strength = _ramp(bb, lo=0.03, hi=0.08, good_is_high=False)
    atr_strength = _ramp(atr_pct, lo=1.0, hi=2.5, good_is_high=False)
    strength = (bb_strength + atr_strength) / 2.0
    return strength >= STRENGTH_FLOOR, strength


# ── Signal 4: Sector lag (stub — needs sector_index OHLC ingester) ───────
def detect_sector_lag(features: Dict[str, Optional[float]],
                       *,
                       bench_ret_20d: Optional[float] = None,
                       ) -> Tuple[bool, float]:
    """Approximation: stock_ret_20d < (bench_ret_20d × 0.4)
    AND stock above SMA50 (so it's not just weak — it's lagging
    a strong sector). Catch-up move setup.

    Until per-sector index OHLC lands, we use Nifty 50 as the
    "benchmark" — gives directional intuition but blurs sector-
    specific lag. Flagged in components blob so this can be upgraded
    to true sector-RS later without breaking callers.
    """
    if bench_ret_20d is None or bench_ret_20d < 2.0:
        # Bench needs to be in tailwind for "lag" to be meaningful
        return False, 0.0
    stock_ret = features.get("return_20d_pct")
    close = features.get("close")
    sma50 = features.get("sma_50")
    if stock_ret is None or close is None or sma50 is None:
        return False, 0.0
    # Above SMA50 = trend not broken
    if close <= sma50:
        return False, 0.0
    # Lagging the bench by 60%+
    lag_threshold = bench_ret_20d * 0.4
    if stock_ret >= lag_threshold:
        return False, 0.0
    # Strength: bigger gap = stronger catch-up case
    gap = bench_ret_20d - stock_ret
    strength = min(1.0, 0.4 + gap / 10.0 * 0.6)
    return strength >= STRENGTH_FLOOR, strength


# ── Composite ────────────────────────────────────────────────────────────
def detect_all(features: Dict[str, Optional[float]],
                *,
                bench_ret_20d: Optional[float] = None,
                ) -> Dict[str, object]:
    """Run all four signals. Returns:
       {
         signals:           list[str]   # names that fired
         strengths:         dict[name → float]
         accumulation_score: float 0..1
         is_early_opportunity: bool
       }

    `accumulation_score` rewards *count*, not just max strength —
    multiple weak confirmations beat one isolated strong signal:

        score = mean(strengths) × (count / 4) ^ 0.5
    """
    detectors = {
        "vol_divergence":  detect_vol_divergence(features),
        "delivery_spike":  detect_delivery_spike(features),
        "bb_squeeze":      detect_bb_squeeze(features),
        "sector_lag":      detect_sector_lag(features, bench_ret_20d=bench_ret_20d),
    }
    fired_names: List[str] = []
    strengths: Dict[str, float] = {}
    for name, (fired, strength) in detectors.items():
        if fired:
            fired_names.append(name)
            strengths[name] = round(strength, 3)

    if not fired_names:
        score = 0.0
    else:
        mean_strength = sum(strengths.values()) / len(strengths)
        # Confirmation factor — rewards multiple signals over one isolated
        # strong one, which is the design goal of an accumulation detector.
        # An isolated signal can be noise; multiple independent confirmations
        # rarely are. Ramp:  1 → 0.5,  2 → 0.85,  3 → 1.0,  4 → 1.05.
        n = len(strengths)
        confirm = {1: 0.5, 2: 0.85, 3: 1.0}.get(n, 1.05)
        score = round(min(1.0, mean_strength * confirm), 3)

    return {
        "signals": fired_names,
        "strengths": strengths,
        "accumulation_score": score,
        "is_early_opportunity": score >= EARLY_OPPORTUNITY_FLOOR,
    }
