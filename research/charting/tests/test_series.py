"""Tests for research/charting/series.py.

Structure:
  A. parity      — last value of each series equals calculator.py's scalar, on synthetic data.
  B. warmup      — first warmup_period-1 values are NaN, exactly.
  C. probe B2    — poisoned-future point-in-time probe, plus its mandatory negative control.
  D. fixture #9  — relative-volume baseline excludes the current (and any future) bar.

calculator.py is imported as the parity ORACLE only (see module docstring in series.py for why
this is safe: technical_indicator_engine/__init__.py is empty, and its parent packages'
__init__.py files are docstring-only — verified below by the import actually succeeding with no
DB/network side effects).
"""
from __future__ import annotations

import importlib
import pathlib
import sys

import numpy as np
import pandas as pd
import pytest

from research.charting import series

# ── calculator.py: parity oracle, test-only import ──────────────────────────
# research/charting/tests/conftest.py already puts the repo ROOT on sys.path (parents[3] from
# this file). calculator.py is `from .accumulation import compute_accumulation` — a *relative*
# import — so it needs its real package path (nidp.services.technical_indicator_engine), which
# needs `backend/` on sys.path too. technical_indicator_engine/__init__.py is 0 bytes and its
# parents (nidp/__init__.py, nidp/services/__init__.py) are docstring-only with no DB/network
# calls, so a plain import is side-effect-free — confirmed empirically before writing this file.
_ROOT = pathlib.Path(__file__).resolve().parents[3]
_BACKEND = _ROOT / "backend"
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

calc = importlib.import_module("nidp.services.technical_indicator_engine.calculator")


# ── synthetic bars generator ─────────────────────────────────────────────────

def _make_synthetic_bars(n: int, seed: int, start_price: float = 100.0) -> pd.DataFrame:
    """Deterministic OHLCV frame. Each field is drawn from its OWN independently-seeded
    Generator (not one shared Generator drawing fields in sequence), so that
    `_make_synthetic_bars(n_big, seed).iloc[:n_small]` is byte-identical to
    `_make_synthetic_bars(n_small, seed)` — required for the poisoned-future probes, which
    compare a short run against a longer run sharing the same prefix.
    """
    daily_returns = np.random.default_rng(seed * 100 + 1).normal(0.0003, 0.02, size=n)
    open_gap = np.random.default_rng(seed * 100 + 2).normal(0.0, 0.004, size=n)
    hi_extra = np.abs(np.random.default_rng(seed * 100 + 3).normal(0.01, 0.004, size=n))
    lo_extra = np.abs(np.random.default_rng(seed * 100 + 4).normal(0.01, 0.004, size=n))
    volume = np.random.default_rng(seed * 100 + 5).lognormal(11.0, 0.4, size=n)

    close = start_price * np.cumprod(1.0 + daily_returns)
    open_ = close * (1.0 + open_gap)
    high = np.maximum(open_, close) * (1.0 + hi_extra)
    low = np.minimum(open_, close) * (1.0 - lo_extra)
    dates = pd.date_range("2020-01-01", periods=n, freq="B")

    return pd.DataFrame(
        {"date": dates, "open": open_, "high": high, "low": low, "close": close, "volume": volume}
    )


def _poison_future(bars: pd.DataFrame, t: int, n_extra: int = 20) -> pd.DataFrame:
    """bars[0..t] unchanged, followed by n_extra adversarial bars: a huge gap, wild swings and a
    10-50x volume spike — a fabricated breakout designed to move any indicator that peeks ahead.
    """
    prefix = bars.iloc[: t + 1].reset_index(drop=True)
    last_close = float(prefix["close"].iloc[-1])
    last_date = prefix["date"].iloc[-1]
    extra_dates = pd.bdate_range(last_date + pd.Timedelta(days=1), periods=n_extra)

    idx = np.arange(n_extra)
    extra_close = last_close * (1.6 + 0.4 * np.sin(idx))
    extra_open = extra_close * 0.97
    extra_high = np.maximum(extra_open, extra_close) * 1.08
    extra_low = np.minimum(extra_open, extra_close) * 0.92
    extra_volume = np.full(n_extra, 50_000_000.0)

    extra = pd.DataFrame(
        {
            "date": extra_dates,
            "open": extra_open,
            "high": extra_high,
            "low": extra_low,
            "close": extra_close,
            "volume": extra_volume,
        }
    )
    return pd.concat([prefix, extra], ignore_index=True)


