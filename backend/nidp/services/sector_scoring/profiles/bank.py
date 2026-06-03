"""Bank sector fundamental scoring profile.

PRD §6.1 — uses bank_metrics_daily (NPA/NIM/ROA/ROE) as the primary source,
supplemented by stock primitives for governance and valuation.

Fundamental weights (sum = 100):
    Asset Quality   28%  (GNPA, NNPA, PCR, Slippage)
    Profitability   22%  (NIM, RoA, RoE)
    Capital Adequacy 15% (CAR, CET1) — proxied from primitives if direct unavailable
    Growth          15%  (Credit growth, CASA, Deposit growth)
    Efficiency      10%  (Cost-to-Income via PAT margin proxy)
    Governance       5%
    Valuation        5%  (P/B based)
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from ..governance import score_governance
from ..normalizers import hib, lib, weighted


def score_fundamental_bank(
    prims: Dict[str, Any],
    bank_metrics: Optional[Dict[str, Any]] = None,
) -> tuple[float, Dict[str, Any]]:
    """Return (fundamental_score 0–100, sub_scores dict).

    bank_metrics: row from nidp.bank_metrics_daily or bank_quality_scores_daily.
    Falls back gracefully when bank_metrics is None.
    """
    bm = bank_metrics or {}

    def _b(key: str) -> Optional[float]:
        v = bm.get(key)
        return float(v) if v is not None else None

    def _p(key: str) -> Optional[float]:
        v = prims.get(key)
        return float(v) if v is not None else None

    # ── Asset Quality (28%) ───────────────────────────────────────────
    # PSU banks tolerate higher GNPA; private have tighter bands.
    # For the unified v3 scorer, use a single standard band per PRD §6.1.
    gnpa    = _b("gnpa_pct")
    nnpa    = _b("nnpa_pct")
    pcr     = _b("pcr_implied_pct")

    gnpa_score = lib(gnpa, floor=1.0, ceiling=5.0)
    nnpa_score = lib(nnpa, floor=0.3, ceiling=2.0)
    pcr_score  = hib(pcr,  floor=50.0, ceiling=85.0)

    # Slippage: quarter-on-quarter change in GNPA as proxy for slippage rate
    gnpa_4q    = _b("gnpa_4q_ago")
    if gnpa is not None and gnpa_4q is not None and gnpa_4q > 0:
        # Annualised new slippage ≈ (GNPA_current − GNPA_4Q_ago + recoveries)
        # Simple proxy: (GNPA_current / GNPA_4Q_ago − 1) × 100 as slippage rate
        slippage_proxy = max(0.0, (gnpa - gnpa_4q))
        slippage_score = lib(slippage_proxy, floor=0.0, ceiling=3.0)
    else:
        slippage_score = 50.0

    has_npa = gnpa is not None
    if has_npa:
        aq_score = weighted([
            (gnpa_score,     35),
            (nnpa_score,     35),
            (pcr_score,      20),
            (slippage_score, 10),
        ])
    else:
        aq_score = None  # no NPA data → omit pillar (handled in composer)

    # ── Profitability (22%) ───────────────────────────────────────────
    # NIM proxy: nii_retention_pct from bank_metrics (NII / revenue × 100)
    nim_proxy  = _b("nii_retention_pct")
    pat_margin = _b("pat_margin_pct")
    roe        = _b("roe_pct") or _p("roe_pct")

    nim_score = hib(nim_proxy,  floor=2.0, ceiling=4.5) if nim_proxy is not None \
                else hib(None, 2.0, 4.5)
    # RoA not directly available; use PAT margin as a proxy for operating efficiency
    roa_proxy_score = hib(pat_margin, floor=8.0, ceiling=22.0)
    roe_score       = hib(roe,        floor=8.0, ceiling=20.0)

    prof_score = weighted([
        (nim_score,       30),
        (roa_proxy_score, 35),
        (roe_score,       35),
    ])

    # ── Capital Adequacy (15%) ─────────────────────────────────────────
    # CAR/CET1 rarely in primitives; use D/E inverse as proxy:
    # Banks are naturally leveraged, so D/E is not penalised, but
    # very high D/E (> 12×) suggests thin capital.
    de = _p("debt_to_equity")
    if de is not None:
        # Scale: D/E 8 = 100 (well-capitalised), D/E 15 = 0 (undercapitalised)
        car_proxy = lib(de, floor=8.0, ceiling=15.0)
    else:
        car_proxy = 50.0
    cap_score = car_proxy

    # ── Growth (15%) ─────────────────────────────────────────────────
    # Credit growth: use revenue YoY as proxy (interest earned growth)
    rev_yoy   = _p("revenue_growth_yoy_pct")
    pat_yoy   = _b("pat_yoy_growth_pct") or _p("pat_growth_yoy_pct")

    # Revenue growth: sector percentile — capped at 25% (aggressive = risk)
    if rev_yoy is not None:
        capped_rev = min(rev_yoy, 25.0)
        credit_score = hib(capped_rev, floor=5.0, ceiling=20.0)
    else:
        credit_score = 50.0

    # NII retention as CASA proxy (higher retention = cheaper funding)
    casa_proxy = hib(nim_proxy, floor=25.0, ceiling=50.0)

    pat_growth_score = hib(pat_yoy, floor=5.0, ceiling=30.0)

    growth_score = weighted([
        (credit_score,    40),
        (casa_proxy,      30),
        (pat_growth_score, 30),
    ])

    # ── Efficiency (10%) ─────────────────────────────────────────────
    # Cost-to-income: use PAT margin as inverse proxy
    # (high PAT margin = low effective C2I, since expenses include provisions)
    eff_score = hib(pat_margin, floor=8.0, ceiling=22.0)

    # ── Governance (5%) ──────────────────────────────────────────────
    gov_score, gov_sub = score_governance(prims)

    # ── Valuation (5%) ───────────────────────────────────────────────
    pb = _p("pb")
    val_score = lib(pb, floor=0.5, ceiling=4.0) if pb is not None else 50.0

    # ── Composite ────────────────────────────────────────────────────
    # If no NPA data, redistribute asset quality weight across other pillars
    if aq_score is not None:
        fundamental = weighted([
            (aq_score,     28),
            (prof_score,   22),
            (cap_score,    15),
            (growth_score, 15),
            (eff_score,    10),
            (gov_score,     5),
            (val_score,     5),
        ])
    else:
        # No NPA — redistribute 28% proportionally across remaining pillars
        fundamental = weighted([
            (prof_score,   22),
            (cap_score,    15),
            (growth_score, 15),
            (eff_score,    10),
            (gov_score,     5),
            (val_score,     5),
        ])

    sub: Dict[str, Any] = {
        "asset_quality":     round(aq_score, 2) if aq_score is not None else None,
        "profitability":     round(prof_score, 2),
        "capital_adequacy":  round(cap_score, 2),
        "growth":            round(growth_score, 2),
        "efficiency":        round(eff_score, 2),
        "governance":        round(gov_score, 2),
        "valuation":         round(val_score, 2),
        "has_npa_data":      has_npa,
        "_gnpa":             gnpa,
        "_nnpa":             nnpa,
        "_pcr":              pcr,
        "_roe":              roe,
        "_pat_margin":       pat_margin,
        "governance_detail": gov_sub,
    }
    return round(fundamental, 2), sub
