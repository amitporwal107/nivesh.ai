"""Poisoned-future probes over `detect_as_of` — test-plan.md Part B methodology applied to
the full detector pipeline (geometry.py + patterns.py), not just `swings_as_of`.

Method: run A truncated at `t`; run B extends past `t` with adversarial bars (huge gap, 10x
volume, a fabricated clean breakout). Every output dated <= `t` must be field-identical.
Mandatory negative control: a deliberately peeking variant (computing "the resistance
level" over the FULL frame instead of confirmed pivots up to `t`) must be DETECTED by the
same comparison — a probe that stays green against a broken detector proves nothing.
"""
from __future__ import annotations

import pandas as pd
import pytest

from research.charting.patterns import detect_as_of
from research.charting.tests import synth


def _serialize(bars: pd.DataFrame, t: int, **kwargs) -> list[dict]:
    pats = detect_as_of(bars, t, symbol="SYN1", **kwargs)
    return sorted((p.to_dict() for p in pats), key=lambda d: d["pattern_id"])


def _poison_alternating_extremes(bars: pd.DataFrame, t: int) -> pd.DataFrame:
    """Every row after `t` becomes a deterministic adversarial extreme (alternating
    huge/tiny OHLC + volume) -- rows [0, t] are left byte-identical. Mirrors
    test_lookahead.py's `_poison_after`."""
    poisoned = bars.copy()
    for i in range(t + 1, len(bars)):
        if (i - t) % 2 == 1:
            poisoned.loc[i, ["open", "high", "low", "close"]] = [9999.0, 9999.5, 9998.5, 9999.0]
            poisoned.loc[i, "volume"] = 9_999_999.0
        else:
            poisoned.loc[i, ["open", "high", "low", "close"]] = [0.02, 0.03, 0.01, 0.02]
            poisoned.loc[i, "volume"] = 1.0
    return poisoned


def _poison_fabricated_clean_breakout(bars: pd.DataFrame, t: int) -> pd.DataFrame:
    """Every row after `t` becomes a smooth, decisive rally on huge volume -- exactly the
    shape a genuine breakout confirmation would have, so a detector that peeked at it would
    plausibly (and wrongly) confirm a breakout dated at or before `t`."""
    poisoned = bars.copy()
    last_close = float(bars["close"].iloc[t])
    for j, i in enumerate(range(t + 1, len(bars))):
        c = last_close + 50.0 + j
        poisoned.loc[i, ["open", "high", "low", "close"]] = [c - 1.0, c + 1.0, c - 2.0, c]
        poisoned.loc[i, "volume"] = 2_000_000.0
    return poisoned


_POISON_FNS = (_poison_alternating_extremes, _poison_fabricated_clean_breakout)


def _lookahead_fixture() -> pd.DataFrame:
    """RECT-1 extended through a full breakout + retest + failure cycle (fixture #4), so the
    sweep below covers formation, confirmation, retest and failure states, not just the
    quiet pre-breakout window."""
    return synth.fixture_04_false_retest(synth.rect1())


def test_detect_as_of_unaffected_by_poisoning_every_bar_after_t():
    base = _lookahead_fixture()
    n = len(base)
    checked = 0
    for t in range(10, n - 1):  # leave >=1 bar after t to poison
        for poison_fn in _POISON_FNS:
            poisoned = poison_fn(base, t)
            # Sanity: rows [0, t] are byte-identical between the two runs.
            pd.testing.assert_frame_equal(
                poisoned.iloc[: t + 1].reset_index(drop=True), base.iloc[: t + 1].reset_index(drop=True)
            )
            result_a = _serialize(base, t)
            result_b = _serialize(poisoned, t)
            assert result_a == result_b, f"leak detected at t={t} via {poison_fn.__name__}"
            checked += 1
    assert checked >= 10  # meaningful sweep breadth, not a single lucky t


def test_detect_as_of_unaffected_by_poisoning_during_formation_only():
    """Same probe restricted to the pre-breakout formation window (t < formation_end),
    where pivot/ATR/clustering computations are most exposed to a look-ahead bug."""
    base = synth.rect1()
    n = len(base)
    checked = 0
    for t in range(6, n - 1):
        poisoned = _poison_alternating_extremes(base, t)
        result_a = _serialize(base, t)
        result_b = _serialize(poisoned, t)
        assert result_a == result_b, f"leak detected at t={t} (formation-only sweep)"
        checked += 1
    assert checked >= 10