# ── A. parity against calculator.py ─────────────────────────────────────────

_PARITY_LENGTHS = [40, 60, 100, 200]
_PARITY_SEEDS = [1, 2, 3]


@pytest.mark.parametrize("n", _PARITY_LENGTHS)
@pytest.mark.parametrize("seed", _PARITY_SEEDS)
def test_parity_sma(n, seed):
    bars = _make_synthetic_bars(n, seed)
    got = series.sma(bars, 20).iloc[-1]
    want = calc.sma(bars["close"].to_numpy(), 20)
    assert np.isclose(got, want, rtol=1e-9)


@pytest.mark.parametrize("n", _PARITY_LENGTHS)
@pytest.mark.parametrize("seed", _PARITY_SEEDS)
def test_parity_ema(n, seed):
    bars = _make_synthetic_bars(n, seed)
    got = series.ema(bars, 20).iloc[-1]
    want = calc.ema(bars["close"].to_numpy(), 20)
    assert np.isclose(got, want, rtol=1e-9)


@pytest.mark.parametrize("n", _PARITY_LENGTHS)
@pytest.mark.parametrize("seed", _PARITY_SEEDS)
def test_parity_rsi(n, seed):
    bars = _make_synthetic_bars(n, seed)
    got = series.rsi(bars, 14).iloc[-1]
    want = calc.rsi(bars["close"].to_numpy(), 14)
    assert np.isclose(got, want, rtol=1e-9)


@pytest.mark.parametrize("n", _PARITY_LENGTHS)
@pytest.mark.parametrize("seed", _PARITY_SEEDS)
def test_parity_macd(n, seed):
    bars = _make_synthetic_bars(n, seed)
    out = series.macd(bars)
    got_macd, got_sig, got_hist = out["macd"].iloc[-1], out["signal"].iloc[-1], out["hist"].iloc[-1]
    want_macd, want_sig, want_hist = calc.macd(bars["close"].to_numpy())
    assert np.isclose(got_macd, want_macd, rtol=1e-9)
    assert np.isclose(got_sig, want_sig, rtol=1e-9)
    assert np.isclose(got_hist, want_hist, rtol=1e-9)


@pytest.mark.parametrize("n", _PARITY_LENGTHS)
@pytest.mark.parametrize("seed", _PARITY_SEEDS)
def test_parity_atr(n, seed):
    bars = _make_synthetic_bars(n, seed)
    got = series.atr(bars, 14).iloc[-1]
    want = calc.atr(bars["high"].to_numpy(), bars["low"].to_numpy(), bars["close"].to_numpy(), 14)
    assert np.isclose(got, want, rtol=1e-9)


@pytest.mark.parametrize("n", _PARITY_LENGTHS)
@pytest.mark.parametrize("seed", _PARITY_SEEDS)
def test_parity_bollinger(n, seed):
    bars = _make_synthetic_bars(n, seed)
    out = series.bollinger(bars)
    got_width, got_pos = out["bb_width"].iloc[-1], out["bb_pos"].iloc[-1]
    want_width, want_pos = calc.bollinger(bars["close"].to_numpy())
    assert np.isclose(got_width, want_width, rtol=1e-9)
    assert np.isclose(got_pos, want_pos, rtol=1e-9)


