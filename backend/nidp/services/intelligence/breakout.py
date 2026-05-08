"""Pre-Breakout Multi-Layer Detector.

Combines corporate event signals + market confirmation data to identify
high-probability pre-breakout setups using the 5-layer approach:

  Layer 1 — Event Quality        (impact_score from scorer.py)
  Layer 2 — Volume Expansion     (volume_spike_ratio from confirmation.py)
  Layer 3 — Delivery Spike       (delivery_spike_ratio from confirmation.py)
  Layer 4 — OI Buildup           (oi_change_pct from confirmation.py)
  Layer 5 — Sector Strength      (sector_return_pct from confirmation.py)

Bonus factors:
  +  Price near 52W high (momentum market) → higher probability continuation
  +  Delivery > 30% (institutional accumulation)
  +  Sector index also breaking out

Breakout Score 0–100:
  ≥ 70 → HIGH confidence  (send alert)
  50–69 → MEDIUM confidence (monitor / low-priority alert)
  < 50 → LOW (skip or watchlist only)

The more layers align simultaneously, the higher the confidence.
Professional desks call this "confluence trading" — no single indicator,
but when 4-5 stack up, the probability of a sustained move is very high.
"""
from __future__ import annotations

from typing import Optional


# ── Layer point allocations (sum to 100 at maximum) ─────────────────
_LAYER_POINTS = {
    "event_high":           30,   # impact_score ≥ 70
    "event_medium":         15,   # impact_score 50–69
    "volume_3x":            25,   # volume spike ≥ 3x
    "volume_2x":            15,   # volume spike 2–3x
    "delivery_2x":          20,   # delivery spike ≥ 2x avg
    "delivery_15x":         10,   # delivery spike 1.5–2x
    "oi_10pct":             18,   # OI buildup ≥ +10%
    "oi_5pct":              10,   # OI buildup +5–10%
    "sector_1pct":          12,   # sector +1%+
    "sector_half_pct":       6,   # sector +0.5–1%
    "institutional_accum":  10,   # delivery>30% + volume>2x (VWAP hold proxy)
    "near_52w_high":         8,   # price within 5% of 52W high
}

# Alert thresholds
_HIGH_THRESHOLD   = 70
_MEDIUM_THRESHOLD = 50


def detect_breakout(
    event_type: str,
    sentiment: str,
    confidence: float,
    impact_score: Optional[float],
    confirmation: dict,
    current_price: float = 0,
    high_52w: float = 0,
    low_52w: float = 0,
) -> dict:
    """Run the multi-layer breakout detection.

    Args:
        event_type:   NIDP event type string.
        sentiment:    Claude signal sentiment.
        confidence:   Claude confidence (0–100).
        impact_score: Pre-computed event impact score (0–100).
        confirmation: Output of confirmation.get_confirmation().
        current_price / high_52w / low_52w: Price context.

    Returns a dict with:
        breakout_score      (0–100)
        breakout_confidence ("HIGH" | "MEDIUM" | "LOW")
        should_alert        (bool)
        layers_hit          (list of signal descriptions)
        summary             (one-line description)
    """
    score = 0
    layers: list[str] = []
    imp = impact_score or 0

    # ── Layer 1: Event quality ───────────────────────────────────────
    if imp >= 70:
        score += _LAYER_POINTS["event_high"]
        layers.append(f"High-impact event (score {imp:.0f})")
    elif imp >= 50:
        score += _LAYER_POINTS["event_medium"]
        layers.append(f"Medium-impact event (score {imp:.0f})")

    # Also factor Claude AI confidence directly
    if confidence and confidence >= 75 and sentiment in ("strongly_bullish", "bullish"):
        score += 5
        layers.append(f"AI: {sentiment} ({confidence:.0f}%)")

    # ── Layer 2: Volume expansion ────────────────────────────────────
    vol = confirmation.get("volume_spike_ratio") or 1.0
    if vol >= 3.0:
        score += _LAYER_POINTS["volume_3x"]
        layers.append(f"Volume spike {vol:.1f}x 20D avg")
    elif vol >= 2.0:
        score += _LAYER_POINTS["volume_2x"]
        layers.append(f"Volume elevated {vol:.1f}x 20D avg")

    # ── Layer 3: Delivery spike (real buying) ────────────────────────
    del_ratio = confirmation.get("delivery_spike_ratio") or 1.0
    del_pct   = confirmation.get("delivery_pct_today") or 0
    if del_ratio >= 2.0:
        score += _LAYER_POINTS["delivery_2x"]
        layers.append(f"Delivery spike {del_ratio:.1f}x avg ({del_pct:.0f}%)")
    elif del_ratio >= 1.5:
        score += _LAYER_POINTS["delivery_15x"]
        layers.append(f"Delivery elevated {del_ratio:.1f}x avg")

    # ── Layer 4: OI buildup (futures participation) ──────────────────
    oi_chg = confirmation.get("oi_change_pct") or 0
    if oi_chg >= 10.0:
        score += _LAYER_POINTS["oi_10pct"]
        layers.append(f"Futures OI buildup +{oi_chg:.0f}%")
    elif oi_chg >= 5.0:
        score += _LAYER_POINTS["oi_5pct"]
        layers.append(f"Futures OI up +{oi_chg:.0f}%")

    # ── Layer 5: Sector strength ─────────────────────────────────────
    sec_ret = confirmation.get("sector_return_pct") or 0
    if sec_ret >= 1.0:
        score += _LAYER_POINTS["sector_1pct"]
        layers.append(f"Sector strong +{sec_ret:.1f}%")
    elif sec_ret >= 0.5:
        score += _LAYER_POINTS["sector_half_pct"]
        layers.append(f"Sector positive +{sec_ret:.1f}%")

    # ── Bonus: Institutional accumulation (VWAP hold proxy) ──────────
    if del_pct >= 30 and vol >= 2.0:
        score += _LAYER_POINTS["institutional_accum"]
        layers.append(f"Institutional accumulation (delivery {del_pct:.0f}%, vol {vol:.1f}x)")

    # ── Bonus: Price near 52W high (momentum) ────────────────────────
    if current_price > 0 and high_52w > 0:
        pct_from_high = (high_52w - current_price) / high_52w * 100
        if pct_from_high <= 5:
            score += _LAYER_POINTS["near_52w_high"]
            layers.append(f"Near 52W high (within {pct_from_high:.1f}%)")

    score = round(min(score, 100.0), 1)

    if score >= _HIGH_THRESHOLD:
        bconf = "HIGH"
    elif score >= _MEDIUM_THRESHOLD:
        bconf = "MEDIUM"
    else:
        bconf = "LOW"

    layers_count = len(layers)
    summary = (
        f"{layers_count} confluence signals: "
        + " | ".join(layers[:3])
        + ("..." if layers_count > 3 else "")
    ) if layers else "No confluence signals detected"

    return {
        "breakout_score":      score,
        "breakout_confidence": bconf,
        "should_alert":        score >= _MEDIUM_THRESHOLD,
        "layers_hit":          layers,
        "layers_count":        layers_count,
        "summary":             summary,
    }


def classify_alert_priority(
    breakout_score: float,
    sentiment: str,
    event_type: str,
) -> str:
    """Return alert priority string for routing: 'immediate' | 'daily' | 'skip'."""
    if breakout_score >= _HIGH_THRESHOLD and sentiment in ("strongly_bullish", "bullish",
                                                            "strongly_bearish", "bearish"):
        return "immediate"
    if breakout_score >= _MEDIUM_THRESHOLD:
        return "daily"
    return "skip"
