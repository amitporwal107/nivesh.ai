"""Default sector fundamental scoring profile.

Applied when no specific sector profile matches.
Balances quality fundamentals: profitability, balance sheet health,
growth, governance, and valuation.

Weights (sum = 100):
    Profitability   25%
    Balance Sheet   25%
    Growth          20%
    Governance      15%
    Valuation       15%
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from ..governance import score_governance
from ..normalizers import hib, lib, weighted


def score_fundamental_default(
    prims: Dict[str, Any],
) -> tuple[float, Dict[str, Any]]:
    """Return (fundamental_score 0–100, sub_scores dict)."""

    def _p(key: str) -> Optional[float]:
        v = prims.get(key)
        return float(v) if v is not None else None

    # ── Profitability (25%) ───────────────────────────────────────────
    roe    = _p("roe_pct")
    roce   = _p("roce_pct")
    pat_mg = _p("profit_margin_pct")

    prof_score = weighted([
        (hib(roe,    floor=8.0,  ceiling=25.0), 40),
        (hib(roce,   floor=8.0,  ceiling=22.0), 35),
        (hib(pat_mg, floor=5.0,  ceiling=20.0), 25),
    ])

    # ── Balance Sheet (25%) ───────────────────────────────────────────
    de = _p("debt_to_equity")
    ic = _p("interest_coverage")

    bs_score = weighted([
        (lib(de, floor=0.0, ceiling=3.0), 50) if de else (50.0, 50),
        (hib(ic, floor=2.0, ceiling=10.0), 50) if ic else (50.0, 50),
    ])

    # ── Growth (20%) ─────────────────────────────────────────────────
    rev_cagr = _p("revenue_growth_3y_cagr_pct")
    eps_cagr = _p("eps_growth_3y_cagr_pct")
    ec       = _p("earnings_consistency_score") or 50.0

    growth_score = weighted([
        (hib(rev_cagr, floor=5.0,  ceiling=20.0), 40),
        (hib(eps_cagr, floor=5.0,  ceiling=20.0), 40),
        (hib(ec,       floor=30.0, ceiling=85.0), 20),
    ])

    # ── Governance (15%) ─────────────────────────────────────────────
    gov_score, gov_sub = score_governance(prims)

    # ── Valuation (15%) ──────────────────────────────────────────────
    pe_over = _p("pe_overvaluation_pct")
    if pe_over is not None:
        val_score = lib(pe_over, floor=-20.0, ceiling=50.0)
    else:
        pe = _p("pe_ttm")
        val_score = lib(pe, floor=8.0, ceiling=40.0) if pe else 50.0

    fundamental = weighted([
        (prof_score,   25),
        (bs_score,     25),
        (growth_score, 20),
        (gov_score,    15),
        (val_score,    15),
    ])

    sub: Dict[str, Any] = {
        "profitability": round(prof_score, 2),
        "balance_sheet": round(bs_score, 2),
        "growth":        round(growth_score, 2),
        "governance":    round(gov_score, 2),
        "valuation":     round(val_score, 2),
        "_roe":          roe,
        "_roce":         roce,
        "governance_detail": gov_sub,
    }
    return round(fundamental, 2), sub
