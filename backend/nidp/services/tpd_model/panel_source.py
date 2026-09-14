"""Which bars the model may use: NSE equity rows only, and which sessions are too thin to trust."""
from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd

NSE_SOURCES = ("NSE_BHAVCOPY", "NSE_SEC_BHAVDATA")


def select_nse_eq(rows: pd.DataFrame, etf_symbols: set[str]) -> pd.DataFrame:
    """NSE EQ bars minus ETFs. BSE gap-fill rows never stand in for a missing NSE bar (their prices and
    volumes differ), so a BSE-only symbol-date is simply a missing bar."""
    keep = rows["source"].isin(NSE_SOURCES) & (rows["series"] == "EQ") & ~rows["symbol"].isin(etf_symbols)
    out = rows[keep]
    # An archive backfill row and a bhavcopy row for the same bar are identical by construction; keep one.
    out = out.sort_values(["symbol", "as_of_date", "source"], kind="mergesort")
    return out.drop_duplicates(["symbol", "as_of_date"], keep="first").reset_index(drop=True)


def thin_sessions(panel: pd.DataFrame, lookback: int = 126, frac: float = 0.8) -> list[date]:
    """Sessions whose row count is below `frac` of the median of the up-to-`lookback` sessions BEFORE them.
    A whole-panel median would let later, larger sessions condemn earlier ones (look-ahead)."""
    counts = panel.groupby("as_of_date").size().sort_index()
    thin = []
    for i, (d, n) in enumerate(counts.items()):
        prior = counts.iloc[max(0, i - lookback):i]
        if len(prior) and n < frac * float(np.median(prior)):
            thin.append(pd.Timestamp(d).date())
    return thin
