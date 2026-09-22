"""Point-in-time context features - PRD docs/charting.md section 35.2 ("Amendment A -- Pattern
Intelligence & Validation") adopting the owner's source PRD
`.claude/workspace/charting-pattern-engine/prd-pattern-intelligence-v1.md`:

  - N10 Trend Context Engine  -> `trend_context()`
  - N11 Relative Strength Engine -> `relative_strength()`
  - N12 Market Regime Engine  -> `market_regime()`
  - India VIX + universe breadth as context fields (35.2/35.3) -> `india_vix_at()`,
    `breadth_at()`

35.1 conflict resolutions that bind this module:
  - The market benchmark is NIFTY 500 (`CONFIG["market_benchmark"]`, unchanged from
    N11's "NIFTY 50" proposal -- resolved by the owner in 35.1). NIFTY 50 is not used
    here.
  - The frozen 30.1 ATR rules stand: `atr_period = 14` (`CONFIG["atr_period"]`), Wilder
    smoothing (`series.atr`).

Point-in-time rule (repo-wide, restated because every function below exists to enforce
it): a feature's value at date `t` may depend only on bars dated `<= t`, AND -- the rule
specific to this module -- a lookback window that would need any bar dated inside the
project-wide sealed out-of-sample block (`research.charting.research_window`,
2023-01-01..2024-07-31 inclusive) is `STATUS_UNAVAILABLE` / `REASON_SEALED_GAP`, even
when the underlying bars frame physically contains rows there (a single symbol's own
Kite history is typically continuous through the sealed window -- see bars.py -- unlike
the market/VIX/sector index CSVs under `research/index_history/data`, which are built
with no rows in that span at all, per `context.py`'s module docstring). Both cases are
covered by the SAME check here (`_window_check`): it compares CALENDAR dates, not row
presence, so it catches a window that reaches into the sealed block whether the
underlying source has rows there (stock bars) or not (index files) -- see that
function's docstring for the exact reasoning, including why a naive `series.sma()` /
`.rolling()` call on a concatenated pre+post-sealed index frame would otherwise
silently compute a number by skipping over the gap positionally.

Every "value" this module returns is wrapped in a `FeatureValue(value, status, reason,
detail)` -- 35.2's "status vocabulary": OK or UNAVAILABLE-with-a-reason, never a
silently-guessed number. `status`/`reason` intentionally reuse `context.py`'s narrower
`STATUS_OK`/`STATUS_UNAVAILABLE` vocabulary (this module computes DERIVED features from
raw context data, same relationship `context.py` has to `bars.py`/`series.py`) --
NOT the 15.3 POSITIVE/NEUTRAL/NEGATIVE/MIXED/UNAVAILABLE vocabulary, which belongs
to whichever module eventually maps these raw features onto that richer 5-way judgment
(out of scope here).

Definitions actually used (see each function's docstring for the full derivation, and
the module's final report for the NEEDS-OWNER-CONFIRMATION list):

  - Relative strength RS5/20/50/100 (N11): `StockReturn_nD - BenchmarkReturn_nD`, both
    SIMPLE (not log) returns over the trailing n TRADING sessions ending at t --
    `(close[t] - close[t-n]) / close[t-n]`. N11 does not state simple-vs-log; simple is
    chosen because it is this codebase's own existing convention for a "return over N
    bars" (`series.rate_of_change`, `calculator.py.pct_return` -- both
    `(close[t]-close[t-n])/close[t-n]`), reused here rather than re-derived, and it is
    the ONLY convention in this file (recorded, not silently invented).

  - Market regime BULL/BEAR/SIDEWAYS (N12): `close > SMA200 AND SMA200_slope > 0` ->
    BULL; `close < SMA200 AND SMA200_slope < 0` -> BEAR; otherwise SIDEWAYS -- N12's own
    "neither" wording is implemented literally as the logical complement, so no numeric
    "sideways band" is invented. The one genuinely unstated parameter is the SMA200
    SLOPE MEASUREMENT WINDOW (N12 says "slope > 0" but never says over how many bars);
    see `FEATURE_CONFIG["regime_slope_lookback_bars"]` -- NEEDS-OWNER-CONFIRMATION.

  - Trend context / 0-1-2 state (N10): SMA20/50/200, EMA20/50, ADX(14), ATR(14), and the
    per-period SMA slope are all raw metrics, always returned regardless of the state.
    N10's own worked example is BULLISH only ("Price > SMA50; SMA20 > SMA50; SMA50 >
    SMA200; SMA50 slope > 0"); BEARISH is implemented as that example's literal mirror
    image (every `>` flipped to `<`), NEUTRAL is everything else. This is the direct,
    symmetric reading of N10's own stated rule, not an independently invented
    threshold. The SMA slope window has the same NEEDS-OWNER-CONFIRMATION gap as
    regime's (`FEATURE_CONFIG["trend_slope_lookback_bars"]`) -- both are grounded, not
    guessed, in `backend/nidp/services/technical_indicator_engine/calculator.py.sma_slope`'s
    existing `lookback: int = 20` default, the only place "SMA slope" is already a
    defined, running convention anywhere in this codebase.

  - N10 also asks for "HH/HL structure, LH/LL structure". This module deliberately does
    NOT compute that: the task specification for this module enumerates N10's deliverable
    as "SMA20/50/200, EMA20/50, ADX(14), SMA slopes, and a 0/1/2 trend state" without
    HH/HL/LH/LL, and that swing-structure logic already exists (`research.charting.swings`,
    used by 13.1's Higher-High/Higher-Low pattern family) in a module this task is
    explicitly barred from touching (`patterns.py`) or duplicating. Scope decision, not a
    silent omission.

Point-in-time gap on the STOCK leg specifically: `bars.py`'s own module docstring records
that it does NOT sort or de-duplicate rows (real data has out-of-order / duplicate dates;
fixing them is `validate.py`'s job). Every bars-like frame this module receives is
therefore defensively sorted-by-date and de-duplicated (keep last) before use -- the same
defensive step `context.py.build_sector_index()` already takes for exactly this reason.
"""
from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

