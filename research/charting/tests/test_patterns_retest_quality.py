"""§35.2 amendment additions -- docs/charting.md §35.2, source PRD N§8 (breakout candle
quality) and N§13 (retest quality), adopted as DESCRIPTIVE fields only (never confirmation
gates -- §35.1's conflict-resolution table: "The percentage distance is stored as a
descriptive field only" sets the same precedent this amendment follows).

Field definitions implemented (all computed from bars <= the event bar only):

  Breakout candle quality (N§8), on the PRICE_CONFIRMED event's own `observed_values`,
  computed from the CONFIRMING bar's OHLC:
    body_pct       = |close - open| / (high - low)
    close_location = (close - low) / (high - low)          # 0 = at the low, 1 = at the high
  A zero-range bar (`high == low`) makes both undefined -> None (never NaN/inf/a
  ZeroDivisionError -- see test_zero_range_candle_returns_none_not_nan_or_error below).

  Retest quality (N§13), one `retest_quality` dict on the pattern (`PatternSnapshot`),
  populated once the pattern reaches PRICE_CONFIRMED (None before that):
    attempts                     = count of distinct dips into the broken level's zone
                                    (transitions from out-of-zone to in-zone), counted only
                                    once the FIRST dip has legitimately opened a retest (i.e.
                                    piggybacked on `_walk_retest_and_failure`'s own
                                    `retest_pending` flag -- see that function's docstring)
    penetration_atr / _pct       = the DEEPEST intrabar penetration beyond the broken level
                                    seen during the retest episode (bullish: broken_level -
                                    low; bearish: high - broken_level), in ATR units and as a
                                    % of the broken level
    retest_relative_volume       = relative volume at the bar of that deepest penetration
    bars_confirmation_to_retest  = first zone-entry bar index - confirmation bar index
    bars_retest_to_continuation  = resolution bar index - first zone-entry bar index, ONLY
                                    when the retest actually resolved RETEST_SUCCESSFUL
                                    (None on failure or on an unresolved walk)
    note                         = set (fields None, attempts 0) when no pullback into the
                                    broken level was ever observed within retest_window_bars

This file hand-verifies each formula against fixtures whose OHLC (and therefore the exact
expected penetration/body/close-location numbers) are stated in each test's own comment.
ATR and relative-volume readings are pulled through the SAME `series.atr` /
`series.relative_volume` functions patterns.py itself uses (matching this package's existing
`_measured_atr_at` convention in test_patterns.py) -- this file is testing patterns.py's OWN
arithmetic that combines those readings with penetration/broken_level, not re-deriving
Wilder's ATR formula by hand.
"""
from __future__ import annotations

import json
import math

import numpy as np
import pandas as pd
import pytest

from research.charting.config import CONFIG
from research.charting.patterns import _candle_quality, detect_as_of
from research.charting.series import atr as atr_series_fn
from research.charting.series import relative_volume as relvol_series_fn
from research.charting.tests import synth

# ── Local fixture builders (this package's convention: small, self-contained per-file
# builders rather than growing synth.py's shared surface -- see test_patterns_lookahead.py's
# _zigzag_bars/_range_then_breakout_bars/_staircase_bars for precedent). ──────────────────


def _zigzag_bars(turns: list[float], bars_per_leg: int = 5, wick: float = 0.05) -> pd.DataFrame:
    closes: list[float] = []
    for i in range(len(turns) - 1):
        seg = list(np.linspace(turns[i], turns[i + 1], bars_per_leg))[:-1]
        closes.extend(seg)
    closes.append(turns[-1])
    return synth.bars_from_closes(closes, wick=wick)


def _sr_resistance_base_bars() -> pd.DataFrame:
    """Identical shape to test_patterns.py's helper of the same name (duplicated locally,
    per this package's convention): a standalone RESISTANCE level at ~110.1-110.2 with 3
    confirmed touches."""
    rows = [
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
    ]
    dates = pd.bdate_range("2024-01-02", periods=len(rows))
    return pd.DataFrame([(d, *r) for d, r in zip(dates, rows)], columns=list(synth.BARS_COLUMNS))