def test_incomplete_bar_poisoning_does_not_affect_completed_bar_output():
    """Passing an `incomplete_bar` must never change any pattern's status/events computed
    from the completed frame alone when the incomplete bar itself does not cross a level —
    only RECTANGLE patterns still awaiting confirmation are touched at all, and only via the
    documented BREAKOUT_ATTEMPT/blocked-rule path (see test_patterns.py fixture #12 tests
    for the crossing case)."""
    base = synth.rect1()
    t = len(base) - 1
    without = _serialize(base, t)
    running_date = pd.bdate_range(start=base["date"].iloc[-1] + pd.tseries.offsets.BDay(1), periods=1)[0]
    quiet_incomplete_bar = {
        "date": running_date, "open": 105.0, "high": 105.5, "low": 104.5, "close": 105.0,
        "volume": 50_000.0, "is_complete": False,
    }
    with_quiet = _serialize(base, t, incomplete_bar=quiet_incomplete_bar)
    assert without == with_quiet


# ── Mandatory negative control ────────────────────────────────────────────────


def _peeking_resistance_level(bars: pd.DataFrame) -> float:
    """NEGATIVE CONTROL ONLY -- deliberately PIT-broken. Takes the max `high` over the WHOLE
    frame it is handed, instead of confirmed pivots up to some `t` -- exactly the mistake of
    calling `bars["high"].max()` on a frame that has grown past the caller's intended cutoff.
    Must NEVER be imported outside this test file."""
    return float(bars["high"].max())


def test_negative_control_peeking_resistance_level_is_detected_by_the_same_probe():
    base = _lookahead_fixture()
    t = 15  # still within RECT-1's own formation window, well before any breakout bar
    poisoned = _poison_alternating_extremes(base, t)

    # Sanity: rows [0, t] are byte-identical, exactly as every other probe in this file checks.
    pd.testing.assert_frame_equal(poisoned.iloc[: t + 1].reset_index(drop=True), base.iloc[: t + 1].reset_index(drop=True))

    peek_a = _peeking_resistance_level(base.iloc[: t + 1])  # a correctly-sliced view: nothing past t
    peek_b = _peeking_resistance_level(poisoned)  # the FULL poisoned frame, unsliced -- the leak
    assert peek_a != peek_b, "negative control failed to detect the leak -- a probe that stays green against a broken detector proves nothing"
    assert peek_a == pytest.approx(110.0)
    assert peek_b == pytest.approx(9999.5)

    # And the real detector shows no such difference for the same (base, poisoned, t) triple.
    result_a = _serialize(base, t)
    result_b = _serialize(poisoned, t)
    assert result_a == result_b


# ── SUPPORT_RESISTANCE and HH_HL ────────────────────────────────────────────────────────────
# The probes above exercise RECTANGLE only. The retest/failure walk was later generalised to
# SUPPORT_RESISTANCE and HH_HL (package 3), so those families get the same guard here: a
# poisoned-future probe with a non-vacuity check, and a peeking negative control.

import math  # noqa: E402  (kept beside the section that needs it)
from collections import Counter  # noqa: E402

import numpy as np  # noqa: E402


def _range_then_breakout_bars() -> pd.DataFrame:
    """A range with repeated touches (S/R levels) that breaks out upward and then pulls back
    through the level, so confirmation and the retest/failure walk both run."""
    rng = np.random.default_rng(7)
    rangebound = [100 + 7 * math.sin(2 * math.pi * i / 20) + rng.normal(0, 0.4) for i in range(180)]
    last = rangebound[-1]
    rally = [last + 1.2 * k for k in range(1, 21)]
    pullback = [last + 24 - 1.0 * k for k in range(1, 61)]
    return synth.bars_from_closes(rangebound + rally + pullback)


def _staircase_bars() -> pd.DataFrame:
    """A rising staircase with oscillation — higher highs and higher lows (HH_HL)."""
    rng = np.random.default_rng(7)
    return synth.bars_from_closes([100 + 0.30 * i + 6 * math.sin(2 * math.pi * i / 16) + rng.normal(0, 0.3) for i in range(260)])


_FAMILY_CASES = [
    pytest.param(_range_then_breakout_bars, "SUPPORT_RESISTANCE", id="support_resistance"),
    pytest.param(_staircase_bars, "HH_HL", id="hh_hl"),
]


@pytest.mark.parametrize("builder, family", _FAMILY_CASES)
def test_poisoned_future_leaves_sr_and_hh_hl_output_at_t_unchanged(builder, family):
    bars = builder()
    seen: Counter = Counter()
    for t in range(120, len(bars) - 3, 12):
        clean = _serialize(bars.iloc[: t + 1].reset_index(drop=True), t)
        poisoned = _serialize(_poison_alternating_extremes(bars, t), t)
        assert clean == poisoned, f"{family}: look-ahead leak at t={t}"
        seen.update(d["pattern_type"] for d in clean)
    # Non-vacuity: the probe must actually have compared patterns of this family.
    assert seen[family] > 0, f"no {family} patterns were compared — the probe proved nothing ({dict(seen)})"


