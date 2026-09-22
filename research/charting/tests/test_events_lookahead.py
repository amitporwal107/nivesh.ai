"""Poisoned-future probes for `research.charting.events` -- this repo's standard methodology
(see `test_patterns_lookahead.py` / `test_early_lookahead.py`): run A vs run B, where B's bars
are mutated ONLY strictly after some cutoff index; anything the module claims is "known as of"
that cutoff must be field-identical between A and B. Each probe below is paired with a
NON-VACUITY check (something downstream of the cutoff DOES change) so a probe can never pass
merely because nothing was compared, and the suite ends with a MANDATORY NEGATIVE CONTROL: a
deliberately broken ("peeking") implementation that the exact same comparison technique must
catch -- a probe that stays green against a broken implementation proves nothing.

Two distinct look-ahead boundaries exist in this package, and each gets its own probe:
  1. SIGNAL fields (pattern_id/type/direction/level_broken/atr_at_t/relative_volume_at_t/
     adv_inr_at_t) must depend only on bars[0..t] (the confirmation bar) -- inherited from
     patterns.py/replay.py's own guarantee, but re-proven here at THIS package's own output to
     catch a leak this package's own code could newly introduce (e.g. accidentally passing the
     full `bars` instead of `view` somewhere in extraction.py).
  2. Each horizon's OUTCOME fields (forward returns/MFE/MAE/bars-to-target/costs) are meant to
     read bars AHEAD of the signal by design (they are labels, not features) -- but only up to
     that horizon's own exit bar, never further. A horizon-h outcome must be unaffected by
     mutating bars strictly AFTER exit_index(h), even though mutating bars AT OR BEFORE it (or
     a LATER horizon's own outcome) must visibly change.
"""
from __future__ import annotations

import pandas as pd
import pytest

from research.charting.events import extraction, outcomes, stops
from research.charting.tests._events_helpers import confirmed_rectangle_with_runway, raw_bars

_SIGNAL_FIELDS = (
    "pattern_id", "pattern_type", "direction", "signal_date", "confirmation_bar_index",
    "level_broken", "level_broken_field", "atr_at_t", "relative_volume_at_t", "config_hash",
    "engine_version", "dataset_version",
)


def _poison_after(bars: pd.DataFrame, k: int) -> pd.DataFrame:
    """Every row with index > k becomes a deterministic adversarial extreme (alternating
    huge/tiny OHLC + volume); rows [0, k] are left byte-identical. Same shape as
    `test_patterns_lookahead.py`'s own `_poison_alternating_extremes`."""
    poisoned = bars.copy()
    for i in range(k + 1, len(bars)):
        if (i - k) % 2 == 1:
            poisoned.loc[i, ["open", "high", "low", "close"]] = [9999.0, 9999.5, 9998.5, 9999.0]
            poisoned.loc[i, "volume"] = 9_999_999.0
        else:
            poisoned.loc[i, ["open", "high", "low", "close"]] = [0.02, 0.03, 0.01, 0.02]
            poisoned.loc[i, "volume"] = 1.0
    return poisoned


def _one_event(bars: pd.DataFrame, symbol: str = "SYN1") -> dict:
    rows = extraction.extract_events(bars, symbol)
    assert len(rows) == 1, "fixture must produce exactly one confirmed event for this probe to be meaningful"
    return rows[0]


# ── Probe 1: signal fields invariant to poisoning anything after the confirmation bar ───────


def test_signal_fields_unaffected_by_poisoning_after_the_confirmation_bar():
    base = confirmed_rectangle_with_runway(tail_len=30)
    row_base = _one_event(base)
    t_idx = row_base["confirmation_bar_index"]

    poisoned = _poison_after(base, t_idx)
    pd.testing.assert_frame_equal(
        poisoned.iloc[: t_idx + 1].reset_index(drop=True), base.iloc[: t_idx + 1].reset_index(drop=True)
    )
    row_poisoned = _one_event(poisoned)

    for field in _SIGNAL_FIELDS:
        assert row_base[field] == row_poisoned[field], f"leak detected in signal field {field!r}"
    # ADV is computed from bars[t-n+1..t] only -- also a signal-time figure, checked separately
    # since it lives under "liquidity", not the flat signal-field set above.
    assert row_base["liquidity"]["adv_inr_at_t"] == row_poisoned["liquidity"]["adv_inr_at_t"]

    # Non-vacuity: the entry bar (t+1) IS inside the poisoned region, so the primary entry
    # price/outcomes MUST differ -- otherwise this probe would pass even if extraction.py were
    # secretly ignoring the poisoned bars object entirely.
    assert row_base["entry"]["primary"]["price"] != row_poisoned["entry"]["primary"]["price"]


