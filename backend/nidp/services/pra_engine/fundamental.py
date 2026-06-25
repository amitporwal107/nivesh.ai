"""Fundamental risk analytics for the PRA engine.

Enriches component VaR rows with per-holding fundamental metrics from
nidp.stock_features_daily and computes a composite risk score + flag set.

Score (0–100, higher = riskier):
  DISTRESS_ZONE        Altman Z < 1.81           +20
  HIGH_LEVERAGE        D/E > 3.0                 +15  (>2.0 → +10)
  WEAK_COVERAGE        Interest coverage < 1.5   +20  (<3.0 → +10)
  LIQUIDITY_SQUEEZE    Current ratio < 1.0       +15
  POOR_CASH_CONVERSION CFO/PAT < 0.3             +15
  HIGH_PLEDGE          Promoter pledge > 50%     +10
  LOW_FREE_FLOAT       Free float < 10%           +5

Portfolio summary: weighted-average score, count/pct of holdings scoring ≥ 50.
"""
from __future__ import annotations

import logging
from datetime import date
from typing import Optional

logger = logging.getLogger(__name__)

# ── Scoring thresholds ────────────────────────────────────────────────────

_THRESHOLDS = {
    "altman_z_distress":      1.81,   # below = distress zone
    "de_high":                3.0,
    "de_elevated":            2.0,
    "coverage_weak":          1.5,
    "coverage_thin":          3.0,
    "current_ratio_squeeze":  1.0,
    "cfo_pat_poor":           0.3,
    "pledge_high":            50.0,
    "free_float_low":         10.0,
}

_HIGH_RISK_THRESHOLD = 50  # score at which a holding is "high fundamental risk"


def score_holding(m: dict) -> tuple[float, list[str]]:
    """Compute a 0-100 fundamental risk score for one holding.

    Args:
        m: dict with keys from stock_features_daily (all may be None)

    Returns:
        (score, flags) — score is 0-100; flags is a list of string codes.
    """
    score = 0.0
    flags: list[str] = []

    z = m.get("altman_z_score")
    if z is not None and z < _THRESHOLDS["altman_z_distress"]:
        score += 20
        flags.append("DISTRESS_ZONE")

    de = m.get("debt_to_equity")
    if de is not None:
        if de > _THRESHOLDS["de_high"]:
            score += 15
            flags.append("HIGH_LEVERAGE")
        elif de > _THRESHOLDS["de_elevated"]:
            score += 10
            flags.append("ELEVATED_LEVERAGE")

    cov = m.get("interest_coverage")
    if cov is not None:
        if cov < _THRESHOLDS["coverage_weak"]:
            score += 20
            flags.append("WEAK_COVERAGE")
        elif cov < _THRESHOLDS["coverage_thin"]:
            score += 10
            flags.append("THIN_COVERAGE")

    cr = m.get("current_ratio")
    if cr is not None and cr < _THRESHOLDS["current_ratio_squeeze"]:
        score += 15
        flags.append("LIQUIDITY_SQUEEZE")

    cfo_pat = m.get("cfo_pat_ratio")
    if cfo_pat is not None and cfo_pat < _THRESHOLDS["cfo_pat_poor"]:
        score += 15
        flags.append("POOR_CASH_CONVERSION")

    pledge = m.get("promoter_pledged_pct")
    if pledge is not None and pledge > _THRESHOLDS["pledge_high"]:
        score += 10
        flags.append("HIGH_PLEDGE")

    ff = m.get("free_float_pct")
    if ff is not None and ff < _THRESHOLDS["free_float_low"]:
        score += 5
        flags.append("LOW_FREE_FLOAT")

    return round(min(score, 100.0), 1), flags


