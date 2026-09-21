"""Indicator SERIES layer — PRD docs/charting.md §8 (framework), §8.7 (contract), §12.2/§12.4
(breakout buffer / volume confirmation), §34.4 (early price-only indicators).

`backend/nidp/services/technical_indicator_engine/calculator.py` computes each indicator as a
SCALAR for the latest bar only. Charts need the whole SERIES (one value per bar, aligned to the
input frame) so a line/band/oscillator can be drawn and so every other module in this engine
(pattern geometry, confirmation, §34 early scoring) can read "the value of indicator X at bar t"
for any t, not just the newest bar.

Point-in-time rule (repo-wide, restated here because it is the entire reason this module is
careful about *how* each series is computed): the value at bar t may depend only on
`bars[0..t]`. Every function below is built from pandas' trailing (never centered) rolling
windows, `.shift()`, and forward-only recursive smoothing loops — never from an index expression
that could go negative and wrap around to the tail of the array (the exact bug the B2 probe in
`tests/test_series.py` exists to catch; see `_broken_atr` there for a worked example of the bug
this module is deliberately built to avoid).

Every function takes a `bars` frame shaped like `config.BARS_COLUMNS` (date, open, high, low,
close, volume; ascending, unique dates — the frame's own invariant, not re-validated here; §9
OHLCV validation is a separate module's job) and returns a pandas Series/DataFrame aligned to
`bars.index`. A value is NaN for every bar until its warmup window is fully populated — this
module never emits a value computed from a partial window.

`calculator.py` is the parity ORACLE for tests (see `tests/test_series.py`), not a runtime
dependency: this file imports nothing from `backend/`, so the research engine stays
self-contained. `calculator.py`'s math is reproduced here, not re-derived, except where it
diverges from the PRD:

Known divergence — relative volume vs. `calculator.py`'s `volume_stats()`:
    PRD §12.4 defines "Relative Volume" as a plain ratio:
        relative_volume[t] = volume[t] / mean(volume[t-N .. t-1])
    `calculator.py.volume_stats()` instead returns `(avg_volume_20, vol_z20)` — a *z-score*
    (`(latest - mean) / std`), not the PRD ratio. The two are different statistics (the z-score
    also needs a standard deviation the PRD formula never asks for). This module implements the
    PRD-correct ratio as `relative_volume()` (the P0 indicator asked for in the plan) and
    separately exposes `volume_zscore()` purely so the parity test in `tests/test_series.py` can
    still verify this file reproduces `calculator.py`'s actual number — `volume_zscore` is a
    parity/testing convenience, not the indicator the PRD or the plan calls "relative volume".
    Both agree that the current bar is excluded from its own baseline (`calculator.py`'s
    `window = volumes[-period-1:-1]` already does this correctly — no divergence there).

ATR method: `calculator.py.atr()` uses Wilder's smoothing (seed = simple mean of the first
`period` true-range values, then `avg = (avg*(period-1) + tr[i]) / period` recursively) — not a
simple moving average of TR. `series.atr()` reproduces exactly this (see `_wilder_smoothing`).
"""
from __future__ import annotations

from typing import Sequence

import numpy as np
import pandas as pd

from .config import CONFIG

_CALC_VERSION = "1.0.0"


# ── internal helpers ────────────────────────────────────────────────────────

def _require_columns(bars: pd.DataFrame, cols: Sequence[str]) -> None:
    missing = [c for c in cols if c not in bars.columns]
    if missing:
        raise ValueError(f"bars frame is missing required column(s): {missing}")


