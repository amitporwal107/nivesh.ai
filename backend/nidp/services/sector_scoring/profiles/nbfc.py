"""NBFC sector fundamental scoring profile.

PRD §6.2 — NBFCs differ from banks in that ALM management is paramount;
cost-of-funds trend and Spread (yield minus CoF) matter more than NPA alone.

Fundamental weights (sum = 100):
    Asset Quality       22%
    Profitability       18%
    Capital Adequacy    13%
    ALM Strength        17%
    Borrowing Cost Trend 10%
    Growth              10%
    Governance           5%
    Valuation            5%
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from ..governance import score_governance
from ..normalizers import hib, lib, weighted


def score_fundamental_nbfc(
    prims: Dict[str, Any],
) -> tuple[float, Dict[str, Any]]:
    """Return (fundamental_score 0–100, sub_scores dict)."""

    def _p(key: str) -> Optional[float]:
        v = prims.get(key)
        return float(v) if v is not None else None

    # ── Asset Quality (22%) ───────────────────────────────────────────
    # NBFCs use GNPA/NNPA similarly to banks but have higher tolerance.
    # Proxy from primitives: debt_trend (rising debt + falling profit = stress)
    # Direct NPA not in primitives → use profit_margin_trend as proxy
    profit_trend = _p("profit_margin_trend_pct")
    debt_trend   = _p("debt_trend_pct")

    # Proxy NPA quality: stable/improving profit margin = good asset quality
    aq_proxy = hib(profit_trend, floor=-5.0, ceiling=5.0)  # -5% = worsening, +5% = improving
    # Rising debt with falling margins = stress signal
    if debt_trend is not None and debt_trend > 20.0 and profit_trend is not None and profit_trend < 0:
        aq_proxy = max(0.0, aq_proxy - 20.0)

    aq_score = aq_proxy

    # ── Profitability (18%) ───────────────────────────────────────────
    # Spread = Yield − CoF; ROA target higher for NBFCs (1.5–3.5%)
    roe    = _p("roe_pct")
    pat_mg = _p("profit_margin_pct")
    roce   = _p("roce_pct")

    # ROA proxy: use PAT margin as high-level profitability signal
    roa_score    = hib(pat_mg, floor=10.0, ceiling=25.0)
    roe_score    = hib(roe,    floor=12.0, ceiling=22.0)
    spread_score = hib(roce,   floor=8.0,  ceiling=18.0)  # ROCE as spread proxy

    prof_score = weighted([
        (spread_score, 40),
        (roa_score,    30),
        (roe_score,    30),
    ])

    # ── Capital Adequacy (13%) ────────────────────────────────────────
    de = _p("debt_to_equity")
    # NBFCs operate at higher leverage than non-financials; D/E 4–8 is normal
    cap_score = lib(de, floor=3.0, ceiling=10.0) if de is not None else 50.0

    # ── ALM Strength (17%) ────────────────────────────────────────────
    # Direct ALM data not in primitives; proxies:
    # - Interest coverage (higher = better ability to service short-term debt)
    # - Debt trend (rapidly rising debt = maturity mismatch risk)
    ic = _p("interest_coverage")
    ic_score       = hib(ic,         floor=1.5, ceiling=5.0)
    borrow_div_score = lib(debt_trend, floor=0.0, ceiling=30.0)  # rapid borrowing surge = bad

    alm_score = weighted([
        (ic_score,        40),
        (borrow_div_score, 30),
        (50.0,            30),   # liquidity coverage: neutral (data not available)
    ])

    # ── Borrowing Cost Trend (10%) ────────────────────────────────────
    # Proxy: if revenue growth is slowing but debt growing = rising CoF pressure
    rev_yoy = _p("revenue_growth_yoy_pct")
    if rev_yoy is not None and debt_trend is not None:
        # Approximation: spread compression signal
        spread_compression = debt_trend - rev_yoy
        borrow_trend_score = lib(spread_compression, floor=-5.0, ceiling=15.0)
    else:
        borrow_trend_score = 50.0

    # ── Growth (10%) ─────────────────────────────────────────────────
    rev_cagr = _p("revenue_growth_3y_cagr_pct")
    pat_yoy  = _p("pat_growth_yoy_pct")
    growth_score = weighted([
        (hib(rev_cagr, floor=10.0, ceiling=25.0), 60),
        (hib(pat_yoy,  floor=5.0,  ceiling=25.0), 40),
    ])

    # ── Governance (5%) ──────────────────────────────────────────────
    gov_score, gov_sub = score_governance(prims)

    # ── Valuation (5%) ───────────────────────────────────────────────
    pb  = _p("pb")
    val_score = lib(pb, floor=0.8, ceiling=4.0) if pb is not None else 50.0

    fundamental = weighted([
        (aq_score,          22),
        (prof_score,        18),
        (cap_score,         13),
        (alm_score,         17),
        (borrow_trend_score, 10),
        (growth_score,      10),
        (gov_score,          5),
        (val_score,          5),
    ])

    sub: Dict[str, Any] = {
        "asset_quality":      round(aq_score, 2),
        "profitability":      round(prof_score, 2),
        "capital_adequacy":   round(cap_score, 2),
        "alm_strength":       round(alm_score, 2),
        "borrowing_cost_trend": round(borrow_trend_score, 2),
        "growth":             round(growth_score, 2),
        "governance":         round(gov_score, 2),
        "valuation":          round(val_score, 2),
        "governance_detail":  gov_sub,
    }
    return round(fundamental, 2), sub
