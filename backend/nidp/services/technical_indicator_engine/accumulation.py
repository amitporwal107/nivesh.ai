"""Pre-breakout accumulation detector — NIDP TI-engine port (SD-12).

Computes ``accumulation_score`` (0..100) + the list of signals that fired, from
the technical features the calculator already produces. Detects quiet smart-money
accumulation *before* a breakout, where positional alpha lives.

This is a deliberate port of backend/services/positional_engine/accumulation_detector.py
(the Nivesh app): the NIDP TI-engine runs in its own container and cannot import the
Nivesh backend at runtime, so the pure, deterministic signal logic is reproduced here.
Keep the two in sync if the thresholds change.

Three signals run inside the TI engine (the fourth, sector_lag, needs a benchmark
return the engine doesn't have per-symbol, so it stays dormant — matching the
detector's own "stub until sector index OHLC" note):

  • vol_divergence — volume rising while price is flat (absorption)
  • delivery_spike — delivery-% trending up while price is flat (real buyers)
  • bb_squeeze     — Bollinger width + ATR compressed (energy building)

The composite rewards *count* of confirming signals, not one isolated strong one,
then scales 0..1 → 0..100 for the scorer (sector_scoring/technical.py uses it as
obv_score on a 0..100 scale).
"""
from __future__ import annotations

from typing import List, Optional, Tuple

import numpy as np

# A signal "fires" only when its strength clears this floor — keeps weak hits out.
_STRENGTH_FLOOR = 0.30


def slope_20_pct(closes: np.ndarray) -> Optional[float]:
    """20-bar least-squares price slope, expressed as % of mean price per bar.

    This is the "flatness gate" the accumulation signals need: |slope| < 0.1 means
    price is going sideways while volume/delivery build — the accumulation tell.
    """
    if closes is None or len(closes) < 20:
        return None
    window = closes[-20:]
    mean = float(np.mean(window))
    if mean == 0:
        return None
    x = np.arange(len(window))
    slope_per_bar = float(np.polyfit(x, window, 1)[0])
    return slope_per_bar / mean * 100.0


def _detect_vol_divergence(vol_z: Optional[float], slope: Optional[float]
                           ) -> Tuple[bool, float]:
    """Volume Z > +1 std AND price flat (|slope| < 0.1%/bar)."""
    if vol_z is None or slope is None or vol_z < 1.0 or abs(slope) >= 0.1:
        return False, 0.0
    strength = min(1.0, 0.4 + (vol_z - 1.0) * 0.3)   # 1σ→0.4, 3σ→1.0
    return strength >= _STRENGTH_FLOOR, strength


def _detect_delivery_spike(deliv_trend: Optional[float], slope: Optional[float]
                           ) -> Tuple[bool, float]:
    """Delivery trend > +15% AND price flat-to-mildly-up (slope <= 0.3%/bar)."""
    if deliv_trend is None or slope is None or deliv_trend < 15.0 or slope > 0.3:
        return False, 0.0
    strength = min(1.0, 0.4 + (deliv_trend - 15.0) / 35.0 * 0.6)   # +15%→0.4, +50%→1.0
    return strength >= _STRENGTH_FLOOR, strength


def _ramp_down(v: Optional[float], lo: float, hi: float) -> float:
    """Clamp v∈[lo,hi]→[1,0] (lower is stronger). None → 0."""
    if v is None or hi == lo:
        return 0.0
    return max(0.0, min(1.0, 1.0 - (v - lo) / (hi - lo)))


def _detect_bb_squeeze(bb_width: Optional[float], atr_pct: Optional[float]
                       ) -> Tuple[bool, float]:
    """BB width < 8% AND ATR% < 2.5% — volatility compression precedes expansion."""
    if bb_width is None or atr_pct is None or bb_width >= 0.08 or atr_pct >= 2.5:
        return False, 0.0
    strength = (_ramp_down(bb_width, 0.03, 0.08) + _ramp_down(atr_pct, 1.0, 2.5)) / 2.0
    return strength >= _STRENGTH_FLOOR, strength


def compute_accumulation(
    *,
    closes: np.ndarray,
    vol_z: Optional[float],
    deliv_trend: Optional[float],
    bb_width: Optional[float],
    atr_pct: Optional[float],
) -> Tuple[Optional[float], Optional[List[str]]]:
    """Return (accumulation_score 0..100, fired-signal names) for the last bar.

    Returns (None, None) when there isn't enough history to even compute the
    flatness gate, so the scorer's own default (50.0) kicks in rather than a
    misleading 0.
    """
    slope = slope_20_pct(closes)
    if slope is None:
        return None, None

    detectors = {
        "vol_divergence": _detect_vol_divergence(vol_z, slope),
        "delivery_spike": _detect_delivery_spike(deliv_trend, slope),
        "bb_squeeze":     _detect_bb_squeeze(bb_width, atr_pct),
    }
    fired = {name: s for name, (ok, s) in detectors.items() if ok}

    if not fired:
        return 0.0, []

    mean_strength = sum(fired.values()) / len(fired)
    # Confirmation factor — multiple independent signals beat one isolated strong
    # one (the whole point of an accumulation detector). 1→0.5, 2→0.85, 3→1.0.
    confirm = {1: 0.5, 2: 0.85}.get(len(fired), 1.0)
    score01 = min(1.0, mean_strength * confirm)
    return round(score01 * 100.0, 2), sorted(fired.keys())