def _wilder_smoothing(x: np.ndarray, period: int) -> np.ndarray:
    """Wilder's recursive smoothing of a 1-D array, causal, same length as `x`.

    out[period-1] = mean(x[0:period])                      (simple-average seed)
    out[i]        = (out[i-1] * (period-1) + x[i]) / period  for i >= period
    out[i]        = NaN                                      for i < period-1

    This is exactly `calculator.py`'s ATR/RSI smoothing loop, generalised so both can share it.
    The loop only ever reads `out[i-1]` and `x[i]` for `i >= period` (i.e. `i-1 >= period-1 >= 0`)
    — no negative indexing, so it cannot wrap.
    """
    m = len(x)
    out = np.full(m, np.nan, dtype=float)
    if m < period:
        return out
    seed = float(np.mean(x[:period]))
    out[period - 1] = seed
    avg = seed
    for i in range(period, m):
        avg = (avg * (period - 1) + x[i]) / period
        out[i] = avg
    return out


# ── P0: trend / momentum / volatility ───────────────────────────────────────

def sma(bars: pd.DataFrame, period: int, field: str = "close") -> pd.Series:
    """Simple moving average. warmup_period = period (matches `calculator.py.sma`)."""
    _require_columns(bars, (field,))
    s = bars[field].astype(float)
    return s.rolling(window=period, min_periods=period).mean().rename(f"sma_{period}")


def ema(bars: pd.DataFrame, period: int, field: str = "close") -> pd.Series:
    """Exponential moving average, `adjust=False` recursion (seed = first bar, alpha=2/(n+1)) —
    bit-for-bit the same recursion as `calculator.py._ema_series`. `calculator.py.ema()` also
    gates on `len(arr) >= period` before returning anything, so — even though the EMA recursion
    is technically already defined from bar 0 — the first `period-1` values are masked to NaN
    here to match that gate. warmup_period = period.
    """
    _require_columns(bars, (field,))
    s = bars[field].astype(float)
    raw = s.ewm(span=period, adjust=False).mean()
    warm = pd.Series(np.arange(len(s)) < period - 1, index=bars.index)
    return raw.mask(warm).rename(f"ema_{period}")


def rsi(bars: pd.DataFrame, period: int = 14) -> pd.Series:
    """Wilder RSI. warmup_period = period + 1 (matches `calculator.py.rsi`'s
    `len(closes) < period + 1` gate: the first bar has no prior close so TR/delta series is one
    bar shorter than `bars`, then Wilder smoothing needs `period` of those)."""
    _require_columns(bars, ("close",))
    close = bars["close"].to_numpy(dtype=float)
    n = len(close)
    out = np.full(n, np.nan, dtype=float)
    if n >= period + 1:
        deltas = np.diff(close)
        gains = np.where(deltas > 0, deltas, 0.0)
        losses = np.where(deltas < 0, -deltas, 0.0)
        avg_gain = _wilder_smoothing(gains, period)
        avg_loss = _wilder_smoothing(losses, period)
        with np.errstate(divide="ignore", invalid="ignore"):
            rs = avg_gain / avg_loss
            vals = 100.0 - 100.0 / (1.0 + rs)
        vals = np.where(avg_loss == 0.0, 100.0, vals)
        vals = np.where(np.isnan(avg_gain) | np.isnan(avg_loss), np.nan, vals)
        out[1:] = vals
    return pd.Series(out, index=bars.index, name="rsi")


def macd(
    bars: pd.DataFrame, fast: int = 12, slow: int = 26, signal: int = 9
) -> pd.DataFrame:
    """MACD line/signal/hist. Matches `calculator.py.macd`: the signal EMA is seeded from
    `macd_line[slow-1:]` (not from bar 0), and all three outputs are masked to NaN together until
    `slow + signal` bars exist — `calculator.py` only ever emits the trio together, never the
    macd line alone. warmup_period = slow + signal.
    """
    _require_columns(bars, ("close",))
    close = bars["close"].astype(float)
    n = len(close)

    ema_fast = close.ewm(span=fast, adjust=False).mean()
    ema_slow = close.ewm(span=slow, adjust=False).mean()
    macd_line = ema_fast - ema_slow

    sig_line = pd.Series(np.nan, index=bars.index, dtype=float)
    if n >= slow:
        tail = macd_line.iloc[slow - 1:]
        sig_line.iloc[slow - 1:] = tail.ewm(span=signal, adjust=False).mean().to_numpy()
    hist_line = macd_line - sig_line

    warm = pd.Series(np.arange(n) < (slow + signal - 1), index=bars.index)
    return pd.DataFrame(
        {
            "macd": macd_line.mask(warm),
            "signal": sig_line.mask(warm),
            "hist": hist_line.mask(warm),
        }
    )


