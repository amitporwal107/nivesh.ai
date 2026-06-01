"""Stress scenario engine.

Applies named historical/hypothetical shocks to a portfolio and estimates impact.

Formula (PRD §9.11):
  Δportfolio ≈ β × equityShock + duration × Δy × w_debt

Where:
  β             = portfolio beta vs Nifty 500 (equity component)
  equityShock   = scenario equity drawdown (negative fraction, e.g. -0.38)
  duration      = weighted-average modified duration of the debt sleeve
  Δy            = rate shock in decimal (bps / 10000)
  w_debt        = weight of debt/bond holdings in the portfolio

This is an indicative single-factor estimate — it captures first-order effects.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class ScenarioResult:
    scenario_id:            str
    scenario_name:          str
    portfolio_impact_pct:   float    # negative = loss
    portfolio_impact_inr:   float
    benchmark_impact_pct:   float    # pure equity shock × 1.0
    equity_contribution_pct: float
    rate_contribution_pct:  float
    recovery_estimate:      str


def compute_stress_scenarios(
    scenarios: list[dict],
    beta: float,
    portfolio_value_inr: float,
    w_debt: float = 0.0,
    weighted_duration: float = 0.0,
) -> list[ScenarioResult]:
    """Compute portfolio impact for each scenario.

    Args:
        scenarios:          Rows from pra.stress_scenarios (enabled=True)
        beta:               Portfolio beta vs Nifty 500
        portfolio_value_inr: Total portfolio value in INR
        w_debt:             Fraction of portfolio in debt/bonds (0–1)
        weighted_duration:  Weighted-average modified duration of debt sleeve (years)

    Returns:
        List of ScenarioResult, one per scenario.
    """
    results = []
    for s in scenarios:
        equity_shock_pct = float(s["equity_shock_pct"])   # e.g. -50.0
        rate_shock_bps   = float(s["rate_shock_bps"])     # e.g. -150.0

        equity_shock_frac = equity_shock_pct / 100.0
        delta_y           = rate_shock_bps / 10000.0

        # Equity leg: β × equityShock
        equity_impact = beta * equity_shock_frac

        # Rate leg: duration × Δy × w_debt
        # Negative rate shock (yield falls) = positive bond price impact
        rate_impact = -weighted_duration * delta_y * w_debt

        total_impact_frac = equity_impact + rate_impact
        total_impact_pct  = round(total_impact_frac * 100, 4)
        total_impact_inr  = round(total_impact_frac * portfolio_value_inr, 2)

        # Benchmark impact = pure equity market shock (no debt adjustment)
        benchmark_impact_pct = round(equity_shock_pct, 4)

        results.append(ScenarioResult(
            scenario_id=s["scenario_id"],
            scenario_name=s["scenario_name"],
            portfolio_impact_pct=total_impact_pct,
            portfolio_impact_inr=total_impact_inr,
            benchmark_impact_pct=benchmark_impact_pct,
            equity_contribution_pct=round(equity_impact * 100, 4),
            rate_contribution_pct=round(rate_impact * 100, 4),
            recovery_estimate=s.get("recovery_estimate") or "",
        ))

        logger.debug(
            "stress[%s]: equity=%.2f%% rate=%.2f%% total=%.2f%%",
            s["scenario_id"],
            equity_impact * 100,
            rate_impact * 100,
            total_impact_pct,
        )

    return results
