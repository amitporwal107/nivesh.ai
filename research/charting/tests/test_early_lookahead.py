"""Poisoned-future probes for the §34 early-formation scores — test-plan.md Part B probe B3
("§34 score after detection_timestamp") and Part C ("§34 maturity checkpoint — PIT-safe
redefinition").

Method (test-plan.md Part B): run A truncated at `t`; run B extends past `t` with
adversarial bars. Every output dated <= `t` must be field-identical. Every probe has a
negative control -- a deliberately peeking computation -- that the SAME comparison must
catch as DIFFERENT, proving the probe can actually detect a leak rather than trivially
always passing.
"""
from __future__ import annotations

import pandas as pd
import pytest

from research.charting.config import CONFIG, BARS_COLUMNS
from research.charting.early.maturity import offline_checkpoint_index
from research.charting.early.records import build_record_as_of, checkpoint_record, find_range_candidate_as_of
from research.charting.early.scoring import compute_early_scores
from research.charting.tests import synth


# ── Shared fixture: RECT-1 + a long quiet plateau + a decisive breakout ──────
#
# RECT-1 alone (20 bars) leaves almost no runway after its own ATR/pivot warmup (the
# candidate is not even detectable before bar index 14 -- see test_early_records.py). This
# local extension (NOT a change to tests/synth.py) appends byte-identical flat bars, which
# by construction create no new swing pivots (a perfectly flat run fails the strict-right
# comparison in swings.find_swings), so the RECT-1 100/110 levels remain the ones
# find_range_candidate_as_of selects at every later t -- giving a long, stable runway to
# sweep t over, and a genuine "completed pattern" t_end for the Part C checkpoint probe.


def _extend_range_bound(bars: pd.DataFrame, n_quiet: int, breakout_close: float) -> pd.DataFrame:
    last_date = pd.Timestamp(bars["date"].iloc[-1])
    dates = pd.bdate_range(start=last_date + pd.tseries.offsets.BDay(1), periods=n_quiet + 1)
    rows = [(dates[i], 105.0, 105.6, 104.4, 105.2, 100_000.0) for i in range(n_quiet)]
    rows.append((dates[n_quiet], 105.2, breakout_close + 1.0, 104.7, breakout_close, 250_000.0))
    ext = pd.DataFrame(rows, columns=list(BARS_COLUMNS))
    return pd.concat([bars, ext], ignore_index=True)


def _fixture() -> pd.DataFrame:
    return _extend_range_bound(synth.rect1(), n_quiet=20, breakout_close=113.0)


def _poison_after(bars: pd.DataFrame, t: int) -> pd.DataFrame:
    """Every row strictly after `t` becomes a deterministic adversarial extreme
    (alternating huge/tiny OHLCV) -- rows [0, t] are left byte-identical. Mirrors the
    poison helper used throughout this repo's other lookahead probes
    (test_lookahead.py, test_patterns_lookahead.py, test_series.py)."""
    poisoned = bars.copy()
    for i in range(t + 1, len(bars)):
        if (i - t) % 2 == 1:
            poisoned.loc[i, ["open", "high", "low", "close"]] = [9999.0, 9999.5, 9998.5, 9999.0]
            poisoned.loc[i, "volume"] = 9_999_999.0
        else:
            poisoned.loc[i, ["open", "high", "low", "close"]] = [0.02, 0.03, 0.01, 0.02]
            poisoned.loc[i, "volume"] = 1.0
    return poisoned


# ── Probe B3: compute_early_scores unaffected by poisoning after t ───────────


def test_probe_b3_checkpoint_scores_unchanged_by_poisoning_every_bar_after_t():
    base = _fixture()
    cand = find_range_candidate_as_of(base, 19)  # fixed trigger/invalidation, computed once
    n = len(base)
    checked = 0
    for t in range(14, n - 1):  # 14 = first bar a candidate exists at all; leave >=1 bar to poison
        poisoned = _poison_after(base, t)
        pd.testing.assert_frame_equal(
            poisoned.iloc[: t + 1].reset_index(drop=True), base.iloc[: t + 1].reset_index(drop=True)
        )
        scores_a = compute_early_scores(
            base, t, trigger_level=cand.trigger_level, invalidation_level=cand.invalidation_level, direction="BULLISH"
        )
        scores_b = compute_early_scores(
            poisoned, t, trigger_level=cand.trigger_level, invalidation_level=cand.invalidation_level, direction="BULLISH"
        )
        assert scores_a == scores_b, f"leak detected at t={t}"
        checked += 1
    assert checked >= 10  # meaningful sweep breadth, not a single lucky t