import numpy as np
import pandas as pd

from research.charting import series
from research.charting.config import CONFIG
from research.charting.context import (
    STATUS_OK as CTX_STATUS_OK,  # noqa: F401  (re-exported for convenience/parity)
    STATUS_UNAVAILABLE as CTX_STATUS_UNAVAILABLE,  # noqa: F401
    load_index_history,
    market_value_at,
)
from research.charting.research_window import (
    SEALED_GAP_END,
    SEALED_GAP_START,
    is_sealed_gap,
    overlaps_sealed_gap,
)

# -- Status / reason vocabulary (35.2) ---------------------------------------
# Deliberately the same two-value vocabulary as context.py (STATUS_OK / STATUS_UNAVAILABLE)
# -- this module computes DERIVED features from that raw layer, not the richer 15.3
# POSITIVE/NEUTRAL/NEGATIVE/MIXED/UNAVAILABLE judgment (out of scope here; see module
# docstring).

STATUS_OK = "OK"
STATUS_UNAVAILABLE = "UNAVAILABLE"

REASON_SEALED_GAP = "SEALED_GAP"
REASON_INSUFFICIENT_HISTORY = "INSUFFICIENT_HISTORY"
REASON_NO_DATA_FOR_DATE = "NO_DATA_FOR_DATE"
REASON_BEFORE_COVERAGE = "BEFORE_COVERAGE"
REASON_AFTER_COVERAGE = "AFTER_COVERAGE"
REASON_ZERO_BASE = "ZERO_BASE"
REASON_BLANK_IN_SOURCE = "BLANK_IN_SOURCE"  # breadth's blank-not-zero semantics


@dataclass(frozen=True)
class FeatureValue:
    """One feature's point-in-time result: a value (`None` unless `status == STATUS_OK`)
    plus the 35.2 status vocabulary. `reason` is populated only when UNAVAILABLE.
    `detail` is an optional free-text qualifier (e.g. which LEG of a two-sided feature
    like relative strength failed) -- never required to interpret status/reason alone."""

    value: Any = None
    status: str = STATUS_UNAVAILABLE
    reason: str | None = None
    detail: str | None = None

    def flatten(self, name: str) -> dict:
        out: dict = {name: self.value, f"{name}_status": self.status}
        if self.reason is not None:
            out[f"{name}_reason"] = self.reason
        if self.detail is not None:
            out[f"{name}_detail"] = self.detail
        return out


def _ok(value: Any) -> FeatureValue:
    return FeatureValue(value=value, status=STATUS_OK)


def _unavailable(reason: str, detail: str | None = None) -> FeatureValue:
    return FeatureValue(value=None, status=STATUS_UNAVAILABLE, reason=reason, detail=detail)


# -- FEATURE_CONFIG / versioning (35.2 "feature versions") ------------------
# A SEPARATE hashed config from research.charting.config.CONFIG (owner instruction: do
# not add keys to CONFIG -- that would change the detector config_hash and the served
# snapshot). Changing a value here changes feature_config_hash() and nothing else.

FEATURE_VERSION = "1.0.0"

