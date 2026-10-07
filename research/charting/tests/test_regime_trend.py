"""N-section-10 Trend Context Engine tests -- hand-computed trend_state on synthetic
linear-ramp fixtures (closed-form SMA of an arithmetic sequence, verifiable by hand: for
close[i] = a + b*i, SMA(period) at index idx = a + b*(idx - (period-1)/2) -- the mean of
an arithmetic run is just its midpoint), an ADX(14) cross-check against an independently
written (not code-shared) naive loop implementation of the same Wilder formula, and
warmup/status boundary checks.

Fixture dates deliberately start 2019-01-02 (`synth.bars_from_closes(..., start_date=...)`)
-- NOT the module default `2024-01-02`, which sits inside the sealed 2023-01-01..2024-07-31
block and would make every 200+-bar lookback in this file spuriously SEALED_GAP.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from research.charting import regime
from research.charting import series
from research.charting.tests import synth

_SAFE_START = "2019-01-02"  # well before the sealed window


# ── Hand-computed trend_state on linear-ramp fixtures ────────────────────────


def test_trend_state_bullish_hand_computed_linear_ramp():
    """close[i] = 100 + 0.5*i, i=0..259 (260 bars). Closed-form SMA(period) at the last
    index (259) = 100 + 0.5*(259 - (period-1)/2):
        SMA200 = 100 + 0.5*(259 - 99.5) = 179.75
        SMA50  = 100 + 0.5*(259 - 24.5) = 217.25
        SMA20  = 100 + 0.5*(259 - 9.5)  = 224.75
        close  = 100 + 0.5*259          = 229.5
    All strictly increasing (close > SMA20 > SMA50 > SMA200) since b=0.5 > 0, and SMA50's
    slope over any lookback L is exactly b*L / SMA50(259-L) / L * 100 > 0 (a positive
    constant per bar, divided by a positive SMA) -- so N-section-10's bullish example is
    satisfied by construction: trend_state must be 2.
    """
    closes = [100 + 0.5 * i for i in range(260)]
    bars = synth.bars_from_closes(closes, start_date=_SAFE_START, wick=0.1)
    t = bars["date"].iloc[-1]

    tc = regime.trend_context(bars, t)

    assert tc["close"].value == pytest.approx(229.5)
    assert tc["sma_20"].value == pytest.approx(224.75)
    assert tc["sma_50"].value == pytest.approx(217.25)
    assert tc["sma_200"].value == pytest.approx(179.75)
    assert tc["sma_50_slope"].value > 0
    assert tc["trend_state"].status == "OK"
    assert tc["trend_state"].value == 2


def test_trend_state_bearish_hand_computed_linear_ramp():
    """close[i] = 500 - 0.5*i, i=0..259. Same closed-form, mirrored:
        SMA200 = 500 - 0.5*159.5 = 420.25
        SMA50  = 500 - 0.5*234.5 = 382.75
        SMA20  = 500 - 0.5*249.5 = 375.25
        close  = 500 - 0.5*259   = 370.5
    close < SMA20 < SMA50 < SMA200 and SMA50's slope is negative by the same reasoning
    (b=-0.5) -- N-section-10's bearish mirror is satisfied by construction: trend_state
    must be 0.
    """
    closes = [500 - 0.5 * i for i in range(260)]
    bars = synth.bars_from_closes(closes, start_date=_SAFE_START, wick=0.1)
    t = bars["date"].iloc[-1]

    tc = regime.trend_context(bars, t)

    assert tc["close"].value == pytest.approx(370.5)
    assert tc["sma_20"].value == pytest.approx(375.25)
    assert tc["sma_50"].value == pytest.approx(382.75)
    assert tc["sma_200"].value == pytest.approx(420.25)
    assert tc["sma_50_slope"].value < 0
    assert tc["trend_state"].status == "OK"
    assert tc["trend_state"].value == 0


def test_trend_state_neutral_when_signals_conflict():
    """A bullish 230-bar ramp (as above) followed by a 30-bar declining tail: SMA20 (a
    short window) is pulled down by the recent decline while SMA50/SMA200 (longer
    windows) barely move -- close/SMA50/SMA200 keep the bullish ordering but SMA20 no
    longer exceeds SMA50, so neither the bullish nor the mirrored bearish rule is fully
    satisfied. Verified once empirically (values asserted below are the actual computed
    numbers, not re-derived by a second implementation) -- this is the "genuinely mixed
    signals" case N-section-10's own text implies NEUTRAL covers, as opposed to the two
    clean-sweep cases above which are provable by the closed-form alone.
    """
    ramp = [100 + 0.5 * i for i in range(230)]
    tail = [ramp[-1] - 0.2 * i for i in range(1, 31)]
    closes = ramp + tail
    bars = synth.bars_from_closes(closes, start_date=_SAFE_START, wick=0.1)
    t = bars["date"].iloc[-1]

    tc = regime.trend_context(bars, t)

    assert tc["trend_state"].status == "OK"
    assert tc["sma_20"].value < tc["sma_50"].value  # the broken condition
    assert tc["close"].value < tc["sma_50"].value  # close has also dropped below sma50
    assert tc["sma_50"].value > tc["sma_200"].value  # but the longer-term ordering still holds
    assert tc["trend_state"].value == 1


def test_trend_state_unavailable_when_any_required_input_is_unavailable():
    """trend_state must be UNAVAILABLE (never silently defaulted to neutral) when one of
    its five required inputs (close/sma20/sma50/sma200/sma50_slope) cannot be computed --
    here, too few bars exist for SMA200 at all."""
    closes = [100 + 0.5 * i for i in range(50)]  # far short of the 200 SMA200 needs
    bars = synth.bars_from_closes(closes, start_date=_SAFE_START, wick=0.1)
    t = bars["date"].iloc[-1]

    tc = regime.trend_context(bars, t)

    assert tc["sma_200"].status == "UNAVAILABLE"
    assert tc["trend_state"].status == "UNAVAILABLE"
    assert tc["trend_state"].value is None


# ── ADX(14) cross-check against an independently written implementation ─────


def _naive_wilder_adx(bars: pd.DataFrame, period: int = 14) -> np.ndarray:
    """A plain Python-loop re-implementation of Wilder's ADX, written independently of
    `regime._adx_series` (no shared helper functions, no vectorised numpy tricks) --
    a redundant-implementation cross-check, not a hand-derived pinned value (ADX's
    double Wilder-smoothing recursion is not practically hand-computable over a large
    enough window to be meaningful; see module docstring's RS/trend_state hand-computed
    tests for the values that ARE done that way)."""
    high = bars["high"].to_numpy(dtype=float)
    low = bars["low"].to_numpy(dtype=float)
    close = bars["close"].to_numpy(dtype=float)
    n = len(close)
    tr = [float("nan")] * n
    plus_dm = [float("nan")] * n
    minus_dm = [float("nan")] * n
    for i in range(1, n):
        up = high[i] - high[i - 1]
        down = low[i - 1] - low[i]
        plus_dm[i] = up if (up > down and up > 0) else 0.0
        minus_dm[i] = down if (down > up and down > 0) else 0.0
        tr[i] = max(high[i] - low[i], abs(high[i] - close[i - 1]), abs(low[i] - close[i - 1]))

    atr = [float("nan")] * n
    pdm = [float("nan")] * n
    mdm = [float("nan")] * n
    if n > period:
        atr[period] = float(np.mean(tr[1:period + 1]))
        pdm[period] = float(np.mean(plus_dm[1:period + 1]))
        mdm[period] = float(np.mean(minus_dm[1:period + 1]))
        for i in range(period + 1, n):
            atr[i] = (atr[i - 1] * (period - 1) + tr[i]) / period
            pdm[i] = (pdm[i - 1] * (period - 1) + plus_dm[i]) / period
            mdm[i] = (mdm[i - 1] * (period - 1) + minus_dm[i]) / period

    plus_di = [float("nan")] * n
    minus_di = [float("nan")] * n
    dx = [float("nan")] * n
    for i in range(period, n):
        if atr[i] == atr[i]:  # not NaN
            plus_di[i] = 100.0 * pdm[i] / atr[i]
            minus_di[i] = 100.0 * mdm[i] / atr[i]
            s = plus_di[i] + minus_di[i]
            dx[i] = 100.0 * abs(plus_di[i] - minus_di[i]) / s if s != 0 else 0.0

    adx = [float("nan")] * n
    first_dx = period
    seed_end = first_dx + period
    if n > seed_end - 1:
        adx[seed_end - 1] = float(np.mean(dx[first_dx:seed_end]))
        for i in range(seed_end, n):
            adx[i] = (adx[i - 1] * (period - 1) + dx[i]) / period
    return np.array(adx)


@pytest.mark.parametrize("seed", [1, 7, 42])
def test_adx_matches_independent_naive_implementation(seed):
    rng = np.random.default_rng(seed)
    n = 90
    closes = 100 + np.cumsum(rng.normal(0.1, 1.5, n))
    bars = synth.bars_from_closes(list(closes), start_date=_SAFE_START, wick=1.0)

    naive = _naive_wilder_adx(bars, period=14)
    vec = regime._adx_series(bars, period=14).to_numpy()

    assert (np.isnan(naive) == np.isnan(vec)).all()
    valid = ~np.isnan(naive)
    assert valid.sum() > 20  # meaningful overlap, not a degenerate all-NaN comparison
    np.testing.assert_allclose(naive[valid], vec[valid], atol=1e-9)

    # `regime._adx_series` delegates to `series.adx` since 2026-09-23 (one implementation).
    # Assert the oracle against the public charting series directly too, so this cross-check
    # stays attached to the real calculation if the delegation direction ever changes.
    public = series.adx(bars, period=14).to_numpy()
    assert (np.isnan(public) == np.isnan(naive)).all()
    np.testing.assert_allclose(naive[valid], public[valid], atol=1e-9)


def test_adx_warmup_period_is_2x_period_first_valid_index():
    """First valid ADX(14) index is 2*14-1=27 (0-based) -- verified against the naive
    cross-check above; this test pins the exact warmup_period this module documents and
    `_window_check(... , 2*adx_period)` relies on."""
    rng = np.random.default_rng(3)
    n = 60
    closes = 100 + np.cumsum(rng.normal(0.0, 1.0, n))
    bars = synth.bars_from_closes(list(closes), start_date=_SAFE_START, wick=1.0)
    vec = regime._adx_series(bars, period=14).to_numpy()
    assert np.isnan(vec[26])
    assert not np.isnan(vec[27])


# ── SMA slope: matches calculator.py.sma_slope's formula exactly ────────────


def test_sma_slope_matches_calculator_formula_on_a_small_frame():
    """8 bars, SMA(period=3, lookback=3): end_sma = mean(closes[-3:]), start_sma =
    mean(closes[-6:-3]) -- hand-computed below."""
    closes = [100.0, 102.0, 101.0, 104.0, 103.0, 106.0, 108.0, 110.0]
    bars = synth.bars_from_closes(closes, start_date=_SAFE_START, wick=0.1)

    end_sma = (106.0 + 108.0 + 110.0) / 3.0  # 108.0
    start_sma = (101.0 + 104.0 + 103.0) / 3.0  # 102.666...
    expected_slope = (end_sma - start_sma) / abs(start_sma) / 3.0 * 100.0

    slope_series = regime._sma_slope(bars, period=3, lookback=3)
    assert slope_series.iloc[-1] == pytest.approx(expected_slope)


# ── Point-in-time / warmup boundary checks (not the sealed gap -- see
#    test_regime_sealed_boundaries.py) ────────────────────────────────────────


def test_ema_uses_period_length_warmup_for_sealed_gap_purposes():
    """Documents the deliberate EMA simplification (module docstring): the sealed-gap
    check uses warmup_period == period (matching series.py/calculator.py's own EMA NaN
    gate), not EMA's true infinite recursive memory. A 30-bar fixture entirely before
    the sealed window: ema_20 must be OK once 20 bars exist, regardless of EMA's
    mathematically-infinite dependency chain."""
    closes = [100.0 + i for i in range(30)]
    bars = synth.bars_from_closes(closes, start_date=_SAFE_START, wick=0.1)
    t = bars["date"].iloc[-1]
    tc = regime.trend_context(bars, t, sma_periods=(), ema_periods=(20,))
    assert tc["ema_20"].status == "OK"


def test_insufficient_history_reason_when_too_few_bars_exist_at_all():
    closes = [100.0 + i for i in range(10)]
    bars = synth.bars_from_closes(closes, start_date=_SAFE_START, wick=0.1)
    t = bars["date"].iloc[-1]
    tc = regime.trend_context(bars, t, sma_periods=(20,), ema_periods=())
    assert tc["sma_20"].status == "UNAVAILABLE"
    assert tc["sma_20"].reason == "INSUFFICIENT_HISTORY"
