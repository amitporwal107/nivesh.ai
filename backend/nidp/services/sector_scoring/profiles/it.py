"""IT Services sector fundamental scoring profile.

PRD §6.4 — Growth is the primary driver for IT; attrition, utilization,
and deal wins matter as operational leading indicators.

Fundamental weights (sum = 100):
    Growth          28%  (CC revenue growth, deal TCV, headcount)
    Profitability   23%  (EBIT margin — tiered by mcap, ROCE, FCF conversion)
    Operational     18%  (utilisation, attrition, offshore ratio)
    Client Health   13%  (client concentration, large-client trend)
    Governance       8%
    Valuation       10%  (PE relative to own 5Y history)
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from ..governance import score_governance
from ..normalizers import hib, lib, weighted


# EBIT margin bands by market-cap tier (PRD §6.4)
_MARGIN_BANDS: Dict[str, tuple[float, float]] = {
    "LARGE_CAP": (15.0, 25.0),
    "MID_CAP":   (12.0, 22.0),
    "SMALL_CAP": (10.0, 20.0),
    "MICRO_CAP": (10.0, 20.0),
}


def score_fundamental_it(
    prims: Dict[str, Any],
) -> tuple[float, Dict[str, Any]]:
    """Return (fundamental_score 0–100, sub_scores dict)."""

    def _p(key: str) -> Optional[float]:
        v = prims.get(key)
        return float(v) if v is not None else None

    mcap_bucket = (prims.get("market_cap_bucket") or "MID_CAP").upper()
    margin_floor, margin_ceil = _MARGIN_BANDS.get(mcap_bucket, (12.0, 22.0))

    # ── Growth (28%) ─────────────────────────────────────────────────
    # CC revenue growth not directly available; use revenue CAGR as proxy
    rev_cagr  = _p("revenue_growth_3y_cagr_pct")
    rev_yoy   = _p("revenue_growth_yoy_pct")
    eps_cagr  = _p("eps_growth_3y_cagr_pct")

    cc_score = hib(rev_cagr, floor=5.0, ceiling=20.0)
    # TCV growth: not available → use EPS CAGR as pipeline quality proxy
    tcv_proxy_score = hib(eps_cagr, floor=5.0, ceiling=25.0)
    # Headcount proxy: revenue YoY growth (faster growth = adding people)
    headcount_proxy = hib(rev_yoy, floor=5.0, ceiling=20.0)

    growth_score = weighted([
        (cc_score,          55),
        (tcv_proxy_score,   25),
        (headcount_proxy,   20),
    ])

    # ── Profitability (23%) ───────────────────────────────────────────
    pat_margin = _p("profit_margin_pct")
    roce       = _p("roce_pct")
    # FCF conversion: not directly available → use earnings_consistency as proxy
    earnings_cons = _p("earnings_consistency_score") or 50.0

    # EBIT margin proxied by PAT margin (IT companies have low D/E and tax)
    margin_score = hib(pat_margin, floor=margin_floor, ceiling=margin_ceil)
    roce_score   = hib(roce, floor=20.0, ceiling=40.0)
    fcf_score    = hib(earnings_cons, floor=40.0, ceiling=90.0)

    prof_score = weighted([
        (margin_score, 50),
        (roce_score,   30),
        (fcf_score,    20),
    ])

    # ── Operational Metrics (18%) ─────────────────────────────────────
    # Attrition, utilisation, offshore ratio — not in primitives.
    # Proxy: earnings_consistency (stable earnings = controlled attrition)
    # and profit_margin_trend (improving = operational leverage)
    margin_trend = _p("profit_margin_trend_pct")
    attrition_proxy = lib(margin_trend, floor=-5.0, ceiling=5.0) if margin_trend else 50.0
    # Proxy for utilisation: high ROCE with stable headcount cost
    util_proxy = hib(roce, floor=15.0, ceiling=35.0) if roce else 50.0
    offshore_proxy = 60.0  # neutral default; no data available

    ops_score = weighted([
        (util_proxy,      30),
        (attrition_proxy, 40),
        (offshore_proxy,  30),
    ])

    # ── Client Health (13%) ───────────────────────────────────────────
    # Client concentration not in primitives.
    # Proxy: revenue CAGR stability vs eps_cagr disparity
    # High disparity suggests client-mix volatility
    if rev_cagr is not None and eps_cagr is not None:
        disparity = abs(rev_cagr - eps_cagr)
        client_score = lib(disparity, floor=0.0, ceiling=15.0)
    else:
        client_score = 50.0

    # ── Governance (8%) ──────────────────────────────────────────────
    gov_score, gov_sub = score_governance(prims)

    # ── Valuation (10%) ──────────────────────────────────────────────
    # PE overvaluation percentile (from primitives: pe_overvaluation_pct)
    pe_over = _p("pe_overvaluation_pct")   # +ve = overvalued vs 5Y median
    if pe_over is not None:
        val_score = lib(pe_over, floor=-20.0, ceiling=50.0)
    else:
        pe = _p("pe_ttm")
        val_score = lib(pe, floor=15.0, ceiling=60.0) if pe else 50.0

    fundamental = weighted([
        (growth_score,  28),
        (prof_score,    23),
        (ops_score,     18),
        (client_score,  13),
        (gov_score,      8),
        (val_score,     10),
    ])

    sub: Dict[str, Any] = {
        "growth":         round(growth_score, 2),
        "profitability":  round(prof_score, 2),
        "operational":    round(ops_score, 2),
        "client_health":  round(client_score, 2),
        "governance":     round(gov_score, 2),
        "valuation":      round(val_score, 2),
        "_rev_cagr":      rev_cagr,
        "_pat_margin":    pat_margin,
        "_roce":          roce,
        "governance_detail": gov_sub,
    }
    return round(fundamental, 2), sub
