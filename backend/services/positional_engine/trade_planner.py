"""Trade plan generator: entry, stop-loss, target, risk-reward.

Stage-aware:
  - ACCUMULATION:    entry on pullback near support, SL below swing low
  - EARLY_BREAKOUT:  entry on break of 20-day high, SL below recent swing low
  - BREAKOUT:        entry at current close (just broken out), SL = breakout - 1×ATR
  - EXTENDED / WEAK: no plan generated (caller should drop)

Targets prefer the structural resistance (52w high, prior swing high) but
fall back to a 2× risk projection so RR is always defined.
"""
from __future__ import annotations

from typing import Dict, Optional


def _round(x: float) -> float:
    """Round to 2 dp; keeps the API tidy without extra deps."""
    return round(x + 1e-9, 2)


def plan(stage: str,
         features: Dict[str, Optional[float]],
         *,
         macro_risk: Optional[str] = None,
         sector_modifier: Optional[float] = None,
         ) -> Optional[Dict[str, float]]:
    """Generate a trade plan for the given stage + features.

    PR-3 macro inputs:
      • macro_risk        — 'LOW' | 'MEDIUM' | 'HIGH' from macro_state
      • sector_modifier   — sector_macro_scores.macro_score for this stock's sector
    Both optional. When provided, we attach `position_size_factor` and
    `position_size_reason` to the returned dict so the UI can render
    "0.7× base size — high-risk regime · sector also penalized".
    """
    close = features.get("close")
    atr = features.get("atr_14")
    high_20 = features.get("high_20d")
    swing_low = features.get("swing_low_20")
    swing_high = features.get("swing_high_20")
    high_52w = features.get("high_52w")

    if close is None or atr is None:
        return None

    # ── Entry ────────────────────────────────────────────────────────────
    entry: Optional[float] = None
    if stage == "BREAKOUT":
        entry = close
    elif stage == "EARLY_BREAKOUT" and high_20 is not None:
        # Trigger on a clean break of 20-day high
        entry = max(close, high_20 * 1.001)
    elif stage == "ACCUMULATION":
        # Buy on pullback close to support; if we're already there, take close.
        if swing_low is not None and close <= swing_low * 1.03:
            entry = close
        elif swing_low is not None:
            entry = swing_low * 1.01
        else:
            entry = close
    else:
        return None

    if entry is None:
        return None

    # ── Stop-loss ────────────────────────────────────────────────────────
    sl_candidates = []
    if swing_low is not None and swing_low < entry:
        sl_candidates.append(swing_low * 0.995)
    sl_candidates.append(entry - 1.5 * atr)
    sl = max(sl_candidates)   # tightest SL that still gives breathing room
    if sl >= entry:
        sl = entry - 1.5 * atr

    risk = entry - sl
    if risk <= 0:
        return None

    # ── Target ───────────────────────────────────────────────────────────
    structural_targets = []
    if swing_high is not None and swing_high > entry:
        structural_targets.append(swing_high)
    if high_52w is not None and high_52w > entry:
        structural_targets.append(high_52w)

    rr_floor = entry + 2.0 * risk    # ensure ≥ 1:2 RR
    if structural_targets:
        # Pick the closer structural target if it gives ≥ 1:1.8 RR; else
        # fall back to the 2× risk projection.
        nearest = min(structural_targets)
        if (nearest - entry) / risk >= 1.8:
            target = nearest
        else:
            target = rr_floor
    else:
        target = rr_floor

    rr = (target - entry) / risk

    if rr < 1.5:
        return None   # Reject low-RR setups upstream

    # Timeframe: tighter setups → shorter horizon
    atr_pct = features.get("atr_pct") or 2.0
    if atr_pct < 2.0:
        tf_min, tf_max = 5, 15
    elif atr_pct < 3.5:
        tf_min, tf_max = 7, 20
    else:
        tf_min, tf_max = 10, 30

    out = {
        "entry": _round(entry),
        "stoploss": _round(sl),
        "target": _round(target),
        "risk_reward": _round(rr),
        "timeframe_days_min": tf_min,
        "timeframe_days_max": tf_max,
    }

    # PR-3: attach the macro-aware position-size factor when caller passes
    # in macro context. Always-present floor of 1.0 when no inputs were
    # supplied, so non-macro callers see no behavioural change.
    if macro_risk is not None or sector_modifier is not None:
        from .macro_overlay import position_size_factor, explain_position_size
        out["position_size_factor"] = position_size_factor(
            risk=macro_risk, sector_modifier=sector_modifier,
        )
        out["position_size_reason"] = explain_position_size(
            risk=macro_risk, sector_modifier=sector_modifier,
        )

    return out


def reasons(features: Dict[str, Optional[float]],
            scores: Dict[str, float],
            scan_hits: list[str],
            stage: str) -> list[str]:
    """Human-readable bullets for the 'Why this trade' panel."""
    out: list[str] = []
    close = features.get("close")
    s50 = features.get("sma_50")
    s200 = features.get("sma_200")

    if close is not None and s50 is not None and s200 is not None:
        if close > s50 > s200:
            out.append("Strong uptrend (above 50 & 200 DMA, 50 above 200)")
        elif close > s50:
            out.append("Above 50-day moving average")

    rsi_v = features.get("rsi_14")
    if rsi_v is not None and 50 <= rsi_v <= 65:
        out.append(f"RSI {rsi_v:.0f} — momentum without being overbought")

    bp = features.get("breakout_proximity_pct")
    if bp is not None and -2 <= bp <= 2:
        out.append("At 20-day breakout level")

    atr_pct = features.get("atr_pct")
    if atr_pct is not None and atr_pct < 2.0:
        out.append("Tight consolidation (low ATR)")

    dt = features.get("delivery_trend_pct")
    if dt is not None and dt > 10:
        out.append("Rising delivery volumes — accumulation")

    vz = features.get("volume_z_20")
    if vz is not None and vz > 1.5:
        out.append("Volume buildup vs 20-day average")

    if scores.get("sector", 0) > 0.6:
        out.append("Sector outperforming Nifty")

    if scan_hits:
        out.append(f"Confirmed by {len(scan_hits)} screener: {', '.join(scan_hits[:3])}")

    if not out:
        out.append(f"Stage: {stage}")
    return out