FEATURE_CONFIG: dict = {
    # N11 relative strength
    "relative_strength_windows": [5, 20, 50, 100],
    # N11 does not say simple vs. log return; simple is this codebase's existing
    # convention for "return over N bars" (series.rate_of_change, calculator.pct_return)
    # -- recorded choice, see module docstring.
    "relative_strength_return_method": "simple",
    "market_benchmark": CONFIG["market_benchmark"],  # NIFTY 500, per 35.1 (read-only mirror)

    # N10 trend context
    "trend_sma_periods": [20, 50, 200],
    "trend_ema_periods": [20, 50],
    "trend_adx_period": 14,
    "trend_atr_period": CONFIG["atr_period"],  # 14, frozen 30.1 -- mirrored, not re-imported
    # NEEDS-OWNER-CONFIRMATION: N10's own example says "SMA50 slope > 0" but never states
    # the slope measurement window. Grounded in (not silently invented from) the only
    # existing "SMA slope" convention in this codebase:
    # backend/nidp/services/technical_indicator_engine/calculator.py.sma_slope(period,
    # lookback=20) -- its default is reused verbatim.
    "trend_slope_lookback_bars": 20,  # NEEDS-OWNER-CONFIRMATION

    # N12 market regime
    "regime_sma_period": 200,  # N12 states "SMA200" explicitly -- not a free parameter.
    # NEEDS-OWNER-CONFIRMATION: same gap as trend_slope_lookback_bars, same grounding.
    "regime_slope_lookback_bars": 20,  # NEEDS-OWNER-CONFIRMATION
    # NEEDS-OWNER-CONFIRMATION: N12 defines SIDEWAYS purely as the logical complement of
    # BULL/BEAR ("neither") -- no explicit numeric dead-band around SMA200 or around
    # slope==0 is stated anywhere in N12. This key is kept here, unused (None), so that
    # if an owner later approves a real band it is a config change covered by
    # feature_config_hash(), never a silent behavioural switch. See market_regime()'s
    # docstring.
    "regime_sideways_band": None,  # NEEDS-OWNER-CONFIRMATION (not implemented; see docstring)
}


def feature_config_hash(cfg: dict | None = None) -> str:
    """SHA-256 of the canonical JSON of a feature configuration (mirrors
    `research.charting.config.config_hash`, deliberately kept as a separate function
    over a separate dict -- see module docstring)."""
    payload = json.dumps(cfg if cfg is not None else FEATURE_CONFIG, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode()).hexdigest()


# -- Breadth universe source path (env-overridable, matches context.py's convention) --

ENV_BREADTH_UNIVERSE_PATH = "CHARTING_BREADTH_UNIVERSE_PATH"
DEFAULT_BREADTH_UNIVERSE_PATH = str(
    Path(__file__).resolve().parents[1] / "index_history" / "data" / "BREADTH_UNIVERSE.csv"
)

BREADTH_BLANK_CAPABLE_COLUMNS = (
    "advance_decline_ratio",
    "pct_above_sma50",
    "pct_above_sma200",
    "new_52w_highs",
    "new_52w_lows",
)
BREADTH_ALWAYS_PRESENT_COLUMNS = ("advancers", "decliners", "unchanged", "names_contributing")


def breadth_universe_path(path: str | Path | None = None) -> Path:
    if path is not None:
        return Path(path)
    return Path(os.environ.get(ENV_BREADTH_UNIVERSE_PATH, DEFAULT_BREADTH_UNIVERSE_PATH))


# -- Shared internal helpers --------------------------------------------------


def _prepare_frame(df: pd.DataFrame, date_col: str = "date") -> pd.DataFrame:
    """Defensively sort-by-date + de-duplicate (keep last), matching
    `context.py.build_sector_index()`'s handling of the same `bars.py` guarantee gap
    (bars.py preserves out-of-order/duplicate rows verbatim -- see module docstring).
    Never mutates the caller's frame."""
    out = df.copy()
    out[date_col] = pd.to_datetime(out[date_col]).dt.normalize()
    out = out.sort_values(date_col).drop_duplicates(subset=date_col, keep="last")
    return out.reset_index(drop=True)


@dataclass(frozen=True)
class _WindowCheck:
    status: str
    reason: str | None
    pos: int | None  # position of `ts` in the frame, only when status == STATUS_OK


