"""PRA engine orchestrator.

Nightly pipeline per user:
  1. Guard: check prices_eod_adjusted is ready for target_date
  2. Load look-through holdings via pra.v_portfolio_lookthrough
  3. Build portfolio return series (returns.py)
  4. Compute covariance matrix (covariance.py)
  5. Compute risk metrics: vol, VaR, MDD, beta, Sharpe, TE, HHI (var_engine.py)
  6. Compute component VaR breakdown (covariance.py)
  7. Run stress scenarios (stress.py)
  8. Write results to pra schema (writer.py)
"""
from __future__ import annotations

import asyncio
import logging
from datetime import date
from typing import Optional

from nidp.shared.storage.pg import get_pool

from .covariance import build_covariance, compute_component_var
from .fundamental import (
    compute_portfolio_fundamental_summary,
    enrich_component_var,
    fetch_fundamental_data,
)
from .returns import build_portfolio_returns
from .stress import compute_stress_scenarios
from .var_engine import compute_all, compute_hhi
from .writer import write_results

logger = logging.getLogger(__name__)


async def _guard_prices_ready(conn, target_date: date) -> bool:
    """Return True if prices_eod_adjusted has data for target_date."""
    count = await conn.fetchval(
        """
        SELECT COUNT(*)
        FROM nidp.prices_eod_adjusted
        WHERE as_of_date = $1
          AND tret_close IS NOT NULL
        """,
        target_date,
    )
    return (count or 0) > 100  # Nifty 500 universe should have 500 rows


async def _get_risk_free_rate(conn, target_date: date) -> float:
    """Fetch 91-day T-bill yield from rbi_yields as risk-free rate."""
    row = await conn.fetchrow(
        """
        SELECT yield_pct
        FROM nidp.rbi_yields
        WHERE tenor = '91D'
          AND as_of_date <= $1
        ORDER BY as_of_date DESC
        LIMIT 1
        """,
        target_date,
    )
    return float(row["yield_pct"]) if row else 6.5  # fallback to 6.5%


async def _get_active_users(conn, target_date: date, user_filter: Optional[str]) -> list[str]:
    """Return external_user_ids with a holdings snapshot on or before target_date."""
    if user_filter:
        return [user_filter]
    rows = await conn.fetch(
        """
        SELECT DISTINCT external_user_id
        FROM portfolio.user_holdings_snapshot
        WHERE snapshot_date <= $1
          AND market_value_inr > 0
        """,
        target_date,
    )
    return [r["external_user_id"] for r in rows]


async def _get_stress_scenarios(conn) -> list[dict]:
    rows = await conn.fetch(
        "SELECT * FROM pra.stress_scenarios WHERE enabled = TRUE ORDER BY scenario_id"
    )
    return [dict(r) for r in rows]


async def _compute_lookthrough_coverage(conn, external_user_id: str, target_date: date) -> float:
    """% of portfolio value that has look-through data (vs total MF/ETF weight)."""
    row = await conn.fetchrow(
        """
        WITH user_snapshot AS (
            SELECT asset_class, weight_pct
            FROM portfolio.user_holdings_snapshot
            WHERE external_user_id = $1
              AND snapshot_date = (
                  SELECT MAX(snapshot_date)
                  FROM portfolio.user_holdings_snapshot
                  WHERE external_user_id = $1 AND snapshot_date <= $2
              )
        ),
        mf_total AS (
            SELECT COALESCE(SUM(weight_pct), 0) AS mf_weight
            FROM user_snapshot
            WHERE asset_class IN ('MF', 'ETF')
        ),
        covered AS (
            SELECT COALESCE(SUM(effective_weight_pct), 0) AS covered_weight
            FROM pra.v_portfolio_lookthrough
            WHERE external_user_id = $1
              AND snapshot_date = (
                  SELECT MAX(snapshot_date)
                  FROM portfolio.user_holdings_snapshot
                  WHERE external_user_id = $1 AND snapshot_date <= $2
              )
        )
        SELECT
            CASE WHEN mf_total.mf_weight > 0
                 THEN LEAST(covered.covered_weight / mf_total.mf_weight * 100, 100)
                 ELSE 100.0
            END AS coverage_pct
        FROM mf_total, covered
        """,
        external_user_id, target_date,
    )
    return float(row["coverage_pct"]) if row else 0.0


