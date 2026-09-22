"""N-section-11 Relative Strength Engine tests -- hand-computed RS_n on a tiny synthetic
(stock, benchmark) pair where every return is a plain fraction a human can check with a
calculator, plus the two-leg UNAVAILABLE-combination and insufficient-history cases.

Fixture dates start 2019-01-02 (see test_regime_trend.py for why: the module default
`2024-01-02` sits inside the sealed window).
"""
from __future__ import annotations

import pytest

from research.charting import regime
from research.charting.tests import synth

_SAFE_START = "2019-01-02"

# 11 bars each. stock rises by a flat +1 per bar; benchmark rises by a flat +1 or +2 per
# bar (irregular, so RS is not trivially zero).
_STOCK_CLOSES = [100.0, 101.0, 102.0, 103.0, 104.0, 105.0, 106.0, 107.0, 108.0, 109.0, 110.0]
_BENCH_CLOSES = [200.0, 202.0, 204.0, 205.0, 206.0, 207.0, 208.0, 209.0, 210.0, 211.0, 212.0]


def _fixtures():
    stock = synth.bars_from_closes(_STOCK_CLOSES, start_date=_SAFE_START, wick=0.1)
    bench = synth.bars_from_closes(_BENCH_CLOSES, start_date=_SAFE_START, wick=0.1)
    return stock, bench


def test_rs5_hand_computed():
    """Last bar (index 10, close=110): StockReturn5D = (110-105)/105 = 5/105.
    BenchmarkReturn5D = (212-207)/207 = 5/207 (bar index10-5=5, bench close=207).
    RS5 = 5/105 - 5/207.
    """
    stock, bench = _fixtures()
    t = stock["date"].iloc[-1]

    stock_ret5 = 5.0 / 105.0
    bench_ret5 = 5.0 / 207.0
    expected_rs5 = stock_ret5 - bench_ret5

    rs = regime.relative_strength(stock, bench, t, windows=(5,))
    assert rs["rs_5"].status == "OK"
    assert rs["rs_5"].value == pytest.approx(expected_rs5)


def test_rs2_hand_computed():
    """StockReturn2D = (110-108)/108 = 2/108. BenchmarkReturn2D = (212-210)/210 = 2/210.
    (bench close at index 8 = 210)."""
    stock, bench = _fixtures()
    t = stock["date"].iloc[-1]

    stock_ret2 = 2.0 / 108.0
    bench_ret2 = 2.0 / 210.0
    expected_rs2 = stock_ret2 - bench_ret2

    rs = regime.relative_strength(stock, bench, t, windows=(2,))
    assert rs["rs_2"].status == "OK"
    assert rs["rs_2"].value == pytest.approx(expected_rs2)


def test_rs_insufficient_history_on_a_short_fixture():
    """The 11-bar fixture has nowhere near the 101 bars RS100 needs (n+1)."""
    stock, bench = _fixtures()
    t = stock["date"].iloc[-1]
    rs = regime.relative_strength(stock, bench, t, windows=(100,))
    assert rs["rs_100"].status == "UNAVAILABLE"
    assert rs["rs_100"].reason == "INSUFFICIENT_HISTORY"


def test_rs_unavailable_when_only_benchmark_leg_is_short():
    """Stock has 30 bars (enough for RS20); benchmark covers the SAME date range (so
    `t` exists in both) but only its last 5 rows are kept -- enough to contain `t`, not
    enough prior history for RS20 -> RS20 UNAVAILABLE, detail names the benchmark leg
    specifically."""
    stock = synth.bars_from_closes([100.0 + i for i in range(30)], start_date=_SAFE_START, wick=0.1)
    bench_full = synth.bars_from_closes([200.0 + i for i in range(30)], start_date=_SAFE_START, wick=0.1)
    bench = bench_full.tail(5).reset_index(drop=True)
    t = stock["date"].iloc[-1]
    assert t in set(bench["date"])  # sanity: t is present, just short on prior history

    rs = regime.relative_strength(stock, bench, t, windows=(20,))
    assert rs["rs_20"].status == "UNAVAILABLE"
    assert rs["rs_20"].reason == "INSUFFICIENT_HISTORY"
    assert rs["rs_20"].detail == "benchmark"


def test_simple_return_zero_base_guard():
    """`_simple_return` (the internal helper both RS legs share) must not raise
    ZeroDivisionError / produce inf when the base close is exactly zero -- REASON_ZERO_BASE,
    UNAVAILABLE. Exercised directly on a plain Series rather than through
    `relative_strength()`/`bars_from_closes()`, because a real OHLCV bar can never have
    close<=0 (PRD section 9.1 -- `synth._assert_ohlc_sane` enforces this on every fixture in
    this repo, so a zero-close bar cannot be constructed as a valid bars frame at all;
    this guard exists for defensive completeness, not a reachable real-data case)."""
    import pandas as pd

    closes = pd.Series([0.0, 100.0, 110.0])
    fv = regime._simple_return(closes, pos=2, n=2)
    assert fv.status == "UNAVAILABLE"
    assert fv.reason == "ZERO_BASE"