def _window_check(dates: pd.Series, ts: pd.Timestamp, warmup_period: int) -> _WindowCheck:
    """Point-in-time + sealed-gap availability check shared by every windowed feature in
    this module (SMA/EMA/ADX/ATR/slope/relative-strength returns/regime SMA200).

    `dates` must be ascending, unique, 0-indexed (see `_prepare_frame`). `warmup_period`
    is "how many consecutive bars ending at (and including) `ts`" the feature needs --
    the exact same convention `series.py`'s INDICATORS registry already documents
    per-indicator as `warmup_period` (e.g. SMA(20) -> 20, ATR(14) -> 15).

    Two independent failure modes, both -> STATUS_UNAVAILABLE:
      1. Not enough bars exist before `ts` at all -> REASON_INSUFFICIENT_HISTORY.
      2. The window *does* have `warmup_period` bars, but the CALENDAR span from the
         window's start date to `ts` overlaps the sealed 2023-01-01..2024-07-31 block
         (`research_window.overlaps_sealed_gap`) -> REASON_SEALED_GAP.

    Case 2 is deliberately a CALENDAR check, not a row-presence check: it is what
    catches "the window's `warmup_period`-th bar back happens to land on the far side
    of the sealed gap" even when the underlying source has physical rows spanning the
    gap (a single stock's continuous Kite history) as well as when it does not (the
    index/VIX CSVs, which have no rows there at all -- there, a naive positional
    `.rolling()` would otherwise silently jump straight over the missing rows and
    compute a number, which is exactly the bug this function exists to prevent; see
    module docstring).
    """
    if is_sealed_gap(ts):
        return _WindowCheck(STATUS_UNAVAILABLE, REASON_SEALED_GAP, None)

    matches = dates.index[dates == ts]
    if len(matches) == 0:
        if dates.empty:
            return _WindowCheck(STATUS_UNAVAILABLE, REASON_NO_DATA_FOR_DATE, None)
        lo, hi = dates.iloc[0], dates.iloc[-1]
        if ts < lo:
            return _WindowCheck(STATUS_UNAVAILABLE, REASON_BEFORE_COVERAGE, None)
        if ts > hi:
            return _WindowCheck(STATUS_UNAVAILABLE, REASON_AFTER_COVERAGE, None)
        return _WindowCheck(STATUS_UNAVAILABLE, REASON_NO_DATA_FOR_DATE, None)

    pos = int(matches[0])
    start_pos = pos - (warmup_period - 1)
    if start_pos < 0:
        return _WindowCheck(STATUS_UNAVAILABLE, REASON_INSUFFICIENT_HISTORY, None)

    window_start_date = dates.iloc[start_pos]
    if overlaps_sealed_gap(window_start_date, ts):
        return _WindowCheck(STATUS_UNAVAILABLE, REASON_SEALED_GAP, None)

    return _WindowCheck(STATUS_OK, None, pos)


def _segment_of(frame: pd.DataFrame, ts: pd.Timestamp) -> tuple[pd.DataFrame, int | None]:
    """The rows of `frame` on the same side of the sealed window as `ts`, re-indexed from 0, and
    `ts`'s position in them. Every indicator series is computed on this segment only: EMA, ATR
    and ADX are recursive, so computing them over the whole frame lets sealed-window bars (a
    stock's continuous history) or pre-gap bars (the index files) reach a post-sealed value even
    when its `warmup_period` window passes `_window_check`. Rolling sums over the whole frame
    also carry floating-point residue from far-away rows. `_window_check` still runs on the full
    frame, so the UNAVAILABLE reasons (SEALED_GAP vs INSUFFICIENT_HISTORY) are unchanged."""
    if ts < SEALED_GAP_START:
        seg = frame[frame["date"] < SEALED_GAP_START]
    elif ts > SEALED_GAP_END:
        seg = frame[frame["date"] > SEALED_GAP_END]
    else:
        seg = frame.iloc[0:0]
    seg = seg.reset_index(drop=True)
    hit = seg.index[seg["date"] == ts]
    return seg, (int(hit[0]) if len(hit) else None)


def _simple_return(closes: pd.Series, pos: int, n: int) -> FeatureValue:
    base = float(closes.iloc[pos - n])
    if base == 0.0:
        return _unavailable(REASON_ZERO_BASE)
    latest = float(closes.iloc[pos])
    return _ok((latest - base) / base)


# -- N11 Relative Strength Engine ---------------------------------------------


def relative_strength(
    stock_bars: pd.DataFrame,
    benchmark_df: pd.DataFrame,
    t: Any,
    windows: Sequence[int] = tuple(FEATURE_CONFIG["relative_strength_windows"]),
) -> dict[str, FeatureValue]:
    """N11: `RS_n = StockReturn_nD - BenchmarkReturn_nD`, benchmark = NIFTY 500 (35.1).
    Returns `{"rs_5": FeatureValue, "rs_20": ..., ...}` for each `n` in `windows`.

    Both legs are simple returns over the trailing n TRADING sessions ending at `t`
    (`(close[t]-close[t-n])/close[t-n]`, matching `series.rate_of_change` /
    `calculator.pct_return`'s existing formula -- see module docstring for why simple,
    not log). Each leg independently point-in-time-checked via `_window_check`
    (`warmup_period = n + 1`: bar `t` and bar `t-n`); if EITHER leg is UNAVAILABLE the
    whole RS_n is UNAVAILABLE, with `detail` naming which leg(s) failed and `reason`
    taken from the failing leg (SEALED_GAP takes priority if either leg reports it, since
    that is the more fundamental research-integrity failure).
    """
    stock = _prepare_frame(stock_bars)
    bench = _prepare_frame(benchmark_df)
    ts = pd.Timestamp(t).normalize()

    out: dict[str, FeatureValue] = {}
    for n in windows:
        key = f"rs_{n}"
        stock_chk = _window_check(stock["date"], ts, n + 1)
        bench_chk = _window_check(bench["date"], ts, n + 1)

        failed_legs = []
        if stock_chk.status != STATUS_OK:
            failed_legs.append(("stock", stock_chk))
        if bench_chk.status != STATUS_OK:
            failed_legs.append(("benchmark", bench_chk))

        if failed_legs:
            reason = next((c.reason for _, c in failed_legs if c.reason == REASON_SEALED_GAP), failed_legs[0][1].reason)
            detail = "+".join(name for name, _ in failed_legs)
            out[key] = _unavailable(reason, detail=detail)
            continue

        stock_ret = _simple_return(stock["close"], stock_chk.pos, n)
        bench_ret = _simple_return(bench["close"], bench_chk.pos, n)
        if stock_ret.status != STATUS_OK or bench_ret.status != STATUS_OK:
            failed = [name for name, fv in (("stock", stock_ret), ("benchmark", bench_ret)) if fv.status != STATUS_OK]
            reason = stock_ret.reason if stock_ret.status != STATUS_OK else bench_ret.reason
            out[key] = _unavailable(reason, detail="+".join(failed))
            continue

        out[key] = _ok(stock_ret.value - bench_ret.value)

    return out


