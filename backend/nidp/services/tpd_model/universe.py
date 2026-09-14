"""Point-in-time universe: the most traded stocks as they stood before the target session."""
from __future__ import annotations

from datetime import date

import pandas as pd


def pit_universe(panel: pd.DataFrame, D: date, n: int = 1000, lookback: int = 126, min_bars: int = 100) -> list[str]:
    """Top `n` symbols by median turnover over the last `lookback` sessions strictly before `D`.

    Symbols need `min_bars` bars inside that window. Ties break on symbol so the list is reproducible.
    Nothing dated D or later is read, so a stock that later dropped out still appears where it was a member.
    """
    cutoff = pd.Timestamp(D)
    prior = panel.loc[panel["as_of_date"] < cutoff, "as_of_date"].drop_duplicates().sort_values()
    window = panel[panel["as_of_date"].isin(prior.iloc[-lookback:])]
    stats = window.groupby("symbol")["turnover"].agg(["count", "median"])
    stats = stats[stats["count"] >= min_bars].reset_index()
    stats = stats.sort_values(["median", "symbol"], ascending=[False, True], kind="mergesort")
    return stats["symbol"].head(n).tolist()
