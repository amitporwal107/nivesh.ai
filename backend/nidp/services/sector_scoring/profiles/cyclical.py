"""Cyclical sector fundamental scoring profile.

PRD §6.3 — Metals, Cement, Auto, Chemicals, Real Estate.
Critical insight: through-cycle normalisation prevents the PE trap.
Counter-intuitive scoring: high score when cycle is at trough.

Fundamental weights (sum = 100):
    Balance Sheet Strength      30%  (D/EBITDA, Interest Coverage, Current Ratio)
    Operational Efficiency      22%  (margin structure, cost discipline)
    Through-Cycle Profitability 20%  (10Y/5Y avg ROCE, avg EBITDA margin)
    Valuation                   15%  (EV/EBITDA trough-sensitive)
    Free Cash Flow Quality       8%
    Governance                   5%

Cycle Position Score (separate 20% weight in final composite):
    Commodity Price Position    40%
    Margin Position             30%
    Capacity Utilization        30%
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from ..governance import score_governance
from ..normalizers import hib, lib, weighted


def score_fundamental_cyclical(
    prims: Dict[str, Any],
) -> tuple[float, Dict[str, Any]]:
    """Return (fundamental_score 0–100, sub_scores dict)."""

    def _p(key: str) -> Optional[float]:
        v = prims.get(key)
        return float(v) if v is not None else None

    # ── Balance Sheet Strength (30%) ──────────────────────────────────
    de  = _p("debt_to_equity")
    ic  = _p("interest_coverage")

    # Proxy D/EBITDA from D/E and EBITDA margin:
    ebitda_margin = _p("profit_margin_pct")  # rough proxy for EBITDA margin
    # For cyclicals, D/E 0.5–4 is the normal range
    de_ebitda_proxy = lib(de, floor=0.5, ceiling=4.0) if de else 50.0
    ic_score = hib(ic, floor=2.0, ceiling=10.0) if ic else 50.0
    # Current ratio not directly in primitives; use interest coverage as proxy
    cr_proxy = hib(ic, floor=1.5, ceiling=5.0) if ic else 50.0

    bs_score = weighted([
        (de_ebitda_proxy, 40),
        (ic_score,        30),
        (cr_proxy,        30),
    ])

    # ── Operational Efficiency (22%) ─────────────────────────────────
    pat_margin    = _p("profit_margin_pct")
    margin_trend  = _p("profit_margin_trend_pct")
    roce          = _p("roce_pct")

    margin_score = hib(pat_margin, floor=5.0, ceiling=20.0)
    trend_score  = hib(margin_trend, floor=-5.0, ceiling=8.0)
    roce_score   = hib(roce, floor=8.0, ceiling=22.0)

    ops_score = weighted([
        (margin_score, 40),
        (trend_score,  30),
        (roce_score,   30),
    ])

    # ── Through-Cycle Profitability (20%) ─────────────────────────────
    # Ideally 10Y averages from nse_financials_annual; use 3Y CAGR as proxy
    rev_cagr = _p("revenue_growth_3y_cagr_pct")
    eps_cagr = _p("eps_growth_3y_cagr_pct")
    ec       = _p("earnings_consistency_score") or 50.0

    # Through-cycle ROCE proxy: 3Y average consistency
    through_roce  = hib(ec, floor=30.0, ceiling=85.0)
    through_margin = hib(eps_cagr, floor=-5.0, ceiling=15.0) if eps_cagr else 50.0

    through_cycle = weighted([
        (through_roce,   50),
        (through_margin, 50),
    ])

    # ── Valuation (15%) ──────────────────────────────────────────────
    # EV/EBITDA trough-sensitive: low EV/EBITDA at cycle bottom = opportunity
    ev_ebitda = _p("ev_ebitda")
    if ev_ebitda is not None:
        # Cyclical EV/EBITDA: 3–5x = trough (score high), 12–15x = peak (score low)
        val_score = lib(ev_ebitda, floor=3.0, ceiling=12.0)
    else:
        pe = _p("pe_ttm")
        val_score = lib(pe, floor=8.0, ceiling=25.0) if pe else 50.0

    # ── Free Cash Flow Quality (8%) ───────────────────────────────────
    # Proxy: earnings consistency + low D/E spike
    debt_spike = prims.get("debt_spike_flag")
    fcf_score  = hib(ec, floor=30.0, ceiling=85.0)
    if debt_spike:
        fcf_score = max(0.0, fcf_score - 20.0)

    # ── Governance (5%) ──────────────────────────────────────────────
    gov_score, gov_sub = score_governance(prims)

    fundamental = weighted([
        (bs_score,      30),
        (ops_score,     22),
        (through_cycle, 20),
        (val_score,     15),
        (fcf_score,      8),
        (gov_score,      5),
    ])

    sub: Dict[str, Any] = {
        "balance_sheet":         round(bs_score, 2),
        "operational_efficiency": round(ops_score, 2),
        "through_cycle_profit":  round(through_cycle, 2),
        "valuation":             round(val_score, 2),
        "fcf_quality":           round(fcf_score, 2),
        "governance":            round(gov_score, 2),
        "_ev_ebitda":            ev_ebitda,
        "_interest_coverage":    ic,
        "_debt_to_equity":       de,
        "governance_detail":     gov_sub,
    }
    return round(fundamental, 2), sub


def score_cycle_position(
    prims: Dict[str, Any],
    commodity_data: Optional[Dict[str, Any]] = None,
) -> tuple[float, Dict[str, Any]]:
    """Score the cycle position (0–100, high = near trough = opportunity).

    PRD §6.3: Counter-intuitive scoring — rewarded for buying at the trough.
    commodity_data: future feed from commodity_prices_daily (not yet available).
    """
    def _p(key: str) -> Optional[float]:
        v = prims.get(key)
        return float(v) if v is not None else None

    cd = commodity_data or {}

    # ── Commodity Price Position (40%) ────────────────────────────────
    commodity_pct_range = cd.get("commodity_pct_of_10y_range")
    if commodity_pct_range is not None:
        # Low in range (< 25%) = trough = score 100; peak (> 75%) = score 0
        comm_score = lib(float(commodity_pct_range), floor=25.0, ceiling=75.0)
    else:
        # No commodity data yet (Section 11 gap) — use EV/EBITDA as proxy
        ev_ebitda = _p("ev_ebitda")
        if ev_ebitda is not None:
            # Low EV/EBITDA = trough; high = peak
            comm_score = lib(ev_ebitda, floor=3.0, ceiling=15.0)
        else:
            comm_score = 50.0

    # ── Margin Position (30%) ────────────────────────────────────────
    # Bottom quartile of own history = compression done → high score
    # Proxy: current margin vs 3Y trend
    margin_trend  = _p("profit_margin_trend_pct")
    pat_margin    = _p("profit_margin_pct")

    if margin_trend is not None and pat_margin is not None:
        # If margins are contracting (negative trend) and absolute level is low
        # → cycle near trough → high score
        if margin_trend < -2.0 and pat_margin < 10.0:
            margin_pos_score = 80.0  # near trough
        elif margin_trend >= 2.0 and pat_margin > 15.0:
            margin_pos_score = 20.0  # at peak — mean reversion likely
        else:
            margin_pos_score = 50.0  # mid-cycle
    else:
        margin_pos_score = 50.0

    # ── Capacity Utilization Position (30%) ──────────────────────────
    # Not directly available; use revenue growth momentum as proxy
    # Low/negative revenue growth + low margins = underutilisation = trough
    rev_yoy = _p("revenue_growth_yoy_pct")
    if rev_yoy is not None:
        if rev_yoy < 0:
            cap_util_score = 80.0   # revenue contracting = low utilisation = trough
        elif rev_yoy > 20.0:
            cap_util_score = 20.0   # high revenue = high utilisation = peak
        else:
            cap_util_score = 50.0
    else:
        cap_util_score = 50.0

    cycle_score = weighted([
        (comm_score,      40),
        (margin_pos_score, 30),
        (cap_util_score,  30),
    ])

    sub: Dict[str, Any] = {
        "commodity_position":  round(comm_score, 2),
        "margin_position":     round(margin_pos_score, 2),
        "capacity_utilization": round(cap_util_score, 2),
        "has_commodity_data":  commodity_pct_range is not None,
    }
    return round(cycle_score, 2), sub