# -- ADX(14), Wilder -- not present in series.py (confirmed by inspection) ---


def _adx_series(bars: pd.DataFrame, period: int = 14) -> pd.Series:
    """Wilder's Average Directional Index, causal, same recursive-smoothing style as
    `series.atr` (reuses `series._wilder_smoothing` rather than re-deriving Wilder's
    recursion a second time -- N10 asks for ADX and it does not exist anywhere in
    `series.py` or its `calculator.py` parity oracle, confirmed by inspection before
    writing this).

    Standard method: +DM/-DM/TR from consecutive high/low/close, each Wilder-smoothed
    over `period`, +DI/-DI from the smoothed DM over smoothed TR (=ATR), DX =
    100*|+DI - -DI| / (+DI + -DI), and ADX itself is DX Wilder-smoothed a SECOND time
    (seeded from the simple mean of its own first `period` valid values, exactly
    `_wilder_smoothing`'s existing seeding rule, applied to the slice of `dx` where it
    is first fully defined -- the same "tail slice, then re-embed" technique
    `series.macd()` already uses for its signal-line EMA).

    First valid index (0-based, aligned to `bars`) is `2*period - 1` -> warmup_period =
    `2*period` (verified against a numerically independent implementation in
    `tests/test_regime_trend.py`).
    """
    for col in ("high", "low", "close"):
        if col not in bars.columns:
            raise ValueError(f"bars frame is missing required column: {col}")
    high = bars["high"].to_numpy(dtype=float)
    low = bars["low"].to_numpy(dtype=float)
    close = bars["close"].to_numpy(dtype=float)
    n = len(close)
    out = np.full(n, np.nan, dtype=float)
    if n < 2 * period + 1:
        return pd.Series(out, index=bars.index, name=f"adx_{period}")

    up_move = high[1:] - high[:-1]
    down_move = low[:-1] - low[1:]
    plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
    minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)

    h, l, c = high[1:], low[1:], close[:-1]
    tr = np.maximum(h - l, np.maximum(np.abs(h - c), np.abs(l - c)))

    atr_sm = series._wilder_smoothing(tr, period)
    plus_dm_sm = series._wilder_smoothing(plus_dm, period)
    minus_dm_sm = series._wilder_smoothing(minus_dm, period)

    with np.errstate(divide="ignore", invalid="ignore"):
        plus_di = 100.0 * plus_dm_sm / atr_sm
        minus_di = 100.0 * minus_dm_sm / atr_sm
        di_sum = plus_di + minus_di
        dx = 100.0 * np.abs(plus_di - minus_di) / di_sum
    dx = np.where(di_sum == 0.0, 0.0, dx)
    dx = np.where(np.isnan(plus_di) | np.isnan(minus_di), np.nan, dx)

    valid_start = period - 1  # first index (within the length-(n-1) dx array) that is not NaN
    dx_tail = dx[valid_start:]
    adx_tail = series._wilder_smoothing(dx_tail, period)
    adx_dm = np.full(len(dx), np.nan, dtype=float)
    adx_dm[valid_start:] = adx_tail

    out[1:] = adx_dm
    return pd.Series(out, index=bars.index, name=f"adx_{period}")


def _sma_slope(bars: pd.DataFrame, period: int, lookback: int) -> pd.Series:
    """Per-day SMA slope as %/day over `lookback` bars -- same formula as
    `backend/nidp/services/technical_indicator_engine/calculator.py.sma_slope`
    (`(end_sma - start_sma) / abs(start_sma) / lookback * 100`), vectorised over the
    whole frame instead of that function's single-scalar form. warmup_period =
    `period + lookback` (matches `calculator.sma_slope`'s own `len(arr) < period +
    lookback` gate)."""
    sma_series = series.sma(bars, period)
    start_sma = sma_series.shift(lookback)
    slope = ((sma_series - start_sma) / start_sma.abs() / lookback * 100.0).where(start_sma != 0)
    return slope.rename(f"sma_{period}_slope")


# -- N10 Trend Context Engine --------------------------------------------------