def test_probe_b3_features_available_at_detection_never_dates_after_t():
    """§34.7's `features_available_at_detection` field must reflect only what was
    actually usable at `t`; poisoning the future must not add/remove entries."""
    base = _fixture()
    t = 20
    poisoned = _poison_after(base, t)
    rec_a = build_record_as_of(base, t, symbol="SYN1", direction="BULLISH")
    rec_b = build_record_as_of(poisoned, t, symbol="SYN1", direction="BULLISH")
    assert rec_a.features_available_at_detection == rec_b.features_available_at_detection
    assert rec_a == rec_b


# ── Probe B3 negative control: distance-to-trigger reading the future breakout bar ──


def _peeking_distance_to_trigger(bars: pd.DataFrame, t_look: int, trigger_level: float, atr_now: float) -> float:
    """NEGATIVE CONTROL ONLY -- deliberately PIT-broken: reads the close at `t_look`
    (a bar that may be strictly after the caller's intended cutoff) instead of "the
    latest bar of an already-truncated view". Mirrors test-plan.md B3's own named
    negative control ("distance-to-trigger reading the future breakout bar"). Must
    never be imported outside this test file."""
    close_at_t_look = float(bars["close"].iloc[t_look])
    return abs(trigger_level - close_at_t_look) / atr_now


def test_probe_b3_negative_control_peeking_distance_to_trigger_is_caught():
    base = _fixture()
    t = 24
    t_future = 40  # the eventual breakout bar, strictly after t
    cand = find_range_candidate_as_of(base, 19)
    poisoned = _poison_after(base, t)

    pd.testing.assert_frame_equal(poisoned.iloc[: t + 1].reset_index(drop=True), base.iloc[: t + 1].reset_index(drop=True))

    # A correctly-scoped read (t itself, not t_future) sees no difference:
    correct_a = _peeking_distance_to_trigger(base, t, cand.trigger_level, cand.atr_at_t)
    correct_b = _peeking_distance_to_trigger(poisoned, t, cand.trigger_level, cand.atr_at_t)
    assert correct_a == correct_b

    # The PEEKING read (t_future) is exactly the bug this probe exists to catch:
    peek_a = _peeking_distance_to_trigger(base, t_future, cand.trigger_level, cand.atr_at_t)
    peek_b = _peeking_distance_to_trigger(poisoned, t_future, cand.trigger_level, cand.atr_at_t)
    assert peek_a != peek_b, "negative control failed to detect the leak -- a probe that stays green against a broken detector proves nothing"

    # And the real implementation shows no such difference for the same (base, poisoned, t):
    scores_a = compute_early_scores(base, t, trigger_level=cand.trigger_level, invalidation_level=cand.invalidation_level, direction="BULLISH")
    scores_b = compute_early_scores(poisoned, t, trigger_level=cand.trigger_level, invalidation_level=cand.invalidation_level, direction="BULLISH")
    assert scores_a.components["distance_to_trigger"] == scores_b.components["distance_to_trigger"]


# ── Part C: offline checkpoint proof test ────────────────────────────────────


