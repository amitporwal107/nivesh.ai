"""Look-ahead / poisoned-future probes — test-plan.md Part B, probe B1 ("swing
before right bars exist"), plus a generic "poison every bar after t" sweep for
`swings_as_of`.

Method (test-plan Part B): run A truncated at `t`; run B extends past `t` with an
adversarial bar. Every output dated <= `t` must be field-identical between the two
runs. Every probe needs a negative control -- a deliberately peeking detector -- that
the SAME comparison turns red, proving the probe can actually detect a leak (a probe
that stays green against a broken detector proves nothing).
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from research.charting.config import BARS_COLUMNS, CONFIG
from research.charting.swings import swings_as_of
from research.charting.tests import synth


def _bars(highs: list[float], lows: list[float]) -> pd.DataFrame:
    n = len(highs)
    assert len(lows) == n
    dates = pd.bdate_range("2024-01-02", periods=n)
    mid = [(h + l) / 2 for h, l in zip(highs, lows)]
    df = pd.DataFrame(
        {"date": dates, "open": mid, "high": highs, "low": lows, "close": mid, "volume": [100_000.0] * n}
    )
    return df[list(BARS_COLUMNS)]


# ── Probe B1 ──────────────────────────────────────────────────────────────────
#
# t=5 is a LOW pivot (left=right=3 -> confirmed_index = t+3 = 8). The poison at
# t+3 touches ONLY the `high` field (H=9999, as the test-plan specifies), leaving
# low/close untouched -- so it cannot legitimately invalidate a LOW pivot's own
# left/right comparisons. This is deliberate: a poison that touched `low` at t+3
# could legitimately invalidate the pivot (a genuinely lower low in its own right
# window), which would not be a look-ahead bug at all. Using `high` isolates the
# thing actually under test: does the detector's view of bars <= t+2 change when
# unrelated future data (dated t+3) is added?

_T = 5
_RIGHT = CONFIG["swing_right_bars"]  # 3
assert _RIGHT == 3, "test assumes the shared CONFIG's swing_right_bars=3"

# Flat, unremarkable highs everywhere except the pivot's low dips at t; the poison
# (run B only) replaces the high at t+3 with 9999.
_HIGHS = [10.0] * 9
_LOWS = [8.0, 8.0, 8.0, 8.0, 8.0, 2.0, 8.0, 8.0, 8.0]
assert len(_HIGHS) == len(_LOWS) == _T + _RIGHT + 1  # room for run B (t+3 inclusive)


def _run_a() -> pd.DataFrame:
    """Data ends at t+2: rows [0, t+2], t+3 does not exist yet."""
    full = _bars(_HIGHS, _LOWS)
    return full.iloc[: _T + 3].reset_index(drop=True)  # indices 0..t+2


def _run_b() -> pd.DataFrame:
    """Data ends at t+3: t+3 is present, poisoned (H=9999)."""
    full = _bars(_HIGHS, _LOWS)
    full = full.copy()
    full.loc[_T + 3, "high"] = 9999.0
    return full


def test_b1_nothing_dated_at_or_before_t_plus_2_differs():
    run_a = _run_a()
    run_b = _run_b()

    # Sanity: the two runs are byte-identical through t+2; only row t+3 (present
    # only in run B) differs.
    pd.testing.assert_frame_equal(run_b.iloc[: _T + 3].reset_index(drop=True), run_a)

    assert swings_as_of(run_a, _T + 2) == swings_as_of(run_b, _T + 2)


def test_b1_swing_at_t_appears_only_once_confirmed_at_t_plus_3():
    run_a = _run_a()
    run_b = _run_b()

    # Not yet confirmable as of t+2 in either run (right_bars=3 not yet available).
    as_of_t_plus_2 = swings_as_of(run_a, _T + 2)
    assert not any(p.kind == "LOW" and p.pivot_index == _T for p in as_of_t_plus_2)

    # Confirmed exactly once t+3 exists (run B only -- run A doesn't have a bar
    # there at all).
    as_of_t_plus_3 = swings_as_of(run_b, _T + 3)
    matches = [p for p in as_of_t_plus_3 if p.kind == "LOW" and p.pivot_index == _T]
    assert len(matches) == 1
    assert matches[0].confirmed_index == _T + 3
    assert matches[0].price == pytest.approx(2.0)


# ── Mandatory negative control ────────────────────────────────────────────────


def _peeking_dominant_high(bars: pd.DataFrame) -> tuple[int, int]:
    """NEGATIVE CONTROL ONLY -- deliberately PIT-broken.

    Takes `argmax` over the FULL `bars` frame (including everything after the
    as-of cutoff the caller cares about) to find "the" dominant high, BEFORE (in
    fact instead of) applying any right-bar confirmation gate against a sliced
    view. A correct implementation slices to `[0, t]` first (see
    `swings_as_of`'s docstring); this one never slices at all, so if a bigger high
    exists anywhere in the future, its answer changes even though the caller only
    asked about bars up to `t`.

    Returns (peak_index, naive_confirmed_index). Must NEVER be imported outside
    this test file -- it exists solely to prove probe B1 can detect a leak.
    """
    highs = bars["high"].to_numpy(dtype=float)  # the WHOLE frame -- the leak
    peak_i = int(np.argmax(highs))
    return peak_i, peak_i + CONFIG["swing_right_bars"]


def test_b1_negative_control_peeking_detector_leaks_future_into_the_past_view():
    run_a = _run_a()
    run_b = _run_b()

    # Re-confirm the premise: rows <= t+2 are identical between the two runs.
    pd.testing.assert_frame_equal(run_b.iloc[: _T + 3].reset_index(drop=True), run_a)

    result_a = _peeking_dominant_high(run_a)
    result_b = _peeking_dominant_high(run_b)

    # THE LEAK: despite identical data through t+2, the peeking detector's answer
    # differs solely because run B contains a poisoned bar dated after t+2.
    assert result_a != result_b, (
        "negative control failed to detect the leak -- a probe that stays green "
        "against a broken detector proves nothing (test-plan Part B)"
    )
    assert result_a == (0, 0 + CONFIG["swing_right_bars"])  # argmax of a flat array -> index 0
    assert result_b == (_T + 3, (_T + 3) + CONFIG["swing_right_bars"])  # argmax jumps to the poison

    # And the real, correct detector shows no such difference for the same t+2 cutoff.
    assert swings_as_of(run_a, _T + 2) == swings_as_of(run_b, _T + 2)


# ── Generic sweep: poison every bar after t, for many t ──────────────────────


def _poison_after(bars: pd.DataFrame, t: int) -> pd.DataFrame:
    """Return a copy of `bars` where every row after position `t` is replaced with
    a deterministic adversarial extreme (alternating huge/tiny OHLC + volume).
    Rows [0, t] are left byte-identical."""
    poisoned = bars.copy()
    for i in range(t + 1, len(bars)):
        if (i - t) % 2 == 1:
            poisoned.loc[i, ["open", "high", "low", "close"]] = [9999.0, 9999.5, 9998.5, 9999.0]
            poisoned.loc[i, "volume"] = 9_999_999.0
        else:
            poisoned.loc[i, ["open", "high", "low", "close"]] = [0.02, 0.03, 0.01, 0.02]
            poisoned.loc[i, "volume"] = 1.0
    return poisoned


def test_swings_as_of_is_unaffected_by_poisoning_every_bar_after_t():
    base = synth.rect1()
    base = synth.fixture_09_future_volume_contamination(base)
    base, _incomplete = synth.fixture_12_incomplete_candle(base)
    n = len(base)
    left = CONFIG["swing_left_bars"]

    checked = 0
    for t in range(left, n - 1):  # leave >=1 bar after t to actually poison
        poisoned = _poison_after(base, t)
        pd.testing.assert_frame_equal(
            poisoned.iloc[: t + 1].reset_index(drop=True), base.iloc[: t + 1].reset_index(drop=True)
        )
        assert swings_as_of(base, t) == swings_as_of(poisoned, t), f"leak detected at t={t}"
        checked += 1

    assert checked >= 10  # make sure the sweep actually exercised a meaningful range of t