@pytest.mark.parametrize("n", _PARITY_LENGTHS)
@pytest.mark.parametrize("seed", _PARITY_SEEDS)
def test_parity_volume_stats(n, seed):
    """calculator.py's volume_stats() returns (avg_volume_20, vol_z20) — a z-score, not the PRD
    §12.4 ratio (see series.py module docstring, 'Known divergence'). avg_volume matches exactly
    (same baseline window); vol_z is tested against series.volume_zscore(), the dedicated parity
    helper — NOT against series.relative_volume(), which implements the PRD-correct ratio and is
    tested against the PRD formula separately below (test_relative_volume_matches_prd_formula).
    """
    bars = _make_synthetic_bars(n, seed)
    got_avg = series.avg_volume(bars, 20).iloc[-1]
    got_z = series.volume_zscore(bars, 20).iloc[-1]
    want_avg, want_z = calc.volume_stats(bars["volume"].to_numpy(), 20)
    assert np.isclose(got_avg, want_avg, rtol=1e-9)
    assert np.isclose(got_z, want_z, rtol=1e-9)


def test_relative_volume_matches_prd_formula():
    """PRD §12.4: relative_volume[t] = volume[t] / mean(volume[t-N..t-1]) — verified against an
    independent, hand-written recomputation (not calculator.py, which does not implement this
    ratio at all — see 'Known divergence' in series.py)."""
    bars = _make_synthetic_bars(50, seed=11)
    n = 20
    got = series.relative_volume(bars, n)
    vol = bars["volume"].to_numpy()
    for t in range(n, len(bars)):
        expected = vol[t] / np.mean(vol[t - n : t])
        assert np.isclose(got.iloc[t], expected, rtol=1e-9), f"mismatch at t={t}"
    assert got.iloc[:n].isna().all()


# ── B. warmup: first warmup_period-1 values are NaN ─────────────────────────

def test_warmup_sma():
    bars = _make_synthetic_bars(60, seed=1)
    s = series.sma(bars, 20)
    assert s.iloc[:19].isna().all()
    assert s.iloc[19:].notna().all()


def test_warmup_ema():
    bars = _make_synthetic_bars(60, seed=1)
    s = series.ema(bars, 20)
    assert s.iloc[:19].isna().all()
    assert s.iloc[19:].notna().all()


def test_warmup_rsi():
    bars = _make_synthetic_bars(60, seed=1)
    s = series.rsi(bars, 14)
    assert s.iloc[:14].isna().all()
    assert s.iloc[14:].notna().all()


def test_warmup_atr():
    bars = _make_synthetic_bars(60, seed=1)
    s = series.atr(bars, 14)
    assert s.iloc[:14].isna().all()
    assert s.iloc[14:].notna().all()


def test_warmup_macd():
    bars = _make_synthetic_bars(80, seed=1)
    out = series.macd(bars)
    for col in ("macd", "signal", "hist"):
        assert out[col].iloc[:34].isna().all(), col
        assert out[col].iloc[34:].notna().all(), col


def test_warmup_bollinger():
    bars = _make_synthetic_bars(60, seed=1)
    out = series.bollinger(bars, period=20)
    for col in ("bb_mid", "bb_upper", "bb_lower", "bb_width", "bb_pos"):
        assert out[col].iloc[:19].isna().all(), col
        assert out[col].iloc[19:].notna().all(), col


def test_warmup_avg_volume_and_relative_volume():
    bars = _make_synthetic_bars(60, seed=1)
    for fn in (series.avg_volume, series.relative_volume, series.volume_zscore):
        s = fn(bars, 20)
        assert s.iloc[:20].isna().all(), fn.__name__
        assert s.iloc[20:].notna().all(), fn.__name__


def test_warmup_rate_of_change():
    bars = _make_synthetic_bars(40, seed=1)
    s = series.rate_of_change(bars, 10)
    assert s.iloc[:10].isna().all()
    assert s.iloc[10:].notna().all()


def test_warmup_range_compression():
    bars = _make_synthetic_bars(150, seed=1)
    out = series.range_compression(bars, short_period=14, long_period=90)
    assert out["range_ratio"].iloc[:89].isna().all()
    assert out["range_ratio"].iloc[89:].notna().all()
    assert out["atr_ratio"].iloc[:90].isna().all()
    assert out["atr_ratio"].iloc[90:].notna().all()


def test_warmup_bb_width_percentile():
    bars = _make_synthetic_bars(200, seed=1)
    s = series.bb_width_percentile(bars, bb_period=20, lookback=126)
    first_valid = s.first_valid_index()
    # warmup_period registered as 145 -> first 144 values NaN, index 144 the first valid one.
    assert s.iloc[:144].isna().all()
    assert s.iloc[144:].notna().all()
    assert first_valid == 144


