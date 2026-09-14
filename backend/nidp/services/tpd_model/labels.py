"""Event labels for the four heads.

1D: the target session's high reaches +10% (or its low -10%) against the prediction day's close.
5D: the highest high (lowest low) over the next five sessions reaches +10% (-10%) against the prediction
day's close — cumulative, not five separate one-day tests.

Comparisons are exact: prices carry two decimals, so they are compared as whole paise
(high x 100 >= close x 110). Float arithmetic would miss a move of exactly 10.00%.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Optional, Sequence

import numpy as np
import pandas as pd

_UP, _DOWN = Decimal("1.10"), Decimal("0.90")


def _d(x) -> Decimal:
    return x if isinstance(x, Decimal) else Decimal(str(x))


def touch_1d(prev_close, high, low) -> tuple[bool, bool]:
    pc = _d(prev_close)
    return _d(high) >= pc * _UP, _d(low) <= pc * _DOWN


def touch_5d(close_T, highs: Sequence, lows: Sequence) -> Optional[tuple[bool, bool]]:
    if len(highs) != 5 or len(lows) != 5:
        return None
    c = _d(close_T)
    return max(map(_d, highs)) >= c * _UP, min(map(_d, lows)) <= c * _DOWN


def _paise(values: pd.Series) -> np.ndarray:
    # Whole paise stay exact in float64 far beyond any traded price, and NaN marks a missing bar.
    return np.round(values.to_numpy(dtype="float64") * 100)


def build_labels(panel: pd.DataFrame, actions: pd.DataFrame, muhurat_sessions=frozenset()) -> pd.DataFrame:
    """One row per (symbol, prediction day T) with the four labels and why a label is missing.

    Horizons are market sessions (every date in the panel), so a suspended stock's next bar is not
    mistaken for the next session. Missing labels carry a reason instead of a silent False.
    """
    sessions = pd.DatetimeIndex(sorted(panel["as_of_date"].unique()))
    n_s = len(sessions)
    muhurat = {pd.Timestamp(d) for d in muhurat_sessions}
    ex_by_symbol: dict[str, set] = {}
    if actions is not None and len(actions):
        for sym, ex in zip(actions["symbol"], pd.to_datetime(actions["ex_date"])):
            ex_by_symbol.setdefault(sym, set()).add(ex)

    frames = []
    for sym, g in panel.groupby("symbol", sort=True):
        g = g.drop_duplicates("as_of_date").set_index("as_of_date").reindex(sessions)
        close, high, low = _paise(g["close"]), _paise(g["high"]), _paise(g["low"])
        present = ~np.isnan(close)
        ex = ex_by_symbol.get(sym, set())
        is_ex = np.array([d in ex for d in sessions])
        is_muhurat = np.array([d in muhurat for d in sessions])

        idx = np.flatnonzero(present)
        up1 = np.full(len(idx), None, dtype=object)
        dn1 = up1.copy()
        up5 = up1.copy()
        dn5 = up1.copy()
        ex1 = up1.copy()
        ex5 = up1.copy()
        target = np.full(len(idx), pd.NaT, dtype=object)
        for k, j in enumerate(idx):
            c = close[j]
            if j + 1 >= n_s:
                ex1[k] = "incomplete_horizon"
            else:
                target[k] = sessions[j + 1]
                if is_ex[j + 1]:
                    ex1[k] = "corporate_action"
                elif is_muhurat[j + 1]:
                    ex1[k] = "muhurat"
                elif not present[j + 1]:
                    ex1[k] = "no_bar_on_target"
                else:
                    up1[k] = bool(high[j + 1] * 100 >= c * 110)
                    dn1[k] = bool(low[j + 1] * 100 <= c * 90)
            w = slice(j + 1, j + 6)
            if j + 5 >= n_s:
                ex5[k] = "incomplete_horizon"
            elif is_ex[w].any():
                ex5[k] = "corporate_action_in_horizon"
            elif is_muhurat[w].any():
                ex5[k] = "muhurat_in_horizon"
            elif not present[w].all():
                ex5[k] = "missing_bar_in_horizon"
            else:
                up5[k] = bool(high[w].max() * 100 >= c * 110)
                dn5[k] = bool(low[w].min() * 100 <= c * 90)
        frames.append(pd.DataFrame({
            "symbol": sym, "as_of_date": sessions[idx], "target_session": target,
            "up_1d": up1, "down_1d": dn1, "up_5d": up5, "down_5d": dn5, "excl_1d": ex1, "excl_5d": ex5,
        }))
    cols = ["symbol", "as_of_date", "target_session", "up_1d", "down_1d", "up_5d", "down_5d", "excl_1d", "excl_5d"]
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=cols)
