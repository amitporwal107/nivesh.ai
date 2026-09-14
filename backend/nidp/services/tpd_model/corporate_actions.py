"""Point-in-time corporate-action adjustment.

A factor is a price multiplier for bars before its ex-date (0.5 for a 1:1 bonus). Only actions with an
ex-date on or before the as-of date apply, so an action announced later can never rewrite a past feature
(the research panel multiplied in every later factor).
"""
from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd


def multipliers(bar_dates: pd.Series | pd.DatetimeIndex, actions: pd.DataFrame, as_of: date) -> np.ndarray:
    """Cumulative price multiplier for each bar: product of factors whose ex-date is after the bar and on
    or before `as_of`."""
    dates = pd.DatetimeIndex(bar_dates)
    out = np.ones(len(dates))
    if actions is None or actions.empty:
        return out
    for ex_date, factor in actions.loc[pd.to_datetime(actions["ex_date"]) <= pd.Timestamp(as_of),
                                       ["ex_date", "factor"]].itertuples(index=False):
        out[dates < pd.Timestamp(ex_date)] *= float(factor)
    return out


def adjusted_closes(bars: pd.DataFrame, actions: pd.DataFrame, as_of: date) -> pd.Series:
    b = bars[bars["as_of_date"] <= pd.Timestamp(as_of)].sort_values("as_of_date", kind="mergesort")
    values = b["close"].to_numpy(dtype="float64") * multipliers(b["as_of_date"], actions, as_of)
    return pd.Series(values, index=pd.DatetimeIndex(b["as_of_date"], name="as_of_date"), name="close")