def test_signal_fields_unaffected_sweep_across_multiple_cutoffs():
    """Same probe as above, swept across several t values within a longer, noisier fixture
    (formation, confirmation and retest bars) -- test_patterns_lookahead.py's own breadth
    requirement ("checked >= 10"), applied at this package's output."""
    from research.charting import replay
    from research.charting.tests._events_helpers import shift_outside_sealed_window
    from research.charting.tests import synth

    base = shift_outside_sealed_window(synth.fixture_04_false_retest(synth.rect1()))
    result = replay.replay(base, symbol="SYN1")
    confirmed_indices = sorted({t.event_index for t in result.transitions if t.new_status == "PRICE_CONFIRMED"})
    assert confirmed_indices, "fixture must produce at least one PRICE_CONFIRMED transition"

    checked = 0
    for t_idx in confirmed_indices:
        if t_idx >= len(base) - 1:
            continue  # need >=1 bar after t to poison at all
        poisoned = _poison_after(base, t_idx)
        rows_base = extraction.extract_events(base, "SYN1")
        rows_poisoned = extraction.extract_events(poisoned, "SYN1")
        row_base = next(r for r in rows_base if r["confirmation_bar_index"] == t_idx)
        row_poisoned = next(r for r in rows_poisoned if r["confirmation_bar_index"] == t_idx)
        for field in _SIGNAL_FIELDS:
            assert row_base[field] == row_poisoned[field], f"leak at t={t_idx}, field {field!r}"
        checked += 1
    assert checked >= 1


# ── Probe 2: a horizon's outcome depends only on bars up to its OWN exit index ──────────────


def test_horizon_outcome_unaffected_beyond_its_own_exit_index_but_a_later_horizon_does_change():
    base = confirmed_rectangle_with_runway(tail_len=30)
    row_base = _one_event(base)
    entry_index = row_base["entry"]["primary"]["index"]
    exit_index_h3 = entry_index + 3

    poisoned = _poison_after(base, exit_index_h3)
    row_poisoned = _one_event(poisoned)

    for h in (1, 3):
        raw_base = row_base["outcomes"]["forward_returns"][h]
        raw_poisoned = row_poisoned["outcomes"]["forward_returns"][h]
        assert raw_base == raw_poisoned, f"horizon {h} outcome leaked bars beyond its own exit index"
        cost_base = row_base["costs"]["by_horizon"][h]
        cost_poisoned = row_poisoned["costs"]["by_horizon"][h]
        assert cost_base["scenarios"]["base"]["net_before_tax"] == pytest.approx(
            cost_poisoned["scenarios"]["base"]["net_before_tax"]
        ), f"horizon {h} cost leaked bars beyond its own exit index"

    # Non-vacuity: horizon 20's exit index (entry_index+20) is well past exit_index_h3, so its
    # forward return MUST differ -- otherwise this probe would pass even if poisoning had no
    # effect on anything at all.
    assert (
        row_base["outcomes"]["forward_returns"][20]["close_return"]
        != row_poisoned["outcomes"]["forward_returns"][20]["close_return"]
    )


def test_bars_to_target_resolved_before_the_poison_point_is_unaffected():
    base = confirmed_rectangle_with_runway(tail_len=30)
    row_base = _one_event(base)
    bt_base = row_base["outcomes"]["bars_to_target"]
    resolved_pct_key, resolved = next((k, v) for k, v in bt_base.items() if v["bars"] is not None)
    entry_index = row_base["entry"]["primary"]["index"]
    resolved_at_index = entry_index + resolved["bars"]

    poisoned = _poison_after(base, resolved_at_index)
    row_poisoned = _one_event(poisoned)
    assert row_poisoned["outcomes"]["bars_to_target"][resolved_pct_key] == resolved


# ── Probe 3: the §37.3 target/stop walk (stops.py) depends only on bars up to its own
# resolution bar -- the same "later bars must not change an earlier answer" property as
# Probe 2, applied to the new `stops.target_outcome_by_horizon` machinery (task hard rule:
# "a poisoned-future probe... plus a peeking negative control"). Hand-built bars (not the
# pattern-confirmation fixture) so the exact resolution offset is known upfront rather than
# discovered, matching `test_events_stops.py`'s own style for this module.