def test_warmup_momentum_slope():
    bars = _make_synthetic_bars(120, seed=1)
    out = series.momentum_slope(bars, k=5, rsi_period=14, macd_fast=12, macd_slow=26, macd_signal=9)
    assert out["rsi_slope"].iloc[:19].isna().all()
    assert out["rsi_slope"].iloc[19:].notna().all()
    assert out["macd_hist_slope"].iloc[:39].isna().all()
    assert out["macd_hist_slope"].iloc[39:].notna().all()


def test_registry_warmup_periods_match_declared_contract():
    """Cross-check: the INDICATORS registry's declared warmup_period for every fixed-parameter
    (non-parametrized) entry matches the empirical NaN count above, one more time, driven off
    the registry itself rather than hardcoded numbers — so a future edit to series.py that
    silently changes warmup behaviour without updating the registry fails here."""
    bars = _make_synthetic_bars(220, seed=2)
    checks = {
        "rsi": (series.rsi(bars, 14), None),
        "atr": (series.atr(bars, series.CONFIG["atr_period"]), None),
        "bollinger": (series.bollinger(bars, period=20)["bb_width"], None),
        "avg_volume": (series.avg_volume(bars, series.CONFIG["volume_baseline_bars"]), None),
        "relative_volume": (series.relative_volume(bars, series.CONFIG["volume_baseline_bars"]), None),
        "rate_of_change": (series.rate_of_change(bars, 10), None),
    }
    for indicator_id, (s, _) in checks.items():
        warmup = series.INDICATORS[indicator_id]["warmup_period"]
        assert isinstance(warmup, int), indicator_id
        assert s.iloc[: warmup - 1].isna().all(), f"{indicator_id}: expected NaN through index {warmup - 2}"
        assert pd.notna(s.iloc[warmup - 1]), f"{indicator_id}: expected a value at index {warmup - 1}"

    macd_out = series.macd(bars)
    macd_warm = series.INDICATORS["macd"]["warmup_period"]
    assert macd_out["hist"].iloc[: macd_warm - 1].isna().all()
    assert pd.notna(macd_out["hist"].iloc[macd_warm - 1])

    rc = series.range_compression(bars, short_period=14, long_period=90)
    rc_warm = series.INDICATORS["range_compression"]["warmup_period"]
    assert rc["range_ratio"].iloc[: rc_warm["range_ratio"] - 1].isna().all()
    assert pd.notna(rc["range_ratio"].iloc[rc_warm["range_ratio"] - 1])
    assert rc["atr_ratio"].iloc[: rc_warm["atr_ratio"] - 1].isna().all()
    assert pd.notna(rc["atr_ratio"].iloc[rc_warm["atr_ratio"] - 1])

    ms = series.momentum_slope(bars)
    ms_warm = series.INDICATORS["momentum_slope"]["warmup_period"]
    assert ms["rsi_slope"].iloc[: ms_warm["rsi_slope"] - 1].isna().all()
    assert pd.notna(ms["rsi_slope"].iloc[ms_warm["rsi_slope"] - 1])
    assert ms["macd_hist_slope"].iloc[: ms_warm["macd_hist_slope"] - 1].isna().all()
    assert pd.notna(ms["macd_hist_slope"].iloc[ms_warm["macd_hist_slope"] - 1])

    bbp = series.bb_width_percentile(bars, bb_period=20, lookback=126)
    bbp_warm = series.INDICATORS["bb_width_percentile"]["warmup_period"]
    assert bbp.iloc[: bbp_warm - 1].isna().all()
    assert pd.notna(bbp.iloc[bbp_warm - 1])


# ── C. probe B2 — poisoned future ────────────────────────────────────────────

_B2_T_VALUES = [15, 25, 35, 45, 55, 65]


