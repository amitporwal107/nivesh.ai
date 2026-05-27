"""Pharma / Healthcare sector fundamental scoring profile.

PRD §6.6 — Export-heavy vs domestic-focused split; regulatory standing
is often binary (import alert = near-zero score).

Fundamental weights — export-heavy variant (sum = 100):
    Pipeline Strength       23%  (ANDA pending, complex generics)
    Regulatory Standing     20%  (USFDA outcomes)
    Profitability           18%
    Geographic Diversification 13%
    R&D Productivity        10%
    Governance               6%
    Valuation               10%

Domestic-focused: Profitability 25%, Growth 20%, Pipeline 15%,
                  Regulatory 5%, Geography 10%, Gov 8%, Val 17%.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from ..governance import score_governance
from ..normalizers import hib, lib, weighted


def score_fundamental_pharma(
    prims: Dict[str, Any],
    event_signals: Optional[Dict[str, Any]] = None,
) -> tuple[float, Dict[str, Any]]:
    """Return (fundamental_score 0–100, sub_scores dict).

    event_signals: dict of recent event categories from corporate_event_signals.
    """
    def _p(key: str) -> Optional[float]:
        v = prims.get(key)
        return float(v) if v is not None else None

    es = event_signals or {}

    # ── Regulatory Standing (20%) ─────────────────────────────────────
    # Sourced from announcement_classifier taxonomy when available.
    # Default neutral (70 = Form 483 minor observations level)
    reg_outcome = es.get("regulatory_standing_score")
    if reg_outcome is not None:
        reg_score = float(reg_outcome)
    else:
        # No signal = assume clean (most pharma companies don't have issues)
        reg_score = 75.0

    # Apply hard penalties from event signals
    if es.get("has_import_alert"):
        reg_score = min(reg_score, 5.0)    # import alert on core = near-zero
    elif es.get("has_warning_letter_core"):
        reg_score = min(reg_score, 10.0)   # warning letter core = very low
    elif es.get("has_warning_letter_noncore"):
        reg_score = min(reg_score, 40.0)   # non-core = moderate penalty

    # ── Pipeline Strength (23%) ────────────────────────────────────────
    # ANDA data not in primitives; proxy: R&D intensity from revenue allocation
    # Use EPS CAGR as pipeline productivity signal (R&D-heavy with launches = EPS growth)
    eps_cagr = _p("eps_growth_3y_cagr_pct")
    rev_cagr = _p("revenue_growth_3y_cagr_pct")

    # Strong EPS CAGR relative to revenue = good pipeline conversion ratio
    pipeline_proxy = hib(eps_cagr, floor=5.0, ceiling=25.0)
    complex_proxy  = hib(rev_cagr, floor=5.0, ceiling=20.0)   # complex generics need market presence

    pipeline_score = weighted([
        (pipeline_proxy, 40),
        (complex_proxy,  30),
        (60.0,           30),  # specialty pipeline: neutral default
    ])

    # ── Profitability (18%) ───────────────────────────────────────────
    roce    = _p("roce_pct")
    pat_mg  = _p("profit_margin_pct")
    roe     = _p("roe_pct")

    roce_score   = hib(roce,    floor=12.0, ceiling=30.0)
    margin_score = hib(pat_mg,  floor=8.0,  ceiling=22.0)
    roe_score    = hib(roe,     floor=12.0, ceiling=25.0)

    prof_score = weighted([
        (roce_score,   40),
        (margin_score, 35),
        (roe_score,    25),
    ])

    # ── Geographic Diversification (13%) ─────────────────────────────
    # Export revenue % not in primitives; use revenue volatility as proxy
    # High revenue volatility (in USD stocks) = likely global = diversified
    ec = _p("earnings_consistency_score") or 50.0
    # For export pharma: revenue consistency comes from diversified geographies
    geo_score = hib(ec, floor=30.0, ceiling=80.0)

    # ── R&D Productivity (10%) ────────────────────────────────────────
    # Proxy: margin trend improving + revenue CAGR > EPS CAGR
    # (R&D companies invest heavily; good R&D = future earnings growth)
    margin_trend = _p("profit_margin_trend_pct")
    if margin_trend is not None and eps_cagr is not None:
        rd_score = hib(margin_trend + eps_cagr / 2.0, floor=0.0, ceiling=15.0)
    else:
        rd_score = 50.0

    # ── Governance (6%) ──────────────────────────────────────────────
    gov_score, gov_sub = score_governance(prims)

    # ── Valuation (10%) ──────────────────────────────────────────────
    pe_over = _p("pe_overvaluation_pct")
    if pe_over is not None:
        val_score = lib(pe_over, floor=-20.0, ceiling=50.0)
    else:
        pe = _p("pe_ttm")
        val_score = lib(pe, floor=15.0, ceiling=50.0) if pe else 50.0

    fundamental = weighted([
        (pipeline_score, 23),
        (reg_score,      20),
        (prof_score,     18),
        (geo_score,      13),
        (rd_score,       10),
        (gov_score,       6),
        (val_score,      10),
    ])

    sub: Dict[str, Any] = {
        "pipeline_strength":    round(pipeline_score, 2),
        "regulatory_standing":  round(reg_score, 2),
        "profitability":        round(prof_score, 2),
        "geo_diversification":  round(geo_score, 2),
        "rd_productivity":      round(rd_score, 2),
        "governance":           round(gov_score, 2),
        "valuation":            round(val_score, 2),
        "_eps_cagr":            eps_cagr,
        "_roce":                roce,
        "governance_detail":    gov_sub,
    }
    return round(fundamental, 2), sub
