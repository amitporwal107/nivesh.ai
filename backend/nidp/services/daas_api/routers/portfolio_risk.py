"""Portfolio Risk Analytics — DaaS endpoints.

Serves precomputed PRA results from pra.portfolio_risk_results for a given user.
These results are computed nightly by the pra_engine Cloud Run job.

Auth: requires a valid NIDP API key (same as all other DaaS routes).
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from nidp.shared.storage.pg import get_pool
from nidp.services.daas_api.auth import require_api_key

router = APIRouter(
    prefix="/portfolio-risk",
    tags=["portfolio-risk"],
    dependencies=[Depends(require_api_key)],
)


@router.get("/{external_user_id}", summary="Latest precomputed portfolio risk snapshot")
async def get_portfolio_risk(
    external_user_id: str,
    include_drivers: bool = Query(True,  description="Include component VaR breakdown"),
    include_stress:  bool = Query(True,  description="Include stress scenario results"),
    top_drivers:     int  = Query(10,    description="Max component-VaR rows to return"),
) -> Dict[str, Any]:
    """Return the latest PRA result for a user.

    All metrics are precomputed by the nightly pra_engine job.
    Returns 404 if no result exists for this user yet.

    Response shape (shared JSON contract used by Nivesh frontend v5 RiskSnapshot):

        {
          "external_user_id": "...",
          "computed_date":    "YYYY-MM-DD",
          "portfolio_value_inr": 5000000,
          "volatility_annual_pct": 15.2,
          "benchmark_vol_annual_pct": 13.8,
          "var_95_1y_pct": 18.5,
          "var_95_1y_inr": 925000,
          "max_drawdown_pct": 24.3,
          "beta_nifty500": 1.05,
          "sharpe_1y": 0.82,
          "tracking_error_pct": 4.2,
          "hhi_lookthrough": 1450,
          "lookthrough_coverage_pct": 78.5,
          "look_through_stale": false,
          "data_stale": false,
          "formula_version": "pra-v1.0",
          "computed_at": "2026-05-31T23:52:14Z",
          "risk_color": "amber",
          "risk_drivers": [...],     // component VaR rows
          "stress_scenarios": [...]  // stress scenario impacts
        }
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT *
            FROM pra.portfolio_risk_results
            WHERE external_user_id = $1
            ORDER BY computed_date DESC
            LIMIT 1
            """,
            external_user_id,
        )

    if not row:
        raise HTTPException(
            status_code=404,
            detail=f"No risk results found for user '{external_user_id}'. "
                   "Results are computed nightly — check back after the first pra_engine run.",
        )

    result_id = row["result_id"]
    result = dict(row)

    # Serialize UUID and date types
    result["result_id"]     = str(result["result_id"])
    result["computed_date"] = str(result["computed_date"])
    result["computed_at"]   = result["computed_at"].isoformat() if result.get("computed_at") else None
    result["missing_symbols"] = list(result.get("missing_symbols") or [])

    # Derive risk_color from VaR (industry standard thresholds)
    var_pct = float(result.get("var_95_1y_pct") or 0)
    result["risk_color"] = _var_color(var_pct)

    # Component VaR drivers
    if include_drivers:
        async with pool.acquire() as conn:
            driver_rows = await conn.fetch(
                """
                SELECT security_key, security_name, asset_class,
                       effective_weight_pct, marginal_var_pct,
                       component_var_pct, share_of_sigma_pct, look_through_path
                FROM pra.component_var
                WHERE result_id = $1
                ORDER BY share_of_sigma_pct DESC
                LIMIT $2
                """,
                result_id, top_drivers,
            )
        result["risk_drivers"] = [dict(r) for r in driver_rows]
    else:
        result["risk_drivers"] = []

    # Stress scenario results
    if include_stress:
        async with pool.acquire() as conn:
            stress_rows = await conn.fetch(
                """
                SELECT sr.scenario_id, ss.scenario_name,
                       sr.portfolio_impact_pct, sr.portfolio_impact_inr,
                       sr.benchmark_impact_pct,
                       ss.recovery_estimate
                FROM pra.stress_results sr
                JOIN pra.stress_scenarios ss USING (scenario_id)
                WHERE sr.result_id = $1
                ORDER BY sr.portfolio_impact_pct ASC  -- worst scenario first
                """,
                result_id,
            )
        result["stress_scenarios"] = [dict(r) for r in stress_rows]
    else:
        result["stress_scenarios"] = []

    return result


@router.get("/{external_user_id}/history", summary="Historical risk snapshots (last N days)")
async def get_portfolio_risk_history(
    external_user_id: str,
    days: int = Query(30, ge=1, le=365),
) -> Dict[str, Any]:
    """Return the last `days` daily risk snapshots for trend charting."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT computed_date, var_95_1y_pct, volatility_annual_pct,
                   max_drawdown_pct, beta_nifty500, data_stale
            FROM pra.portfolio_risk_results
            WHERE external_user_id = $1
              AND computed_date >= CURRENT_DATE - $2::int
            ORDER BY computed_date ASC
            """,
            external_user_id, days,
        )

    history = [
        {
            "date":                  str(r["computed_date"]),
            "var_95_1y_pct":         r["var_95_1y_pct"],
            "volatility_annual_pct": r["volatility_annual_pct"],
            "max_drawdown_pct":      r["max_drawdown_pct"],
            "beta_nifty500":         r["beta_nifty500"],
            "data_stale":            r["data_stale"],
        }
        for r in rows
    ]
    return {"external_user_id": external_user_id, "history": history}


# ── Color threshold helpers ───────────────────────────────────────────────────
# Industry-standard thresholds for Indian portfolios.
# Aligned with SEBI risk-o-meter framework (1Y 95% VaR basis).
#
# Green  (Conservative/Moderate):  VaR < 10%
# Amber  (Moderately High):        10% ≤ VaR < 25%
# Red    (High/Very High):         VaR ≥ 25%

THRESHOLDS = {
    "var_green_max":   10.0,   # VaR % 1Y 95%
    "var_amber_max":   25.0,
    "vol_green_max":   12.0,   # annualised vol %
    "vol_amber_max":   20.0,
    "mdd_green_max":   15.0,   # max drawdown %
    "mdd_amber_max":   35.0,
    "beta_green_max":   0.8,   # portfolio beta vs Nifty 500
    "beta_amber_max":   1.2,
}


def _var_color(var_pct: float) -> str:
    if var_pct < THRESHOLDS["var_green_max"]:
        return "green"
    if var_pct < THRESHOLDS["var_amber_max"]:
        return "amber"
    return "red"