def atr(bars: pd.DataFrame, period: int = CONFIG["atr_period"]) -> pd.Series:
    """Average True Range, Wilder's smoothing (see module docstring). warmup_period = period + 1
    (matches `calculator.py.atr`'s `len(closes) < period + 1` gate)."""
    _require_columns(bars, ("high", "low", "close"))
    high = bars["high"].to_numpy(dtype=float)
    low = bars["low"].to_numpy(dtype=float)
    close = bars["close"].to_numpy(dtype=float)
    n = len(close)
    out = np.full(n, np.nan, dtype=float)
    if n >= period + 1:
        h, l, c = high[1:], low[1:], close[:-1]
        tr = np.maximum(h - l, np.maximum(np.abs(h - c), np.abs(l - c)))
        out[1:] = _wilder_smoothing(tr, period)
    return pd.Series(out, index=bars.index, name="atr")


def bollinger(bars: pd.DataFrame, period: int = 20, n_std: float = 2.0) -> pd.DataFrame:
    """Bollinger mid/upper/lower + normalised band width `(upper-lower)/mid` + position within
    the band. Matches `calculator.py.bollinger`: both width and position are NaN when std==0 or
    mid==0 (a flat window). warmup_period = period."""
    _require_columns(bars, ("close",))
    close = bars["close"].astype(float)
    mid = close.rolling(window=period, min_periods=period).mean()
    std = close.rolling(window=period, min_periods=period).std(ddof=1)
    upper = mid + n_std * std
    lower = mid - n_std * std
    denom = upper - lower

    width = (upper - lower) / mid
    pos = ((close - lower) / denom).where(denom != 0, 0.5)

    invalid = (std == 0) | (mid == 0)
    width = width.mask(invalid)
    pos = pos.mask(invalid)

    return pd.DataFrame({"bb_mid": mid, "bb_upper": upper, "bb_lower": lower, "bb_width": width, "bb_pos": pos})


# ── P0: volume ───────────────────────────────────────────────────────────────

def avg_volume(bars: pd.DataFrame, n: int = CONFIG["volume_baseline_bars"]) -> pd.Series:
    """Mean volume of the PRIOR `n` completed bars (current bar excluded). Matches
    `calculator.py.volume_stats`'s `avg_volume_20` (same baseline window, no leniency for
    NaN volumes — this module's missing_data_policy is strict: any NaN volume inside the
    window makes the window's output NaN). warmup_period = n + 1 (bar 0 has no prior bar,
    then `n` more prior bars must exist)."""
    _require_columns(bars, ("volume",))
    vol = bars["volume"].astype(float)
    return vol.shift(1).rolling(window=n, min_periods=n).mean().rename(f"avg_volume_{n}")


def relative_volume(bars: pd.DataFrame, n: int = CONFIG["volume_baseline_bars"]) -> pd.Series:
    """PRD §12.4: `volume[t] / mean(volume[t-n .. t-1])` — the current bar is excluded from its
    own baseline. This is the PRD-correct "relative volume" (see module docstring for the
    divergence from `calculator.py`'s z-score). warmup_period = n + 1."""
    _require_columns(bars, ("volume",))
    vol = bars["volume"].astype(float)
    baseline = avg_volume(bars, n)
    rel = (vol / baseline).where(baseline != 0)
    return rel.rename(f"relative_volume_{n}")


