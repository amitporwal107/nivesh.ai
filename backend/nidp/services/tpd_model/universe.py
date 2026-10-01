"""Point-in-time universe: the stocks liquid enough to trade, as they stood before the target session."""
from __future__ import annotations

from datetime import date
from typing import Optional

import pandas as pd

#: Median 20-session turnover a symbol must clear, in rupees. This is the number the paper rules
#: have always documented (`rules_v1.json` → eligibility → min_traded_value). Until 2026-10-01 the
#: universe did not actually apply it: it took the top 1,000 by turnover instead, which on
#: 2026-09-30 put the real floor at Rs 4.67 cr — 4.7x the documented bar — and left 371 symbols
#: that cleared Rs 1 cr permanently unscored.
MIN_MEDIAN_TURNOVER = 1.0e7

#: Bars required inside the lookback window. 60, not 100, because 60 is what the SCORER already
#: demands (`forward.WARMUP_BARS`), and that in turn is set by the longest feature window in
#: MODEL_COLUMNS_V4 — `ret60`, with `dist_sma50` and `sma50_slope` close behind. A universe gate
#: stricter than the scorer's silently drops symbols the model could have handled; a looser one
#: admits symbols whose features are undefined. They should be the same number.
MIN_BARS = 60


def pit_universe(panel: pd.DataFrame, D: date, *, lookback: int = 126,
                 min_bars: int = MIN_BARS, min_turnover: float = MIN_MEDIAN_TURNOVER,
                 max_symbols: Optional[int] = None) -> list[str]:
    """Symbols clearing `min_turnover` median turnover over the `lookback` sessions before `D`.

    Ordered by median turnover descending, ties on symbol, so the list is reproducible. Nothing
    dated D or later is read, so a stock that later dropped out still appears where it was a member.

    `max_symbols` is a safety ceiling, not a selection rule, and defaults to OFF. The previous
    implementation made a `head(1000)` the de-facto eligibility criterion — a liquidity threshold
    expressed as whatever rank 1,000 happened to be that day. Sizing the universe by the filter
    rather than by a number is the point of this function; pass `max_symbols` only to bound a
    runaway run, and record it when you do.
    """
    cutoff = pd.Timestamp(D)
    prior = panel.loc[panel["as_of_date"] < cutoff, "as_of_date"].drop_duplicates().sort_values()
    window = panel[panel["as_of_date"].isin(prior.iloc[-lookback:])]
    stats = window.groupby("symbol")["turnover"].agg(["count", "median"])
    stats = stats[(stats["count"] >= min_bars) & (stats["median"] >= min_turnover)].reset_index()
    stats = stats.sort_values(["median", "symbol"], ascending=[False, True], kind="mergesort")
    syms = stats["symbol"].tolist()
    return syms[:max_symbols] if max_symbols is not None else syms