async def fetch_fundamental_data(
    conn,
    isins: list[str],
    target_date: date,
) -> dict[str, dict]:
    """Fetch latest fundamental metrics from stock_features_daily for a list of ISINs.

    Returns {isin: {altman_z_score, debt_to_equity, ...}} — unknown ISINs
    (e.g. MFs without look-through equity ISINs) are absent from the dict.
    """
    if not isins:
        return {}

    rows = await conn.fetch(
        """
        SELECT
            sm.isin,
            f.altman_z_score,
            f.debt_to_equity,
            f.interest_coverage,
            f.current_ratio,
            f.cfo_pat_ratio,
            f.promoter_pledged_pct,
            f.free_float_pct,
            f.operating_margin_pct
        FROM nidp.stock_features_daily f
        JOIN nidp.sector_master sm ON sm.symbol = f.symbol
        WHERE sm.isin = ANY($1::text[])
          AND f.as_of_date = (
              SELECT MAX(as_of_date)
              FROM nidp.stock_features_daily
              WHERE as_of_date <= $2
          )
        """,
        isins, target_date,
    )

    result: dict[str, dict] = {}
    for r in rows:
        isin = r["isin"]
        if isin:
            result[isin] = dict(r)

    logger.debug("fundamental.fetch: %d ISINs requested, %d found", len(isins), len(result))
    return result


def enrich_component_var(
    component_var_rows: list[dict],
    fundamental_data: dict[str, dict],
) -> list[dict]:
    """Attach fundamental metrics and risk score to each component VaR row.

    For holdings not in fundamental_data (MFs, unresolved ISINs),
    fundamental fields are None and score is None.
    """
    enriched = []
    for row in component_var_rows:
        isin = row.get("security_key", "")
        m = fundamental_data.get(isin, {})

        if m:
            fund_score, flags = score_holding(m)
        else:
            fund_score, flags = None, []

        enriched.append({
            **row,
            "altman_z_score":       m.get("altman_z_score"),
            "debt_to_equity":       m.get("debt_to_equity"),
            "interest_coverage":    m.get("interest_coverage"),
            "current_ratio":        m.get("current_ratio"),
            "cfo_pat_ratio":        m.get("cfo_pat_ratio"),
            "promoter_pledged_pct": m.get("promoter_pledged_pct"),
            "free_float_pct":       m.get("free_float_pct"),
            "operating_margin_pct": m.get("operating_margin_pct"),
            "fundamental_risk_score": fund_score,
            "risk_flags":            flags,
        })
    return enriched


def compute_portfolio_fundamental_summary(
    enriched_rows: list[dict],
) -> dict:
    """Compute portfolio-level fundamental risk summary from enriched rows.

    Returns:
        portfolio_fundamental_risk_score: weight-avg score (None if no data)
        n_high_fundamental_risk: count of holdings with score >= 50
        pct_value_high_fundamental_risk: total weight_pct of those holdings
    """
    scored = [
        r for r in enriched_rows
        if r.get("fundamental_risk_score") is not None
    ]

    if not scored:
        return {
            "portfolio_fundamental_risk_score": None,
            "n_high_fundamental_risk":          0,
            "pct_value_high_fundamental_risk":  0.0,
        }

    total_weight = sum(r["effective_weight_pct"] for r in scored)
    if total_weight <= 0:
        return {
            "portfolio_fundamental_risk_score": None,
            "n_high_fundamental_risk":          0,
            "pct_value_high_fundamental_risk":  0.0,
        }

    # Weighted average score
    weighted_score = sum(
        r["fundamental_risk_score"] * r["effective_weight_pct"]
        for r in scored
    ) / total_weight

    high_risk = [
        r for r in scored
        if r["fundamental_risk_score"] >= _HIGH_RISK_THRESHOLD
    ]
    high_risk_weight = sum(r["effective_weight_pct"] for r in high_risk)

    return {
        "portfolio_fundamental_risk_score": round(weighted_score, 1),
        "n_high_fundamental_risk":          len(high_risk),
        "pct_value_high_fundamental_risk":  round(high_risk_weight, 2),
    }
