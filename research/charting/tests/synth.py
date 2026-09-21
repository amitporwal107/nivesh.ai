"""Deterministic synthetic OHLCV fixture builders — test-plan.md Part A.

Every builder returns a `pandas.DataFrame` with `BARS_COLUMNS` (imported from
`research.charting.config`, never copied): one row per completed session, ascending
by date, unique dates, valid OHLC. No randomness anywhere in this module — the same
call must return byte-identical output every time, which is what makes the
look-ahead poison probes in `test_lookahead.py` (and every other package's reuse of
these fixtures) meaningful.

RECT-1 is the shared base fixture (test-plan "Shared fixture config" + "RECT-1 base
fixture"): symbol SYN1, support 100.0 / resistance 110.0, resistance touches
(confirmed swing highs) at fixture bars 3 and 9, support touches (confirmed swing
lows) at bars 6 and 12, >=70% of closes inside the zone, a 20-bar volume baseline of
exactly 100,000. `rect1()` prepends 5 warm-up bars (indices 0-4) before "fixture bar
1" (index 5) so that:
  - bar 3's pivot (index 7) has 3 real left-neighbour bars (swing_left_bars=3), and
  - the 20-bar volume baseline used by any bar-16 breakout fixture is fully covered
    by real data (indices 0-19), never padded or wrapped.
Everything appended by the `fixture_*` helpers below counts from that same "fixture
bar 16" onward (array index 20+).

ATR note: the test-plan states "ATR~=2.0 (range 5.0 ATR)" for RECT-1. Given the
fixture's OTHER exactly-stated properties -- support/resistance 10.0 points apart,
and touches at bars 3/6/9/12 (i.e. every leg is exactly `touch_min_separation_bars`
= 3 bars, the tightest spacing the config allows) -- a 14-period ATR of exactly 2.0
is not simultaneously achievable: covering a 10-point round trip in 3-bar legs
forces true ranges of roughly 3+ on the transition/touch bars themselves (touch bars
realistically carry a large rejection wick, which is itself part of what makes them
identifiable touches). The table below was tuned to bring Wilder ATR-14 as close to
2.0 as those constraints allow (~2.45); `test_synth.py` asserts it lands in a
documented tolerance band rather than pinning an unreachable exact value. This does
not affect any of the fixture-1..12 classifications below: every appended close
(111, 96, ...) clears the 100/110 boundaries with enough margin that the exact ATR
figure (2.0 vs ~2.45) never changes which side of a breakout/breakdown level it's on.
"""
from __future__ import annotations

from typing import Sequence

import pandas as pd

from research.charting.config import BARS_COLUMNS

# ── Shared constants (RECT-1) ───────────────────────────────────────────────

RECT1_SYMBOL = "SYN1"
RECT1_SUPPORT = 100.0
RECT1_RESISTANCE = 110.0
RECT1_ATR_APPROX = 2.0  # test-plan's nominal target; see module docstring
RECT1_BREAKOUT_LEVEL = 110.50  # test-plan reference: resistance + 0.25 * ATR(=2.0)
RECT1_BREAKDOWN_LEVEL = 99.50  # test-plan reference: support - 0.25 * ATR(=2.0)
RECT1_VOLUME_BASELINE = 100_000.0

# Fixture-bar-number -> 0-indexed array position, given the 5-bar warm-up prefix.
RECT1_WARMUP_BARS = 5
RECT1_PATTERN_LENGTH = 15  # fixture bars 1-15


def _fixture_bar_index(fixture_bar_number: int) -> int:
    """Array position of 1-indexed `fixture_bar_number` (e.g. 3 -> resistance touch)."""
    return RECT1_WARMUP_BARS + fixture_bar_number - 1


_START_DATE = "2024-01-02"  # arbitrary fixed anchor (a Tuesday); business days only


def _dates(n: int, start: str = _START_DATE) -> pd.DatetimeIndex:
    return pd.bdate_range(start=start, periods=n)


