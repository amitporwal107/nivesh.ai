"""Regression tests for mf_analytics_engine.calculator risk-ratio stability.

Locks in the near-zero-volatility floor (2026-06-24): a near-flat (stale/
interpolated) NAV series drives annualised volatility toward zero, which made
Sharpe/Sortino explode — observed up to the -99999.9999 NUMERIC clamp in
analytics.fund_category_rank. The floor returns None ("insufficient signal")
below _MIN_ANN_VOL_PCT while preserving legitimate low-vol debt/liquid funds.
"""
from __future__ import annotations

import numpy as np

from nidp.services.mf_analytics_engine.calculator import (
    _MIN_ANN_VOL_PCT,
    sharpe,
    sortino,
)


def test_sharpe_floors_degenerate_low_volatility():
    # Real staging garbage row: return 3.82%, vol 0.0472% -> sharpe was -56.8.
    assert sharpe(3.82, 0.0472) is None
    assert sharpe(8.0, 0.20) is None


def test_sharpe_preserves_legit_low_vol_debt_fund():
    # 0.3-0.5% vol band is legitimate overnight/liquid funds (96% sane sharpe).
    assert sharpe(7.0, 0.40) == 1.25
    # Equity-scale vol unaffected.
    assert round(sharpe(18.0, 12.0), 4) == 0.9583


def test_sharpe_boundary_is_inclusive_at_floor():
    assert sharpe(7.0, _MIN_ANN_VOL_PCT) is not None
    assert sharpe(7.0, _MIN_ANN_VOL_PCT - 0.0001) is None


def test_sharpe_none_inputs():
    assert sharpe(None, 5.0) is None
    assert sharpe(7.0, None) is None


def test_sortino_floors_near_zero_downside_deviation():
    # Tiny, near-identical negative returns -> downside dev below the floor -> None.
    flat_neg = np.array([-1e-6, -1.01e-6, -0.99e-6] + [1e-4] * 30)
    assert sortino(flat_neg, 7.0) is None


def test_sortino_computes_with_real_downside():
    rng = np.linspace(-0.02, 0.02, 60)  # mix of up/down days, real dispersion
    val = sortino(rng, 12.0)
    assert val is not None and np.isfinite(val)