def _rectangle_multi_attempt_success_bars() -> pd.DataFrame:
    """RECT-1 + a breakout that gets retested TWICE (a shallow dip that pops back out, then a
    deeper dip) before finally succeeding -- exercises `attempts` > 1 and a real
    bars_retest_to_continuation."""
    return synth._append(
        synth.rect1(),
        [
            (109.0, 111.3, 108.8, 111.0, 120_000.0),  # bar16 idx20 breakout confirm
            (111.0, 111.2, 109.0, 109.5, 100_000.0),  # bar17 idx21 dip in -- attempt 1 (pen to low 109.0)
            (109.5, 110.3, 109.4, 110.2, 100_000.0),  # bar18 idx22 pops back out (close 110.2 > 110.0)
            (110.2, 110.4, 108.5, 109.7, 150_000.0),  # bar19 idx23 dips again -- attempt 2 (pen to low 108.5, deeper)
            (109.7, 113.5, 109.6, 113.0, 100_000.0),  # bar20 idx24 RETEST_SUCCESSFUL
        ],
    )


def _rect_snapshot(bars: pd.DataFrame, t: int | None = None) -> dict:
    if t is None:
        t = len(bars) - 1
    rects = [p for p in detect_as_of(bars, t, symbol="SYN1") if p.pattern_type == "RECTANGLE"]
    assert len(rects) == 1
    return rects[0].to_dict()


def _confirmed_event(d: dict) -> dict:
    matches = [e for e in d["events"] if e["event_type"] == "PRICE_CONFIRMED"]
    assert len(matches) == 1
    return matches[0]


# ── Breakout candle quality (N§8) -- direct unit tests on the helper ──────────────────────


def test_candle_quality_hand_computed_normal_bar():
    """O=109, H=111.3, L=108.8, C=111.0 (RECT-1 fixture bar16): range=2.5, body=|111-109|=2.0
    -> body_pct=0.8; close_location=(111-108.8)/2.5=2.2/2.5=0.88."""
    bars = synth._append(synth.rect1(), [(109.0, 111.3, 108.8, 111.0, 120_000.0)])
    idx = len(bars) - 1
    q = _candle_quality(bars, idx)
    assert q["body_pct"] == pytest.approx(0.8)
    assert q["close_location"] == pytest.approx(0.88)


def test_candle_quality_doji_zero_body_but_nonzero_range():
    """O=C=100 (a doji): body_pct must be exactly 0.0, not None -- only a ZERO-RANGE bar
    (high == low) is undefined, a zero-BODY bar is a perfectly ordinary computation."""
    bars = synth._append(synth.rect1(), [(100.0, 102.0, 98.0, 100.0, 100_000.0)])
    idx = len(bars) - 1
    q = _candle_quality(bars, idx)
    assert q["body_pct"] == pytest.approx(0.0)
    assert q["close_location"] == pytest.approx((100.0 - 98.0) / (102.0 - 98.0))


def test_zero_range_candle_returns_none_not_nan_or_error():
    """A flat/circuit-frozen bar (O=H=L=C) must return None for both fields -- never NaN, never
    a ZeroDivisionError."""
    bars = synth._append(synth.rect1(), [(111.0, 111.0, 111.0, 111.0, 120_000.0)])
    idx = len(bars) - 1
    q = _candle_quality(bars, idx)
    assert q == {"body_pct": None, "close_location": None}


def test_zero_range_breakout_bar_end_to_end_via_detect_as_of():
    """Same zero-range edge case, but through the REAL detector: a flat bar at 111.0 still
    closes above RECT-1's breakout level (~110.6-110.7) and legitimately confirms the
    breakout -- the PRICE_CONFIRMED event must record None/None, not crash or fabricate a
    value, and the pattern's status must still be PRICE_CONFIRMED (the new fields never gate
    anything)."""
    bars = synth._append(synth.rect1(), [(111.0, 111.0, 111.0, 111.0, 120_000.0)])
    d = _rect_snapshot(bars)
    assert d["status"] == "PRICE_CONFIRMED"
    confirmed = _confirmed_event(d)
    assert confirmed["observed_values"]["body_pct"] is None
    assert confirmed["observed_values"]["close_location"] is None


# ── Retest quality (N§13) -- no retest observed ────────────────────────────────────────────