def _frame(rows: Sequence[tuple]) -> pd.DataFrame:
    """rows: (date, open, high, low, close, volume). Validates OHLC sanity (PRD §9.1)."""
    df = pd.DataFrame(list(rows), columns=list(BARS_COLUMNS))
    df["date"] = pd.to_datetime(df["date"])
    for c in ("open", "high", "low", "close", "volume"):
        df[c] = df[c].astype(float)
    _assert_ohlc_sane(df)
    if df["date"].duplicated().any():
        raise ValueError("synthetic fixture produced duplicate dates")
    if not df["date"].is_monotonic_increasing:
        raise ValueError("synthetic fixture produced out-of-order dates")
    return df.reset_index(drop=True)


def _assert_ohlc_sane(df: pd.DataFrame) -> None:
    body_hi = df[["open", "close"]].max(axis=1)
    body_lo = df[["open", "close"]].min(axis=1)
    bad = df[
        (df["high"] < body_hi)
        | (df["low"] > body_lo)
        | (df["high"] < df["low"])
        | (df["open"] <= 0)
        | (df["close"] <= 0)
        | (df["volume"] < 0)
    ]
    if len(bad):
        raise ValueError(f"synthetic fixture produced invalid OHLCV rows:\n{bad}")


def _next_business_dates(bars: pd.DataFrame, n: int) -> pd.DatetimeIndex:
    last = pd.Timestamp(bars["date"].iloc[-1])
    return pd.bdate_range(start=last + pd.tseries.offsets.BDay(1), periods=n)


def _append(bars: pd.DataFrame, ohlcv_rows: Sequence[tuple]) -> pd.DataFrame:
    """Append `ohlcv_rows` (open, high, low, close, volume) as new bars dated
    immediately after `bars`' last date. Never mutates `bars`; returns a new frame."""
    dates = _next_business_dates(bars, len(ohlcv_rows))
    new_rows = [(d, *r) for d, r in zip(dates, ohlcv_rows)]
    return pd.concat([bars, _frame(new_rows)], ignore_index=True)


# ── Generic builder ──────────────────────────────────────────────────────────


def bars_from_closes(
    closes: Sequence[float],
    *,
    start_date: str = _START_DATE,
    volume: float | Sequence[float] = 100_000.0,
    wick: float = 0.30,
) -> pd.DataFrame:
    """Derive a plausible OHLCV frame from a close path alone.

    Deterministic, no randomness: `open[i] = close[i-1]` (`close[0]` for the first
    bar, i.e. no opening gap on bar 0), `high`/`low` pad the open-close body by
    `wick` on each side. `volume` is either a single value applied to every bar or a
    sequence matching `len(closes)`. Useful for other packages' hand-built sequences
    (e.g. triangle/wedge slope fixtures) where only the close path matters.
    """
    closes = [float(c) for c in closes]
    n = len(closes)
    if n == 0:
        raise ValueError("closes must be non-empty")
    dates = _dates(n, start_date)
    vols = [float(volume)] * n if isinstance(volume, (int, float)) else [float(v) for v in volume]
    if len(vols) != n:
        raise ValueError("volume sequence length must match closes length")

    rows = []
    prev_close = closes[0]
    for i, c in enumerate(closes):
        o = prev_close if i > 0 else c
        hi = max(o, c) + wick
        lo = min(o, c) - wick
        rows.append((dates[i], o, hi, lo, c, vols[i]))
        prev_close = c
    return _frame(rows)


# ── RECT-1 base fixture ──────────────────────────────────────────────────────

