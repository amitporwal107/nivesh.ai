"""Walk-forward protocol (B1): one fold per calendar month of target sessions, trained only on rows whose
label was fully known before that month began."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.linear_model import LogisticRegression

# The research walk-forward's settings (research/tpd_run/code/backtest.py), which produced the 0.804 baseline.
GBM_PARAMS = {"max_iter": 150, "learning_rate": 0.08, "max_leaf_nodes": 31, "l2_regularization": 1.0, "random_state": 7}


@dataclass(frozen=True)
class Fold:
    month: str
    train_start: date
    first_scored: date
    last_scored: date


def month_folds(sessions: list[date], first: date, last: date, cap_months: int = 18) -> list[Fold]:
    """Growing window from the first session, capped at `cap_months` before each scored month."""
    s = pd.DatetimeIndex(sorted(sessions))
    scored = s[(s >= pd.Timestamp(first)) & (s <= pd.Timestamp(last))]
    folds = []
    for month in sorted(set(scored.strftime("%Y-%m"))):
        days = scored[scored.strftime("%Y-%m") == month]
        first_scored = days.min()
        train_start = s[s >= first_scored - pd.DateOffset(months=cap_months)].min()
        folds.append(Fold(month, train_start.date(), first_scored.date(), days.max().date()))
    return folds


def _horizon_col(head: str) -> str:
    return "horizon_end_1d" if head.endswith("_1d") else "horizon_end_5d"


def training_rows(rows: pd.DataFrame, fold: Fold, head: str) -> pd.DataFrame:
    """Rows from the window whose label horizon ended before the scored month (K2), with a label."""
    y = f"y_{head}"
    keep = ((rows["as_of_date"] >= pd.Timestamp(fold.train_start))
            & (rows[_horizon_col(head)] < pd.Timestamp(fold.first_scored))
            & rows[y].notna())
    return rows[keep]


def scored_rows(rows: pd.DataFrame, fold: Fold) -> pd.DataFrame:
    ts = rows["target_session"]
    return rows[(ts >= pd.Timestamp(fold.first_scored)) & (ts <= pd.Timestamp(fold.last_scored))]


def fit_gbm(X: pd.DataFrame, y) -> HistGradientBoostingClassifier:
    return HistGradientBoostingClassifier(**GBM_PARAMS).fit(X.astype(np.float64), np.asarray(y, dtype=int))


class SingleFeatureLogit:
    """Comparator: logistic regression on one standardised column (NaN -> training median)."""

    def __init__(self, column: str):
        self.column = column

    def fit(self, X: pd.DataFrame, y):
        x = X[self.column].to_numpy(np.float64)
        self.median = float(np.nanmedian(x))
        x = np.where(np.isnan(x), self.median, x)
        self.mu, self.sd = float(x.mean()), float(x.std() or 1.0)
        self.model = LogisticRegression(max_iter=1000).fit(((x - self.mu) / self.sd).reshape(-1, 1), np.asarray(y, int))
        return self

    def predict(self, X: pd.DataFrame) -> np.ndarray:
        x = X[self.column].to_numpy(np.float64)
        x = np.where(np.isnan(x), self.median, x)
        return self.model.predict_proba(((x - self.mu) / self.sd).reshape(-1, 1))[:, 1]
