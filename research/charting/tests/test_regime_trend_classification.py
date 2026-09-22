"""37.1 Trend classification tests (docs/charting.md, "Amendment C -- Owner decision
baseline for validation", owner decision 2026-09-22) -- `regime.trend_classification()`.

Covers, per the task brief:
  - Hand-computed OLS slope on a small (mean=100) ramp fixture.
  - Every class boundary, exactly at 0.15 / 0.30 (slope_pct_per_day) and 20 / 25 (ADX) --
    tested against the pure `_classify_trend_label` helper directly (ADX's double Wilder
    recursion is not practically hand-computable to an exact pinned value over a large
    enough window to be meaningful -- see test_regime_trend.py's own note on the same
    point for `_adx_series`; the ADX *computation* itself is already cross-checked there).
  - A poisoned-future probe + a negative (peeking) control.
  - The sealed-input probe style of test_regime_sealed_inputs.py, adapted to this series.
"""
from __future__ import annotations

import math

import pandas as pd
import pytest

from research.charting import regime, research_window as rw, series
from research.charting.tests import synth

_SAFE_START = "2019-01-02"  # well before the sealed window


def _same(a, b) -> bool:
    return math.isclose(a, b, rel_tol=1e-9, abs_tol=1e-9)


# ── Hand-computed OLS slope (mean=100 ramp: slope_pct_per_day == b exactly) ─────────────


def _mean100_ramp(b: float, n: int = 20) -> list[float]:
    """closes[i] = a + b*i, i=0..n-1, with a chosen so mean(closes) == 100.0 exactly (mean
    of an arithmetic run is its midpoint: a + b*(n-1)/2). Since slope_pct_per_day =
    raw_slope / mean_close * 100 and raw_slope == b exactly for a perfect line, mean=100
    makes slope_pct_per_day == b directly -- a hand-checkable construction, not a
    re-derivation of the OLS formula itself (that is `geometry.ols_slope`'s own job,
    already exercised by geometry's own tests)."""
    a = 100.0 - b * (n - 1) / 2.0
    return [a + b * i for i in range(n)]


def test_slope_pct_per_day_hand_computed_on_mean100_ramp():
    closes = _mean100_ramp(0.15)
    assert sum(closes) / len(closes) == pytest.approx(100.0)
    bars = synth.bars_from_closes(closes, start_date=_SAFE_START, wick=0.1)
    t = bars["date"].iloc[-1]

    tc = regime.trend_classification(bars, t)

    assert tc["slope_pct_per_day"].status == "OK"
    assert tc["slope_pct_per_day"].value == pytest.approx(0.15, abs=1e-9)


def test_slope_pct_per_day_hand_computed_negative_ramp():
    closes = _mean100_ramp(-0.42)
    bars = synth.bars_from_closes(closes, start_date=_SAFE_START, wick=0.1)
    t = bars["date"].iloc[-1]

    tc = regime.trend_classification(bars, t)

    assert tc["slope_pct_per_day"].status == "OK"
    assert tc["slope_pct_per_day"].value == pytest.approx(-0.42, abs=1e-9)


def test_slope_and_class_are_self_consistent_with_the_pure_classifier():
    """End-to-end wiring check: whatever (slope, adx) `trend_classification` actually
    computes from real bars, feeding those SAME two numbers into `_classify_trend_label`
    directly must reproduce the same class -- proves the function calls the classifier
    correctly, distinct from the classifier's OWN boundary correctness (proven below with
    exact numbers)."""
    closes = _mean100_ramp(0.5, n=90)  # strong, unambiguous uptrend -- real ADX will be high
    bars = synth.bars_from_closes(closes, start_date=_SAFE_START, wick=0.3)
    t = bars["date"].iloc[-1]

    tc = regime.trend_classification(bars, t)
    assert tc["slope_pct_per_day"].status == "OK"
    assert tc["adx_14"].status == "OK"
    assert tc["class"].status == "OK"

    expected = regime._classify_trend_label(
        tc["slope_pct_per_day"].value, tc["adx_14"].value,
        slope_threshold_pct=regime.FEATURE_CONFIG["trend_class_slope_threshold_pct"],
        strong_slope_threshold_pct=regime.FEATURE_CONFIG["trend_class_strong_slope_threshold_pct"],
        adx_threshold=regime.FEATURE_CONFIG["trend_class_adx_threshold"],
        strong_adx_threshold=regime.FEATURE_CONFIG["trend_class_strong_adx_threshold"],
    )
    assert tc["class"].value == expected