def trend_context(
    bars: pd.DataFrame,
    t: Any,
    *,
    sma_periods: Sequence[int] = tuple(FEATURE_CONFIG["trend_sma_periods"]),
    ema_periods: Sequence[int] = tuple(FEATURE_CONFIG["trend_ema_periods"]),
    adx_period: int = FEATURE_CONFIG["trend_adx_period"],
    atr_period: int = FEATURE_CONFIG["trend_atr_period"],
    slope_lookback: int = FEATURE_CONFIG["trend_slope_lookback_bars"],
) -> dict[str, FeatureValue]:
    """N10 Trend Context Engine for one symbol's own bars at date `t`.

    Raw metrics (`sma_20/50/200`, `ema_20/50`, `atr_14`, `adx_14`, `sma_20/50/200_slope`,
    `close`) are ALWAYS returned, each independently point-in-time-checked -- N10:
    "Raw metrics must always be retained even with a composite." `trend_state` is the
    single 0/1/2 composite (0=bearish, 1=neutral, 2=bullish) built ONLY from
    close/SMA20/SMA50/SMA200/SMA50-slope, per N10's own worked BULLISH example ("Price >
    SMA50; SMA20 > SMA50; SMA50 > SMA200; SMA50 slope > 0"); BEARISH is that example's
    literal mirror (every `>` flipped to `<`), NEUTRAL is everything else -- see module
    docstring for why this is a direct reading, not an invented threshold. `trend_state`
    is itself UNAVAILABLE (not defaulted to neutral) if any one of those five inputs is
    UNAVAILABLE.

    EMA's sealed-gap check treats EMA's lookback window as length=`period` (its
    warmup_period), the SAME simplification `series.py` and `calculator.py` already use
    to gate EMA's own NaN warmup -- not EMA's true infinite recursive memory back to bar
    0. This is an explicit, precedent-based design choice (see module docstring), not a
    silent one.

    N10 also lists "HH/HL structure, LH/LL structure" -- deliberately NOT computed here;
    see module docstring for the scope reasoning.
    """
    frame = _prepare_frame(bars)
    ts = pd.Timestamp(t).normalize()
    dates = frame["date"]
    seg, seg_pos = _segment_of(frame, ts)  # series are computed on t's side of the sealed window only

    out: dict[str, FeatureValue] = {}

    close_chk = _window_check(dates, ts, 1)
    if close_chk.status == STATUS_OK:
        out["close"] = _ok(float(frame["close"].iloc[close_chk.pos]))
    else:
        out["close"] = _unavailable(close_chk.reason)

    for period in sma_periods:
        chk = _window_check(dates, ts, period)
        key = f"sma_{period}"
        if chk.status == STATUS_OK:
            s = series.sma(seg, period)
            out[key] = _ok(float(s.iloc[seg_pos]))
        else:
            out[key] = _unavailable(chk.reason)

    for period in ema_periods:
        chk = _window_check(dates, ts, period)  # EMA warmup treated as `period` -- see docstring
        key = f"ema_{period}"
        if chk.status == STATUS_OK:
            e = series.ema(seg, period)
            out[key] = _ok(float(e.iloc[seg_pos]))
        else:
            out[key] = _unavailable(chk.reason)

    atr_chk = _window_check(dates, ts, atr_period + 1)
    if atr_chk.status == STATUS_OK:
        a = series.atr(seg, period=atr_period)
        out[f"atr_{atr_period}"] = _ok(float(a.iloc[seg_pos]))
    else:
        out[f"atr_{atr_period}"] = _unavailable(atr_chk.reason)

    adx_chk = _window_check(dates, ts, 2 * adx_period)
    if adx_chk.status == STATUS_OK:
        adx_s = _adx_series(seg, period=adx_period)
        out[f"adx_{adx_period}"] = _ok(float(adx_s.iloc[seg_pos]))
    else:
        out[f"adx_{adx_period}"] = _unavailable(adx_chk.reason)

    for period in sma_periods:
        chk = _window_check(dates, ts, period + slope_lookback)
        key = f"sma_{period}_slope"
        if chk.status == STATUS_OK:
            slope_s = _sma_slope(seg, period, slope_lookback)
            val = slope_s.iloc[seg_pos]
            out[key] = _ok(float(val)) if pd.notna(val) else _unavailable(REASON_ZERO_BASE)
        else:
            out[key] = _unavailable(chk.reason)

    # trend_state: 0/1/2, built only from close/sma20/sma50/sma200/sma50_slope (N10's
    # own worked example). UNAVAILABLE if any required input is UNAVAILABLE.
    required = [out.get("close"), out.get("sma_20"), out.get("sma_50"), out.get("sma_200"), out.get("sma_50_slope")]
    if any(r is None or r.status != STATUS_OK for r in required):
        first_bad = next(r for r in required if r is None or r.status != STATUS_OK)
        out["trend_state"] = _unavailable(first_bad.reason if first_bad is not None else REASON_NO_DATA_FOR_DATE)
    else:
        close_v = out["close"].value
        sma20_v = out["sma_20"].value
        sma50_v = out["sma_50"].value
        sma200_v = out["sma_200"].value
        slope50_v = out["sma_50_slope"].value
        bullish = close_v > sma50_v and sma20_v > sma50_v and sma50_v > sma200_v and slope50_v > 0
        bearish = close_v < sma50_v and sma20_v < sma50_v and sma50_v < sma200_v and slope50_v < 0
        state = 2 if bullish else (0 if bearish else 1)
        out["trend_state"] = _ok(state)

    return out


