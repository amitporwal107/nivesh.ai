"""Pure-numpy MF return and risk computations.

All functions take numpy arrays (oldest-first) of NAV values or daily returns,
and return scalars or dicts. No DB imports — unit-testable without infrastructure.

Return conventions:
  - All returns are in % (e.g. 15.2 means 15.2% annualised)
  - CAGR used for periods >= 252 trading days
  - Simple annualised % for periods < 252 days (avoids CAGR distortion on short windows)
  - Returns are net of NAV (which itself is post-expense-ratio)
"""
from __future__ import annotations

import math
from typing import Optional

import numpy as np

# India 10-year G-Sec proxy risk-free rate (6.5% annualised)
RISK_FREE_ANNUAL = 6.5
RISK_FREE_DAILY = RISK_FREE_ANNUAL / 252 / 100


# ── Returns ───────────────────────────────────────────────────────────

def cagr(nav_start: float, nav_end: float, years: float) -> Optional[float]:
    """Compound Annual Growth Rate between two NAV points."""
    if nav_start <= 0 or nav_end <= 0 or years <= 0:
        return None
    return float(((nav_end / nav_start) ** (1.0 / years) - 1.0) * 100)


def simple_return(nav_start: float, nav_end: float) -> Optional[float]:
    """Simple point-to-point return (no annualisation)."""
    if nav_start <= 0:
        return None
    return float((nav_end / nav_start - 1.0) * 100)


def annualised_return(nav_start: float, nav_end: float, trading_days: int) -> Optional[float]:
    """CAGR for long windows; simple annualised for short windows (< 252 bars)."""
    if nav_start <= 0 or nav_end <= 0 or trading_days <= 0:
        return None
    years = trading_days / 252.0
    if years >= 1.0:
        return cagr(nav_start, nav_end, years)
    # Annualise short-period return: (1 + r)^(252/days) - 1
    r = nav_end / nav_start - 1.0
    ann = ((1.0 + r) ** (252.0 / trading_days) - 1.0) * 100
    return float(ann)


def ytd_return(navs: np.ndarray, dates: np.ndarray, rank_date) -> Optional[float]:
    """Return from the last trading day of prior calendar year to rank_date."""
    if len(navs) < 2:
        return None
    year_start_year = rank_date.year
    # Find the last NAV of prior year
    prev_year_mask = np.array([d.year < year_start_year for d in dates])
    if not prev_year_mask.any():
        return None
    nav_prior_yr = float(navs[prev_year_mask][-1])  # last obs of prior year
    return simple_return(nav_prior_yr, float(navs[-1]))


def compute_returns(navs: np.ndarray, rank_date) -> dict:
    """Compute all point-to-point and CAGR returns for a NAV series.

    Args:
        navs: numpy array of NAV values, oldest-first, one per trading day
        rank_date: the date of the last nav value (datetime.date)

    Returns dict with keys: return_1m, return_3m, return_6m, return_1y,
    return_2y, return_3y, return_5y, return_ytd, return_since_launch_cagr
    All values in % or None if insufficient data.
    """
    n = len(navs)
    if n < 2:
        return {}

    end_nav = float(navs[-1])

    def _ret(bars: int, *, use_cagr: bool = False) -> Optional[float]:
        if n <= bars:
            return None
        start_nav = float(navs[-(bars + 1)])
        if use_cagr:
            return cagr(start_nav, end_nav, bars / 252.0)
        return annualised_return(start_nav, end_nav, bars)

    # Approximate trading day counts (252 per year)
    return {
        "return_1m":  _ret(21),
        "return_3m":  _ret(63),
        "return_6m":  _ret(126),
        "return_1y":  _ret(252),
        "return_2y":  _ret(504, use_cagr=True),
        "return_3y":  _ret(756, use_cagr=True),
        "return_5y":  _ret(1260, use_cagr=True),
        "return_since_launch_cagr": cagr(float(navs[0]), end_nav, (n - 1) / 252.0),
    }


# ── Risk Metrics ──────────────────────────────────────────────────────

