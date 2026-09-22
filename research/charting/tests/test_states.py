"""37.6 pattern research-state mapping tests -- `research/charting/states.py`.

Covers: every documented (state -> research_state) / (stage -> research_state) pair, the
"unconfirmed pattern is never called a breakout" rule, unknown-value / both-given /
neither-given failures, and unknown-direction failures.
"""
from __future__ import annotations

import pytest

from research.charting import states
from research.charting.lifecycle import LifecycleState


# ── section 11 lifecycle state -> research_state (every enum member) ────────────────────


@pytest.mark.parametrize(
    "lifecycle_state, volume, expected",
    [
        (LifecycleState.CANDIDATE.value, None, states.FORMING),
        (LifecycleState.FORMING.value, None, states.FORMING),
        (LifecycleState.GEOMETRY_VALID.value, None, states.EARLY_SIGNAL),
        (LifecycleState.BREAKOUT_ATTEMPT.value, None, states.EARLY_SIGNAL),  # wick only: no close beyond the level
        # owner's flow: close beyond the level -> BREAKOUT_CANDIDATE; + volume confirmation -> CONFIRMED_BREAKOUT
        (LifecycleState.PRICE_CONFIRMED.value, "PENDING", states.BREAKOUT_CANDIDATE),
        (LifecycleState.PRICE_CONFIRMED.value, "FAIL", states.BREAKOUT_CANDIDATE),
        (LifecycleState.PRICE_CONFIRMED.value, None, states.BREAKOUT_CANDIDATE),
        (LifecycleState.PRICE_CONFIRMED.value, "PASS", states.CONFIRMED_BREAKOUT),
        (LifecycleState.PRICE_CONFIRMED.value, "CONFIRMED", states.CONFIRMED_BREAKOUT),
        (LifecycleState.VOLUME_CONFIRMED.value, None, states.CONFIRMED_BREAKOUT),
        (LifecycleState.CONTEXT_VALIDATED.value, "PENDING", states.BREAKOUT_CANDIDATE),
        (LifecycleState.CONTEXT_VALIDATED.value, "PASS", states.CONFIRMED_BREAKOUT),
        (LifecycleState.RESEARCH_ELIGIBLE.value, "PENDING", states.BREAKOUT_CANDIDATE),  # never COMPLETED
        (LifecycleState.RESEARCH_ELIGIBLE.value, "PASS", states.CONFIRMED_BREAKOUT),
        (LifecycleState.FAILED.value, None, states.FAILED_BREAKOUT),
        # never broke out / could not be assessed: unmapped pending an owner decision, never FAILED_BREAKOUT
        (LifecycleState.INVALIDATED.value, None, None),
        (LifecycleState.EXPIRED.value, None, None),
        (LifecycleState.DATA_BLOCKED.value, None, None),
        (LifecycleState.UNRESOLVED.value, None, None),
    ],
)
def test_every_lifecycle_state_maps(lifecycle_state, volume, expected):
    for direction in ("BULLISH", "BEARISH", "NEUTRAL"):
        assert states.derive_research_state(lifecycle_state, None, direction, volume_status=volume) == expected


def test_completed_is_never_produced_from_the_lifecycle():
    for state in LifecycleState:
        for volume in ("PASS", "FAIL", "PENDING", None):
            assert states.derive_research_state(state.value, None, "BULLISH", volume_status=volume) != states.COMPLETED


def test_unknown_volume_status_raises():
    with pytest.raises(ValueError):
        states.derive_research_state(LifecycleState.PRICE_CONFIRMED.value, None, "BULLISH", volume_status="MAYBE")


def test_every_lifecycle_state_enum_member_is_covered_by_the_map():
    """Closed-set check: every `LifecycleState` member the enum currently defines has an
    explicit entry in `_LIFECYCLE_STATE_MAP` -- catches a future enum addition this module
    has not been updated for, independent of the parametrized test above."""
    for member in LifecycleState:
        assert member.value in states._LIFECYCLE_STATE_MAP, member.value


# ── section 34 early formation stage -> research_state (every FormationStage literal) ───


@pytest.mark.parametrize(
    "early_stage, expected",
    [
        ("EARLY_FORMATION", states.FORMING),
        ("PATTERN_DEVELOPING", states.EARLY_SIGNAL),
        ("BREAKOUT_READINESS", states.BREAKOUT_CANDIDATE),
    ],
)
def test_every_early_stage_maps(early_stage, expected):
    assert states.derive_research_state(None, early_stage, "BULLISH") == expected
    assert states.derive_research_state(None, early_stage, "BEARISH") == expected


def test_early_stage_literal_matches_records_py():
    """`early/records.py`'s `FormationStage` is a `typing.Literal`, so its values cannot be
    introspected at runtime -- this test pins the 3 literal strings it actually uses
    (verified by reading `classify_stage()`'s own return values) so a future rename there
    is caught here rather than silently drifting."""
    from research.charting.early.records import classify_stage
    from research.charting.early.maturity import LiveMaturity
    from research.charting.early.scoring import ScoreValue

    unavailable = ScoreValue(value=None, status="UNAVAILABLE")
    assert classify_stage(live_mat=LiveMaturity(0, 15, 0.0), readiness=unavailable, formation=unavailable) == "EARLY_FORMATION"
    assert classify_stage(live_mat=LiveMaturity(6, 15, 0.4), readiness=unavailable, formation=unavailable) == "PATTERN_DEVELOPING"
    ready = ScoreValue(value=0.9, status="OK")
    assert classify_stage(live_mat=LiveMaturity(10, 15, 0.67), readiness=ready, formation=unavailable) == "BREAKOUT_READINESS"


# ── section 37.6: "an unconfirmed pattern is never called a breakout" ───────────────────


@pytest.mark.parametrize(
    "unconfirmed_state",
    [
        LifecycleState.CANDIDATE.value,
        LifecycleState.FORMING.value,
        LifecycleState.GEOMETRY_VALID.value,
        LifecycleState.BREAKOUT_ATTEMPT.value,
        LifecycleState.FAILED.value,
        LifecycleState.INVALIDATED.value,
        LifecycleState.EXPIRED.value,
        LifecycleState.DATA_BLOCKED.value,
        LifecycleState.UNRESOLVED.value,
    ],
)
def test_unconfirmed_states_never_map_to_confirmed_breakout_or_completed(unconfirmed_state):
    for volume in ("PASS", "FAIL", "PENDING", None):  # even a passing volume component cannot confirm an unconfirmed state
        result = states.derive_research_state(unconfirmed_state, None, "NEUTRAL", volume_status=volume)
        assert result not in (states.CONFIRMED_BREAKOUT, states.COMPLETED)


# ── failure modes: unknown value, both given, neither given, unknown direction ──────────


def test_unknown_lifecycle_state_raises():
    with pytest.raises(ValueError):
        states.derive_research_state("NOT_A_REAL_STATE", None, "BULLISH")


def test_unknown_early_stage_raises():
    with pytest.raises(ValueError):
        states.derive_research_state(None, "NOT_A_REAL_STAGE", "BULLISH")


def test_both_given_raises():
    with pytest.raises(ValueError):
        states.derive_research_state(LifecycleState.FORMING.value, "EARLY_FORMATION", "BULLISH")


def test_neither_given_raises():
    with pytest.raises(ValueError):
        states.derive_research_state(None, None, "BULLISH")


def test_unknown_direction_raises():
    with pytest.raises(ValueError):
        states.derive_research_state(LifecycleState.FORMING.value, None, "SIDEWAYS")