async def _process_user(
    conn,
    external_user_id: str,
    target_date: date,
    scenarios: list[dict],
    risk_free_rate: float,
    dry_run: bool,
) -> bool:
    """Run the full PRA pipeline for one user. Returns True on success."""
    try:
        # Build portfolio return series
        pr = await build_portfolio_returns(conn, external_user_id, target_date)
        if pr is None:
            logger.info("pra_engine: skipping user=%s (no holdings / insufficient data)",
                        external_user_id)
            return False

        # Compute risk metrics
        metrics = compute_all(
            portfolio_returns=pr.portfolio_returns,
            benchmark_returns=pr.benchmark_returns,
            effective_weights=pr.effective_weights,
            portfolio_value_inr=pr.portfolio_value_inr,
            risk_free_rate_pct=risk_free_rate,
        )

        # Build covariance matrix and component VaR
        cov = build_covariance(pr.security_returns, pr.effective_weights)

        # Build security metadata for component VaR display
        security_meta = {}
        lt_rows = await conn.fetch(
            """
            SELECT security_isin, security_name, asset_class, look_through_path
            FROM pra.v_portfolio_lookthrough
            WHERE external_user_id = $1
              AND snapshot_date = (
                  SELECT MAX(snapshot_date)
                  FROM portfolio.user_holdings_snapshot
                  WHERE external_user_id = $1 AND snapshot_date <= $2
              )
            """,
            external_user_id, target_date,
        )
        for r in lt_rows:
            security_meta[r["security_isin"]] = {
                "name":             r["security_name"],
                "asset_class":      r["asset_class"],
                "look_through_path": r["look_through_path"] or [],
            }

        component_var_rows = compute_component_var(
            cov=cov,
            weights=pr.effective_weights,
            total_var_pct=metrics.var_95_1y_pct,
            portfolio_value_inr=pr.portfolio_value_inr,
            security_meta=security_meta,
        )

        # Enrich with fundamental risk analytics
        isins = [r["security_key"] for r in component_var_rows]
        fundamental_data = await fetch_fundamental_data(conn, isins, target_date)
        component_var_rows = enrich_component_var(component_var_rows, fundamental_data)
        fundamental_summary = compute_portfolio_fundamental_summary(component_var_rows)

        # HHI
        hhi = compute_hhi(pr.effective_weights)

        # Stress scenarios (debt params: placeholder — extend when bond sleeve added)
        stress_results = compute_stress_scenarios(
            scenarios=scenarios,
            beta=metrics.beta_nifty500,
            portfolio_value_inr=pr.portfolio_value_inr,
            w_debt=0.0,          # TODO: compute from user's DEBT/BOND holdings weight
            weighted_duration=0.0,
        )

        # Look-through coverage
        coverage_pct = await _compute_lookthrough_coverage(conn, external_user_id, target_date)

        # Persist
        result_id = await write_results(
            conn=conn,
            external_user_id=external_user_id,
            target_date=target_date,
            pr=pr,
            metrics=metrics,
            component_var_rows=component_var_rows,
            stress_results=stress_results,
            lookthrough_coverage_pct=coverage_pct,
            fundamental_summary=fundamental_summary,
            dry_run=dry_run,
        )

        logger.info(
            "pra_engine: user=%s date=%s result_id=%s var=%.2f%% vol=%.2f%% mdd=%.2f%% beta=%.3f",
            external_user_id, target_date, result_id,
            metrics.var_95_1y_pct, metrics.volatility_annual_pct,
            metrics.max_drawdown_pct, metrics.beta_nifty500,
        )
        return True

    except Exception:
        logger.exception("pra_engine: unhandled error for user=%s date=%s",
                         external_user_id, target_date)
        return False


async def run(
    target_date: date,
    user_filter: Optional[str] = None,
    dry_run: bool = False,
) -> None:
    """Main entry point: run the PRA engine for all active users on target_date."""
    pool = await get_pool()

    async with pool.acquire() as conn:
        # Guard: ensure prices are ready before proceeding
        if not await _guard_prices_ready(conn, target_date):
            logger.error(
                "pra_engine: prices_eod_adjusted not ready for %s — aborting. "
                "Ensure price_adjuster has completed before this job runs.",
                target_date,
            )
            return

        risk_free_rate = await _get_risk_free_rate(conn, target_date)
        users = await _get_active_users(conn, target_date, user_filter)
        scenarios = await _get_stress_scenarios(conn)

    if not users:
        logger.warning("pra_engine: no active users found for %s", target_date)
        return

    logger.info("pra_engine: processing %d users for %s (dry_run=%s)",
                len(users), target_date, dry_run)

    success = failed = 0
    # Process users with bounded concurrency (DB connection pool is the bottleneck)
    sem = asyncio.Semaphore(4)

    async def _bounded(user_id: str) -> None:
        nonlocal success, failed
        async with sem:
            async with pool.acquire() as conn:
                ok = await _process_user(
                    conn, user_id, target_date, scenarios, risk_free_rate, dry_run
                )
                if ok:
                    success += 1
                else:
                    failed += 1

    await asyncio.gather(*[_bounded(u) for u in users])

    logger.info(
        "pra_engine: completed date=%s users=%d success=%d failed=%d",
        target_date, len(users), success, failed,
    )
