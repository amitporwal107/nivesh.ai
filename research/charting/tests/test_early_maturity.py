"""§34.7.1 maturity definitions — docs/charting.md §34.7.1, test-plan.md Part C."""
from __future__ import annotations

import inspect

import pytest

from research.charting.config import CONFIG
from research.charting.early.maturity import (
    checkpoints_for,
    live_maturity,
    offline_checkpoint_index,
)


# ── Live definition (§34.7.1 def 1) ──────────────────────────────────────────


def test_live_maturity_grows_linearly_then_caps_at_one():
    min_len = CONFIG["minimum_pattern_length"]
    m0 = live_maturity(0)
    assert m0.maturity == 0.0
    m_half = live_maturity(min_len // 2)
    assert m_half.maturity == pytest.approx((min_len // 2) / min_len)
    m_full = live_maturity(min_len)
    assert m_full.maturity == 1.0
    m_over = live_maturity(min_len * 10)
    assert m_over.maturity == 1.0  # capped, never exceeds 1.0


def test_live_maturity_uses_configured_minimum_pattern_length():
    m = live_maturity(3)
    assert m.minimum_pattern_length == CONFIG["minimum_pattern_length"]


def test_live_maturity_rejects_negative_bars():
    with pytest.raises(ValueError):
        live_maturity(-1)


def test_live_maturity_signature_has_no_t_end_or_bars_parameter():
    """Test-plan.md Part C's "trivial-pass control": the live definition must be
    unaffected by poisoning `t_end` BY CONSTRUCTION -- there is nothing in its
    signature that could carry a future bar or a final-length value in the first
    place."""
    params = set(inspect.signature(live_maturity).parameters)
    assert not any("end" in p or "bars" in p or "length_actual" in p for p in params if p != "bars_since_first_detection")
    assert params == {"bars_since_first_detection", "cfg"}


# ── Offline definition (§34.7.1 def 2) ───────────────────────────────────────


@pytest.mark.parametrize("t_start,t_end,fraction,expected", [
    (0, 30, 0.2, 6),
    (0, 30, 0.4, 12),
    (0, 30, 0.6, 18),
    (0, 30, 0.8, 24),
    (14, 40, 0.2, 19),
    (14, 40, 0.4, 24),
    (14, 40, 0.6, 30),
    (14, 40, 0.8, 35),
])
def test_offline_checkpoint_index_matches_the_formula(t_start, t_end, fraction, expected):
    ck = offline_checkpoint_index(t_start, t_end, fraction)
    assert ck.t_ck == expected == t_start + round(fraction * (t_end - t_start))
    assert ck.t_start == t_start
    assert ck.t_end == t_end
    assert ck.fraction == fraction


def test_offline_checkpoint_index_rejects_t_end_before_t_start():
    with pytest.raises(ValueError):
        offline_checkpoint_index(10, 5, 0.5)


def test_offline_checkpoint_index_rejects_fraction_outside_unit_interval():
    with pytest.raises(ValueError):
        offline_checkpoint_index(0, 10, 1.5)
    with pytest.raises(ValueError):
        offline_checkpoint_index(0, 10, -0.1)


def test_checkpoints_for_uses_the_frozen_config_fractions_verbatim():
    """§34.9 AC5: the four maturity checkpoints (20/40/60/80%) are each evaluated --
    read from CONFIG, never a locally hard-coded copy of the list."""
    cks = checkpoints_for(10, 50, CONFIG)
    assert [c.fraction for c in cks] == CONFIG["early_maturity_checkpoints"] == [0.2, 0.4, 0.6, 0.8]
    assert [c.t_ck for c in cks] == [18, 26, 34, 42]


# ── Negative control: naive "percent of formation" is unstable under t_end revision ──


def _naive_percent_of_formation(current_index: int, t_start: int, t_end: int) -> float:
    """NEGATIVE CONTROL ONLY -- deliberately the exact leak §34.7.1 rules out: "percent
    of formation" against a still-unknown final length. `t_end` does not exist yet
    during real-time detection, so this formula cannot even be evaluated live; it is
    reproduced here only to demonstrate WHY `live_maturity()` has no such parameter."""
    return (current_index - t_start) / (t_end - t_start)


def test_negative_control_naive_percent_of_formation_is_unstable_under_t_end_revision():
    """This negative control is checked on a different axis than the bar-value
    poisoning probe in test_early_lookahead.py: `_naive_percent_of_formation` depends
    only on integer bar INDICES, not bar values, so mutating OHLCV data after some `t`
    could never move it at all -- that would be a trivially-passing (meaningless)
    probe for this particular formula. Its actual leak surfaces when the assumed
    `t_end` itself is later revised (the pattern ran longer than first guessed), which
    is exactly what "in live use `t_end` is not yet known" (§34.7.1) means in practice.
    """
    t_start, current_index = 14, 24
    optimistic_t_end = 30  # a live guess: "this looks about ready to finish soon"
    actual_t_end = 40  # the pattern actually keeps consolidating much longer

    naive_early_guess = _naive_percent_of_formation(current_index, t_start, optimistic_t_end)
    naive_revised = _naive_percent_of_formation(current_index, t_start, actual_t_end)
    assert naive_early_guess != naive_revised, (
        "a percent-of-formation value computed from an assumed t_end retroactively changes "
        "when the true completion point differs -- exactly the leak §34.7.1 exists to prevent"
    )

    # live_maturity, by contrast, is invariant: it was never given a t_end to revise.
    bars_since = current_index - t_start
    lm_a = live_maturity(bars_since)
    lm_b = live_maturity(bars_since)  # nothing about "t_end" could even be threaded through
    assert lm_a == lm_b
    assert "t_end" not in inspect.signature(live_maturity).parameters
