"""nidp-yfinance-backfill — historical OHLCV backfill from Yahoo Finance.

Source:    https://query1.finance.yahoo.com/v8/finance/chart/{SYMBOL}.NS
Cadence:   One-shot historical backfill (e.g. 2010-2024). Daily ingestion
           remains on NSE bhavcopy (more authoritative for India).
Output:    nidp.prices_eod  (source = 'YFINANCE')

Coexistence with NSE bhavcopy: prices_eod PK is
(as_of_date, symbol, series, source). Same (date, symbol) can carry
both NSE_BHAVCOPY and YFINANCE rows; downstream views prefer
NSE_BHAVCOPY when both exist.

Use case: 20-year backtests, longer-window technicals, MAX-period
charts. NSE archives only go back ~5y reliably.
"""
__all__ = ["service", "parser", "writer"]

# Side-effect: register validation rules
from . import validators  # noqa: F401
