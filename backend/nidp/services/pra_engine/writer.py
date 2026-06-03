"""Persist PRA results to pra schema tables.

All writes are upsert-safe (ON CONFLICT DO UPDATE) so re-running for the
same (user, date) replaces prior results cleanly.
"""
from __future__ import annotations

import hashlib
import json
import logging
from datetime import date, datetime, timezone

from .covariance import CovarianceResult
from .returns import PortfolioReturns
from .stress import ScenarioResult
from .var_engine import RiskMetrics

logger = logging.getLogger(__name__)

FORMULA_VERSION = "pra-v1.0"


def _snapshot_hash(user_id: str, target_date: date, weights: dict) -> str:
    """Stable SHA-256 of the input holdings used this run."""
    payload = json.dumps(
        {"user": user_id, "date": str(target_date), "weights": sorted(weights.items())},
        sort_keys=True,
    ).encode()
    return hashlib.sha256(payload).hexdigest()[:16]


async def write_results(
    conn,
    external_user_id: str,
    target_date: date,
    pr: PortfolioReturns,
    metrics: RiskMetrics,
    component_var_rows: list[dict],
    stress_results: list[ScenarioResult],
    lookthrough_coverage_pct: float,
    dry_run: bool = False,
) -> str:
    """Write a complete PRA result set for one user. Returns result_id."""
    snap_hash = _snapshot_hash(
        external_user_id, target_date,
        pr.effective_weights.to_dict(),
    )
    data_stale = pr.look_through_stale or pr.price_stale

    if dry_run:
        logger.info("writer[dry-run]: would write %s @ %s vol=%.2f%% var=%.2f%%",
                    external_user_id, target_date,
                    metrics.volatility_annual_pct, metrics.var_95_1y_pct)
        return "dry-run"

    # ── Main result row ─────────────────────────────────────────────────
    result_id = await conn.fetchval(
        """
        INSERT INTO pra.portfolio_risk_results (
            external_user_id,
            computed_date,
            portfolio_value_inr,
            holding_count,
            lookthrough_coverage_pct,
            volatility_annual_pct,
            benchmark_vol_annual_pct,
            var_95_1y_pct,
            var_95_1y_inr,
            max_drawdown_pct,
            beta_nifty500,
            sharpe_1y,
            tracking_error_pct,
            look_through_stale,
            price_stale,
            data_stale,
            missing_symbols,
            holdings_snapshot_hash,
            formula_version,
            lookback_days,
            risk_free_rate_pct,
            computed_at
        ) VALUES (
            $1,$2,$3,$4,$5,$6,$7,$8,$9,$10,
            $11,$12,$13,$14,$15,$16,$17,$18,$19,$20,$21,$22
        )
        ON CONFLICT (external_user_id, computed_date) DO UPDATE SET
            portfolio_value_inr         = EXCLUDED.portfolio_value_inr,
            holding_count               = EXCLUDED.holding_count,
            lookthrough_coverage_pct    = EXCLUDED.lookthrough_coverage_pct,
            volatility_annual_pct       = EXCLUDED.volatility_annual_pct,
            benchmark_vol_annual_pct    = EXCLUDED.benchmark_vol_annual_pct,
            var_95_1y_pct               = EXCLUDED.var_95_1y_pct,
            var_95_1y_inr               = EXCLUDED.var_95_1y_inr,
            max_drawdown_pct            = EXCLUDED.max_drawdown_pct,
            beta_nifty500               = EXCLUDED.beta_nifty500,
            sharpe_1y                   = EXCLUDED.sharpe_1y,
            tracking_error_pct          = EXCLUDED.tracking_error_pct,
            look_through_stale          = EXCLUDED.look_through_stale,
            price_stale                 = EXCLUDED.price_stale,
            data_stale                  = EXCLUDED.data_stale,
            missing_symbols             = EXCLUDED.missing_symbols,
            holdings_snapshot_hash      = EXCLUDED.holdings_snapshot_hash,
            formula_version             = EXCLUDED.formula_version,
            lookback_days               = EXCLUDED.lookback_days,
            risk_free_rate_pct          = EXCLUDED.risk_free_rate_pct,
            computed_at                 = EXCLUDED.computed_at
        RETURNING result_id
        """,
        external_user_id,
        target_date,
        pr.portfolio_value_inr,
        len(pr.effective_weights),
        lookthrough_coverage_pct,
        metrics.volatility_annual_pct,
        metrics.benchmark_vol_annual_pct,
        metrics.var_95_1y_pct,
        metrics.var_95_1y_inr,
        metrics.max_drawdown_pct,
        metrics.beta_nifty500,
        metrics.sharpe_1y,
        metrics.tracking_error_pct,
        pr.look_through_stale,
        pr.price_stale,
        data_stale,
        pr.missing_symbols,
        snap_hash,
        FORMULA_VERSION,
        pr.lookback_days_actual,
        metrics.risk_free_rate_pct,
        datetime.now(tz=timezone.utc),
    )

    # ── Component VaR rows (delete + re-insert for clean upsert) ────────
    if component_var_rows:
        await conn.execute(
            "DELETE FROM pra.component_var WHERE result_id = $1",
            result_id,
        )
        await conn.executemany(
            """
            INSERT INTO pra.component_var (
                result_id, security_key, security_name, asset_class,
                effective_weight_pct, marginal_var_pct, component_var_pct,
                share_of_sigma_pct, look_through_path
            ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9)
            """,
            [
                (
                    result_id,
                    r["security_key"],
                    r.get("security_name"),
                    r.get("asset_class"),
                    r["effective_weight_pct"],
                    r["marginal_var_pct"],
                    r["component_var_pct"],
                    r["share_of_sigma_pct"],
                    json.dumps(r.get("look_through_path", [])),
                )
                for r in component_var_rows
            ],
        )

    # ── Stress results ───────────────────────────────────────────────────
    if stress_results:
        await conn.execute(
            "DELETE FROM pra.stress_results WHERE result_id = $1",
            result_id,
        )
        await conn.executemany(
            """
            INSERT INTO pra.stress_results (
                result_id, scenario_id,
                portfolio_impact_pct, portfolio_impact_inr,
                benchmark_impact_pct,
                equity_contribution_pct, rate_contribution_pct,
                computed_at
            ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8)
            """,
            [
                (
                    result_id,
                    sr.scenario_id,
                    sr.portfolio_impact_pct,
                    sr.portfolio_impact_inr,
                    sr.benchmark_impact_pct,
                    sr.equity_contribution_pct,
                    sr.rate_contribution_pct,
                    datetime.now(tz=timezone.utc),
                )
                for sr in stress_results
            ],
        )

    # ── Audit log (key metrics) ──────────────────────────────────────────
    audit_rows = [
        ("volatility_annual_pct",   metrics.volatility_annual_pct),
        ("var_95_1y_pct",           metrics.var_95_1y_pct),
        ("var_parametric_pct",      metrics.var_parametric_pct),
        ("var_historical_pct",      metrics.var_historical_pct),
        ("max_drawdown_pct",        metrics.max_drawdown_pct),
        ("beta_nifty500",           metrics.beta_nifty500),
        ("sharpe_1y",               metrics.sharpe_1y),
    ]
    await conn.executemany(
        """
        INSERT INTO pra.audit_log (
            result_id, metric_name, computed_value,
            input_snapshot_hash, formula_version, computation_timestamp
        ) VALUES ($1,$2,$3,$4,$5,$6)
        """,
        [
            (result_id, name, value, snap_hash, FORMULA_VERSION,
             datetime.now(tz=timezone.utc))
            for name, value in audit_rows
        ],
    )

    logger.info(
        "writer: saved result_id=%s user=%s date=%s var=%.2f%% vol=%.2f%%",
        result_id, external_user_id, target_date,
        metrics.var_95_1y_pct, metrics.volatility_annual_pct,
    )
    return str(result_id)