def test_slope_zero_base_reason_when_mean_close_is_exactly_zero():
    """closes[i] = -9.5 + i, i=0..19 -- mean == 0.0 exactly (arithmetic-run midpoint), so
    slope_pct_per_day's division is undefined -> ZERO_BASE, never a fabricated number.
    Built directly (not via `synth.bars_from_closes`, which rejects non-positive
    open/close) since only a `close` column matters for this codepath."""
    dates = pd.bdate_range(_SAFE_START, periods=20)
    closes = [-9.5 + i for i in range(20)]
    assert sum(closes) == pytest.approx(0.0)
    df = pd.DataFrame({
        "date": dates,
        "open": closes, "high": [c + 1.0 for c in closes], "low": [c - 1.0 for c in closes],
        "close": closes, "volume": [100_000.0] * 20,
    })
    t = dates[-1]

    tc = regime.trend_classification(df, t)

    assert tc["slope_pct_per_day"].status == "UNAVAILABLE"
    assert tc["slope_pct_per_day"].reason == "ZERO_BASE"


# ── Class boundaries -- exact numbers against the pure `_classify_trend_label` ──────────


_SLOPE_THRESH = regime.FEATURE_CONFIG["trend_class_slope_threshold_pct"]  # 0.15
_STRONG_SLOPE_THRESH = regime.FEATURE_CONFIG["trend_class_strong_slope_threshold_pct"]  # 0.30
_ADX_THRESH = regime.FEATURE_CONFIG["trend_class_adx_threshold"]  # 20
_STRONG_ADX_THRESH = regime.FEATURE_CONFIG["trend_class_strong_adx_threshold"]  # 25


def _classify(slope: float, adx: float) -> str:
    return regime._classify_trend_label(
        slope, adx,
        slope_threshold_pct=_SLOPE_THRESH,
        strong_slope_threshold_pct=_STRONG_SLOPE_THRESH,
        adx_threshold=_ADX_THRESH,
        strong_adx_threshold=_STRONG_ADX_THRESH,
    )


@pytest.mark.parametrize(
    "slope, adx, expected",
    [
        # STRONG_BULL: both gates exactly met
        (0.30, 25.0, "STRONG_BULL"),
        (0.50, 30.0, "STRONG_BULL"),
        # just under the ADX-strong gate -> falls back to plain BULL (slope still qualifies)
        (0.30, 24.999999, "BULL"),
        # just under the slope-strong gate -> plain BULL
        (0.299999, 25.0, "BULL"),
        # BULL: both gates exactly met
        (0.15, 20.0, "BULL"),
        (0.20, 22.0, "BULL"),
        # just under the ADX gate -> SIDEWAYS (slope alone is not enough)
        (0.15, 19.999999, "SIDEWAYS"),
        # just under the slope gate -> SIDEWAYS
        (0.149999, 20.0, "SIDEWAYS"),
        # STRONG_BEAR: mirror of STRONG_BULL
        (-0.30, 25.0, "STRONG_BEAR"),
        (-0.50, 30.0, "STRONG_BEAR"),
        (-0.30, 24.999999, "BEAR"),
        (-0.299999, 25.0, "BEAR"),
        # BEAR: mirror of BULL
        (-0.15, 20.0, "BEAR"),
        (-0.20, 22.0, "BEAR"),
        (-0.15, 19.999999, "SIDEWAYS"),
        (-0.149999, 20.0, "SIDEWAYS"),
        # SIDEWAYS: high ADX but flat slope, and high slope but low ADX
        (0.02, 50.0, "SIDEWAYS"),
        (0.80, 5.0, "SIDEWAYS"),
        (0.0, 0.0, "SIDEWAYS"),
    ],
)
def test_class_boundaries_exact(slope, adx, expected):
    assert _classify(slope, adx) == expected


