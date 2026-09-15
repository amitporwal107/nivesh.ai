"""Model inputs for the four heads: monotone transforms of the point-in-time features plus each stock's own
history of large moves, shrunk toward the training base rate (the research model's design, without F&O
membership)."""
from __future__ import annotations

import numpy as np
import pandas as pd

HEADS = ("p_up10_1d", "p_down10_1d", "p_up10_5d", "p_down10_5d")

# A stock's past +10% (or -10%) days in the last year: the own-history comparator and a model input.
OWN_HISTORY_COUNT = {
    "p_up10_1d": "n_high_up_252", "p_down10_1d": "n_low_down_252",
    "p_up10_5d": "n_high_up_252", "p_down10_5d": "n_low_down_252",
    "p_up5_1d": "n_high_up_252", "p_down5_1d": "n_low_down_252",     # v4: the 10% counts stand in as the own-history comparator
}
HEADS_V4 = ("p_up10_1d", "p_down10_1d", "p_up5_1d", "p_down5_1d")
# The one-day event whose training base rate anchors each count's shrinkage.
COUNT_PRIOR_HEAD = {"n_high_up_252": "p_up10_1d", "n_low_down_252": "p_down10_1d"}
SHRINK_K = 50.0

PASSTHROUGH = ("rsi14", "ret1", "ret5", "ret20", "ret60", "bb_pos", "vol_z20", "deliv_prev", "deliv_avg20",
               "deliv_trend10", "deliv_missing", "dist_52w_high", "dist_swing20", "dist_sma20", "dist_sma50",
               "sma50_slope", "maxabs20", "gap1", "range1", "mkt_ret1", "breadth", "n_gap_up_252",
               "n_range10_252", "res_on_T", "res_on_D")
MODEL_COLUMNS = PASSTHROUGH + ("log_atr_pct", "log_bbw", "log_dist_52w_low", "log_turn", "log_price",
                               "lr_n_high_up_252", "lr_n_low_down_252")

# v3 (user scope change 2026-09-15): the PRD's technical extensions, point-in-time fundamentals and ownership
# are passed through raw — gradient-boosted trees split on them directly and handle NaN natively. Cash flow
# (CFO/PAT) has no filing timestamp in the warehouse, so it is not point-in-time and stays out.
from .fundamentals import FUNDAMENTAL_FEATURES, OWNERSHIP_FEATURES  # noqa: E402
from .results_print import RESULTS_PRINT_FEATURES
from .technical_ext import TECHNICAL_EXT_FEATURES  # noqa: E402

MODEL_COLUMNS_V3 = MODEL_COLUMNS + TECHNICAL_EXT_FEATURES + FUNDAMENTAL_FEATURES + OWNERSHIP_FEATURES
MODEL_COLUMNS_V4 = MODEL_COLUMNS_V3 + RESULTS_PRINT_FEATURES


def own_rate(features: pd.DataFrame, count: str, prior: float) -> pd.Series:
    """log((past event days + K x prior) / (bars counted + K)): a young listing's few bars pull toward the
    training base rate instead of reading 1-in-30 as a 3% habit."""
    bars = (features["nbars"] - 1).clip(lower=0, upper=252)
    return np.log((features[count] + SHRINK_K * prior) / (bars + SHRINK_K))


def design_matrix(features: pd.DataFrame, priors: dict[str, float], columns: tuple = MODEL_COLUMNS) -> pd.DataFrame:
    """`priors` maps a one-day head to its training event rate (the heads in COUNT_PRIOR_HEAD). `columns`
    selects the model version's inputs; any column beyond the v2 transforms is passed through as float."""
    Z = pd.DataFrame(index=features.index)
    for c in PASSTHROUGH:
        Z[c] = features[c].astype("float64")
    Z["log_atr_pct"] = np.log(features["atr_pct"].clip(lower=0.1))
    Z["log_bbw"] = np.log(features["bb_width"].clip(lower=1e-3))
    Z["log_dist_52w_low"] = np.log1p(features["dist_52w_low"].clip(lower=0))
    Z["log_turn"] = np.log(features["turn_med20"].clip(lower=1))
    Z["log_price"] = np.log(features["close_raw"].clip(lower=1))
    for count, head in COUNT_PRIOR_HEAD.items():
        Z[f"lr_{count}"] = own_rate(features, count, priors[head])
    for c in columns:
        if c not in Z.columns:
            Z[c] = features[c].astype("float64")
    return Z[list(columns)]
