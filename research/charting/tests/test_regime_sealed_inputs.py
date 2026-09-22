"""Sealed-window bars as INPUTS to regime features (review 2026-09-22).

EMA, ATR and ADX are recursive: computed over a whole frame, a post-sealed value keeps a share of
every earlier bar, including sealed-window bars in a stock's continuous history, even after its
warm-up window passes `_window_check`. Probe: multiply only the sealed bars (or, for the index
files, only the pre-gap rows) and require every OK post-sealed feature to stay the same.
Negative control: the same probe on a whole-frame EMA shows the leak it is looking for."""
from __future__ import annotations

import math

import pandas as pd
import pytest

from research.charting import regime, research_window as rw, series
from research.charting.tests import synth

DATES = ("2024-09-30", "2024-12-31", "2025-06-30")


def _continuous_bars() -> pd.DataFrame:
    """Business-day bars from 2022-06 through 2025-08, crossing the sealed window."""
    n = len(pd.bdate_range("2022-06-01", "2025-08-29"))
    closes = [100.0 + (i % 11) * 0.7 + i * 0.03 for i in range(n)]
    bars = synth.bars_from_closes(closes, start_date="2022-06-01")
    bars["date"] = pd.bdate_range("2022-06-01", periods=len(bars))
    return bars


def _poison(bars: pd.DataFrame, mask) -> pd.DataFrame:
    out = bars.copy()
    for c in ("open", "high", "low", "close"):
        out.loc[mask, c] = out.loc[mask, c] * 1000
    return out


def _same(a, b) -> bool:
    return math.isclose(a, b, rel_tol=1e-9, abs_tol=1e-9)


@pytest.mark.parametrize("t", DATES)
def test_sealed_bars_never_reach_a_post_sealed_trend_feature(t):
    bars = _continuous_bars()
    poisoned = _poison(bars, bars["date"].between(rw.SEALED_GAP_START, rw.SEALED_GAP_END))
    clean, dirty = regime.trend_context(bars, t), regime.trend_context(poisoned, t)
    ok = [k for k, v in clean.items() if v.status == regime.STATUS_OK and isinstance(v.value, float)]
    assert {"ema_20", "atr_14"} <= set(ok)  # the recursive ones are actually exercised
    moved = [k for k in ok if not _same(clean[k].value, dirty[k].value)]
    assert moved == []


@pytest.mark.parametrize("t", DATES)
def test_pre_gap_index_rows_never_reach_a_post_sealed_regime_or_trend_feature(t):
    bars = _continuous_bars()
    index = bars[~bars["date"].between(rw.SEALED_GAP_START, rw.SEALED_GAP_END)].reset_index(drop=True)
    poisoned = _poison(index, index["date"] < rw.SEALED_GAP_START)
    for fn in (regime.trend_context, regime.market_regime):
        clean, dirty = fn(index, t), fn(poisoned, t)
        moved = [k for k, v in clean.items() if v.status == regime.STATUS_OK and isinstance(v.value, float)
                 and not _same(v.value, dirty[k].value)]
        assert moved == [], (fn.__name__, moved)


def test_negative_control_a_whole_frame_ema_does_carry_sealed_bars():
    bars = _continuous_bars()
    poisoned = _poison(bars, bars["date"].between(rw.SEALED_GAP_START, rw.SEALED_GAP_END))
    pos = int(bars.index[bars["date"] == pd.Timestamp("2024-09-30")][0])
    assert not _same(series.ema(bars, 20).iloc[pos], series.ema(poisoned, 20).iloc[pos])
