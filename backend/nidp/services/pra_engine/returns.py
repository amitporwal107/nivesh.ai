"""Portfolio return series builder.

Fetches per-security daily total-return prices/NAVs from NIDP TimescaleDB and
assembles a portfolio-weighted daily return vector for a given user.

Return series:
  - Equities: from nidp.prices_eod_adjusted.tret_close (split+bonus+dividend adjusted)
  - MFs/ETFs: from nidp.mf_nav_daily.nav (AMFI daily NAV)
  - Calendar: intersection of trading days across all holdings (handles NSE/AMFI gaps)
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

LOOKBACK_DAYS = 252  # 1 trading year


@dataclass
class PortfolioReturns:
    """Output of build_portfolio_returns()."""
    portfolio_returns: pd.Series          # daily log-returns indexed by date
    benchmark_returns: pd.Series          # Nifty 500 daily log-returns
    security_returns: pd.DataFrame        # columns = security_isin, rows = dates
    effective_weights: pd.Series          # index = security_isin, values = weight (sum ≈ 1)
    portfolio_value_inr: float
    lookback_days_actual: int
    missing_symbols: list[str]
    look_through_stale: bool
    price_stale: bool


async def build_portfolio_returns(
    conn,
    external_user_id: str,
    target_date: date,
    lookback_days: int = LOOKBACK_DAYS,
) -> Optional[PortfolioReturns]:
    """Build daily portfolio return series for one user.

    Returns None if the user has no holdings or insufficient price history.
    """
    from_date = target_date - timedelta(days=lookback_days * 2)  # extra buffer for gaps

    # 1. Load look-through effective weights from the view
    lt_rows = await conn.fetch(
        """
        SELECT security_isin, security_name, asset_class,
               effective_weight_pct, look_through_path, holdings_as_of_month
        FROM pra.v_portfolio_lookthrough
        WHERE external_user_id = $1
          AND snapshot_date     = (
              SELECT MAX(snapshot_date)
              FROM portfolio.user_holdings_snapshot
              WHERE external_user_id = $1
                AND snapshot_date   <= $2
          )
        ORDER BY effective_weight_pct DESC
        """,
        external_user_id, target_date,
    )

    if not lt_rows:
        logger.warning("pra_engine[returns]: no holdings for user=%s at %s", external_user_id, target_date)
        return None

    # Check look-through staleness (>45 days since last holdings disclosure)
    holdings_months = [r["holdings_as_of_month"] for r in lt_rows if r["holdings_as_of_month"]]
    look_through_stale = False
    if holdings_months:
        oldest = min(holdings_months)
        days_stale = (target_date - oldest).days
        if days_stale > 45:
            look_through_stale = True
            logger.warning("pra_engine[returns]: look-through stale by %d days for user=%s",
                           days_stale, external_user_id)

    # Build weight series (normalise to sum=1 in case of rounding)
    weights = pd.Series(
        {r["security_isin"]: float(r["effective_weight_pct"] or 0) / 100.0 for r in lt_rows}
    )
    weights = weights[weights > 0]
    if weights.sum() == 0:
        logger.warning("pra_engine[returns]: zero total weight for user=%s", external_user_id)
        return None
    weights = weights / weights.sum()

    isins = list(weights.index)

    # 2. Resolve ISINs → equity symbols and MF scheme codes
    symbol_map = await conn.fetch(
        """
        SELECT isin, symbol
        FROM nidp.sector_master
        WHERE isin = ANY($1::text[])
        """,
        isins,
    )
    isin_to_symbol = {r["isin"]: r["symbol"] for r in symbol_map}

    scheme_map = await conn.fetch(
        """
        SELECT isin_growth AS isin, scheme_code
        FROM nidp.mf_scheme_master
        WHERE isin_growth = ANY($1::text[])
        UNION ALL
        SELECT isin_idcw AS isin, scheme_code
        FROM nidp.mf_scheme_master
        WHERE isin_idcw = ANY($1::text[])
        """,
        isins,
    )
    isin_to_scheme = {r["isin"]: r["scheme_code"] for r in scheme_map}

    # 3. Fetch equity total-return prices
    equity_isins = [i for i in isins if i in isin_to_symbol]
    equity_symbols = [isin_to_symbol[i] for i in equity_isins]

    equity_prices: pd.DataFrame = pd.DataFrame()
    if equity_symbols:
        price_rows = await conn.fetch(
            """
            SELECT a.as_of_date, sm.isin, a.tret_close
            FROM nidp.prices_eod_adjusted a
            JOIN nidp.sector_master sm ON sm.symbol = a.symbol
            WHERE a.symbol = ANY($1::text[])
              AND a.as_of_date BETWEEN $2 AND $3
              AND a.tret_close IS NOT NULL
              AND a.tret_close > 0
            ORDER BY a.as_of_date
            """,
            equity_symbols, from_date, target_date,
        )
        if price_rows:
            df = pd.DataFrame(price_rows, columns=["date", "isin", "price"])
            equity_prices = df.pivot(index="date", columns="isin", values="price")

    # 4. Fetch MF NAV series
    mf_isins = [i for i in isins if i in isin_to_scheme]
    scheme_codes = [isin_to_scheme[i] for i in mf_isins]
    isin_to_scheme_rev = {isin_to_scheme[i]: i for i in mf_isins}

    mf_navs: pd.DataFrame = pd.DataFrame()
    if scheme_codes:
        nav_rows = await conn.fetch(
            """
            SELECT nav_date, scheme_code, nav
            FROM nidp.mf_nav_daily
            WHERE scheme_code = ANY($1::text[])
              AND nav_date BETWEEN $2 AND $3
              AND nav IS NOT NULL
              AND nav > 0
            ORDER BY nav_date
            """,
            scheme_codes, from_date, target_date,
        )
        if nav_rows:
            df = pd.DataFrame(nav_rows, columns=["date", "scheme_code", "nav"])
            df["isin"] = df["scheme_code"].map(isin_to_scheme_rev)
            mf_navs = df.pivot(index="date", columns="isin", values="nav")

    # 5. Fetch Nifty 500 benchmark prices
    bench_rows = await conn.fetch(
        """
        SELECT as_of_date, close_price
        FROM nidp.index_eod
        WHERE index_name = 'NIFTY 500'
          AND as_of_date BETWEEN $1 AND $2
          AND close_price > 0
        ORDER BY as_of_date
        """,
        from_date, target_date,
    )
    benchmark_series: pd.Series = pd.Series(dtype=float)
    if bench_rows:
        bench_df = pd.DataFrame(bench_rows, columns=["date", "price"]).set_index("date")["price"]
        benchmark_series = np.log(bench_df / bench_df.shift(1)).dropna()

    # 6. Combine equity + MF price frames and compute log-returns
    prices = pd.concat(
        [p for p in [equity_prices, mf_navs] if not p.empty],
        axis=1,
    ).sort_index()

    if prices.empty:
        logger.warning("pra_engine[returns]: no price data for user=%s", external_user_id)
        return None

    # Forward-fill short gaps (holidays, MF NAV lag) up to 5 days
    prices = prices.ffill(limit=5)

    # Compute log-returns and drop first row (NaN from shift)
    log_returns = np.log(prices / prices.shift(1)).dropna(how="all")

    # Keep only the last `lookback_days` trading days
    log_returns = log_returns.tail(lookback_days)

    if len(log_returns) < 60:
        logger.warning("pra_engine[returns]: only %d return days for user=%s (need 60+)",
                       len(log_returns), external_user_id)
        return None

    # Track which symbols had no price data
    missing_symbols = [i for i in isins if i not in log_returns.columns]
    if missing_symbols:
        logger.warning("pra_engine[returns]: %d symbols missing price data: %s",
                       len(missing_symbols), missing_symbols[:5])

    # Drop missing from weights and re-normalise
    available = [i for i in weights.index if i in log_returns.columns]
    weights = weights[available]
    if weights.sum() == 0:
        return None
    weights = weights / weights.sum()

    # 7. Build portfolio return series: r_p(t) = Σ w_i × r_i(t)
    returns_subset = log_returns[available].fillna(0)
    portfolio_ret = returns_subset.dot(weights)

    # Check for price staleness (last price older than 3 trading days)
    last_price_date = prices.index.max()
    price_stale = (target_date - last_price_date).days > 5

    # Portfolio value: use user's latest snapshot total
    pf_value_row = await conn.fetchrow(
        """
        SELECT SUM(market_value_inr) AS total_value
        FROM portfolio.user_holdings_snapshot
        WHERE external_user_id = $1
          AND snapshot_date = (
              SELECT MAX(snapshot_date)
              FROM portfolio.user_holdings_snapshot
              WHERE external_user_id = $1 AND snapshot_date <= $2
          )
        """,
        external_user_id, target_date,
    )
    portfolio_value = float(pf_value_row["total_value"] or 0)

    # Align benchmark to same dates as portfolio
    aligned_bench = benchmark_series.reindex(portfolio_ret.index).fillna(0)

    return PortfolioReturns(
        portfolio_returns=portfolio_ret,
        benchmark_returns=aligned_bench,
        security_returns=returns_subset,
        effective_weights=weights,
        portfolio_value_inr=portfolio_value,
        lookback_days_actual=len(portfolio_ret),
        missing_symbols=missing_symbols,
        look_through_stale=look_through_stale,
        price_stale=price_stale,
    )