def volume_zscore(bars: pd.DataFrame, n: int = CONFIG["volume_baseline_bars"]) -> pd.Series:
    """Parity helper reproducing `calculator.py.volume_stats`'s `vol_z20` exactly (z-score, NOT
    the PRD relative-volume ratio — see module docstring). `calculator.py` returns `0.0` (not
    NaN) when the baseline has zero variance but is otherwise fully populated; NaN only during
    true warmup. warmup_period = n + 1."""
    _require_columns(bars, ("volume",))
    vol = bars["volume"].astype(float)
    baseline = vol.shift(1).rolling(window=n, min_periods=n)
    mean = baseline.mean()
    std = baseline.std(ddof=1)
    z = (vol - mean) / std
    z = z.where(std > 0, 0.0)
    z = z.mask(mean.isna())
    return z.rename(f"volume_zscore_{n}")


# ── §34.4 early, price-only indicators ───────────────────────────────────────

def range_compression(
    bars: pd.DataFrame, short_period: int = 14, long_period: int = 90
) -> pd.DataFrame:
    """§34.4 "Range compression": how quiet the recent high-low range and ATR are relative to
    their OWN longer trailing history — a ratio < 1 means recent bars are quieter than the
    stock's own longer-run behaviour (compression); > 1 means expansion.

    range_ratio = mean(high-low, short_period) / mean(high-low, long_period)
    atr_ratio   = ATR(short_period) / ATR(long_period)

    Both are self-referential (no external volatility benchmark) and causal.
    warmup_period: range_ratio = long_period; atr_ratio = long_period + 1 (ATR's own +1).
    """
    _require_columns(bars, ("high", "low"))
    hl_range = bars["high"].astype(float) - bars["low"].astype(float)
    short_avg = hl_range.rolling(window=short_period, min_periods=short_period).mean()
    long_avg = hl_range.rolling(window=long_period, min_periods=long_period).mean()
    range_ratio = (short_avg / long_avg).where(long_avg != 0)

    atr_short = atr(bars, period=short_period)
    atr_long = atr(bars, period=long_period)
    atr_ratio = (atr_short / atr_long).where(atr_long != 0)

    return pd.DataFrame({"range_ratio": range_ratio, "atr_ratio": atr_ratio})


def bb_width_percentile(
    bars: pd.DataFrame, bb_period: int = 20, lookback: int = 126
) -> pd.Series:
    """§34.4 Bollinger Band Width percentile: where today's `bb_width` sits, in percentile terms
    (0-100), within its OWN trailing `lookback` bars of history (causal — the window is
    `[t-lookback+1, t]`, inclusive of t). 0 = the tightest band-width in that window (maximum
    compression); 100 = the widest. warmup_period = bb_period + lookback - 1 (bb_width itself is
    first valid at index bb_period-1, then the percentile window needs `lookback` consecutive
    valid bb_width values ending at t, so the first valid t is (bb_period-1) + (lookback-1))."""
    width = bollinger(bars, period=bb_period)["bb_width"]

    def _pct_rank(window: np.ndarray) -> float:
        current = window[-1]
        if np.isnan(current):
            return np.nan
        valid = window[~np.isnan(window)]
        if len(valid) <= 1:
            return 50.0
        rank = int(np.sum(valid <= current))
        return float(rank - 1) / (len(valid) - 1) * 100.0

    pct = width.rolling(window=lookback, min_periods=lookback).apply(_pct_rank, raw=True)
    return pct.rename(f"bb_width_pctile_{lookback}")


def rate_of_change(bars: pd.DataFrame, period: int = 10) -> pd.Series:
    """§34.4 rate of change: `(close[t] - close[t-period]) / close[t-period] * 100`. Same formula
    as `calculator.py.pct_return` (series form). warmup_period = period + 1."""
    _require_columns(bars, ("close",))
    close = bars["close"].astype(float)
    base = close.shift(period)
    roc = ((close - base) / base * 100.0).where(base != 0)
    return roc.rename(f"roc_{period}")


