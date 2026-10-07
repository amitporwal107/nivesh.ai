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

from research.charting import enrich
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


# ── §35.2 amendment additions: breakout candle quality (N§8) / retest quality (N§13) ──────
# CANDLE-MOVE (2026-09-22, docs/charting.md §38.18 decisions-log #93/#110): these two fields
# no longer live on `detect_as_of`'s own output at all -- `research.charting.enrich
# .enrich_pattern` computes them separately, from a production pattern dict + bars, so the
# whole-object probes above (`_serialize` -> `p.to_dict()`) no longer cover them even
# incidentally. These two tests keep the SAME poisoned-future probe + negative control, only
# now aimed at the enrichment layer -- repo standard: every field this detector pipeline
# reports point-in-time gets its own leak probe, wherever it is actually computed.


def _synthetic_benchmark(n: int = 300, start_date: str = "2019-01-02") -> pd.DataFrame:
    """A long, clean benchmark frame so `enrich_pattern`'s trend-classification calls never
    raise -- these tests assert on `candle_quality`/`retest_quality` only."""
    closes = [200 + 0.2 * i + (i % 5) * 0.3 for i in range(n)]
    return synth.bars_from_closes(closes, start_date=start_date, wick=0.5)


def _retest_multi_attempt_bars() -> pd.DataFrame:
    """RECT-1 + a two-dip retest that eventually succeeds (bar20/idx24), plus two quiet
    filler bars afterwards so there is room to poison/peek past the resolution bar itself
    (fixture_04_false_retest has none -- its failure bar is the last bar in the frame)."""
    return synth._append(
        synth.rect1(),
        [
            (109.0, 111.3, 108.8, 111.0, 120_000.0),  # bar16 idx20 breakout confirm
            (111.0, 111.2, 109.0, 109.5, 100_000.0),  # bar17 idx21 dip in -- attempt 1 (pen 1.0)
            (109.5, 110.3, 109.4, 110.2, 100_000.0),  # bar18 idx22 pops back out, not a success close
            (110.2, 110.4, 108.5, 109.7, 150_000.0),  # bar19 idx23 dips again -- attempt 2 (pen 1.5, deeper)
            (109.7, 113.5, 109.6, 113.0, 100_000.0),  # bar20 idx24 RETEST_SUCCESSFUL
            (113.0, 113.2, 112.8, 113.1, 100_000.0),  # idx25 quiet filler (poison/peek room)
            (113.1, 113.3, 112.9, 113.2, 100_000.0),  # idx26 quiet filler (poison/peek room)
        ],
    )


def test_new_descriptive_fields_unaffected_by_poisoning_the_future():
    """Breakout candle quality (`enrich_pattern`'s `candle_quality`) and retest quality
    (`enrich_pattern`'s `retest_quality`) must be unaffected by anything dated after `t` --
    checked across t values before, during and after the retest actually resolves (t=21
    mid-retest, t=22 same attempt count, t=23 the second attempt just occurred, t=24 the
    resolution bar itself), each swept against both poison shapes. Both the production
    pattern dict AND the bars handed to `enrich_pattern` come from the SAME (clean/poisoned)
    source, so this also proves the enrichment layer's own bar-truncation (`bars <= t`) does
    the job -- not just that it was handed an already-safe pattern dict."""
    base = _retest_multi_attempt_bars()
    benchmark = _synthetic_benchmark()
    checked = 0
    for t in (21, 22, 23, 24, 25):
        for poison_fn in _POISON_FNS:
            poisoned = poison_fn(base, t)
            pd.testing.assert_frame_equal(
                poisoned.iloc[: t + 1].reset_index(drop=True), base.iloc[: t + 1].reset_index(drop=True)
            )
            clean = [p.to_dict() for p in detect_as_of(base, t, symbol="SYN1") if p.pattern_type == "RECTANGLE"]
            dirty = [p.to_dict() for p in detect_as_of(poisoned, t, symbol="SYN1") if p.pattern_type == "RECTANGLE"]
            assert len(clean) == 1 and len(dirty) == 1

            ts = base["date"].iloc[t]  # byte-identical to poisoned["date"].iloc[t] (asserted above)
            clean_enriched = enrich.enrich_pattern(clean[0], base, t=ts, benchmark_df=benchmark)
            dirty_enriched = enrich.enrich_pattern(dirty[0], poisoned, t=ts, benchmark_df=benchmark)

            assert clean_enriched["retest_quality"] == dirty_enriched["retest_quality"], f"retest_quality leaked future data at t={t} via {poison_fn.__name__}"
            for key in ("body_pct", "close_location"):
                assert clean_enriched["candle_quality"][key] == dirty_enriched["candle_quality"][key], (
                    f"candle quality '{key}' leaked future data at t={t} via {poison_fn.__name__}"
                )
            checked += 1
    assert checked >= 8  # 5 t-values x 2 poison shapes, minus nothing skipped


def _peeking_retest_attempts(bars: pd.DataFrame, confirm_index: int, broken_level: float) -> int:
    """NEGATIVE CONTROL ONLY -- deliberately PIT-broken: counts zone re-entries over the WHOLE
    frame it is handed (`len(bars)`), instead of stopping at some caller-intended `t` -- exactly
    the mistake this task's rule 1 forbids ("bars <= the event bar only"). Mirrors this file's
    `_peeking_resistance_level` convention. Must never be imported outside this test file."""
    closes = bars["close"].to_numpy(dtype=float)
    attempts = 0
    in_zone = False
    for i in range(confirm_index + 1, len(bars)):
        bar_in_zone = closes[i] <= broken_level
        if bar_in_zone and not in_zone:
            attempts += 1
        in_zone = bar_in_zone
    return attempts


def test_negative_control_peeking_attempts_count_is_detected_by_the_same_probe():
    """The real detector's `attempts` at t=22 (only the first dip, idx21, has happened) must
    be 1 -- proven directly below -- while a deliberately-peeking count taken over the FULL,
    untruncated frame sees BOTH dips (idx21 and idx23) and reports 2. The two disagree, which
    is exactly what the probe above would have caught had `patterns.py`'s real bookkeeping
    made this mistake -- a probe that stays green against a broken counter proves nothing."""
    base = _retest_multi_attempt_bars()
    t = 22  # bar18: the second dip (idx23) has not happened yet
    confirm_index = 20  # bar16, the PRICE_CONFIRMED bar
    broken_level = 110.0  # RECT-1 resistance

    correctly_sliced = _peeking_retest_attempts(base.iloc[: t + 1].reset_index(drop=True), confirm_index, broken_level)
    peeking_full_frame = _peeking_retest_attempts(base, confirm_index, broken_level)
    assert correctly_sliced == 1
    assert peeking_full_frame == 2
    assert correctly_sliced != peeking_full_frame, (
        "negative control failed to detect the leak -- a probe that stays green against a "
        "broken attempts-counter proves nothing"
    )

    # And the real detector + enrichment, run at t=22, agrees with the correctly-sliced count
    # -- it does NOT peek, even though the naive counter above shows peeking would have
    # changed the answer.
    real = [p.to_dict() for p in detect_as_of(base, t, symbol="SYN1") if p.pattern_type == "RECTANGLE"][0]
    real_enriched = enrich.enrich_pattern(real, base, t=base["date"].iloc[t], benchmark_df=_synthetic_benchmark())
    assert real_enriched["retest_quality"]["attempts"] == correctly_sliced == 1


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