# ── Sealed-window input probe (test_regime_sealed_inputs.py style) ──────────────────────


def _continuous_bars() -> pd.DataFrame:
    """Business-day bars from 2022-06 through 2025-08, crossing the sealed window (same
    construction as test_regime_sealed_inputs.py, kept local per this repo's own
    per-test-file convention)."""
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


_DATES = ("2024-09-30", "2024-12-31", "2025-06-30")


@pytest.mark.parametrize("t", _DATES)
def test_sealed_bars_never_reach_a_post_sealed_trend_class(t):
    """ADX is recursive (same leak risk `test_regime_sealed_inputs.py` documents for
    `trend_context`'s `adx_14`/`ema_20`): poisoning only the sealed-window bars must never
    move an OK post-sealed `trend_classification` field."""
    bars = _continuous_bars()
    poisoned = _poison(bars, bars["date"].between(rw.SEALED_GAP_START, rw.SEALED_GAP_END))
    clean, dirty = regime.trend_classification(bars, t), regime.trend_classification(poisoned, t)
    ok = [k for k, v in clean.items() if v.status == regime.STATUS_OK and isinstance(v.value, float)]
    assert "adx_14" in ok  # the recursive one is actually exercised
    moved = [k for k in ok if not _same(clean[k].value, dirty[k].value)]
    assert moved == []


@pytest.mark.parametrize("t", _DATES)
def test_pre_gap_index_rows_never_reach_a_post_sealed_trend_class(t):
    bars = _continuous_bars()
    index = bars[~bars["date"].between(rw.SEALED_GAP_START, rw.SEALED_GAP_END)].reset_index(drop=True)
    poisoned = _poison(index, index["date"] < rw.SEALED_GAP_START)
    clean, dirty = regime.trend_classification(index, t), regime.trend_classification(poisoned, t)
    moved = [k for k, v in clean.items() if v.status == regime.STATUS_OK and isinstance(v.value, float)
             and not _same(v.value, dirty[k].value)]
    assert moved == []


def test_negative_control_a_whole_frame_ema_does_carry_sealed_bars():
    """Same negative control as test_regime_sealed_inputs.py: proves the poison+compare
    methodology actually detects a leak when one exists, rather than trivially passing."""
    bars = _continuous_bars()
    poisoned = _poison(bars, bars["date"].between(rw.SEALED_GAP_START, rw.SEALED_GAP_END))
    pos = int(bars.index[bars["date"] == pd.Timestamp("2024-09-30")][0])
    assert not _same(series.ema(bars, 20).iloc[pos], series.ema(poisoned, 20).iloc[pos])


# ── Poisoned-future probe + peeking negative control ─────────────────────────────────────


def _poison_after(bars: pd.DataFrame, t_pos: int) -> pd.DataFrame:
    """Every row strictly after position `t_pos` becomes a deterministic adversarial
    extreme -- copied locally per this repo's own per-test-file poison-helper convention
    (test_regime_lookahead.py, test_early_lookahead.py, test_series.py each define their
    own)."""
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


def test_probe_bars_poisoned_after_t_leave_trend_class_at_t_unchanged():
    closes = [100 + 0.3 * i + (i % 7) * 0.4 for i in range(260)]
    stock = synth.bars_from_closes(closes, start_date=_SAFE_START, wick=0.5)
    n = len(stock)
    checked = 0
    for t_pos in range(210, n - 1, 7):
        t = stock["date"].iloc[t_pos]
        poisoned = _poison_after(stock, t_pos)
        pd.testing.assert_frame_equal(
            poisoned.iloc[: t_pos + 1].reset_index(drop=True), stock.iloc[: t_pos + 1].reset_index(drop=True)
        )
        a = regime.trend_classification(stock, t)
        b = regime.trend_classification(poisoned, t)
        assert a == b, f"trend_classification leak at t_pos={t_pos}"
        checked += 1
    assert checked >= 5


def _peeking_slope(stock: pd.DataFrame, t_pos: int, look_ahead: int, lookback: int = 20) -> float:
    """NEGATIVE CONTROL ONLY -- deliberately PIT-broken: computes the OLS slope over a
    window ending `look_ahead` bars AFTER `t_pos` instead of AT it. Never used by real code."""
    from research.charting import geometry
    end = t_pos + look_ahead
    window = stock["close"].iloc[end - lookback + 1 : end + 1].to_numpy(dtype=float)
    xs = list(range(lookback))
    return geometry.ols_slope(xs, window.tolist())


