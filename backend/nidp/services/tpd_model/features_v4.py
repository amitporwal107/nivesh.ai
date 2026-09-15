"""v4 features: v3 plus the results-print block read at the freeze-time cutoff (results_print.py)."""
from __future__ import annotations

from datetime import date
from typing import Optional

import numpy as np
import pandas as pd

from .features_v3 import FEATURE_LIST_V3, compute_features_v3
from .results_print import RESULTS_PRINT_FEATURES, results_print

FEATURE_LIST_V4 = FEATURE_LIST_V3 + RESULTS_PRINT_FEATURES


def compute_features_v4(panel: pd.DataFrame, T: date, financials: Optional[pd.DataFrame] = None, **kw) -> pd.DataFrame:
    v3 = compute_features_v3(panel, T, financials=financials, **kw)
    return add_results_print(v3, financials, T)


def add_results_print(v3: pd.DataFrame, financials: Optional[pd.DataFrame], T: date) -> pd.DataFrame:
    """Append the print block to a v3 feature frame (index = symbol). Without financials the block is unknown (NaN)."""
    symbols = list(v3.index)
    if financials is None:
        block = pd.DataFrame(np.nan, index=pd.Index(symbols, name="symbol"), columns=list(RESULTS_PRINT_FEATURES), dtype="float64")
    else:
        block = results_print(financials, symbols, T)
    out = pd.concat([v3, block.loc[symbols]], axis=1)[list(FEATURE_LIST_V4)]
    out.index.name = "symbol"
    return out