# (open, high, low, close, volume) — index 0-4 warm-up, index 5-19 = fixture bar 1-15.
# Resistance touches (confirmed swing highs, left=right=3): index 7 (bar 3), index 13
# (bar 9). Support touches (confirmed swing lows): index 10 (bar 6), index 16 (bar 12).
_RECT1_ROWS: tuple[tuple[float, float, float, float, float], ...] = (
    (105.0, 105.6, 104.4, 105.2, 100_000.0),  # idx0  warm-up
    (105.2, 105.8, 104.6, 105.4, 100_000.0),  # idx1  warm-up
    (105.4, 106.0, 104.8, 105.6, 100_000.0),  # idx2  warm-up
    (105.6, 106.2, 105.0, 105.8, 100_000.0),  # idx3  warm-up
    (105.8, 106.4, 105.2, 106.0, 100_000.0),  # idx4  warm-up
    (106.0, 107.2, 105.8, 107.0, 100_000.0),  # idx5  bar1  approach
    (107.0, 109.2, 106.9, 109.0, 100_000.0),  # idx6  bar2  approach
    (109.0, 110.0, 108.6, 109.3, 100_000.0),  # idx7  bar3  RESISTANCE TOUCH (H=110)
    (109.3, 109.5, 106.8, 107.0, 100_000.0),  # idx8  bar4  pull back
    (107.0, 107.3, 103.3, 103.5, 100_000.0),  # idx9  bar5  drop toward support
    (103.5, 103.8, 100.0, 101.5, 100_000.0),  # idx10 bar6  SUPPORT TOUCH (L=100)
    (101.5, 104.0, 101.2, 103.8, 100_000.0),  # idx11 bar7  recover
    (103.8, 107.3, 103.6, 107.0, 100_000.0),  # idx12 bar8  approach again
    (107.0, 110.0, 106.8, 108.8, 100_000.0),  # idx13 bar9  RESISTANCE TOUCH (H=110)
    (108.8, 109.0, 106.3, 106.5, 100_000.0),  # idx14 bar10 pull back
    (106.5, 106.8, 102.8, 103.0, 100_000.0),  # idx15 bar11 drop toward support
    (103.0, 103.3, 100.0, 101.3, 100_000.0),  # idx16 bar12 SUPPORT TOUCH (L=100)
    (101.3, 103.8, 101.0, 103.5, 100_000.0),  # idx17 bar13 recover
    (103.5, 105.8, 103.3, 105.5, 100_000.0),  # idx18 bar14
    (105.5, 106.0, 104.0, 105.0, 100_000.0),  # idx19 bar15 settle mid-range
)


def rect1() -> pd.DataFrame:
    """RECT-1 base fixture — test-plan Part A. 20 bars total (5 warm-up + fixture
    bars 1-15). See module docstring for the ATR tolerance note."""
    rows = [(d, *ohlcv) for d, ohlcv in zip(_dates(len(_RECT1_ROWS)), _RECT1_ROWS)]
    return _frame(rows)


# ── Fixture-specific extensions (test-plan Part A #1-#5b, #8, #9, #12) ───────


def fixture_01_wick_only_breakout(bars: pd.DataFrame) -> pd.DataFrame:
    """#1 — RECT-1 + bar16 O108 H112 L107 C109.8: the wick pierces the breakout
    level but the close does not -> `BREAKOUT_ATTEMPT`, never `PRICE_CONFIRMED`."""
    return _append(bars, [(108.0, 112.0, 107.0, 109.8, 100_000.0)])


def fixture_02_low_volume_breakout(bars: pd.DataFrame) -> pd.DataFrame:
    """#2 — RECT-1 + bar16 C111, vol 90k (rel-vol 0.90 against the 100k baseline).
    O/H/L are this module's own plausible fill (only C and volume are test-plan
    fixed)."""
    return _append(bars, [(109.0, 111.2, 108.8, 111.0, 90_000.0)])


def fixture_03_close_back_inside(bars: pd.DataFrame) -> pd.DataFrame:
    """#3 — bar16 C111 (confirms) -> bar17 C105 (closes back inside the pattern)."""
    return _append(
        bars,
        [
            (109.0, 111.3, 108.8, 111.0, 120_000.0),  # bar16 breakout
            (111.0, 111.2, 104.5, 105.0, 100_000.0),  # bar17 closes back inside
        ],
    )


def fixture_04_false_retest(bars: pd.DataFrame) -> pd.DataFrame:
    """#4 — bar16 C111 -> bars17-18 retest ~109.8 -> bar19 C98 (hard failure)."""
    return _append(
        bars,
        [
            (109.0, 111.3, 108.8, 111.0, 120_000.0),  # bar16 breakout
            (111.0, 111.2, 109.6, 109.8, 100_000.0),  # bar17 retest
            (109.8, 110.2, 109.5, 109.8, 100_000.0),  # bar18 retest holds
            (109.8, 109.9, 98.0, 98.0, 100_000.0),  # bar19 fails hard
        ],
    )