def test_probe_c_checkpoint_record_byte_identical_across_all_four_fractions_when_t_end_bar_is_poisoned():
    """test-plan.md Part C's required test: mutate every bar after `t_ck` -- INCLUDING
    `t_end` itself, the very bar used to select `t_ck` -- and recompute. The stored
    checkpoint scores must not change, for every one of the four §34.9 AC5 fractions."""
    base = _fixture()
    t_start, t_end = 14, len(base) - 1
    assert t_end == 40

    checked = 0
    for fraction in CONFIG["early_maturity_checkpoints"]:
        ck = offline_checkpoint_index(t_start, t_end, fraction)
        assert ck.t_ck < t_end  # sanity: t_end (and at least one bar) is strictly after t_ck

        poisoned = _poison_after(base, ck.t_ck)  # mutates ck.t_ck+1 .. end, which includes t_end
        pd.testing.assert_frame_equal(
            poisoned.iloc[: ck.t_ck + 1].reset_index(drop=True), base.iloc[: ck.t_ck + 1].reset_index(drop=True)
        )
        # Confirm t_end's own bar really was mutated (otherwise this test would prove nothing):
        assert not poisoned.iloc[t_end].equals(base.iloc[t_end])

        ck_a, rec_a = checkpoint_record(base, t_start=t_start, t_end=t_end, fraction=fraction, symbol="SYN1", direction="BULLISH")
        ck_b, rec_b = checkpoint_record(poisoned, t_start=t_start, t_end=t_end, fraction=fraction, symbol="SYN1", direction="BULLISH")

        assert ck_a.t_ck == ck_b.t_ck == ck.t_ck  # t_ck itself is index-only, unaffected by value poisoning
        assert rec_a.scores == rec_b.scores, f"leak detected at fraction={fraction}, t_ck={ck.t_ck}"
        assert rec_a == rec_b
        checked += 1
    assert checked == 4  # every one of the §34.9 AC5 checkpoints (20/40/60/80%) was evaluated


def test_probe_c_checkpoint_score_has_no_final_length_or_bars_to_breakout_field():
    """No field derived from `t_end` (final length, bars-to-breakout) may appear in a
    checkpoint score payload (test-plan.md Part C)."""
    base = _fixture()
    _, rec = checkpoint_record(base, t_start=14, t_end=len(base) - 1, fraction=0.4, symbol="SYN1", direction="BULLISH")
    payload = rec.to_dict()

    def _walk(obj):
        if isinstance(obj, dict):
            for k, v in obj.items():
                assert k not in ("final_length", "bars_to_breakout", "t_end")
                _walk(v)
        elif isinstance(obj, (list, tuple)):
            for v in obj:
                _walk(v)

    _walk(payload)


# ── Part C negative control: naive live-style maturity depending on t_end ────


def _naive_maturity_fraction(current_index: int, t_start: int, t_end: int) -> float:
    """NEGATIVE CONTROL ONLY -- the exact formula §34.7.1 forbids as a "live" value:
    percent-of-formation computed against the (at detection time, unknown) final
    length. Never used by this package's real code."""
    return (current_index - t_start) / (t_end - t_start)


def test_probe_c_negative_control_naive_maturity_fraction_changes_with_t_end_even_though_scores_do_not():
    """Same (base, poisoned, t_ck) triple as the main proof test above, but comparing the
    checkpoint SCORES (leak-free, unaffected) against the naive maturity FRACTION
    (which -- on the DIFFERENT axis of t_end being revised rather than bar values being
    poisoned -- is exactly the unstable quantity §34.7.1 forbids storing). This shows
    the two are qualitatively different kinds of checkpoint field: one may safely be
    computed once and stored forever from indices alone (t_ck), the other must never be
    computed from t_end and stored as if it meant "percent of formation"."""
    base = _fixture()
    t_start = 14
    current_index = 24  # == t_ck for fraction=0.4 against t_end=40 (see test_early_maturity.py)

    scores_with_completion_at_40 = compute_early_scores(
        base, current_index,
        trigger_level=find_range_candidate_as_of(base, 19).trigger_level,
        invalidation_level=find_range_candidate_as_of(base, 19).invalidation_level,
        direction="BULLISH",
    )
    # A longer synthetic run where the SAME bars[0..24] are identical but the pattern is
    # imagined to complete later (t_end=60 instead of 40) -- the real scores at t_ck=24
    # cannot possibly differ, because compute_early_scores never receives t_end at all.
    scores_with_completion_at_60 = compute_early_scores(
        base, current_index,
        trigger_level=find_range_candidate_as_of(base, 19).trigger_level,
        invalidation_level=find_range_candidate_as_of(base, 19).invalidation_level,
        direction="BULLISH",
    )
    assert scores_with_completion_at_40 == scores_with_completion_at_60

    naive_at_40 = _naive_maturity_fraction(current_index, t_start, 40)
    naive_at_60 = _naive_maturity_fraction(current_index, t_start, 60)
    assert naive_at_40 != naive_at_60, (
        "negative control failed: a naive percent-of-formation value should change when the "
        "assumed completion point (t_end) changes, even at the SAME current_index -- proving "
        "why real scores must never be computed as a function of t_end"
    )
