"""Universal governance sub-score.

Applies across all sector profiles (weighting varies per sector).
Inputs sourced from nidp.v_v3_stock_primitives (shareholding_pattern).

Formula (from PRD §4.3):
    Governance = (Promoter_Stability × 0.30) + (Pledge_Score × 0.40)
               + (FII_MF_Trend × 0.30)
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from .normalizers import hib, weighted


def score_governance(prims: Dict[str, Any]) -> tuple[float, Dict[str, float]]:
    """Return (governance_score 0–100, sub_scores dict).

    prims keys used:
        promoter_pct             — current promoter holding %
        promoter_pct_change_qoq  — QoQ change in promoter holding
        promoter_pledged_pct     — pledged shares as % of total
        fii_pct_change_qoq       — FII holding QoQ change
        dii_pct_change_qoq       — DII (includes MF) holding QoQ change
    """
    def _get(key: str) -> Optional[float]:
        v = prims.get(key)
        return float(v) if v is not None else None

    # ── Promoter Stability ─────────────────────────────────────────────
    # Uses QoQ change as a proxy for trend (3-month window)
    # Ideally we'd track 4-quarter trend, but QoQ is available in primitives.
    promo_chg = _get("promoter_pct_change_qoq")
    if promo_chg is None:
        stability_score = 50.0
    elif promo_chg >= 0:                   # stable or rising
        stability_score = 100.0
    elif promo_chg >= -2.0:               # minor decline (< 2%)
        stability_score = 50.0
    else:                                  # material decline (> 2%)
        stability_score = max(0.0, 50.0 + promo_chg * 10.0)  # steeper drop → lower

    # ── Pledge Score ────────────────────────────────────────────────────
    pledge = _get("promoter_pledged_pct")
    if pledge is None:
        pledge_score = 70.0  # slight positive default — most promoters don't pledge
    else:
        # MAX(0, 100 − pledge% × 2)  → 0% pledge = 100, 50%+ pledge = 0
        pledge_score = max(0.0, 100.0 - pledge * 2.0)

    # ── FII + MF Trend ─────────────────────────────────────────────────
    fii_chg = _get("fii_pct_change_qoq") or 0.0
    dii_chg = _get("dii_pct_change_qoq") or 0.0
    # Base 50; +25 for rising FII; +25 for rising DII/MF (scaled)
    fii_bonus = min(25.0, max(-25.0, fii_chg * 5.0))
    dii_bonus = min(25.0, max(-25.0, dii_chg * 5.0))
    fiimf_score = min(100.0, max(0.0, 50.0 + fii_bonus + dii_bonus))

    score = weighted([
        (stability_score, 30),
        (pledge_score,    40),
        (fiimf_score,     30),
    ])

    sub = {
        "promoter_stability": round(stability_score, 2),
        "pledge":             round(pledge_score, 2),
        "fii_mf_trend":       round(fiimf_score, 2),
    }
    return score, sub
