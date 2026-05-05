"""Conviction framework — 4-pillar score + penalties + tradable verdict.

Built on top of the existing `scorer.py` final_score (which weights
trend/momentum/structure/accumulation/sector/risk). That score answers
"is this a good setup *intrinsically*?". This module answers
"should we *trade* it *now*?", which factors in:

  • Live LTP → late-entry / chase risk
  • Volume confirmation specific to today's bar
  • Hard penalty triggers (RSI overbought, gap-up, near-resistance)
  • Multi-scan agreement (signal clustering)

Output is a typed verdict the UI can hard-gate on:

  HIGH_CONVICTION   — top of pile; show prominently
  SETUP_FORMING     — promising but no trigger yet; watchlist
  AVOID_LATE        — extended / chasing / overbought; do not enter

Pure function — takes the feature pack + trade plan + live context,
returns a dict. Doesn't touch DB.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

# Pillar weights — sum to 1.0. Per the user's spec.
PILLAR_WEIGHTS = {
    "trend":     0.30,
    "volume":    0.25,
    "structure": 0.25,
    "rr":        0.20,
}

# Verdict thresholds (after penalty deductions, on a 0-100 scale)
HIGH_CONVICTION_FLOOR = 65.0
SETUP_FORMING_FLOOR   = 45.0
# Below SETUP_FORMING_FLOOR → AVOID_LATE


# ── Pillar 1: trend strength ─────────────────────────────────────────────
def _pillar_trend(features: Dict[str, Optional[float]]) -> float:
    """Above 50EMA + 50>200 + slope rising. 0..100."""
    parts: List[float] = []
    close = features.get("close")
    s50 = features.get("sma_50")
    s200 = features.get("sma_200")
    if close is not None and s50 is not None:
        parts.append(100.0 if close > s50 else 30.0)
    if close is not None and s200 is not None:
        parts.append(100.0 if close > s200 else 30.0)
    if s50 is not None and s200 is not None:
        parts.append(100.0 if s50 > s200 else 30.0)
    slope = features.get("slope_20_pct")
    if slope is not None:
        # 0%/bar → 50, 0.5%/bar → 100
        parts.append(max(0.0, min(100.0, 50 + slope * 100)))
    return sum(parts) / len(parts) if parts else 50.0


# ── Pillar 2: volume confirmation ────────────────────────────────────────
def _pillar_volume(features: Dict[str, Optional[float]]) -> float:
    """Volume Z + delivery-trend. Volume confirms the setup is real."""
    parts: List[float] = []
    vz = features.get("volume_z_20")
    if vz is not None:
        # -1 → 0, 0 → 50, 1 → 75, 2 → 100
        parts.append(max(0.0, min(100.0, 50 + vz * 25)))
    dt = features.get("delivery_trend_pct")
    if dt is not None:
        # -10 → 0, 0 → 50, 20 → 100
        parts.append(max(0.0, min(100.0, 50 + dt * 2.5)))
    return sum(parts) / len(parts) if parts else 50.0


# ── Pillar 3: structure quality ──────────────────────────────────────────
def _pillar_structure(features: Dict[str, Optional[float]]) -> float:
    """Tight ATR + BB squeeze + breakout proximity in the actionable band."""
    parts: List[float] = []
    atr_pct = features.get("atr_pct")
    if atr_pct is not None:
        # 1% → 100, 4% → 0
        parts.append(max(0.0, min(100.0, (4.0 - atr_pct) / 3.0 * 100)))
    bb = features.get("bb_width_20")
    if bb is not None:
        # 0.05 → 100, 0.20 → 0
        parts.append(max(0.0, min(100.0, (0.20 - bb) / 0.15 * 100)))
    bp = features.get("breakout_proximity_pct")
    if bp is not None:
        # Sweet spot: -2% to +1% from 20d high
        if -2.0 <= bp <= 1.0:
            parts.append(100.0)
        elif bp > 1.0:
            parts.append(max(0.0, 100 - (bp - 1.0) * 20))
        else:
            parts.append(max(0.0, 100 - (-bp - 2.0) * 12.5))
    return sum(parts) / len(parts) if parts else 50.0


# ── Pillar 4: risk-reward integrity ──────────────────────────────────────
def _pillar_rr(trade_plan: Optional[Dict[str, Any]]) -> float:
    """RR ≥ 1:2 = good; 1:3+ = excellent. Below 1:1.5 → fails."""
    if not trade_plan:
        return 0.0
    rr = float(trade_plan.get("risk_reward") or 0)
    if rr < 1.5:
        return 0.0
    if rr >= 3.0:
        return 100.0
    # 1.5 → 50, 2.0 → 70, 3.0 → 100
    return max(0.0, min(100.0, 30 + (rr - 1.5) * 47))


# ── Penalties — confidence killers ───────────────────────────────────────
def _penalties(features: Dict[str, Optional[float]],
                trade_plan: Optional[Dict[str, Any]],
                live_ltp: Optional[float]) -> List[Dict[str, Any]]:
    """Each penalty is a {name, points (negative), reason} dict.
    The *sum* is subtracted from the weighted pillar score."""
    out: List[Dict[str, Any]] = []

    # Late entry — LTP already 8%+ past plan entry. The user's exact ask.
    if trade_plan and live_ltp is not None:
        entry = float(trade_plan.get("entry") or 0)
        if entry > 0:
            ext_pct = (live_ltp - entry) / entry * 100.0
            if ext_pct > 15.0:
                out.append({"name": "extended_chasing", "points": -25,
                            "reason": f"Already {ext_pct:.1f}% past entry — chasing"})
            elif ext_pct > 8.0:
                out.append({"name": "extended_late", "points": -15,
                            "reason": f"Already {ext_pct:.1f}% past entry — late"})

    # Overbought RSI
    rsi_v = features.get("rsi_14")
    if rsi_v is not None and rsi_v > 75:
        out.append({"name": "overbought_rsi", "points": -15,
                    "reason": f"RSI {rsi_v:.0f} — overextended"})
    elif rsi_v is not None and rsi_v > 70:
        out.append({"name": "high_rsi", "points": -8,
                    "reason": f"RSI {rsi_v:.0f} — approaching overbought"})

    # Gap-up risk — if today's open was >3% above prior close, the move is
    # already in the gap, not the trade. We approximate from intraday-open
    # vs prior-close = (close - open) / open ≈ 0 means no gap; large
    # negative slope_20 + bullish stage suggests gap risk. Lacking the open
    # explicitly here, fall back on 5d return: > 12% in 5d → likely gapped.
    r5 = features.get("return_5d_pct")
    if r5 is not None and r5 > 12.0:
        out.append({"name": "recent_spike", "points": -10,
                    "reason": f"+{r5:.1f}% in 5d — gap-up risk"})

    # Stage extended (the engine's own classifier)
    # Note: stage='EXTENDED' already filtered upstream from Active Trades;
    # this catches edge cases where stage is 'EARLY_BREAKOUT' but bp is
    # already extended (pipeline race condition).
    bp = features.get("breakout_proximity_pct")
    if bp is not None and bp > 5.0:
        out.append({"name": "above_breakout", "points": -10,
                    "reason": f"Already {bp:.1f}% above 20d high"})

    return out


# ── Hard caps — readiness gates that ignore the score ───────────────────
# A stock that's already extended past entry is NEVER high-conviction,
# no matter how clean the underlying setup looks. The user's exact ask:
# "ASTERDM (+12%) → should NOT be 58% → should drop to ~45–50%". The
# soft -15 penalty wasn't enough, so we add a hard cap by readiness.
def _readiness_cap(live_ltp: Optional[float], entry: float) -> Optional[str]:
    """Return the maximum verdict allowed given the LTP-vs-entry relation,
    or None if no cap applies. Independent of score."""
    if live_ltp is None or entry <= 0:
        return None
    pct = (live_ltp - entry) / entry * 100.0
    if pct > 15.0:
        # Already 15%+ past entry — flat-out chasing. Never even SETUP.
        return "AVOID_LATE"
    if pct > 8.0:
        # 8-15% past entry — at most a watchlist item, never high conviction
        return "SETUP_FORMING"
    return None


def _apply_cap(verdict: str, cap: Optional[str]) -> str:
    """Demote `verdict` to `cap` if `cap` is more restrictive."""
    if cap is None:
        return verdict
    order = ["HIGH_CONVICTION", "SETUP_FORMING", "AVOID_LATE"]
    if order.index(cap) > order.index(verdict):
        return cap
    return verdict


# ── Top-level: classify_verdict ──────────────────────────────────────────
def classify_verdict(*,
                     features: Dict[str, Optional[float]],
                     trade_plan: Optional[Dict[str, Any]],
                     live_ltp: Optional[float] = None,
                     scan_count: int = 0,
                     ) -> Dict[str, Any]:
    """Compute pillars + penalties + final verdict. Returns:
    {
      pillars:     {trend, volume, structure, rr}      0-100 each
      base_score:  weighted pillar sum                  0-100
      penalties:   [{name, points, reason}, ...]
      net_score:   base_score + sum(penalty.points)    0-100
      scan_bonus:  bonus for multi-scan confirmation   0-10
      final_score: net_score + scan_bonus               0-100
      verdict:     HIGH_CONVICTION | SETUP_FORMING | AVOID_LATE
      reasons:     [human-readable]
    }
    """
    pillars = {
        "trend":     round(_pillar_trend(features), 1),
        "volume":    round(_pillar_volume(features), 1),
        "structure": round(_pillar_structure(features), 1),
        "rr":        round(_pillar_rr(trade_plan), 1),
    }
    base = sum(pillars[k] * PILLAR_WEIGHTS[k] for k in pillars)

    pens = _penalties(features, trade_plan, live_ltp)
    pen_total = sum(p["points"] for p in pens)

    # Multi-scan bonus — independent confirmations are alpha
    scan_bonus = 0
    if scan_count >= 3:
        scan_bonus = 10
    elif scan_count == 2:
        scan_bonus = 6
    elif scan_count == 1:
        scan_bonus = 3

    net = base + pen_total
    final = max(0.0, min(100.0, net + scan_bonus))

    if final >= HIGH_CONVICTION_FLOOR:
        verdict = "HIGH_CONVICTION"
    elif final >= SETUP_FORMING_FLOOR:
        verdict = "SETUP_FORMING"
    else:
        verdict = "AVOID_LATE"

    # Hard cap by extension — a great setup we missed is still missed.
    entry = float((trade_plan or {}).get("entry") or 0)
    cap = _readiness_cap(live_ltp, entry)
    verdict = _apply_cap(verdict, cap)

    # Build human-readable reason list
    reasons: List[str] = []
    if pillars["trend"] >= 75:
        reasons.append("Strong trend (above 50/200 DMA)")
    if pillars["volume"] >= 75:
        reasons.append("Volume confirms (rising delivery / Z-spike)")
    if pillars["structure"] >= 75:
        reasons.append("Clean structure (tight range, near breakout)")
    if pillars["rr"] >= 75:
        reasons.append(f"RR ≥ 1:{(trade_plan or {}).get('risk_reward', 0):.1f}")
    for p in pens:
        reasons.append(f"⚠ {p['reason']} ({p['points']:+d})")
    if scan_count >= 2:
        reasons.append(f"+{scan_bonus} bonus — {scan_count} screeners confirm")

    return {
        "pillars": pillars,
        "base_score": round(base, 1),
        "penalties": pens,
        "net_score": round(net, 1),
        "scan_bonus": scan_bonus,
        "final_score": round(final, 1),
        "verdict": verdict,
        "reasons": reasons,
    }