# -- N12 Market Regime Engine ---------------------------------------------------


def market_regime(
    benchmark_df: pd.DataFrame,
    t: Any,
    *,
    sma_period: int = FEATURE_CONFIG["regime_sma_period"],
    slope_lookback: int = FEATURE_CONFIG["regime_slope_lookback_bars"],
    atr_period: int = FEATURE_CONFIG["trend_atr_period"],
) -> dict[str, FeatureValue]:
    """N12 Market Regime Engine against the NIFTY 500 benchmark (35.1).

    `regime` is one of `"BULL"`/`"BEAR"`/`"SIDEWAYS"` (as a `FeatureValue.value`) or
    UNAVAILABLE:
      - BULL:     `close > SMA200 AND SMA200_slope > 0`
      - BEAR:     `close < SMA200 AND SMA200_slope < 0`
      - SIDEWAYS: neither -- N12's own word, implemented as the literal logical
        complement. No numeric "sideways band" is invented (see
        `FEATURE_CONFIG["regime_sideways_band"]` and the module docstring).

    The SMA200 slope MEASUREMENT WINDOW is the one parameter N12 never states --
    `FEATURE_CONFIG["regime_slope_lookback_bars"]`, NEEDS-OWNER-CONFIRMATION (grounded in
    `calculator.py.sma_slope`'s existing default, not invented from nothing; see module
    docstring).

    Also returns N12's "where available" context metrics as raw fields (never gating
    the regime label itself): `close`, `sma_200`, `sma_200_slope`, `nifty_atr_14`.
    HIGH_VOLATILITY/LOW_VOLATILITY (N12's "eventually") are explicitly deferred --
    not implemented.
    """
    frame = _prepare_frame(benchmark_df)
    ts = pd.Timestamp(t).normalize()
    dates = frame["date"]
    seg, seg_pos = _segment_of(frame, ts)  # series are computed on t's side of the sealed window only

    out: dict[str, FeatureValue] = {}

    close_chk = _window_check(dates, ts, 1)
    out["close"] = _ok(float(frame["close"].iloc[close_chk.pos])) if close_chk.status == STATUS_OK else _unavailable(close_chk.reason)

    sma_chk = _window_check(dates, ts, sma_period)
    if sma_chk.status == STATUS_OK:
        sma_s = series.sma(seg, sma_period)
        out[f"sma_{sma_period}"] = _ok(float(sma_s.iloc[seg_pos]))
    else:
        out[f"sma_{sma_period}"] = _unavailable(sma_chk.reason)

    slope_chk = _window_check(dates, ts, sma_period + slope_lookback)
    if slope_chk.status == STATUS_OK:
        slope_s = _sma_slope(seg, sma_period, slope_lookback)
        val = slope_s.iloc[seg_pos]
        out[f"sma_{sma_period}_slope"] = _ok(float(val)) if pd.notna(val) else _unavailable(REASON_ZERO_BASE)
    else:
        out[f"sma_{sma_period}_slope"] = _unavailable(slope_chk.reason)

    atr_chk = _window_check(dates, ts, atr_period + 1)
    if atr_chk.status == STATUS_OK and "high" in frame.columns and "low" in frame.columns:
        atr_s = series.atr(seg, period=atr_period)
        out[f"nifty_atr_{atr_period}"] = _ok(float(atr_s.iloc[seg_pos]))
    else:
        out[f"nifty_atr_{atr_period}"] = _unavailable(atr_chk.reason if atr_chk.status != STATUS_OK else REASON_NO_DATA_FOR_DATE)

    required = [out["close"], out.get(f"sma_{sma_period}"), out.get(f"sma_{sma_period}_slope")]
    if any(r.status != STATUS_OK for r in required):
        first_bad = next(r for r in required if r.status != STATUS_OK)
        out["regime"] = _unavailable(first_bad.reason)
    else:
        close_v = out["close"].value
        sma_v = out[f"sma_{sma_period}"].value
        slope_v = out[f"sma_{sma_period}_slope"].value
        if close_v > sma_v and slope_v > 0:
            out["regime"] = _ok("BULL")
        elif close_v < sma_v and slope_v < 0:
            out["regime"] = _ok("BEAR")
        else:
            out["regime"] = _ok("SIDEWAYS")

    return out


# -- India VIX (35.2/35.3 context field) --------------------------------------