def test_no_retest_fields_are_none_with_a_reason_not_nan_or_error():
    """fixture_03_close_back_inside: the pattern confirms then fails on the VERY NEXT bar
    without ever legitimately opening a retest (FALSE_BREAKOUT, not FAILED_RETEST -- see
    test_patterns.py's own fixture-03 test). `attempts` must be 0 and every other retest
    field None, with `note` explaining why -- never NaN, never absent by accident."""
    bars = synth.fixture_03_close_back_inside(synth.rect1())
    d = _rect_snapshot(bars)
    rq = d["retest_quality"]
    assert rq == {
        "attempts": 0, "penetration_atr": None, "penetration_pct": None,
        "retest_relative_volume": None, "bars_confirmation_to_retest": None,
        "bars_retest_to_continuation": None,
        "note": "no pullback into the broken level observed within retest_window_bars",
    }


def test_no_retest_yet_because_the_walk_has_not_had_time():
    """fixture_02_low_volume_breakout: the breakout confirms on the LAST available bar --
    there simply hasn't been time for a retest yet. Same shape as the false-breakout case
    (attempts=0, fields None, a note) -- distinguishing "won't" from "hasn't yet" is not
    claimed by this descriptive field set, only that nothing was fabricated."""
    bars = synth.fixture_02_low_volume_breakout(synth.rect1())
    d = _rect_snapshot(bars)
    assert d["status"] == "PRICE_CONFIRMED"
    assert d["retest_quality"]["attempts"] == 0
    assert d["retest_quality"]["note"] is not None


def test_pattern_never_confirmed_has_no_retest_quality_block_at_all():
    """fixture_01_wick_only_breakout: a wick-only touch never reaches PRICE_CONFIRMED at all
    -- retest is not yet applicable, so the pattern-level `retest_quality` is None (distinct
    from "confirmed but no retest happened yet", which is a dict with attempts=0)."""
    bars = synth.fixture_01_wick_only_breakout(synth.rect1())
    d = _rect_snapshot(bars)
    assert d["status"] == "BREAKOUT_ATTEMPT"
    assert d["retest_quality"] is None


# ── Retest quality (N§13) -- a real (failed) retest, hand-verified ────────────────────────


def test_failed_retest_quality_hand_computed():
    """fixture_04_false_retest: bar16 confirms (idx20, close 111.0 > breakout_level, broken
    resistance level = 110.0). bar17 (idx21) dips to low=109.6 -> RETEST_PENDING (attempt 1,
    penetration so far 110.0-109.6=0.4). bar18 (idx22) still closes inside the zone
    (109.8<=110.0, low=109.5) -> deepens the SAME attempt to 110.0-109.5=0.5 (not a second
    attempt: it never closed back out above 110.0 in between). bar19 (idx23) fails hard,
    close=98.0, low=98.0 -> deepens to the bar's own worst point 110.0-98.0=12.0, this is the
    walk's final (deepest) reading; FAILED_RETEST fires here so there is no continuation."""
    bars = synth.fixture_04_false_retest(synth.rect1())
    d = _rect_snapshot(bars)
    rq = d["retest_quality"]

    confirm_idx, first_entry_idx, deepest_idx = 20, 21, 23
    broken_level = 110.0
    deepest_pen = broken_level - 98.0  # = 12.0, bar19's own low

    a = atr_series_fn(bars, period=CONFIG["atr_period"])
    rv = relvol_series_fn(bars, n=CONFIG["volume_baseline_bars"])

    assert rq["attempts"] == 1
    assert rq["bars_confirmation_to_retest"] == first_entry_idx - confirm_idx == 1
    assert rq["bars_retest_to_continuation"] is None  # failed, never continued
    assert rq["penetration_pct"] == pytest.approx(deepest_pen / broken_level * 100.0)
    assert rq["penetration_atr"] == pytest.approx(deepest_pen / float(a.iloc[deepest_idx]))
    assert rq["retest_relative_volume"] == pytest.approx(float(rv.iloc[deepest_idx]))
    assert rq["note"] is None

    failed = [e for e in d["events"] if e["event_type"] == "FAILED"][0]
    assert failed["rule_id"] == "FAILED_RETEST"  # sanity: this really is the retest-failed path


# ── Retest quality (N§13) -- a successful retest with TWO attempts, hand-verified ─────────


