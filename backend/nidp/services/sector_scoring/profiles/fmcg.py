"""FMCG / Consumer Staples sector fundamental scoring profile.

PRD §6.5 — Volume growth matters more than value growth; valuation is
always optically high — compare to own history only.

Fundamental weights (sum = 100):
    Growth Quality      28%  (volume growth, value growth, rural mix)
    Profitability       23%  (ROE, PAT margin trend)
    Capital Efficiency  20%  (ROCE, Working Capital days)
    Brand Strength      15%  (gross margin stability, A&P intensity)
    Governance           5%
    Valuation            9%  (PE relative to OWN 5Y history)
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from ..governance import score_governance
from ..normalizers import hib, lib, weighted


def score_fundamental_fmcg(
    prims: Dict[str, Any],
) -> tuple[float, Dict[str, Any]]:
    """Return (fundamental_score 0–100, sub_scores dict)."""

    def _p(key: str) -> Optional[float]:
        v = prims.get(key)
        return float(v) if v is not None else None

    # ── Growth Quality (28%) ─────────────────────────────────────────
    # Volume growth not directly available; use revenue CAGR as proxy
    # (FMCG pricing power means value ≈ volume + price, so CAGR captures both)
    rev_cagr = _p("revenue_growth_3y_cagr_pct")
    rev_yoy  = _p("revenue_growth_yoy_pct")
    eps_cagr = _p("eps_growth_3y_cagr_pct")

    volume_proxy_score = hib(rev_cagr, floor=0.0, ceiling=10.0)
    value_score        = hib(rev_yoy,  floor=2.0,  ceiling=12.0)
    # Rural mix not available; use earnings consistency as consumer breadth proxy
    ec = _p("earnings_consistency_score") or 50.0
    rural_proxy = hib(ec, floor=40.0, ceiling=90.0)

    growth_score = weighted([
        (volume_proxy_score, 60),
        (value_score,        30),
        (rural_proxy,        10),
    ])

    # ── Profitability (23%) ───────────────────────────────────────────
    roe    = _p("roe_pct")
    pat_mg = _p("profit_margin_pct")

    roe_score  = hib(roe,    floor=15.0, ceiling=40.0)
    margin_score = hib(pat_mg, floor=8.0,  ceiling=20.0)

    prof_score = weighted([
        (roe_score,    50),
        (margin_score, 50),
    ])

    # ── Capital Efficiency (20%) ──────────────────────────────────────
    roce = _p("roce_pct")
    de   = _p("debt_to_equity")
    ic   = _p("interest_coverage")

    roce_score = hib(roce, floor=20.0, ceiling=50.0)
    # Working capital proxy: interest coverage (high IC = strong WC management)
    wc_score   = hib(ic, floor=5.0, ceiling=20.0) if ic else 50.0
    # Capital-light check: low D/E is a positive signal for FMCG
    de_score   = lib(de, floor=0.0, ceiling=1.5) if de else 50.0

    cap_eff = weighted([
        (roce_score, 50),
        (de_score,   30),
        (wc_score,   20),
    ])

    # ── Brand Strength (15%) ─────────────────────────────────────────
    # Gross margin stability: use profit_margin_trend as proxy
    margin_trend = _p("profit_margin_trend_pct")
    # Stable or improving margin = strong brand pricing power
    if margin_trend is not None:
        gm_stability = hib(margin_trend, floor=-3.0, ceiling=3.0)
    else:
        gm_stability = 50.0

    # A&P intensity not available; use revenue_growth vs earnings_decline
    earnings_decline = prims.get("earnings_decline_flag")
    if earnings_decline:
        ap_proxy = 30.0  # earnings declining → likely cutting A&P
    else:
        ap_proxy = 65.0  # neutral-positive default

    brand_score = weighted([
        (gm_stability, 50),
        (ap_proxy,     30),
        (50.0,         20),   # distribution reach: neutral
    ])

    # ── Governance (5%) ──────────────────────────────────────────────
    gov_score, gov_sub = score_governance(prims)

    # ── Valuation (9%) ───────────────────────────────────────────────
    # FMCG: compare to own history, not absolute PE
    pe_over = _p("pe_overvaluation_pct")
    if pe_over is not None:
        # pe_overvaluation_pct: +20 = 20% above 5Y median (expensive)
        val_score = lib(pe_over, floor=-20.0, ceiling=40.0)
    else:
        pe = _p("pe_ttm")
        # Absolute PE: FMCG trades at 25–60x; use wide band
        val_score = lib(pe, floor=20.0, ceiling=70.0) if pe else 50.0

    fundamental = weighted([
        (growth_score, 28),
        (prof_score,   23),
        (cap_eff,      20),
        (brand_score,  15),
        (gov_score,     5),
        (val_score,     9),
    ])

    sub: Dict[str, Any] = {
        "growth_quality":    round(growth_score, 2),
        "profitability":     round(prof_score, 2),
        "capital_efficiency": round(cap_eff, 2),
        "brand_strength":    round(brand_score, 2),
        "governance":        round(gov_score, 2),
        "valuation":         round(val_score, 2),
        "_rev_cagr":         rev_cagr,
        "_roe":              roe,
        "_roce":             roce,
        "governance_detail": gov_sub,
    }
    return round(fundamental, 2), sub
