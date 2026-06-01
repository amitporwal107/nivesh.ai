"""Risk metric computation.

All metrics operate on log-return series (pandas Series / DataFrames).

Formulas per PRD Appendix A:
  Volatility:       σ_annual = std(r) × √252
  Parametric VaR:   z × σ_annual × V  (z=1.645 @95%)
  Historical VaR:   empirical 5th-percentile of return distribution × √h
  Max Drawdown:     max_t((Peak − Trough_t) / Peak)
  Beta:             Cov(r_p, r_m) / Var(r_m)
  Sharpe:           (mean(r_p)×252 − r_f) / σ_annual
  Tracking Error:   std(r_p − r_m) × √252
  HHI:              Σ (w_i × 100)²
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

Z_95 = 1.6449   # z-score for 95th percentile
TRADING_DAYS = 252


@dataclass
class RiskMetrics:
    """All computed risk metrics for one portfolio."""
    volatility_annual_pct:      float = 0.0
    benchmark_vol_annual_pct:   float = 0.0
    var_95_1y_pct:              float = 0.0    # max(parametric, historical)
    var_95_1y_inr:              float = 0.0
    var_parametric_pct:         float = 0.0
    var_historical_pct:         float = 0.0
    max_drawdown_pct:           float = 0.0
    beta_nifty500:              float = 0.0
    sharpe_1y:                  float = 0.0
    tracking_error_pct:         float = 0.0
    risk_free_rate_pct:         float = 6.5    # fallback if DB lookup fails


def compute_volatility(returns: pd.Series) -> float:
    """Annualised volatility from daily log-returns."""
    if len(returns) < 5:
        return 0.0
    return float(returns.std(ddof=1) * np.sqrt(TRADING_DAYS) * 100)


def compute_parametric_var(vol_pct: float, portfolio_value: float = 1.0) -> float:
    """Parametric VaR at 95% confidence, 1-year horizon.

    VaR% = z × σ_annual    (expressed as a positive %)
    """
    return Z_95 * vol_pct


def compute_historical_var(
    portfolio_returns: pd.Series,
    confidence: float = 0.95,
    horizon_days: int = TRADING_DAYS,
) -> float:
    """Historical simulation VaR at `confidence` level, scaled to `horizon_days`.

    Uses the empirical α-percentile of the daily return distribution,
    scaled to the target horizon by √T (suitable for i.i.d. returns).
    """
    if len(portfolio_returns) < 20:
        return 0.0
    alpha = 1.0 - confidence
    daily_var = float(portfolio_returns.quantile(alpha))       # negative number
    # Scale to horizon and flip sign (VaR is reported as a positive %)
    var_pct = -daily_var * np.sqrt(horizon_days) * 100
    return max(var_pct, 0.0)


def compute_max_drawdown(portfolio_returns: pd.Series) -> float:
    """Maximum peak-to-trough drawdown over the return series.

    Returns a positive percentage (e.g. 24.3 for -24.3% drawdown).
    """
    if len(portfolio_returns) < 2:
        return 0.0
    cum_returns = (1 + portfolio_returns).cumprod()
    rolling_peak = cum_returns.cummax()
    drawdown = (cum_returns - rolling_peak) / rolling_peak
    return float(-drawdown.min() * 100)


def compute_beta(portfolio_returns: pd.Series, benchmark_returns: pd.Series) -> float:
    """Portfolio beta vs. benchmark: Cov(r_p, r_m) / Var(r_m)."""
    aligned = pd.concat([portfolio_returns, benchmark_returns], axis=1).dropna()
    if len(aligned) < 10:
        return 0.0
    rp = aligned.iloc[:, 0].values
    rm = aligned.iloc[:, 1].values
    var_m = float(np.var(rm, ddof=1))
    if var_m == 0:
        return 0.0
    cov_pm = float(np.cov(rp, rm, ddof=1)[0, 1])
    return round(cov_pm / var_m, 4)


def compute_sharpe(
    portfolio_returns: pd.Series,
    vol_pct: float,
    risk_free_rate_pct: float = 6.5,
) -> float:
    """Sharpe ratio: (r_p_annual − r_f) / σ_annual."""
    if vol_pct <= 0 or len(portfolio_returns) < 10:
        return 0.0
    annualised_return_pct = float(portfolio_returns.mean() * TRADING_DAYS * 100)
    return round((annualised_return_pct - risk_free_rate_pct) / vol_pct, 4)


def compute_tracking_error(
    portfolio_returns: pd.Series,
    benchmark_returns: pd.Series,
) -> float:
    """Tracking error: σ(r_p − r_benchmark) × √252, in %."""
    aligned = pd.concat([portfolio_returns, benchmark_returns], axis=1).dropna()
    if len(aligned) < 10:
        return 0.0
    active = aligned.iloc[:, 0] - aligned.iloc[:, 1]
    return float(active.std(ddof=1) * np.sqrt(TRADING_DAYS) * 100)


def compute_hhi(effective_weights: pd.Series) -> int:
    """Herfindahl-Hirschman Index on look-through effective weights.

    HHI = Σ (w_i × 100)²  — ranges 100 (equally distributed, 100 securities)
    to 10,000 (fully concentrated in 1 security).
    """
    w = effective_weights.values
    w = w / w.sum()  # ensure sums to 1
    return int(round(float(np.sum((w * 100) ** 2))))


def compute_all(
    portfolio_returns: pd.Series,
    benchmark_returns: pd.Series,
    effective_weights: pd.Series,
    portfolio_value_inr: float,
    risk_free_rate_pct: float = 6.5,
) -> RiskMetrics:
    """Compute the full risk metrics set for a portfolio."""
    vol = compute_volatility(portfolio_returns)
    bench_vol = compute_volatility(benchmark_returns)
    var_p = compute_parametric_var(vol)
    var_h = compute_historical_var(portfolio_returns)
    var = max(var_p, var_h)  # conservative: take larger estimate

    mdd = compute_max_drawdown(portfolio_returns)
    beta = compute_beta(portfolio_returns, benchmark_returns)
    sharpe = compute_sharpe(portfolio_returns, vol, risk_free_rate_pct)
    te = compute_tracking_error(portfolio_returns, benchmark_returns)

    logger.debug(
        "var_engine: vol=%.2f%% var_p=%.2f%% var_h=%.2f%% mdd=%.2f%% beta=%.3f sharpe=%.3f",
        vol, var_p, var_h, mdd, beta, sharpe,
    )

    return RiskMetrics(
        volatility_annual_pct=round(vol, 4),
        benchmark_vol_annual_pct=round(bench_vol, 4),
        var_95_1y_pct=round(var, 4),
        var_95_1y_inr=round(var / 100 * portfolio_value_inr, 2),
        var_parametric_pct=round(var_p, 4),
        var_historical_pct=round(var_h, 4),
        max_drawdown_pct=round(mdd, 4),
        beta_nifty500=beta,
        sharpe_1y=sharpe,
        tracking_error_pct=round(te, 4),
        risk_free_rate_pct=round(risk_free_rate_pct, 4),
    )