def test_target_stop_walk_unaffected_by_poisoning_after_its_own_resolution_bar():
    bars = raw_bars(
        [
            (100.0, 104.0, 98.0, 102.0, 1e5),   # offset0 entry -- no touch
            (102.0, 106.0, 100.0, 104.0, 1e5),  # offset1 -- no touch
            (104.0, 111.0, 103.0, 108.0, 1e5),  # offset2 -- high>=110 target touched, resolves here
        ]
        + [(108.0, 109.0, 107.0, 108.0, 1e5)] * 18  # flat filler out to 21 bars (horizon 20 needs it)
    )
    out_base = stops.target_outcome_by_horizon(bars, 0, 100.0, target_price=110.0, stop_price=95.0, qty=10, adv_inr=None)
    resolved_offset = out_base[5]["target_hit_session"]
    assert resolved_offset == 2

    poisoned = _poison_after(bars, resolved_offset)
    pd.testing.assert_frame_equal(
        poisoned.iloc[: resolved_offset + 1].reset_index(drop=True), bars.iloc[: resolved_offset + 1].reset_index(drop=True)
    )
    out_poisoned = stops.target_outcome_by_horizon(poisoned, 0, 100.0, target_price=110.0, stop_price=95.0, qty=10, adv_inr=None)
    for h in (3, 5, 10, 20):
        assert out_base[h] == out_poisoned[h], f"horizon {h} leaked bars beyond the walk's own resolution offset"

    # Non-vacuity: a target that is only ever reached via the poisoned filler bars (never in the
    # base frame) MUST differ once poisoned -- otherwise this probe would pass even if
    # `target_outcome_by_horizon` secretly ignored the `bars` object entirely.
    never_reached_base = stops.target_outcome_by_horizon(bars, 0, 100.0, target_price=9000.0, stop_price=1.0, qty=10, adv_inr=None)
    never_reached_poisoned = stops.target_outcome_by_horizon(poisoned, 0, 100.0, target_price=9000.0, stop_price=1.0, qty=10, adv_inr=None)
    assert never_reached_base[20]["neither_hit"] is True
    assert never_reached_poisoned[20]["neither_hit"] is False  # the poisoned 9999-high bars DO reach it


# ── Mandatory negative control ───────────────────────────────────────────────────────────


def _peeking_adv(bars: pd.DataFrame, t: int, n: int) -> float:
    """NEGATIVE CONTROL ONLY -- deliberately PIT-broken. Averages traded value over the WHOLE
    frame it is handed instead of the trailing n-bar window ending at t -- exactly the mistake
    of forgetting to slice/window at all. Must never be imported outside this test file."""
    return float((bars["close"] * bars["volume"]).mean())


def test_negative_control_a_full_frame_peek_is_caught_while_the_real_adv_is_not():
    base = confirmed_rectangle_with_runway(tail_len=30)
    row_base = _one_event(base)
    t_idx = row_base["confirmation_bar_index"]
    poisoned = _poison_after(base, t_idx)

    pd.testing.assert_frame_equal(
        poisoned.iloc[: t_idx + 1].reset_index(drop=True), base.iloc[: t_idx + 1].reset_index(drop=True)
    )

    peek_a = _peeking_adv(base, t_idx, n=20)
    peek_b = _peeking_adv(poisoned, t_idx, n=20)
    assert peek_a != peek_b, (
        "negative control failed to detect the leak -- a probe that stays green against a "
        "broken implementation proves nothing"
    )

    # And the REAL implementation shows no such difference for the identical (base, poisoned, t) triple.
    real_a = outcomes.adv_inr_at(base, t_idx, n=20)
    real_b = outcomes.adv_inr_at(poisoned, t_idx, n=20)
    assert real_a == real_b


def _peeking_target_reached_within_horizon(bars: pd.DataFrame, entry_index: int, target_price: float) -> bool:
    """NEGATIVE CONTROL ONLY -- deliberately horizon-unbounded. Scans every bar from
    `entry_index` to the END of whatever frame it is handed, ignoring the horizon cap entirely
    -- exactly the mistake of forgetting to bound the walk to `max_offset` (§37.3's "over each
    horizon" is not optional). Must never be imported outside this test file."""
    return bool((bars["high"].iloc[entry_index:] >= target_price).any())


def test_negative_control_an_unbounded_horizon_scan_is_caught_while_the_real_walk_is_not():
    bars = raw_bars(
        [(100.0, 104.0, 98.0, 102.0, 1e5), (102.0, 106.0, 100.0, 104.0, 1e5)]
        + [(103.0, 104.0, 102.0, 103.0, 1e5)] * 6  # flat -- target 9000 never reached in this base frame
    )
    poisoned = _poison_after(bars, 1)  # poison strictly after offset 1 -- outside horizon h=1's own window
    pd.testing.assert_frame_equal(poisoned.iloc[:2].reset_index(drop=True), bars.iloc[:2].reset_index(drop=True))

    peek_a = _peeking_target_reached_within_horizon(bars, 0, target_price=9000.0)
    peek_b = _peeking_target_reached_within_horizon(poisoned, 0, target_price=9000.0)
    assert peek_a != peek_b, (
        "negative control failed to detect the leak -- a probe that stays green against a "
        "broken implementation proves nothing"
    )

    # The REAL, horizon-bounded walk shows no such difference for horizon 1 (offsets 0-1 only --
    # the poisoned bars at offset >= 2 are outside that horizon's own window by construction).
    real_a = stops.target_outcome_by_horizon(bars, 0, 100.0, target_price=9000.0, stop_price=1.0, qty=10, adv_inr=None, horizons=(1,))
    real_b = stops.target_outcome_by_horizon(poisoned, 0, 100.0, target_price=9000.0, stop_price=1.0, qty=10, adv_inr=None, horizons=(1,))
    assert real_a == real_b