def momentum_slope(
    bars: pd.DataFrame,
    k: int = 5,
    rsi_period: int = 14,
    macd_fast: int = 12,
    macd_slow: int = 26,
    macd_signal: int = 9,
) -> pd.DataFrame:
    """§34.4 momentum slope: change in RSI and MACD histogram over the trailing `k` bars —
    `x[t] - x[t-k]`, both operands already-causal series, so the slope is causal too.
    warmup_period: rsi_slope = rsi_period + k + 1; macd_hist_slope = macd_slow + macd_signal + k.
    """
    rsi_series = rsi(bars, period=rsi_period)
    hist_series = macd(bars, fast=macd_fast, slow=macd_slow, signal=macd_signal)["hist"]
    return pd.DataFrame(
        {
            "rsi_slope": rsi_series - rsi_series.shift(k),
            "macd_hist_slope": hist_series - hist_series.shift(k),
        }
    )


# ── Indicator registry — PRD §8.7 contract ──────────────────────────────────
# warmup_period is an int for a single-output series, or a {output_field: int} dict when an
# indicator returns several columns with different warmup depths.

INDICATORS: dict = {
    "sma": {
        "indicator_id": "sma",
        "indicator_name": "Simple Moving Average",
        "parameters": {"period": "n (caller-specified, no fixed default)"},
        "input_fields": ("close",),
        "output_fields": ("sma",),
        "warmup_period": "n",
        "calculation_version": _CALC_VERSION,
        "point_in_time_validated": True,
        "missing_data_policy": "NaN until n consecutive non-null closes are available; any NaN close inside the window propagates to NaN.",
    },
    "ema": {
        "indicator_id": "ema",
        "indicator_name": "Exponential Moving Average",
        "parameters": {"period": "n (caller-specified, no fixed default)"},
        "input_fields": ("close",),
        "output_fields": ("ema",),
        "warmup_period": "n",
        "calculation_version": _CALC_VERSION,
        "point_in_time_validated": True,
        "missing_data_policy": "NaN for the first n-1 bars (matches calculator.py's gate); recursive thereafter, seeded on the first available close.",
    },
    "rsi": {
        "indicator_id": "rsi",
        "indicator_name": "Relative Strength Index (Wilder)",
        "parameters": {"period": 14},
        "input_fields": ("close",),
        "output_fields": ("rsi",),
        "warmup_period": 15,
        "calculation_version": _CALC_VERSION,
        "point_in_time_validated": True,
        "missing_data_policy": "NaN until period+1 consecutive closes are available (one bar consumed to form the first delta).",
    },
    "macd": {
        "indicator_id": "macd",
        "indicator_name": "MACD (12/26/9)",
        "parameters": {"fast": 12, "slow": 26, "signal": 9},
        "input_fields": ("close",),
        "output_fields": ("macd", "signal", "hist"),
        "warmup_period": 35,
        "calculation_version": _CALC_VERSION,
        "point_in_time_validated": True,
        "missing_data_policy": "All three outputs are NaN together until slow+signal bars exist (matches calculator.py: never emits the macd line alone).",
    },
    "atr": {
        "indicator_id": "atr",
        "indicator_name": "Average True Range (Wilder)",
        "parameters": {"period": CONFIG["atr_period"]},
        "input_fields": ("high", "low", "close"),
        "output_fields": ("atr",),
        "warmup_period": CONFIG["atr_period"] + 1,
        "calculation_version": _CALC_VERSION,
        "point_in_time_validated": True,
        "missing_data_policy": "NaN until period+1 consecutive bars are available (bar 0 has no prior close, so TR needs one bar of history before Wilder smoothing starts).",
    },
    "bollinger": {
        "indicator_id": "bollinger",
        "indicator_name": "Bollinger Bands + band width",
        "parameters": {"period": 20, "n_std": 2.0},
        "input_fields": ("close",),
        "output_fields": ("bb_mid", "bb_upper", "bb_lower", "bb_width", "bb_pos"),
        "warmup_period": 20,
        "calculation_version": _CALC_VERSION,
        "point_in_time_validated": True,
        "missing_data_policy": "NaN until period consecutive closes are available; also NaN (not divide-by-zero) whenever the window's std or mean is exactly zero.",
    },
    "avg_volume": {
        "indicator_id": "avg_volume",
        "indicator_name": "Average volume of the prior N completed bars",
        "parameters": {"n": CONFIG["volume_baseline_bars"]},
        "input_fields": ("volume",),
        "output_fields": ("avg_volume",),
        "warmup_period": CONFIG["volume_baseline_bars"] + 1,
        "calculation_version": _CALC_VERSION,
        "point_in_time_validated": True,
        "missing_data_policy": "NaN until n prior (non-current) bars are all non-null volume; the current bar is never part of its own baseline.",
    },
    "relative_volume": {
        "indicator_id": "relative_volume",
        "indicator_name": "Relative Volume (PRD §12.4)",
        "parameters": {"n": CONFIG["volume_baseline_bars"]},
        "input_fields": ("volume",),
        "output_fields": ("relative_volume",),
        "warmup_period": CONFIG["volume_baseline_bars"] + 1,
        "calculation_version": _CALC_VERSION,
        "point_in_time_validated": True,
        "missing_data_policy": "NaN until the n-bar prior baseline is fully populated and non-zero; current bar excluded from its own baseline (PRD §12.4).",
    },
    "volume_zscore": {
        "indicator_id": "volume_zscore",
        "indicator_name": "Volume z-score (calculator.py parity; NOT the PRD relative-volume ratio)",
        "parameters": {"n": CONFIG["volume_baseline_bars"]},
        "input_fields": ("volume",),
        "output_fields": ("volume_zscore",),
        "warmup_period": CONFIG["volume_baseline_bars"] + 1,
        "calculation_version": _CALC_VERSION,
        "point_in_time_validated": True,
        "missing_data_policy": "NaN until the n-bar prior baseline is fully populated; 0.0 (not NaN) when that baseline has zero variance, matching calculator.py.",
    },
    "range_compression": {
        "indicator_id": "range_compression",
        "indicator_name": "Range compression (§34.4)",
        "parameters": {"short_period": 14, "long_period": 90},
        "input_fields": ("high", "low", "close"),
        "output_fields": ("range_ratio", "atr_ratio"),
        "warmup_period": {"range_ratio": 90, "atr_ratio": 91},
        "calculation_version": _CALC_VERSION,
        "point_in_time_validated": True,
        "missing_data_policy": "NaN until both the short and long trailing windows are fully populated; ratio undefined (NaN) if the long-window denominator is zero.",
    },
    "bb_width_percentile": {
        "indicator_id": "bb_width_percentile",
        "indicator_name": "Bollinger Band Width percentile (§34.4)",
        "parameters": {"bb_period": 20, "lookback": 126},
        "input_fields": ("close",),
        "output_fields": ("bb_width_pctile",),
        "warmup_period": 145,
        "calculation_version": _CALC_VERSION,
        "point_in_time_validated": True,
        "missing_data_policy": "NaN until bb_period + lookback bars are available (bb_width itself must be warm for the full lookback window).",
    },
    "rate_of_change": {
        "indicator_id": "rate_of_change",
        "indicator_name": "Rate of Change (§34.4)",
        "parameters": {"period": 10},
        "input_fields": ("close",),
        "output_fields": ("roc",),
        "warmup_period": 11,
        "calculation_version": _CALC_VERSION,
        "point_in_time_validated": True,
        "missing_data_policy": "NaN until period+1 closes are available; NaN (not inf) if the base close is exactly zero.",
    },
    "momentum_slope": {
        "indicator_id": "momentum_slope",
        "indicator_name": "Momentum slope — change in RSI / MACD histogram over k bars (§34.4)",
        "parameters": {"k": 5, "rsi_period": 14, "macd_fast": 12, "macd_slow": 26, "macd_signal": 9},
        "input_fields": ("close",),
        "output_fields": ("rsi_slope", "macd_hist_slope"),
        "warmup_period": {"rsi_slope": 20, "macd_hist_slope": 40},
        "calculation_version": _CALC_VERSION,
        "point_in_time_validated": True,
        "missing_data_policy": "NaN until the underlying RSI/MACD series are themselves warm for k+1 additional bars.",
    },
}
