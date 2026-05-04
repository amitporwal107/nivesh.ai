"""Sector relative-strength helper.

We approximate per-stock sector strength as:
   stock's 20-bar return − Nifty 50's 20-bar return
… until proper NSE sector-index OHLCV is wired up. Once sector indices
land in stock_ohlcv (with a synthetic symbol like '^NIFTY_IT'), this
function will switch to comparing stock vs sector vs Nifty.

Public API:
   compute_rs_pct(stock_ret_20d, nifty_ret_20d) → float | None
   load_nifty_ret(end_date) → float | None
"""
from __future__ import annotations

import logging
from datetime import date
from typing import Optional

from . import feature_calculator as fc
from . import ohlcv_store

logger = logging.getLogger(__name__)

# Benchmark proxy for Nifty 50. NSE bhavcopy only ships cash-segment
# securities (EQ/BE), not indices, so we use NIFTYBEES (Nippon India ETF
# Nifty BeES) which is in the bhavcopy and tracks Nifty 50 with tight
# error. If a true index ingester lands later (writing a synthetic
# 'NIFTY50' row), update this constant.
NIFTY_SYMBOL = "NIFTYBEES"


def compute_rs_pct(stock_ret_20d: Optional[float],
                   bench_ret_20d: Optional[float]) -> Optional[float]:
    if stock_ret_20d is None or bench_ret_20d is None:
        return None
    return stock_ret_20d - bench_ret_20d


async def load_bench_return(end_date: Optional[date] = None,
                             lookback: int = 20) -> Optional[float]:
    bars = await ohlcv_store.load_bars(NIFTY_SYMBOL, end_date=end_date,
                                        lookback_bars=lookback + 5)
    if not bars:
        return None
    closes = [float(b["close"]) for b in bars]
    return fc.return_pct(closes, lookback)