def test_probe_negative_control_peeking_slope_is_caught_by_the_same_comparison():
    closes = [100 + 0.3 * i + (i % 7) * 0.4 for i in range(260)]
    stock = synth.bars_from_closes(closes, start_date=_SAFE_START, wick=0.5)
    t_pos = 230
    look_ahead = 3
    poisoned = _poison_after(stock, t_pos)
    pd.testing.assert_frame_equal(
        poisoned.iloc[: t_pos + 1].reset_index(drop=True), stock.iloc[: t_pos + 1].reset_index(drop=True)
    )

    peek_a = _peeking_slope(stock, t_pos, look_ahead)
    peek_b = _peeking_slope(poisoned, t_pos, look_ahead)
    assert peek_a != peek_b, (
        "negative control failed to detect the leak -- a probe methodology that stays "
        "green against a broken (peeking) implementation proves nothing"
    )

    t = stock["date"].iloc[t_pos]
    real_a = regime.trend_classification(stock, t)
    real_b = regime.trend_classification(poisoned, t)
    assert real_a == real_b


# ── Insufficient history ──────────────────────────────────────────────────────────────


def test_insufficient_history_when_too_few_bars_exist_for_the_slope_window():
    closes = [100.0 + i for i in range(10)]  # far short of the 20-bar slope window
    bars = synth.bars_from_closes(closes, start_date=_SAFE_START, wick=0.1)
    t = bars["date"].iloc[-1]

    tc = regime.trend_classification(bars, t)

    assert tc["slope_pct_per_day"].status == "UNAVAILABLE"
    assert tc["slope_pct_per_day"].reason == "INSUFFICIENT_HISTORY"
    assert tc["class"].status == "UNAVAILABLE"
    assert tc["class"].value is None


# ── Generic on any bars-like frame (works for NIFTY 500 too, per 37.1) ──────────────────


def test_trend_classification_also_works_on_a_benchmark_shaped_frame():
    """37.1: "Applied to each stock and to NIFTY 500" -- `trend_classification` is generic
    on any bars-like frame, so calling it with a benchmark (index) frame must work exactly
    the same way as a stock frame; no separate benchmark-only code path exists."""
    closes = [100 + 0.4 * i + (i % 5) * 0.3 for i in range(90)]  # unambiguous uptrend, 90 bars (>= ADX warmup)
    bench = synth.bars_from_closes(closes, start_date=_SAFE_START, wick=0.3)
    t = bench["date"].iloc[-1]

    mc = regime.trend_classification(bench, t)
    assert mc["slope_pct_per_day"].status == "OK"
    assert mc["slope_pct_per_day"].value > 0  # rising ramp -> positive slope, whatever the exact number
    assert mc["adx_14"].status == "OK"
    assert mc["class"].status == "OK"


# ── features_at() integration -- both legs present under distinct field names ───────────


def test_features_at_surfaces_both_stock_and_market_trend_class_without_colliding_with_existing_fields():
    from pathlib import Path

    from research.charting import bars as bars_mod, context

    real_dir = Path(context.DEFAULT_INDEX_HISTORY_DIR)
    if not (real_dir / "NIFTY_500.csv").is_file():
        pytest.skip("real index_history CSVs not present")

    sym_bars = bars_mod.load_symbol("RELIANCE")
    flat = regime.features_at(sym_bars, "2022-12-30", symbol="RELIANCE")

    for key in ("trend_class_slope_pct_per_day", "trend_class_adx_14", "trend_class_class"):
        assert key in flat, key
        assert f"{key}_status" in flat
    for key in ("market_trend_class_slope_pct_per_day", "market_trend_class_adx_14", "market_trend_class_class"):
        assert key in flat, key
        assert f"{key}_status" in flat
    # distinct from trend_context's own trend_adx_14 / market_regime's regime_regime
    assert "trend_adx_14" in flat
    assert "regime_regime" in flat
