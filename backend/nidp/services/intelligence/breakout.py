"""Pre-Breakout Multi-Layer Detector.

Combines corporate event signals + market confirmation data to identify
high-probability pre-breakout setups using a 7-layer approach:

  Layer 1 — Event Quality        (impact_score from scorer.py)
  Layer 2 — Volume Expansion     (volume_spike_ratio from confirmation.py)
  Layer 3 — Delivery Spike       (delivery_spike_ratio — real buying)
  Layer 4 — OI / PCR             (futures OI change + put-call ratio)
  Layer 5 — Sector Strength      (sector_return_pct from confirmation.py)
  Layer 6 — Price Breakout       (close vs 20D high, gap-up at open)
  Layer 7 — Range Expansion      (today's H-L vs 20D average range)

Bonus:
  +  Long buildup OI signal (OI up + price up)
  +  Short covering (OI down + price up — momentum follow-through)
  +  Institutional accumulation proxy (delivery > 30% + vol > 2x)

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


# ── Layer point allocations (max reachable ~130 → capped at 100) ────
_LAYER_POINTS = {
    # Layer 1: Event quality
    "event_high":           30,   # impact_score ≥ 70
    "event_medium":         15,   # impact_score 50–69
    # Layer 2: Volume
    "volume_3x":            25,   # ≥ 3x 20D avg
    "volume_2x":            15,   # 2–3x
    # Layer 3: Delivery
    "delivery_2x":          20,   # ≥ 2x avg delivery%
    "delivery_15x":         10,   # 1.5–2x
    # Layer 4: Futures OI + PCR
    "oi_10pct":             18,   # OI buildup ≥ +10%
    "oi_5pct":              10,   # +5–10%
    "pcr_very_bullish":      8,   # PCR ≤ 0.7
    "pcr_bullish":           4,   # PCR ≤ 0.85
    "oi_long_buildup":       5,   # OI up + price up (bonus on top of oi_10/5)
    "oi_short_covering":     5,   # OI down + price up
    # Layer 5: Sector
    "sector_1pct":          12,   # sector +1%+
    "sector_half_pct":       6,   # sector +0.5–1%
    # Layer 6: Price breakout
    "price_20d_high":       15,   # close > 20D high close
    "price_near_high":       8,   # within 2% of 20D high
    "gap_up_2pct":          12,   # gap-up ≥ 2% at open
    # Layer 7: Range expansion
    "range_expansion_15x":   8,   # today range ≥ 1.5x avg
    # Bonus
    "institutional_accum":  10,   # delivery>30% + vol>2x
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

    # Claude AI confidence bonus
    if confidence and confidence >= 75 and sentiment in ("strongly_bullish", "bullish"):
        score += 5
        layers.append(f"AI signal: {sentiment} ({confidence:.0f}%)")

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

    # ── Layer 4: Futures OI + PCR ────────────────────────────────────
    oi_chg     = confirmation.get("oi_change_pct") or 0
    oi_signal  = confirmation.get("oi_signal") or ""
    pcr        = confirmation.get("put_call_ratio")
    pcr_signal = confirmation.get("pcr_signal") or ""

    if oi_chg >= 10.0:
        score += _LAYER_POINTS["oi_10pct"]
        layers.append(f"Futures OI buildup +{oi_chg:.0f}%")
    elif oi_chg >= 5.0:
        score += _LAYER_POINTS["oi_5pct"]
        layers.append(f"Futures OI up +{oi_chg:.0f}%")

    if oi_signal == "LONG_BUILDUP":
        score += _LAYER_POINTS["oi_long_buildup"]
        layers.append("Long buildup (OI ↑ + price ↑)")
    elif oi_signal == "SHORT_COVERING":
        score += _LAYER_POINTS["oi_short_covering"]
        layers.append("Short covering (OI ↓ + price ↑)")

    if pcr is not None:
        if pcr_signal == "VERY_BULLISH":
            score += _LAYER_POINTS["pcr_very_bullish"]
            layers.append(f"PCR {pcr:.2f} — heavy call buildup")
        elif pcr_signal == "BULLISH":
            score += _LAYER_POINTS["pcr_bullish"]
            layers.append(f"PCR {pcr:.2f} — options bullish")

    # ── Layer 5: Sector strength ─────────────────────────────────────
    sec_ret    = confirmation.get("sector_return_pct") or 0
    sector_idx = confirmation.get("sector_index") or ""
    if sec_ret >= 1.0:
        score += _LAYER_POINTS["sector_1pct"]
        layers.append(f"Sector strong +{sec_ret:.1f}% ({sector_idx})")
    elif sec_ret >= 0.5:
        score += _LAYER_POINTS["sector_half_pct"]
        layers.append(f"Sector positive +{sec_ret:.1f}% ({sector_idx})")

    # ── Layer 6: Price breakout ──────────────────────────────────────
    if confirmation.get("price_breakout"):
        score += _LAYER_POINTS["price_20d_high"]
        vs_high = confirmation.get("vs_20d_high_pct") or 0
        layers.append(f"20D high close breakout ({vs_high:+.1f}% vs prior high)")
    elif (confirmation.get("vs_20d_high_pct") or -99) >= -2:
        score += _LAYER_POINTS["price_near_high"]
        layers.append(f"Approaching 20D high (within 2%)")

    gap_up = confirmation.get("gap_up_pct") or 0
    if gap_up >= 2.0:
        score += _LAYER_POINTS["gap_up_2pct"]
        layers.append(f"Gap-up +{gap_up:.1f}% at open")

    # ── Layer 7: Range expansion ─────────────────────────────────────
    range_exp = confirmation.get("range_expansion") or 1.0
    if range_exp >= 1.5:
        score += _LAYER_POINTS["range_expansion_15x"]
        layers.append(f"Range expansion {range_exp:.1f}x normal")

    # ── Bonus: Institutional accumulation ────────────────────────────
    if del_pct >= 30 and vol >= 2.0:
        score += _LAYER_POINTS["institutional_accum"]
        layers.append(f"Institutional accumulation (delivery {del_pct:.0f}%, vol {vol:.1f}x)")

    # ── Bonus: Price near 52W high ───────────────────────────────────
    if current_price > 0 and high_52w > 0:
        pct_from_52w_high = (high_52w - current_price) / high_52w * 100
        if pct_from_52w_high <= 5:
            score += _LAYER_POINTS["near_52w_high"]
            layers.append(f"Near 52W high (within {pct_from_52w_high:.1f}%)")

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
