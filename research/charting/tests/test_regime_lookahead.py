"""Poisoned-future probes (repo standard, see research/charting/tests/test_early_lookahead.py
and test_series.py's B2 probe): mutate every bar/index row strictly AFTER `t` and confirm
every feature this module computes AT `t` is unchanged. Each probe is paired with a
negative control -- a deliberately peeking implementation -- proving the comparison
methodology can actually detect a leak rather than trivially always passing.

Covers all four inputs `features_at()` reads: the stock's own bars (RS's stock leg +
trend_context), the NIFTY 500 benchmark (RS's benchmark leg + market_regime), India VIX,
and the breadth universe.
"""
from __future__ import annotations

import pandas as pd
import pytest

from research.charting import regime
from research.charting.tests import synth

_SAFE_START = "2019-01-02"


def _poison_after(bars: pd.DataFrame, t_pos: int) -> pd.DataFrame:
    """Every row strictly after position `t_pos` becomes a deterministic adversarial
    extreme (alternating huge/tiny OHLCV) -- rows [0, t_pos] are left byte-identical.
    Copied locally (not imported) matching this repo's own convention of a per-test-file
    poison helper (test_early_lookahead.py, test_lookahead.py, test_patterns_lookahead.py,
    test_series.py each define their own rather than sharing one)."""
    poisoned = bars.copy()
    for i in range(t_pos + 1, len(bars)):
        if (i - t_pos) % 2 == 1:
            poisoned.loc[i, ["open", "high", "low", "close"]] = [9999.0, 9999.5, 9998.5, 9999.0]
            if "volume" in poisoned.columns:
                poisoned.loc[i, "volume"] = 9_999_999.0
        else:
            poisoned.loc[i, ["open", "high", "low", "close"]] = [0.02, 0.03, 0.01, 0.02]
            if "volume" in poisoned.columns:
                poisoned.loc[i, "volume"] = 1.0
    return poisoned


def _build_stock_and_bench(n: int = 260):
    stock_closes = [100 + 0.3 * i + (i % 7) * 0.4 for i in range(n)]
    bench_closes = [200 + 0.2 * i + (i % 5) * 0.3 for i in range(n)]
    stock = synth.bars_from_closes(stock_closes, start_date=_SAFE_START, wick=0.5)
    bench = synth.bars_from_closes(bench_closes, start_date=_SAFE_START, wick=0.5)
    return stock, bench


# ── Probe: features_at() unaffected by poisoning the STOCK bars after t ─────


def test_probe_stock_bars_poisoned_after_t_leaves_features_at_t_unchanged():
    stock, bench = _build_stock_and_bench()
    n = len(stock)
    checked = 0
    for t_pos in range(210, n - 1, 7):  # sweep several t values, always leaving room to poison
        t = stock["date"].iloc[t_pos]
        poisoned_stock = _poison_after(stock, t_pos)
        pd.testing.assert_frame_equal(
            poisoned_stock.iloc[: t_pos + 1].reset_index(drop=True), stock.iloc[: t_pos + 1].reset_index(drop=True)
        )

        rs_a = regime.relative_strength(stock, bench, t)
        rs_b = regime.relative_strength(poisoned_stock, bench, t)
        assert rs_a == rs_b, f"RS leak at t_pos={t_pos}"

        tc_a = regime.trend_context(stock, t)
        tc_b = regime.trend_context(poisoned_stock, t)
        assert tc_a == tc_b, f"trend_context leak at t_pos={t_pos}"
        checked += 1
    assert checked >= 5


# ── Probe: features_at() unaffected by poisoning the BENCHMARK after t ─────


def test_probe_benchmark_poisoned_after_t_leaves_features_at_t_unchanged():
    stock, bench = _build_stock_and_bench()
    n = len(bench)
    checked = 0
    for t_pos in range(210, n - 1, 7):
        t = bench["date"].iloc[t_pos]
        poisoned_bench = _poison_after(bench, t_pos)
        pd.testing.assert_frame_equal(
            poisoned_bench.iloc[: t_pos + 1].reset_index(drop=True), bench.iloc[: t_pos + 1].reset_index(drop=True)
        )

        rs_a = regime.relative_strength(stock, bench, t)
        rs_b = regime.relative_strength(stock, poisoned_bench, t)
        assert rs_a == rs_b, f"RS (benchmark leg) leak at t_pos={t_pos}"

        mr_a = regime.market_regime(bench, t)
        mr_b = regime.market_regime(poisoned_bench, t)
        assert mr_a == mr_b, f"market_regime leak at t_pos={t_pos}"
        checked += 1
    assert checked >= 5


# ── Probe: india_vix_at unaffected by poisoning VIX rows after t ───────────