def daily_log_returns(navs: np.ndarray) -> np.ndarray:
    """Log returns: ln(NAV_t / NAV_{t-1}). Oldest-first input."""
    return np.diff(np.log(navs.astype(float)))


def volatility_annualised(log_rets: np.ndarray) -> Optional[float]:
    """Annualised volatility (std dev of log returns × √252)."""
    if len(log_rets) < 20:
        return None
    return float(np.std(log_rets, ddof=1) * math.sqrt(252) * 100)


def sharpe(ann_return_pct: Optional[float], ann_vol_pct: Optional[float]) -> Optional[float]:
    """Sharpe ratio = (return - risk_free) / volatility."""
    if ann_return_pct is None or ann_vol_pct is None or ann_vol_pct == 0:
        return None
    return float((ann_return_pct - RISK_FREE_ANNUAL) / ann_vol_pct)


def sortino(log_rets: np.ndarray, ann_return_pct: Optional[float]) -> Optional[float]:
    """Sortino ratio = (return - risk_free) / downside_deviation.
    Downside deviation uses only negative daily returns."""
    if ann_return_pct is None or len(log_rets) < 20:
        return None
    neg_rets = log_rets[log_rets < 0]
    if len(neg_rets) == 0:
        return None
    downside_dev = float(np.std(neg_rets, ddof=1) * math.sqrt(252) * 100)
    if downside_dev == 0:
        return None
    return float((ann_return_pct - RISK_FREE_ANNUAL) / downside_dev)


def max_drawdown(navs: np.ndarray) -> Optional[float]:
    """Maximum peak-to-trough drawdown (%) over the series.
    Returns a negative number (e.g. -23.5 means 23.5% max drawdown)."""
    if len(navs) < 2:
        return None
    navs_f = navs.astype(float)
    cummax = np.maximum.accumulate(navs_f)
    drawdowns = (navs_f - cummax) / cummax * 100
    return float(np.min(drawdowns))


def alpha_beta(
    fund_log_rets: np.ndarray,
    bench_log_rets: np.ndarray,
) -> tuple[Optional[float], Optional[float], Optional[float]]:
    """Compute Jensen's Alpha, Beta, and R² vs benchmark using OLS regression.

    Returns (alpha_annual_pct, beta, r_squared).
    Alpha is annualised and expressed in % per year.
    Beta is dimensionless. R² is in [0, 1].
    """
    n = min(len(fund_log_rets), len(bench_log_rets))
    if n < 30:
        return None, None, None

    x = bench_log_rets[-n:]
    y = fund_log_rets[-n:]

    x_mean = np.mean(x)
    y_mean = np.mean(y)
    cov_xy = np.sum((x - x_mean) * (y - y_mean))
    var_x = np.sum((x - x_mean) ** 2)
    var_y = np.sum((y - y_mean) ** 2)

    if var_x == 0:
        return None, None, None

    beta = float(cov_xy / var_x)
    alpha_daily = float(y_mean - beta * x_mean)
    alpha_annual = float(alpha_daily * 252 * 100)
    r_squared = float((cov_xy ** 2) / (var_x * var_y)) if var_y > 0 else None

    return alpha_annual, beta, r_squared


def tracking_error(
    fund_log_rets: np.ndarray,
    bench_log_rets: np.ndarray,
) -> Optional[float]:
    """Annualised tracking error = std dev of (fund − bench) daily log-returns × √252.

    Result in % p.a. Requires ≥ 20 aligned observations.
    """
    n = min(len(fund_log_rets), len(bench_log_rets))
    if n < 20:
        return None
    excess = fund_log_rets[-n:] - bench_log_rets[-n:]
    return float(np.std(excess, ddof=1) * math.sqrt(252) * 100)


def information_ratio(
    ann_fund_return_pct: Optional[float],
    ann_bench_return_pct: Optional[float],
    te_pct: Optional[float],
) -> Optional[float]:
    """Information Ratio = (fund return − benchmark return) / tracking error."""
    if ann_fund_return_pct is None or ann_bench_return_pct is None:
        return None
    if te_pct is None or te_pct == 0:
        return None
    return float((ann_fund_return_pct - ann_bench_return_pct) / te_pct)


