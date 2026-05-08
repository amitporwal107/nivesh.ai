"""Impact Scoring Engine.

Formula:
    Impact Score = Event Importance
                 × Revenue Factor      (order size / annual revenue)
                 × (1 + Volume Factor) (volume spike above normal)
                 × (1 + Sector Factor) (sector trend strength)
                 × MCap Adjustment     (inverse: smaller cap → bigger moves)

All inputs are optional — missing values fall back to conservative defaults
so the score still provides a useful ranking.

Score range: 0–100
  ≥ 70 → HIGH impact (alert-worthy)
  50–69 → MEDIUM impact
  < 50 → LOW / monitoring only

Keyword extraction is used for order_win events to pull the order value from
the announcement text when a structured figure isn't available.
"""
from __future__ import annotations

import re
from typing import Optional

# ── Event importance weights (0.0–1.0) ──────────────────────────────
_EVENT_IMPORTANCE: dict[str, float] = {
    "quarterly_results": 1.00,
    "order_win":         0.92,
    "insolvency":        0.92,  # heavily negative
    "regulatory":        0.88,  # FDA/RBI approvals, government clearances
    "merger_acquisition":0.85,
    "litigation":        0.82,
    "debt_reduction":    0.75,
    "credit_rating":     0.75,
    "management":        0.72,
    "buyback":           0.80,
    "promoter_buying":   0.75,
    "promoter_selling":  0.72,
    "index_change":      0.70,
    "rights_issue":      0.68,
    "qip":               0.65,
    "pledge_change":     0.65,
    "shareholding":      0.60,
    "dividend":          0.60,
    "bonus":             0.55,
    "split":             0.50,
    "board_meeting":     0.48,
    "agm":               0.35,
    "other":             0.40,
}

# Market cap bands for MCap adjustment factor
_MCAP_BASELINE_CR = 10_000  # ₹10,000 Cr (midcap baseline)


def event_importance(event_type: str) -> float:
    return _EVENT_IMPORTANCE.get(event_type, 0.40)


def revenue_factor(order_size_cr: float, annual_revenue_cr: float) -> float:
    """How large is the event relative to the company's revenue?"""
    if not annual_revenue_cr or annual_revenue_cr <= 0:
        return 0.35  # conservative default when revenue unknown
    ratio = min(order_size_cr / annual_revenue_cr, 1.0)
    # Scale: 5% of revenue → 0.37, 20% → 0.63, 50%+ → 1.0
    return 0.25 + 0.75 * ratio


def volume_factor(volume_spike_ratio: float) -> float:
    """Normalise volume spike to 0.0–1.0 (5x spike = max contribution)."""
    spike = max(volume_spike_ratio - 1.0, 0.0)  # excess above normal
    return min(spike / 4.0, 1.0)


def sector_factor(sector_return_pct: float) -> float:
    """Map sector day return (typically −2% to +2%) to 0.0–1.0."""
    return max(0.0, min((sector_return_pct + 2.0) / 4.0, 1.0))


def mcap_adjustment(market_cap_cr: float) -> float:
    """Smaller-cap stocks move more on events; inverse scaling capped at 2×."""
    if not market_cap_cr or market_cap_cr <= 0:
        return 1.0
    return min(_MCAP_BASELINE_CR / market_cap_cr, 2.0)


def calc_impact_score(
    event_type: str,
    order_size_cr: float = 0.0,
    annual_revenue_cr: float = 0.0,
    volume_spike_ratio: float = 1.0,
    sector_return_pct: float = 0.0,
    market_cap_cr: float = 0.0,
) -> float:
    """Calculate 0–100 impact score for a corporate event.

    Args:
        event_type:        One of the 20 NIDP event type strings.
        order_size_cr:     For order_win events — order value in ₹ Crore.
        annual_revenue_cr: LTM revenue for revenue-factor calculation.
        volume_spike_ratio: today_volume / avg_20d_volume (1.0 = normal).
        sector_return_pct: Sector index return today in percent.
        market_cap_cr:     Market cap in ₹ Crore (for scaling).
    """
    imp = event_importance(event_type)

    # Revenue factor (only meaningful for order_win; default to 0.5 otherwise)
    rev_f = (
        revenue_factor(order_size_cr, annual_revenue_cr)
        if order_size_cr > 0 and annual_revenue_cr > 0
        else 0.50
    )

    vol_f = volume_factor(volume_spike_ratio)
    sec_f = sector_factor(sector_return_pct)
    mc_adj = mcap_adjustment(market_cap_cr)

    # Base score: 0–50 from importance × revenue factor
    base = imp * rev_f * 50

    # Amplify with volume and sector tail-winds
    amplified = base * (1 + 0.6 * vol_f) * (1 + 0.3 * sec_f)

    # Market cap scaling
    final = amplified * mc_adj

    return round(min(final, 100.0), 1)


# ── Keyword-based order value extractor ─────────────────────────────

_CR_PATTERN  = re.compile(r"(?:rs\.?|inr|₹)\s*([\d,]+(?:\.\d+)?)\s*cr(?:ore)?", re.IGNORECASE)
_MN_PATTERN  = re.compile(r"(?:rs\.?|inr|₹)\s*([\d,]+(?:\.\d+)?)\s*mn|million", re.IGNORECASE)
_NUM_CR_PATTERN = re.compile(r"([\d,]+(?:\.\d+)?)\s*(?:crore|cr\b)", re.IGNORECASE)


def extract_order_value_cr(text: str) -> Optional[float]:
    """Try to extract an order/contract value in ₹ Crore from announcement text."""
    for pat in (_CR_PATTERN, _NUM_CR_PATTERN):
        m = pat.search(text or "")
        if m:
            try:
                return float(m.group(1).replace(",", ""))
            except ValueError:
                pass
    # Million rupees fallback
    m = _MN_PATTERN.search(text or "")
    if m:
        try:
            return float(m.group(1).replace(",", "")) / 100  # mn → Cr
        except ValueError:
            pass
    return None