def test_probe_vix_poisoned_after_t_leaves_india_vix_at_t_unchanged():
    closes = [12.0 + 0.05 * (i % 30) for i in range(120)]
    vix = synth.bars_from_closes(closes, start_date=_SAFE_START, wick=0.2)
    vix["source"] = "SYNTH"  # market_value_at (context.py) requires a `source` column
    n = len(vix)
    checked = 0
    for t_pos in range(20, n - 1, 11):
        t = vix["date"].iloc[t_pos]
        poisoned = _poison_after(vix, t_pos)
        a = regime.india_vix_at(t, vix)
        b = regime.india_vix_at(t, poisoned)
        assert a == b, f"VIX leak at t_pos={t_pos}"
        checked += 1
    assert checked >= 5


# ── Probe: breadth_at unaffected by poisoning breadth rows after t ─────────


def test_probe_breadth_poisoned_after_t_leaves_breadth_at_t_unchanged():
    n = 60
    dates = pd.bdate_range(start=_SAFE_START, periods=n)
    df = pd.DataFrame({
        "date": dates,
        "advancers": [1000 + i for i in range(n)],
        "decliners": [800 - (i % 5) for i in range(n)],
        "unchanged": [20] * n,
        "advance_decline_ratio": [1.2 + 0.01 * i for i in range(n)],
        "pct_above_sma50": [50.0 + (i % 10) for i in range(n)],
        "pct_above_sma200": [45.0 + (i % 8) for i in range(n)],
        "new_52w_highs": [float(i % 4) for i in range(n)],
        "new_52w_lows": [float(i % 3) for i in range(n)],
        "names_contributing": [2000] * n,
    })

    def _poison_breadth_after(frame: pd.DataFrame, t_pos: int) -> pd.DataFrame:
        poisoned = frame.copy()
        numeric_cols = [c for c in frame.columns if c != "date"]
        for i in range(t_pos + 1, len(frame)):
            for c in numeric_cols:
                poisoned.loc[i, c] = 8_888_888.0
        return poisoned

    checked = 0
    for t_pos in range(10, n - 1, 7):
        t = df["date"].iloc[t_pos]
        poisoned = _poison_breadth_after(df, t_pos)
        a = regime.breadth_at(t, df)
        b = regime.breadth_at(t, poisoned)
        assert a == b, f"breadth leak at t_pos={t_pos}"
        checked += 1
    assert checked >= 5


# ── Negative controls: deliberately peeking helpers the SAME comparisons must catch ──


def _peeking_stock_return(stock: pd.DataFrame, t_pos: int, look_ahead: int) -> float:
    """NEGATIVE CONTROL ONLY -- deliberately PIT-broken: reads a close STRICTLY AFTER
    `t_pos` (`t_pos + look_ahead`) instead of `t_pos` itself. Never used by real code."""
    base = float(stock["close"].iloc[t_pos - 20])
    future_close = float(stock["close"].iloc[t_pos + look_ahead])
    return (future_close - base) / base


def test_probe_negative_control_peeking_return_is_caught_by_the_same_comparison():
    stock, bench = _build_stock_and_bench()
    t_pos = 230
    look_ahead = 3
    poisoned = _poison_after(stock, t_pos)
    pd.testing.assert_frame_equal(
        poisoned.iloc[: t_pos + 1].reset_index(drop=True), stock.iloc[: t_pos + 1].reset_index(drop=True)
    )

    # The peeking helper reads bar t_pos+look_ahead, which IS poisoned -> must differ:
    peek_a = _peeking_stock_return(stock, t_pos, look_ahead)
    peek_b = _peeking_stock_return(poisoned, t_pos, look_ahead)
    assert peek_a != peek_b, (
        "negative control failed to detect the leak -- a probe methodology that stays "
        "green against a broken (peeking) implementation proves nothing"
    )

    # The real implementation, same (base, poisoned, t), shows no such difference:
    t = stock["date"].iloc[t_pos]
    rs_a = regime.relative_strength(stock, bench, t, windows=(20,))
    rs_b = regime.relative_strength(poisoned, bench, t, windows=(20,))
    assert rs_a == rs_b


def _peeking_vix_value(vix: pd.DataFrame, t_pos: int, look_ahead: int) -> float:
    """NEGATIVE CONTROL ONLY -- reads VIX close at t_pos+look_ahead instead of t_pos."""
    return float(vix["close"].iloc[t_pos + look_ahead])


def test_probe_negative_control_peeking_vix_is_caught():
    closes = [12.0 + 0.05 * (i % 30) for i in range(60)]
    vix = synth.bars_from_closes(closes, start_date=_SAFE_START, wick=0.2)
    vix["source"] = "SYNTH"  # market_value_at (context.py) requires a `source` column
    t_pos = 40
    look_ahead = 2
    poisoned = _poison_after(vix, t_pos)

    peek_a = _peeking_vix_value(vix, t_pos, look_ahead)
    peek_b = _peeking_vix_value(poisoned, t_pos, look_ahead)
    assert peek_a != peek_b, "negative control failed to detect the leak"

    t = vix["date"].iloc[t_pos]
    real_a = regime.india_vix_at(t, vix)
    real_b = regime.india_vix_at(t, poisoned)
    assert real_a == real_b