def india_vix_at(t: Any, vix_df: pd.DataFrame | None = None) -> FeatureValue:
    """India VIX close at `t` -- a plain point lookup (no rolling window), reusing
    `context.market_value_at` directly (task instruction: "use ... market_value_at").
    `vix_df` defaults to `load_index_history("INDIA VIX")` when omitted; a caller doing
    many lookups should load once and pass it in."""
    if vix_df is None:
        vix_df = load_index_history("INDIA VIX")
    mc = market_value_at(t, vix_df)
    if mc.status == CTX_STATUS_OK:
        return _ok(mc.close)
    return _unavailable(mc.reason or REASON_NO_DATA_FOR_DATE)


# -- Universe breadth (35.2/35.3 context field) -------------------------------


def load_breadth_universe(path: str | Path | None = None) -> pd.DataFrame:
    """Load `BREADTH_UNIVERSE.csv` (already-computed daily breadth, see
    `research.index_history.breadth`): ascending, unique dates, blanks parsed as NaN by
    `pandas.read_csv` (never coerced to 0 -- "blank stays blank" per that module's own
    blank-not-zero design, reused here as-is, not re-derived)."""
    p = breadth_universe_path(path)
    df = pd.read_csv(p)
    df["date"] = pd.to_datetime(df["date"]).dt.normalize()
    df = df.sort_values("date").drop_duplicates(subset="date", keep="last").reset_index(drop=True)
    return df


def breadth_at(t: Any, breadth_df: pd.DataFrame | None = None) -> dict[str, FeatureValue]:
    """Universe breadth fields at `t` (advancers, decliners, unchanged,
    advance_decline_ratio, pct_above_sma50, pct_above_sma200, new_52w_highs,
    new_52w_lows, names_contributing), each an independent `FeatureValue`.

    A date with no row at all (sealed gap / before / after coverage) -> every field
    UNAVAILABLE with that shared reason. A date WITH a row but a blank source cell (the
    underlying `breadth.py` module's own "full-window-only" rule: e.g.
    `pct_above_sma200` before 200 names have a full trailing window) ->
    `REASON_BLANK_IN_SOURCE`, value `None` -- NEVER coerced to 0."""
    if breadth_df is None:
        breadth_df = load_breadth_universe()
    frame = breadth_df  # already prepared by load_breadth_universe; do not re-sort a caller's own frame assumptions
    ts = pd.Timestamp(t).normalize()

    columns = [c for c in frame.columns if c != "date"]
    chk = _window_check(frame["date"], ts, 1)
    if chk.status != STATUS_OK:
        return {c: _unavailable(chk.reason) for c in columns}

    row = frame.iloc[chk.pos]
    out: dict[str, FeatureValue] = {}
    for c in columns:
        v = row[c]
        if pd.isna(v):
            out[c] = _unavailable(REASON_BLANK_IN_SOURCE)
        else:
            out[c] = _ok(float(v) if c in BREADTH_BLANK_CAPABLE_COLUMNS else int(v))
    return out


# -- 35.2 convenience join: one flat dict per (symbol, t) --------------------


def features_at(
    symbol_bars: pd.DataFrame,
    t: Any,
    *,
    symbol: str | None = None,
    benchmark_df: pd.DataFrame | None = None,
    vix_df: pd.DataFrame | None = None,
    breadth_df: pd.DataFrame | None = None,
) -> dict:
    """One flat dict of every feature this module computes for `symbol_bars` at date
    `t`, suitable for joining onto a pattern-event row (35.2's own phrasing) -- each
    feature contributes `{name, name_status, name_reason?, name_detail?}` (see
    `FeatureValue.flatten`), plus top-level versioning fields (35.2 "each signal
    carries ... strategy/feature versions, config hash").

    `benchmark_df`/`vix_df`/`breadth_df` default to loading fresh from the real source
    files when omitted (`load_index_history("NIFTY 500")` / `("INDIA VIX")` /
    `load_breadth_universe()`) -- a caller processing many (symbol, t) pairs should load
    each once and pass it in, exactly `context.py`'s own convention for `market_df`.
    """
    if benchmark_df is None:
        benchmark_df = load_index_history(FEATURE_CONFIG["market_benchmark"])
    if vix_df is None:
        vix_df = load_index_history("INDIA VIX")
    if breadth_df is None:
        breadth_df = load_breadth_universe()

    ts = pd.Timestamp(t).normalize()
    out: dict[str, Any] = {
        "symbol": symbol,
        "date": ts,
        "feature_version": FEATURE_VERSION,
        "feature_config_hash": feature_config_hash(),
        "data_cutoff_date": ts,
    }

    for key, fv in relative_strength(symbol_bars, benchmark_df, ts).items():
        out.update(fv.flatten(key))

    for key, fv in trend_context(symbol_bars, ts).items():
        out.update(fv.flatten(f"trend_{key}"))

    for key, fv in market_regime(benchmark_df, ts).items():
        out.update(fv.flatten(f"regime_{key}"))

    out.update(india_vix_at(ts, vix_df).flatten("india_vix_close"))

    for key, fv in breadth_at(ts, breadth_df).items():
        out.update(fv.flatten(f"breadth_{key}"))

    return out