def test_successful_retest_with_two_attempts_hand_computed():
    """See `_rectangle_multi_attempt_success_bars` for the OHLC. Attempt 1 opens at idx21
    (low 109.0, pen 1.0) and closes back OUTSIDE the zone at idx22 (close 110.2 > 110.0) --
    a genuine exit, so the next dip is a SECOND attempt. Attempt 2 opens at idx23 (low 108.5,
    pen 1.5 -- deeper, becomes the reported penetration) and resolves RETEST_SUCCESSFUL at
    idx24 (close 113.0)."""
    bars = _rectangle_multi_attempt_success_bars()
    d = _rect_snapshot(bars)
    rq = d["retest_quality"]

    confirm_idx, first_entry_idx, deepest_idx, resolve_idx = 20, 21, 23, 24
    broken_level = 110.0
    deepest_pen = broken_level - 108.5  # = 1.5, bar19/idx23's low -- deeper than attempt 1's 1.0

    a = atr_series_fn(bars, period=CONFIG["atr_period"])
    rv = relvol_series_fn(bars, n=CONFIG["volume_baseline_bars"])

    assert d["status"] == "PRICE_CONFIRMED"
    assert rq["attempts"] == 2
    assert rq["bars_confirmation_to_retest"] == first_entry_idx - confirm_idx == 1
    assert rq["bars_retest_to_continuation"] == resolve_idx - first_entry_idx == 3
    assert rq["penetration_pct"] == pytest.approx(deepest_pen / broken_level * 100.0)
    assert rq["penetration_atr"] == pytest.approx(deepest_pen / float(a.iloc[deepest_idx]))
    assert rq["retest_relative_volume"] == pytest.approx(float(rv.iloc[deepest_idx]))
    assert rq["note"] is None

    types = [e["event_type"] for e in d["events"]]
    assert types == ["PRICE_CONFIRMED", "RETEST_PENDING", "RETEST_SUCCESSFUL"]  # ONE RETEST_PENDING event even for 2 attempts


def test_attempt_count_is_not_simply_bars_spent_in_the_zone():
    """Guards against the naive-but-wrong implementation of `attempts` (counting every
    in-zone BAR rather than every DISTINCT dip): the multi-attempt fixture spends 3 bars
    total inside the zone (idx21, idx23, and idx23 is also the deepest bar of attempt 2 --
    idx22 is OUTSIDE the zone, breaking the run) but only 2 attempts."""
    bars = _rectangle_multi_attempt_success_bars()
    d = _rect_snapshot(bars)
    assert d["retest_quality"]["attempts"] == 2


# ── Retest quality (N§13) -- SUPPORT_RESISTANCE and HH_HL families ────────────────────────


def test_sr_level_successful_retest_quality_hand_computed():
    """test_patterns.py's own `test_sr_level_retest_after_confirmation_succeeds` fixture:
    level=110.15 (RESISTANCE). Confirm bar closes 113.5 (idx21). Retest dips to low=109.8
    (idx22) -> pen = 110.15-109.8 = 0.35. Resolves RETEST_SUCCESSFUL at idx23 (close 112.5)."""
    bars = synth._append(
        _sr_resistance_base_bars(),
        [
            (100.0, 114.0, 99.8, 113.5, 150_000.0),   # idx21 confirms
            (113.5, 113.6, 109.8, 110.0, 100_000.0),  # idx22 dip into the level (retest zone)
            (110.0, 113.0, 109.9, 112.5, 100_000.0),  # idx23 close back above -> RETEST_SUCCESSFUL
        ],
    )
    t = len(bars) - 1
    sr = [p for p in detect_as_of(bars, t, symbol="SYN2") if p.pattern_type == "SUPPORT_RESISTANCE" and p.direction == "BULLISH"]
    assert len(sr) == 1
    d = sr[0].to_dict()
    rq = d["retest_quality"]

    confirm_idx, first_entry_idx, resolve_idx = 21, 22, 23
    broken_level = 110.15
    deepest_pen = broken_level - 109.8  # = 0.35

    a = atr_series_fn(bars, period=CONFIG["atr_period"])
    rv = relvol_series_fn(bars, n=CONFIG["volume_baseline_bars"])

    assert rq["attempts"] == 1
    assert rq["bars_confirmation_to_retest"] == first_entry_idx - confirm_idx == 1
    assert rq["bars_retest_to_continuation"] == resolve_idx - first_entry_idx == 1
    assert rq["penetration_pct"] == pytest.approx(deepest_pen / broken_level * 100.0)
    assert rq["penetration_atr"] == pytest.approx(deepest_pen / float(a.iloc[first_entry_idx]))
    assert rq["retest_relative_volume"] == pytest.approx(float(rv.iloc[first_entry_idx]))

    confirmed = _confirmed_event(d)
    assert confirmed["observed_values"]["body_pct"] is not None
    assert confirmed["observed_values"]["close_location"] is not None


