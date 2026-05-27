"""Capital Goods / Infrastructure sector fundamental scoring profile.

PRD §6.7 — Order book is the leading indicator; revenue is lagging.
Technical weight is higher (40%) since execution risk makes momentum important.

Fundamental weights (sum = 100):
    Order Book Strength     28%  (OB/Revenue, OB growth, order quality)
    Execution Track Record  20%  (revenue growth consistency)
    Profitability           18%
    Balance Sheet           15%
    Working Capital         10%
    Governance               4%
    Valuation                5%
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from ..governance import score_governance
from ..normalizers import hib, lib, weighted


def score_fundamental_capgoods(
    prims: Dict[str, Any],
    event_signals: Optional[Dict[str, Any]] = None,
) -> tuple[float, Dict[str, Any]]:
    """Return (fundamental_score 0–100, sub_scores dict)."""

    def _p(key: str) -> Optional[float]:
        v = prims.get(key)
        return float(v) if v is not None else None

    es = event_signals or {}

    # ── Order Book Strength (28%) ─────────────────────────────────────
    # Order book data not directly in primitives; proxy:
    # - Revenue CAGR consistency = good order book execution
    # - event_signals for major order wins
    rev_cagr = _p("revenue_growth_3y_cagr_pct")
    ec       = _p("earnings_consistency_score") or 50.0

    ob_rev_proxy   = hib(rev_cagr, floor=8.0, ceiling=25.0) if rev_cagr else 50.0
    ob_growth_proxy = hib(ec, floor=30.0, ceiling=85.0)

    # Order quality: event signals for major order wins boost score
    order_quality = 60.0  # neutral default
    if es.get("has_major_order_win"):
        order_quality = min(100.0, order_quality + 20.0)
    if es.get("has_large_project_delay"):
        order_quality = max(0.0, order_quality - 20.0)

    ob_score = weighted([
        (ob_rev_proxy,    50),
        (ob_growth_proxy, 30),
        (order_quality,   20),
    ])

    # ── Execution Track Record (20%) ─────────────────────────────────
    # Consistent revenue growth = good execution
    rev_yoy      = _p("revenue_growth_yoy_pct")
    pat_yoy      = _p("pat_growth_yoy_pct")
    margin_trend = _p("profit_margin_trend_pct")

    exec_score = weighted([
        (hib(rev_cagr, floor=8.0, ceiling=20.0),    40),
        (hib(pat_yoy,  floor=5.0, ceiling=25.0),    35) if pat_yoy else (50.0, 35),
        (hib(margin_trend, floor=-2.0, ceiling=5.0), 25) if margin_trend else (50.0, 25),
    ])

    # ── Profitability (18%) ───────────────────────────────────────────
    roce   = _p("roce_pct")
    pat_mg = _p("profit_margin_pct")
    roe    = _p("roe_pct")

    prof_score = weighted([
        (hib(roce,   floor=10.0, ceiling=22.0), 40),
        (hib(pat_mg, floor=5.0,  ceiling=15.0), 35),
        (hib(roe,    floor=10.0, ceiling=22.0), 25),
    ])

    # ── Balance Sheet (15%) ───────────────────────────────────────────
    de = _p("debt_to_equity")
    ic = _p("interest_coverage")

    bs_score = weighted([
        (lib(de, floor=0.5, ceiling=2.5), 50) if de else (50.0, 50),
        (hib(ic, floor=3.0, ceiling=12.0), 50) if ic else (50.0, 50),
    ])

    # ── Working Capital (10%) ─────────────────────────────────────────
    # Capgoods companies have long cash conversion cycles.
    # Proxy: interest coverage (good IC = well-managed WC)
    # Also: receivables spike from event signals
    wc_score = hib(ic, floor=3.0, ceiling=10.0) if ic else 50.0
    if es.get("has_receivables_spike"):
        wc_score = max(0.0, wc_score - 20.0)

    # ── Governance (4%) ──────────────────────────────────────────────
    gov_score, gov_sub = score_governance(prims)

    # ── Valuation (5%) ───────────────────────────────────────────────
    pe_over = _p("pe_overvaluation_pct")
    if pe_over is not None:
        val_score = lib(pe_over, floor=-15.0, ceiling=40.0)
    else:
        pe = _p("pe_ttm")
        val_score = lib(pe, floor=15.0, ceiling=40.0) if pe else 50.0

    fundamental = weighted([
        (ob_score,   28),
        (exec_score, 20),
        (prof_score, 18),
        (bs_score,   15),
        (wc_score,   10),
        (gov_score,   4),
        (val_score,   5),
    ])

    sub: Dict[str, Any] = {
        "order_book_strength":    round(ob_score, 2),
        "execution_track_record": round(exec_score, 2),
        "profitability":          round(prof_score, 2),
        "balance_sheet":          round(bs_score, 2),
        "working_capital":        round(wc_score, 2),
        "governance":             round(gov_score, 2),
        "valuation":              round(val_score, 2),
        "_rev_cagr":              rev_cagr,
        "_roce":                  roce,
        "governance_detail":      gov_sub,
    }
    return round(fundamental, 2), sub
