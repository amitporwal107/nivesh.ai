"""v3 feature set: the v2 point-in-time features plus the PRD's technical extensions (§6-12), fundamentals
(§17-18, 21-22, 25) and ownership (§23), one row per symbol with a bar on T.

The v2 columns are produced by the same function as v2 and are bit-identical to it. The new blocks obey the same
rule: nothing dated after T, and a filing counts only from its exchange timestamp at or before 15:30 IST on T.
When a block's inputs are not supplied its columns are NaN with the missing flag set, so a run without
fundamentals is visible, not silently equal to zeros.
"""
from __future__ import annotations

from datetime import date
from typing import Optional

import numpy as np
import pandas as pd

from .features import FEATURE_LIST, compute_features
from .fundamentals import FUNDAMENTAL_FEATURES, OWNERSHIP_FEATURES, pit_fundamentals, pit_ownership
from .technical_ext import TECHNICAL_EXT_FEATURES, extended_technical

FEATURE_LIST_V3 = FEATURE_LIST + TECHNICAL_EXT_FEATURES + FUNDAMENTAL_FEATURES + OWNERSHIP_FEATURES


def _missing_block(symbols: list[str], columns: tuple, flag: str) -> pd.DataFrame:
    out = pd.DataFrame(np.nan, index=pd.Index(symbols, name="symbol"), columns=list(columns), dtype="float64")
    out[flag] = 1.0
    return out


def compute_features_v3(panel: pd.DataFrame, T: date, events: Optional[pd.DataFrame] = None,
                        actions: Optional[pd.DataFrame] = None, target_session: Optional[date] = None,
                        market_members: Optional[set] = None, financials: Optional[pd.DataFrame] = None,
                        shareholding: Optional[pd.DataFrame] = None) -> pd.DataFrame:
    v2 = compute_features(panel, T, events=events, actions=actions, target_session=target_session,
                          market_members=market_members)
    symbols = list(v2.index)
    upto = panel[panel["as_of_date"] <= pd.Timestamp(T)]
    tech = pd.DataFrame.from_dict({sym: extended_technical(g) for sym, g in upto.groupby("symbol", sort=False) if sym in v2.index},
                                  orient="index", columns=list(TECHNICAL_EXT_FEATURES)).reindex(symbols).astype("float64")
    if financials is not None:
        fund = pit_fundamentals(financials, symbols, T, close=v2["close_raw"].to_dict())[list(FUNDAMENTAL_FEATURES)]
    else:
        fund = _missing_block(symbols, FUNDAMENTAL_FEATURES, "fund_missing")
    own = pit_ownership(shareholding, symbols, T) if shareholding is not None else _missing_block(symbols, OWNERSHIP_FEATURES, "own_missing")
    out = pd.concat([v2, tech, fund.astype("float64"), own.astype("float64")], axis=1)[list(FEATURE_LIST_V3)]
    out.index.name = "symbol"
    return out