@pytest.mark.parametrize("t", _B2_T_VALUES)
def test_probe_b2_poisoned_future_does_not_change_past_values(t):
    """Run A: bars truncated at t. Run B: same bars[0..t], then 20 adversarial future bars.
    Every value dated <= t must be exactly identical between the two runs, for every P0/§34
    series function in this module."""
    bars = _make_synthetic_bars(90, seed=7)
    truncated = bars.iloc[: t + 1].reset_index(drop=True)
    poisoned = _poison_future(bars, t)

    pairs = [
        ("sma", series.sma(truncated, 20), series.sma(poisoned, 20).iloc[: t + 1]),
        ("ema", series.ema(truncated, 20), series.ema(poisoned, 20).iloc[: t + 1]),
        ("rsi", series.rsi(truncated, 14), series.rsi(poisoned, 14).iloc[: t + 1]),
        ("atr", series.atr(truncated, 14), series.atr(poisoned, 14).iloc[: t + 1]),
        (
            "avg_volume",
            series.avg_volume(truncated, 20),
            series.avg_volume(poisoned, 20).iloc[: t + 1],
        ),
        (
            "relative_volume",
            series.relative_volume(truncated, 20),
            series.relative_volume(poisoned, 20).iloc[: t + 1],
        ),
        (
            "volume_zscore",
            series.volume_zscore(truncated, 20),
            series.volume_zscore(poisoned, 20).iloc[: t + 1],
        ),
        (
            "macd_hist",
            series.macd(truncated)["hist"],
            series.macd(poisoned)["hist"].iloc[: t + 1],
        ),
        (
            "bb_width",
            series.bollinger(truncated)["bb_width"],
            series.bollinger(poisoned)["bb_width"].iloc[: t + 1],
        ),
        (
            "rate_of_change",
            series.rate_of_change(truncated, 10),
            series.rate_of_change(poisoned, 10).iloc[: t + 1],
        ),
        (
            "range_ratio",
            series.range_compression(truncated, short_period=5, long_period=20)["range_ratio"],
            series.range_compression(poisoned, short_period=5, long_period=20)["range_ratio"].iloc[: t + 1],
        ),
        (
            "bb_width_pctile",
            series.bb_width_percentile(truncated, bb_period=10, lookback=20),
            series.bb_width_percentile(poisoned, bb_period=10, lookback=20).iloc[: t + 1],
        ),
        (
            "momentum_slope_rsi",
            series.momentum_slope(truncated, k=3, rsi_period=5, macd_fast=3, macd_slow=6, macd_signal=3)["rsi_slope"],
            series.momentum_slope(poisoned, k=3, rsi_period=5, macd_fast=3, macd_slow=6, macd_signal=3)["rsi_slope"].iloc[: t + 1],
        ),
        (
            "momentum_slope_macd_hist",
            series.momentum_slope(truncated, k=3, rsi_period=5, macd_fast=3, macd_slow=6, macd_signal=3)["macd_hist_slope"],
            series.momentum_slope(poisoned, k=3, rsi_period=5, macd_fast=3, macd_slow=6, macd_signal=3)["macd_hist_slope"].iloc[: t + 1],
        ),
        (
            "atr_ratio",
            series.range_compression(truncated, short_period=5, long_period=20)["atr_ratio"],
            series.range_compression(poisoned, short_period=5, long_period=20)["atr_ratio"].iloc[: t + 1],
        ),
    ]
    for name, a, b in pairs:
        a = a.reset_index(drop=True)
        b = b.reset_index(drop=True)
        pd.testing.assert_series_equal(a, b, check_names=False, check_exact=True), name


# ── negative control (mandatory) ─────────────────────────────────────────────