@pytest.mark.parametrize("builder, family", _FAMILY_CASES)
def test_negative_control_a_three_bar_peek_is_caught_for_sr_and_hh_hl(builder, family):
    """A detector evaluated three bars past t on the poisoned frame (i.e. one that peeks) must
    differ from the clean output at t — otherwise the probe above could not detect a leak."""
    bars = builder()
    trials = caught = 0
    for t in range(120, len(bars) - 3, 12):
        clean = _serialize(bars.iloc[: t + 1].reset_index(drop=True), t)
        peeking = _serialize(_poison_alternating_extremes(bars, t), t + 3)
        trials += 1
        caught += clean != peeking
    assert trials > 0 and caught == trials, f"{family}: peek caught in only {caught}/{trials} trials"


# ── Fix 3 (review 2026-09-22): HH_HL breakout-buffer ATR must be read causally ───────────
# HH_HL confirmation now requires clearing the prior high/low by breakout_buffer_atr * ATR
# (see patterns.py's _hh_hl_patterns). ATR is read off `atr_ser.iloc[i]`, already computed
# over the `t`-truncated view exactly like every other family's own buffer -- this probe
# pins that down specifically for the new buffer arithmetic, at a bar deliberately chosen
# to sit right at the buffer boundary (the case most exposed to a look-ahead bug: a
# borderline classification is exactly where a leaked future ATR value would flip the
# outcome).


def _zigzag_bars(turns: list[float], bars_per_leg: int = 5, wick: float = 0.05) -> pd.DataFrame:
    """Same shape as test_patterns.py's helper of the same name (duplicated locally, matching
    this file's existing convention of self-contained fixtures)."""
    closes: list[float] = []
    for i in range(len(turns) - 1):
        seg = list(np.linspace(turns[i], turns[i + 1], bars_per_leg))[:-1]
        closes.extend(seg)
    closes.append(turns[-1])
    return synth.bars_from_closes(closes, wick=wick)


def _hh_hl_buffer_boundary_fixture_with_room() -> tuple[pd.DataFrame, int]:
    """A bullish HH_HL structure one bar away from confirming, extended with a close just
    0.05 above the raw prior high (INSIDE the breakout buffer -- must stay GEOMETRY_VALID),
    plus 3 quiet filler bars afterwards so there is room to poison/peek past `t`. Returns
    (bars, t) where `t` is the index of the buffer-boundary bar itself."""
    base_pre = _zigzag_bars([15.0, 8.0, 20.0, 9.0, 25.0, 12.0, 30.0, 16.0, 35.0, 20.0])
    t0 = len(base_pre) - 1
    hh0 = [p for p in detect_as_of(base_pre, t0, symbol="ZZ") if p.pattern_type == "HH_HL"]
    assert len(hh0) == 1
    prior_high = hh0[0].levels["prior_high"]

    inside_at_t = synth._append(base_pre, [(prior_high, prior_high + 0.20, prior_high - 1.0, prior_high + 0.05, 100_000.0)])
    t = len(inside_at_t) - 1
    filler = [(prior_high + 0.05, prior_high + 0.1, prior_high - 0.5, prior_high + 0.05, 100_000.0)] * 3
    with_room = synth._append(inside_at_t, filler)
    return with_room, t


def test_hh_hl_breakout_buffer_boundary_unaffected_by_poisoning_the_future():
    bars, t = _hh_hl_buffer_boundary_fixture_with_room()
    hh_clean = [p for p in detect_as_of(bars, t, symbol="ZZ") if p.pattern_type == "HH_HL"]
    assert len(hh_clean) == 1
    assert hh_clean[0].status == "GEOMETRY_VALID", "fixture is vacuous: expected to sit inside the buffer, unconfirmed"

    for poison_fn in _POISON_FNS:
        poisoned = poison_fn(bars, t)
        pd.testing.assert_frame_equal(
            poisoned.iloc[: t + 1].reset_index(drop=True), bars.iloc[: t + 1].reset_index(drop=True)
        )
        result_clean = _serialize(bars, t)
        result_poisoned = _serialize(poisoned, t)
        assert result_clean == result_poisoned, f"leak detected via {poison_fn.__name__}"


def test_negative_control_peeking_past_t_is_caught_for_the_hh_hl_buffer_boundary():
    """Mandatory negative control: evaluating the poisoned frame PAST `t` (a peek) must show
    a different HH_HL status than the clean frame at `t` — proving the probe above really
    can detect a leak, not just always agree."""
    bars, t = _hh_hl_buffer_boundary_fixture_with_room()
    poisoned = _poison_fabricated_clean_breakout(bars, t)

    clean_at_t = _serialize(bars, t)
    peeking_past_t = _serialize(poisoned, t + 3)
    assert clean_at_t != peeking_past_t, (
        "negative control failed to detect the leak -- a probe that stays green against a "
        "broken detector proves nothing"
    )
    hh_peek = [p for p in peeking_past_t if p["pattern_type"] == "HH_HL"]
    assert hh_peek and hh_peek[0]["status"] == "PRICE_CONFIRMED"  # the fabricated rally confirms it