def fixture_05_gap_through_invalidation(bars: pd.DataFrame) -> pd.DataFrame:
    """#5 (corrected, orchestrator C1) — bar16 C111 (bullish PRICE_CONFIRMED) then
    bar17 O97 C96, never trading 100-110 in between: gap-through invalidation."""
    return _append(
        bars,
        [
            (109.0, 111.3, 108.8, 111.0, 120_000.0),  # bar16 breakout, PRICE_CONFIRMED
            (97.0, 97.5, 95.5, 96.0, 150_000.0),  # bar17 gaps clean through the zone
        ],
    )


def fixture_05b_gap_breakdown_control(bars: pd.DataFrame) -> pd.DataFrame:
    """#5b (added, orchestrator C1) — RECT-1 + bar16 O97 C96, NO prior breakout: a
    first-ever gap below the breakdown level, never trading 100-110, is a valid
    bearish PRICE_CONFIRMED — a control proving GAP_FAILURE is not over-applied."""
    return _append(bars, [(97.0, 97.5, 95.5, 96.0, 150_000.0)])


def fixture_08_lookahead_swing() -> pd.DataFrame:
    """#8 — standalone (not built on RECT-1): rises to bar5 H=112, bars 6-8 lower.
    With swing_left_bars=swing_right_bars=3, bar5's swing high is only CONFIRMED
    once bar8 exists (confirmed_index = pivot_index + 3). See test_lookahead.py
    probe B1, which truncates this exact fixture at bar7 vs bar8."""
    rows = (
        (100.0, 101.0, 99.0, 100.5, 100_000.0),  # bar1
        (100.5, 103.0, 100.0, 102.5, 100_000.0),  # bar2
        (102.5, 106.0, 102.0, 105.5, 100_000.0),  # bar3
        (105.5, 109.0, 105.0, 108.5, 100_000.0),  # bar4
        (108.5, 112.0, 108.0, 111.0, 100_000.0),  # bar5 — swing-high candidate
        (111.0, 111.2, 107.0, 108.0, 100_000.0),  # bar6
        (108.0, 108.2, 104.0, 105.0, 100_000.0),  # bar7
        (105.0, 105.2, 101.0, 102.0, 100_000.0),  # bar8 — confirms bar5
    )
    dates = _dates(len(rows))
    return _frame([(d, *r) for d, r in zip(dates, rows)])


def fixture_09_future_volume_contamination(bars: pd.DataFrame) -> pd.DataFrame:
    """#9 — bar16 vol 150k (rel-vol 1.50 against the 100k baseline), then bar18's
    volume jumps to 5,000,000. The volume baseline for bar16 must be the prior 20
    COMPLETED bars only, so bar16's rel-vol stays exactly 1.50 regardless of what
    bar18 does two bars later (see test_lookahead.py)."""
    return _append(
        bars,
        [
            (109.0, 111.3, 108.8, 111.0, 150_000.0),  # bar16 rel-vol 1.50
            (111.0, 111.5, 110.5, 111.2, 100_000.0),  # bar17 normal filler
            (111.2, 112.0, 111.0, 111.8, 5_000_000.0),  # bar18 poisoned future volume
        ],
    )


def fixture_12_incomplete_candle(bars: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    """#12 — extends to a completed bar19, then returns bar20 SEPARATELY as a
    running/incomplete candle (running close 110.6) rather than as a row in the
    completed-bars frame: `BARS_COLUMNS`' own contract is "one row per completed
    daily session" (config.py), so an incomplete session is never a row in it.

    Returns (completed_bars, incomplete_bar) where `incomplete_bar` is a dict with
    BARS_COLUMNS' fields plus `is_complete: False`.
    """
    extended = _append(
        bars,
        [
            (109.0, 111.3, 108.8, 111.0, 120_000.0),  # bar16 breakout
            (111.0, 111.5, 110.3, 111.2, 100_000.0),  # bar17
            (111.2, 111.6, 110.5, 111.3, 100_000.0),  # bar18
            (111.3, 111.6, 110.6, 111.4, 100_000.0),  # bar19
        ],
    )
    running_date = _next_business_dates(extended, 1)[0]
    incomplete_bar = {
        "date": running_date,
        "open": 111.4,
        "high": 111.4,
        "low": 110.5,
        "close": 110.6,
        "volume": 45_000.0,
        "is_complete": False,
    }
    return extended, incomplete_bar