def _broken_atr(bars: pd.DataFrame, period: int = 14) -> np.ndarray:
    """Deliberately broken ATR — negative control for probe B2, NOT used anywhere in series.py.

    Loops over every bar index without guarding `i >= period`, so `tr[i - period : i]` for
    `i < period` is a negative-start slice. When the array itself is shorter than `period`
    ('warmup crossing dataset start' — B2's own name for this case), that slice's translated
    start (`len(tr) + (i - period)`) can land BEFORE the stop index `i`, producing a non-empty
    slice that wraps around and grabs real elements from the TAIL of the (short) array — a
    classic point-in-time leak: it reads bars beyond the point-in-time cut for bar i, and its
    output for bar i changes the instant more history is appended (because appending bars pushes
    `len(tr)` past `period`, which makes the same slice for the same `i` become properly empty
    again). This is exactly the bug §B2 of the test plan names by pattern (`arr[i-14:i]`, i<14).
    """
    high = bars["high"].to_numpy(dtype=float)
    low = bars["low"].to_numpy(dtype=float)
    close = bars["close"].to_numpy(dtype=float)
    n = len(close)
    tr = np.zeros(n)
    for i in range(1, n):
        tr[i] = max(high[i] - low[i], abs(high[i] - close[i - 1]), abs(low[i] - close[i - 1]))
    out = np.full(n, np.nan)
    for i in range(n):
        window = tr[i - period : i]  # BUG: no `if i < period: continue` guard
        if len(window) > 0:
            out[i] = float(np.mean(window))
    return out


def test_negative_control_broken_atr_is_detected_by_the_b2_probe():
    """Mandatory negative control: the probe methodology itself must be able to catch a real
    look-ahead bug, or it proves nothing. `_broken_atr` only misbehaves while the WHOLE dataset
    is shorter than `period` (n < period) — that is the 'warmup crossing dataset start' regime
    B2 targets — so this control uses n=10 with period=14, not the 90-bar fixture above."""
    period = 14
    short = _make_synthetic_bars(n=10, seed=99)
    future = _make_synthetic_bars(n=10 + 25, seed=99)

    # Sanity: the two datasets really do share an identical prefix (required for the comparison
    # below to mean anything).
    pd.testing.assert_frame_equal(
        future.iloc[:10].reset_index(drop=True), short.reset_index(drop=True)
    )

    broken_short = _broken_atr(short, period=period)
    broken_extended = _broken_atr(future, period=period)[:10]

    assert not np.allclose(broken_short, broken_extended, equal_nan=True), (
        "negative control did not trigger: _broken_atr produced identical output before and "
        "after extending history, so it failed to demonstrate the wraparound bug — the B2 "
        "probe would have nothing to catch. Re-check the fixture length is still < period."
    )
    # And confirm at least one of the 'vulnerable' indices (0..period-2) is where it happened.
    diff_at = np.where(~np.isclose(broken_short[: period - 1], broken_extended[: period - 1], equal_nan=True))[0]
    assert len(diff_at) > 0, "expected the wraparound leak inside the i < period-1 range"

    # Positive control: the real, correct series.atr() is unaffected by the identical poison.
    real_short = series.atr(short, period=period).to_numpy()
    real_extended = series.atr(future, period=period).to_numpy()[:10]
    assert np.allclose(real_short, real_extended, equal_nan=True)


# ── D. fixture #9 — relative-volume baseline excludes the current bar ───────

def test_relative_volume_excludes_current_and_future_bars_fixture9():
    """calculator.py's own deliberate-failure fixture #9: mutating a LATER bar's volume must
    not change relative volume at an earlier bar t. Uses relative_volume() (the PRD ratio); also
    checks avg_volume() and volume_zscore() for the same property, since all three share the
    same baseline-window construction."""
    bars = _make_synthetic_bars(40, seed=3)
    t = 10
    n = 20

    mutated = bars.copy()
    mutated.loc[t + 2, "volume"] = 5_000_000.0  # contaminate a bar strictly after t

    for fn in (series.relative_volume, series.avg_volume, series.volume_zscore):
        before = fn(bars, n).iloc[t]
        after = fn(mutated, n).iloc[t]
        if pd.isna(before):
            assert pd.isna(after), fn.__name__
        else:
            assert before == after, fn.__name__

    # Not a vacuous test: the same mutation MUST move relative_volume computed AT bar t+2 itself
    # (proving the mutation is real and the baseline-exclusion property above isn't trivially
    # true because nothing changed at all).
    rel_before_at_mutated_bar = series.relative_volume(bars, n).iloc[t + 2]
    rel_after_at_mutated_bar = series.relative_volume(mutated, n).iloc[t + 2]
    assert rel_before_at_mutated_bar != rel_after_at_mutated_bar