def rolling_returns_distribution(
    navs: np.ndarray,
    window_trading_days: int,
) -> Optional[dict]:
    """Summary statistics of rolling CAGR distribution.

    Returns dict with obs_count, positive_pct, and percentiles (min, p10,
    p25, p50, p75, p90, max). All returns annualised %. Returns None when
    fewer than 10 valid windows exist.
    """
    n = len(navs)
    if n <= window_trading_days + 10:
        return None

    years = window_trading_days / 252.0
    starts = navs[:n - window_trading_days].astype(float)
    ends = navs[window_trading_days:].astype(float)

    valid = (starts > 0) & (ends > 0)
    if valid.sum() < 10:
        return None

    ratio = ends[valid] / starts[valid]
    cagr_pct = (ratio ** (1.0 / years) - 1.0) * 100.0

    obs = int(len(cagr_pct))
    return {
        "obs_count":    obs,
        "positive_pct": round(float(np.sum(cagr_pct > 0) / obs * 100), 2),
        "ret_min":      round(float(np.min(cagr_pct)), 4),
        "ret_p10":      round(float(np.percentile(cagr_pct, 10)), 4),
        "ret_p25":      round(float(np.percentile(cagr_pct, 25)), 4),
        "ret_p50":      round(float(np.percentile(cagr_pct, 50)), 4),
        "ret_p75":      round(float(np.percentile(cagr_pct, 75)), 4),
        "ret_p90":      round(float(np.percentile(cagr_pct, 90)), 4),
        "ret_max":      round(float(np.max(cagr_pct)), 4),
    }


def compute_risk_metrics(
    navs: np.ndarray,
    bench_navs: Optional[np.ndarray],
    ann_return_pct: Optional[float],
    window_bars: int = 252,
    bench_ann_return_pct: Optional[float] = None,
) -> dict:
    """Compute all risk metrics over a trailing window.

    Args:
        navs:                 NAV series (oldest-first)
        bench_navs:           benchmark NAV series aligned to same dates (or None)
        ann_return_pct:       pre-computed annualised return for the same window
        window_bars:          number of bars to use (default 252 = 1 year)
        bench_ann_return_pct: benchmark annualised return for IR computation

    Returns dict with: volatility_1y, sharpe_1y, sortino_1y, max_drawdown_1y,
    alpha_1y, beta_1y, r_squared_1y, tracking_error_1y, information_ratio_1y
    (all None if insufficient data).
    """
    n = len(navs)
    if n < 21:
        return {k: None for k in [
            "volatility_1y", "sharpe_1y", "sortino_1y", "max_drawdown_1y",
            "alpha_1y", "beta_1y", "r_squared_1y",
            "tracking_error_1y", "information_ratio_1y",
        ]}

    window_navs = navs[-min(window_bars + 1, n):]
    log_rets = daily_log_returns(window_navs)

    vol = volatility_annualised(log_rets)
    sh = sharpe(ann_return_pct, vol)
    so = sortino(log_rets, ann_return_pct)
    mdd = max_drawdown(window_navs)

    alpha, beta, r_sq, te, ir = None, None, None, None, None
    if bench_navs is not None and len(bench_navs) > 1:
        bench_window = bench_navs[-min(window_bars + 1, len(bench_navs)):]
        bench_log_rets = daily_log_returns(bench_window)
        n_align = min(len(log_rets), len(bench_log_rets))
        if n_align >= 30:
            alpha, beta, r_sq = alpha_beta(log_rets[-n_align:], bench_log_rets[-n_align:])
            te = tracking_error(log_rets[-n_align:], bench_log_rets[-n_align:])
            ir = information_ratio(ann_return_pct, bench_ann_return_pct, te)

    return {
        "volatility_1y":        vol,
        "sharpe_1y":            sh,
        "sortino_1y":           so,
        "max_drawdown_1y":      mdd,
        "alpha_1y":             alpha,
        "beta_1y":              beta,
        "r_squared_1y":         r_sq,
        "tracking_error_1y":    te,
        "information_ratio_1y": ir,
    }
