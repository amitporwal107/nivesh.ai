"""Covariance matrix engine.

Computes the look-through covariance matrix Σ from the daily return series
of all underlying securities. Used for:
  - Portfolio variance: σ²_p = wᵀ Σ w
  - Marginal VaR:       MVaR_i = VaR × (Σw)_i / (wᵀΣw)
  - Component VaR:      CVaR_i = w_i × MVaR_i  (sums to total VaR)
  - HHI on effective weights

All inputs are pandas DataFrames / Series with security_isin as column names.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


@dataclass
class CovarianceResult:
    sigma: np.ndarray          # (n × n) covariance matrix, annualised
    symbols: list[str]         # ordered list of security_isins (column order)
    portfolio_variance: float  # wᵀ Σ w (annualised)
    portfolio_vol: float       # √(portfolio_variance)
    sigma_w: np.ndarray        # Σ w — used for marginal VaR


def build_covariance(
    security_returns: pd.DataFrame,
    weights: pd.Series,
    annualise_factor: int = 252,
) -> CovarianceResult:
    """Compute annualised covariance matrix from daily log-return DataFrame.

    Args:
        security_returns: DataFrame — rows=dates, cols=security_isin, values=log-return
        weights: Series — index=security_isin, values=weight (must sum to 1)
        annualise_factor: trading days per year (default 252)

    Returns:
        CovarianceResult with Σ, Σw, portfolio variance and vol.
    """
    # Align weights to columns present in returns
    common = [s for s in weights.index if s in security_returns.columns]
    if len(common) < 2:
        logger.warning("covariance: only %d securities available; skipping matrix", len(common))
        w = weights.reindex(common).fillna(0).values
        sigma = np.array([[security_returns[common[0]].var() * annualise_factor]]) if common else np.array([[0.0]])
        pv = float(w @ sigma @ w) if len(w) == 1 else 0.0
        return CovarianceResult(
            sigma=sigma,
            symbols=common,
            portfolio_variance=pv,
            portfolio_vol=float(np.sqrt(max(pv, 0))),
            sigma_w=sigma @ w,
        )

    ret_matrix = security_returns[common].fillna(0).values  # shape (T, n)
    w = weights.reindex(common).fillna(0).values

    # Annualised covariance matrix: Cov(daily) × 252
    sigma = np.cov(ret_matrix, rowvar=False) * annualise_factor   # (n, n)

    # Portfolio variance and vol
    sigma_w = sigma @ w                                            # (n,)
    port_var = float(w @ sigma_w)
    port_vol = float(np.sqrt(max(port_var, 0.0)))

    logger.debug("covariance: %d×%d matrix, σ_p=%.4f", len(common), len(common), port_vol)

    return CovarianceResult(
        sigma=sigma,
        symbols=common,
        portfolio_variance=port_var,
        portfolio_vol=port_vol,
        sigma_w=sigma_w,
    )


def compute_component_var(
    cov: CovarianceResult,
    weights: pd.Series,
    total_var_pct: float,
    portfolio_value_inr: float,
    security_meta: dict[str, dict],
) -> list[dict]:
    """Compute per-holding component VaR breakdown.

    Args:
        cov:                CovarianceResult from build_covariance()
        weights:            effective weights Series (index=isin)
        total_var_pct:      total portfolio VaR % (for normalisation)
        portfolio_value_inr: portfolio value for INR figures
        security_meta:      {isin: {name, asset_class, look_through_path}} from returns

    Returns:
        List of dicts ready to insert into pra.component_var.
    """
    if cov.portfolio_variance <= 0 or total_var_pct <= 0:
        return []

    w = weights.reindex(cov.symbols).fillna(0).values
    sigma_w = cov.sigma_w                        # Σw

    # Marginal VaR: MVaR_i = VaR × (Σw)_i / (wᵀΣw)
    mvars = total_var_pct * sigma_w / cov.portfolio_variance  # per unit weight

    rows = []
    for i, isin in enumerate(cov.symbols):
        wi = float(w[i])
        mvar_i = float(mvars[i])
        cvar_i = wi * mvar_i                      # component VaR (% of portfolio)
        share_i = (cvar_i / total_var_pct * 100) if total_var_pct > 0 else 0.0

        meta = security_meta.get(isin, {})
        rows.append({
            "security_key":         isin,
            "security_name":        meta.get("name"),
            "asset_class":          meta.get("asset_class"),
            "effective_weight_pct": round(wi * 100, 6),
            "marginal_var_pct":     round(mvar_i, 6),
            "component_var_pct":    round(cvar_i, 6),
            "share_of_sigma_pct":   round(share_i, 4),
            "look_through_path":    meta.get("look_through_path", []),
        })

    # Sort by share_of_sigma descending
    rows.sort(key=lambda r: r["share_of_sigma_pct"], reverse=True)
    return rows