def test_hh_hl_failed_retest_quality_hand_computed():
    """test_patterns.py's own `test_hh_hl_retest_after_confirmation_fails` fixture: broken
    level = prior_high = 35.05. Confirm bar closes 40.0. Retest dips to low=34.8 -> pen =
    35.05-34.8 = 0.25. Then fails hard (close 31.0) -- the deepest reading is whichever bar's
    low is worse; the retest bar (34.8) is deeper than the failure bar's own low."""
    bars = _zigzag_bars([15.0, 8.0, 20.0, 9.0, 25.0, 12.0, 30.0, 16.0, 35.0, 20.0, 40.0])
    confirm_idx = len(bars) - 1
    bars = synth._append(
        bars,
        [
            (40.0, 40.2, 34.8, 35.0, 100_000.0),  # dip into the broken prior-high (retest zone)
            (35.0, 35.2, 30.0, 31.0, 100_000.0),  # hard failure
        ],
    )
    t = len(bars) - 1
    hh = [p for p in detect_as_of(bars, t, symbol="ZZ") if p.pattern_type == "HH_HL"]
    assert len(hh) == 1
    d = hh[0].to_dict()
    rq = d["retest_quality"]

    first_entry_idx = confirm_idx + 1
    broken_level = 35.05
    retest_pen = broken_level - 34.8    # = 0.25
    failure_pen = broken_level - 30.0   # = 5.05, deeper -- the failure bar itself widens the reading
    deepest_pen = max(retest_pen, failure_pen)
    deepest_idx = confirm_idx + 2  # the failure bar, since it is the deeper of the two

    a = atr_series_fn(bars, period=CONFIG["atr_period"])
    rv = relvol_series_fn(bars, n=CONFIG["volume_baseline_bars"])

    assert rq["attempts"] == 1
    assert rq["bars_confirmation_to_retest"] == first_entry_idx - confirm_idx == 1
    assert rq["bars_retest_to_continuation"] is None
    assert rq["penetration_pct"] == pytest.approx(deepest_pen / broken_level * 100.0)
    assert rq["penetration_atr"] == pytest.approx(deepest_pen / float(a.iloc[deepest_idx]))
    assert rq["retest_relative_volume"] == pytest.approx(float(rv.iloc[deepest_idx]))


# ── JSON safety (rule 5: the backend serves strict JSON, no NaN/Infinity) ─────────────────


@pytest.mark.parametrize(
    "bars_fn",
    [
        lambda: synth.fixture_04_false_retest(synth.rect1()),           # failed retest
        lambda: synth.fixture_03_close_back_inside(synth.rect1()),      # no retest (false breakout)
        lambda: synth.fixture_02_low_volume_breakout(synth.rect1()),    # no retest (walk exhausted)
        lambda: synth.fixture_01_wick_only_breakout(synth.rect1()),     # never confirmed
        _rectangle_multi_attempt_success_bars,                          # successful, 2 attempts
        lambda: synth._append(synth.rect1(), [(111.0, 111.0, 111.0, 111.0, 120_000.0)]),  # zero-range confirm bar
    ],
)
def test_new_fields_are_json_safe_no_nan_or_infinity(bars_fn):
    bars = bars_fn()
    d = _rect_snapshot(bars)
    # allow_nan=False raises ValueError on any NaN/Infinity float anywhere in the structure --
    # the strictest possible check, matching "the backend serves strict JSON".
    raw = json.dumps(d, allow_nan=False)
    reloaded = json.loads(raw)
    assert reloaded["retest_quality"] == d["retest_quality"]
    for e in d["events"]:
        if e["event_type"] == "PRICE_CONFIRMED":
            for key in ("body_pct", "close_location"):
                v = e["observed_values"][key]
                assert v is None or (isinstance(v, (int, float)) and math.isfinite(v))
