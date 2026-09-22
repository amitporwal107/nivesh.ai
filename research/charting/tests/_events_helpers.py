"""Shared, non-test helpers for `test_events_*.py` -- deliberately NOT named `test_*.py` so
pytest never collects it as a test module (matches how `synth.py` itself is a fixture builder,
not a test file, sitting in this same directory).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from research.charting.config import BARS_COLUMNS
from research.charting.tests import synth


def raw_bars(rows, start_date: str = "2021-01-04") -> pd.DataFrame:
    """Explicit-OHLC synthetic bars, one business day apart -- unlike `synth.bars_from_closes`
    (which derives high/low from a close path plus a fixed wick), every field is given here, so
    a gap/wick/ambiguity scenario for the §37.3 target/stop walk (`stops.py`) can be hand-crafted
    exactly. `rows`: (open, high, low, close, volume) tuples."""
    dates = pd.bdate_range(start=start_date, periods=len(rows))
    df = pd.DataFrame([(d, *r) for d, r in zip(dates, rows)], columns=list(BARS_COLUMNS))
    for c in ("open", "high", "low", "close", "volume"):
        df[c] = df[c].astype(float)
    return df


def shift_outside_sealed_window(bars: pd.DataFrame, years: int = 3) -> pd.DataFrame:
    """Shift every date back `years` years -- the same technique `test_replay.py`'s own
    `_shift_outside_sealed_window` uses: `synth.py`'s fixtures are anchored at 2024-01-02,
    which falls inside the project-wide sealed 2023-01-01..2024-07-31 block, and every
    research-evaluation path in this package (via `replay.replay`) now refuses to run over a
    window that overlaps it. Only the calendar dates move; OHLCV values are untouched."""
    shifted = bars.copy()
    shifted["date"] = shifted["date"] - pd.DateOffset(years=years)
    return shifted


def extend_with_closes(bars: pd.DataFrame, closes, *, volume: float = 100_000.0, wick: float = 0.30) -> pd.DataFrame:
    """Append len(closes) more bars after `bars`' own last date, one business day apart, using
    the SAME deterministic (open = prior close, high/low pad the body by `wick`) construction
    `synth.bars_from_closes` uses for its own frames -- so a fixture can be extended far enough
    forward to exercise every S35.2 horizon (up to 20 sessions past an entry bar) without
    inventing a new bar-construction convention."""
    last_date = pd.Timestamp(bars["date"].iloc[-1])
    last_close = float(bars["close"].iloc[-1])
    dates = pd.bdate_range(start=last_date + pd.tseries.offsets.BDay(1), periods=len(closes))
    rows = []
    prev_close = last_close
    for d, c in zip(dates, closes):
        c = float(c)
        o = prev_close
        hi = max(o, c) + wick
        lo = min(o, c) - wick
        rows.append((d, o, hi, lo, c, float(volume)))
        prev_close = c
    extra = pd.DataFrame(rows, columns=list(BARS_COLUMNS))
    return pd.concat([bars, extra], ignore_index=True)


def confirmed_rectangle_bearish_with_runway(*, tail_closes=None, tail_len: int = 30) -> pd.DataFrame:
    """RECT-1 + `synth.fixture_05b_gap_breakdown_control` (a first-ever gap below the
    breakdown level, no prior breakout attempt -- a clean, unambiguous BEARISH
    PRICE_CONFIRMED, per that fixture's own docstring/control purpose) + `tail_len` more bars
    drifting gently downward, shifted outside the sealed window -- the BEARISH counterpart of
    `confirmed_rectangle_with_runway`, used to test §37.4 (no stop/target trade or cost block
    for a bearish row)."""
    base = synth.fixture_05b_gap_breakdown_control(synth.rect1())
    if tail_closes is None:
        last_close = float(base["close"].iloc[-1])
        tail_closes = [last_close - 0.3 * i for i in range(1, tail_len + 1)]
    extended = extend_with_closes(base, tail_closes)
    return shift_outside_sealed_window(extended)


def confirmed_rectangle_with_runway(*, tail_closes=None, tail_len: int = 30) -> pd.DataFrame:
    """RECT-1 + fixture #2 (a clean, low-volume-but-still-confirming breakout -- avoids the
    retest/failure noise of fixture #4) + `tail_len` more bars drifting gently upward, shifted
    outside the sealed window. Gives every S35.2 horizon (1/3/5/10/20 sessions past the entry
    bar, itself one bar after the confirmation bar) real forward data to resolve against,
    which the bare 24-bar fixtures in `synth.py` do not (see test_events_extraction.py's own
    note on this)."""
    base = synth.fixture_02_low_volume_breakout(synth.rect1())
    if tail_closes is None:
        last_close = float(base["close"].iloc[-1])
        tail_closes = [last_close + 0.3 * i for i in range(1, tail_len + 1)]
    extended = extend_with_closes(base, tail_closes)
    return shift_outside_sealed_window(extended)


# ── SUPPORT_RESISTANCE confirmed fixture (same shape as test_patterns.py's own
#    `_sr_resistance_base_bars`, kept independent here rather than importing a test-private
#    helper from another test module) ─────────────────────────────────────────────────────

_SR_RESISTANCE_ROWS: tuple = (
    (100.0, 100.6, 99.4, 100.2, 100_000.0),
    (100.2, 100.8, 99.6, 100.4, 100_000.0),
    (100.4, 101.0, 99.8, 100.6, 100_000.0),
    (100.6, 103.0, 100.5, 102.8, 100_000.0),
    (102.8, 106.0, 102.7, 105.8, 100_000.0),
    (105.8, 110.2, 105.7, 109.8, 100_000.0),  # touch 1 (high=110.2)
    (109.8, 110.0, 104.0, 104.5, 100_000.0),
    (104.5, 104.8, 99.0, 99.5, 100_000.0),
    (99.5, 99.8, 95.0, 95.5, 100_000.0),
    (95.5, 98.0, 95.3, 97.8, 100_000.0),
    (97.8, 102.0, 97.7, 101.8, 100_000.0),
    (101.8, 110.1, 101.7, 109.7, 100_000.0),  # touch 2 (high=110.1)
    (109.7, 109.9, 104.0, 104.5, 100_000.0),
    (104.5, 104.8, 99.0, 99.5, 100_000.0),
    (99.5, 99.8, 95.0, 95.5, 100_000.0),
    (95.5, 98.0, 95.3, 97.8, 100_000.0),
    (97.8, 102.0, 97.7, 101.8, 100_000.0),
    (101.8, 110.15, 101.7, 109.75, 100_000.0),  # touch 3 (high=110.15)
    (109.75, 109.9, 104.0, 104.5, 100_000.0),
    (104.5, 104.8, 99.0, 99.5, 100_000.0),
    (99.5, 99.8, 95.0, 100.0, 100_000.0),
)


def _sr_resistance_base_bars() -> pd.DataFrame:
    dates = pd.bdate_range("2024-01-02", periods=len(_SR_RESISTANCE_ROWS))
    return pd.DataFrame([(d, *r) for d, r in zip(dates, _SR_RESISTANCE_ROWS)], columns=list(BARS_COLUMNS))


def confirmed_support_resistance_with_runway(*, tail_len: int = 30) -> pd.DataFrame:
    """The standalone RESISTANCE level `test_patterns.py`'s own SR fixtures use, extended with
    one clean confirming breakout bar and `tail_len` more bars drifting upward, shifted outside
    the sealed window."""
    base = _sr_resistance_base_bars()
    confirmed = extend_with_closes(base, [113.5], volume=150_000.0)  # closes well above the ~110.15 trigger
    last_close = float(confirmed["close"].iloc[-1])
    tail = [last_close + 0.3 * i for i in range(1, tail_len + 1)]
    extended = extend_with_closes(confirmed, tail)
    return shift_outside_sealed_window(extended)


# ── HH_HL confirmed fixture (same construction as test_patterns.py's own `_zigzag_bars`) ────


def _zigzag_bars(turns: list, bars_per_leg: int = 5, wick: float = 0.05) -> pd.DataFrame:
    closes: list = []
    for i in range(len(turns) - 1):
        seg = list(np.linspace(turns[i], turns[i + 1], bars_per_leg))[:-1]
        closes.extend(seg)
    closes.append(turns[-1])
    return synth.bars_from_closes(closes, wick=wick)


def confirmed_hh_hl_with_runway(*, tail_len: int = 30) -> pd.DataFrame:
    """A bullish HH/HL zigzag confirmed on close above the prior high (same turn sequence
    `test_patterns.py::test_hh_hl_bullish_continuation_confirms_on_close_above_prior_high`
    uses), extended with `tail_len` more bars drifting upward, shifted outside the sealed
    window."""
    base = _zigzag_bars([15.0, 8.0, 20.0, 9.0, 25.0, 12.0, 30.0, 16.0, 35.0, 20.0, 40.0])
    last_close = float(base["close"].iloc[-1])
    tail = [last_close + 0.3 * i for i in range(1, tail_len + 1)]
    extended = extend_with_closes(base, tail)
    return shift_outside_sealed_window(extended)
