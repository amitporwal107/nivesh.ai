"""`research_eligible()` truth table (spec gap G-2, incl. every require_* flag),
independence of the seven component statuses, deterministic lifecycle/retest
transitions, and the PatternEvent record.
"""
from __future__ import annotations

import dataclasses
import itertools

import pandas as pd
import pytest

from research.charting.config import CONFIG, config_hash
from research.charting.lifecycle import (
    ALLOWED_TRANSITIONS,
    RETEST_ALLOWED_TRANSITIONS,
    REQUIRE_FLAG_TO_COMPONENT,
    ComponentStatus,
    DataQualityStatus,
    FailureReason,
    LifecycleState,
    PatternComponents,
    PatternEvent,
    RetestState,
    RuleResult,
    research_eligible,
    retest_transition,
    transition,
)

CONFIRMED = ComponentStatus.CONFIRMED
PENDING = ComponentStatus.PENDING
FAILED = ComponentStatus.FAILED


def _components(**overrides) -> PatternComponents:
    base = dict(geometry=CONFIRMED, price=CONFIRMED, data_quality=DataQualityStatus.VALID)
    base.update(overrides)
    return PatternComponents(**base)


# ── research_eligible(): baseline gates ──────────────────────────────────────


def test_eligible_requires_geometry_confirmed():
    c = _components(geometry=PENDING)
    assert research_eligible(c, CONFIG) is False
    c = _components(geometry=FAILED)
    assert research_eligible(c, CONFIG) is False


def test_eligible_requires_price_confirmed():
    c = _components(price=PENDING)
    assert research_eligible(c, CONFIG) is False
    c = _components(price=FAILED)
    assert research_eligible(c, CONFIG) is False


@pytest.mark.parametrize("blocking", [DataQualityStatus.INVALID, DataQualityStatus.BLOCKED, DataQualityStatus.PIT_UNVERIFIED])
def test_eligible_blocked_by_specific_data_quality_statuses(blocking):
    c = _components(data_quality=blocking)
    assert research_eligible(c, CONFIG) is False


@pytest.mark.parametrize("non_blocking", [DataQualityStatus.VALID, DataQualityStatus.STALE, DataQualityStatus.PARTIAL])
def test_eligible_not_blocked_by_the_other_data_quality_statuses(non_blocking):
    # Literal G-2 text: only {INVALID, BLOCKED, PIT_UNVERIFIED} block. STALE/PARTIAL
    # do not, even though a production system might want to warn about them.
    c = _components(data_quality=non_blocking)
    assert research_eligible(c, CONFIG) is True


def test_eligible_under_prd_defaults_ignores_volume_market_sector():
    # This IS the crux of spec G-2: under CONFIG's own defaults
    # (require_volume/market/sector = False), volume/market/sector statuses must
    # not affect eligibility at all -- otherwise nothing could ever be eligible,
    # since the PRD's §11 chain would never be traversable under its own defaults.
    assert CONFIG["require_volume_confirmation"] is False
    assert CONFIG["require_market_alignment"] is False
    assert CONFIG["require_sector_alignment"] is False

    for v, m, s in itertools.product([PENDING, CONFIRMED, FAILED], repeat=3):
        c = _components(volume=v, market=m, sector=s)
        assert research_eligible(c, CONFIG) is True, (v, m, s)


# ── research_eligible(): every require_* flag, individually and combined ─────


@pytest.mark.parametrize("flag_key,component_name", sorted(REQUIRE_FLAG_TO_COMPONENT.items()))
def test_eligible_gated_by_each_require_flag_when_true(flag_key, component_name):
    cfg = dict(CONFIG, **{flag_key: True})
    not_confirmed = _components(**{component_name: PENDING})
    assert research_eligible(not_confirmed, cfg) is False

    confirmed = _components(**{component_name: CONFIRMED})
    assert research_eligible(confirmed, cfg) is True


@pytest.mark.parametrize(
    "flag_key,component_name",
    [
        (f, c)
        for f, c in sorted(REQUIRE_FLAG_TO_COMPONENT.items())
        # require_close_confirmation -> price is excluded here on purpose: `price`
        # is baseline-required unconditionally ("geometry AND price confirmed"),
        # so this flag never actually frees it up -- see the next test instead.
        if f != "require_close_confirmation"
    ],
)
def test_eligible_not_gated_by_a_require_flag_when_false(flag_key, component_name):
    cfg = dict(CONFIG, **{flag_key: False})
    c = _components(**{component_name: PENDING})
    assert research_eligible(c, cfg) is True


def test_require_close_confirmation_is_redundant_with_the_unconditional_price_gate():
    # price is required unconditionally by G-2's baseline condition, so toggling
    # require_close_confirmation changes nothing either way -- it maps to `price`,
    # which was never "free." This documents that redundancy explicitly rather
    # than leaving it as an implicit assumption.
    price_pending = _components(price=PENDING)
    assert research_eligible(price_pending, dict(CONFIG, require_close_confirmation=True)) is False
    assert research_eligible(price_pending, dict(CONFIG, require_close_confirmation=False)) is False

    price_confirmed = _components()
    assert research_eligible(price_confirmed, dict(CONFIG, require_close_confirmation=True)) is True
    assert research_eligible(price_confirmed, dict(CONFIG, require_close_confirmation=False)) is True


def test_eligible_full_combinatorial_require_flag_truth_table():
    """All 16 combinations of the four require_* flags: eligible iff every flagged
    component is CONFIRMED, regardless of unflagged components' statuses."""
    flags = sorted(REQUIRE_FLAG_TO_COMPONENT)
    for combo in itertools.product([False, True], repeat=len(flags)):
        cfg = dict(CONFIG, **dict(zip(flags, combo)))
        required_components = {
            REQUIRE_FLAG_TO_COMPONENT[f] for f, required in zip(flags, combo) if required
        }

        # Every required component confirmed, everything else PENDING -> eligible.
        all_satisfied = _components(**{name: CONFIRMED for name in required_components})
        assert research_eligible(all_satisfied, cfg) is True, combo

        # Exactly one required component NOT confirmed -> not eligible.
        for missing in required_components:
            statuses = {name: CONFIRMED for name in required_components}
            statuses[missing] = PENDING
            c = _components(**statuses)
            assert research_eligible(c, cfg) is False, (combo, missing)


def test_eligible_predicate_is_configurable_and_does_not_mutate_shared_config():
    frozen_before = dict(CONFIG)
    cfg = dict(CONFIG, require_volume_confirmation=True)
    c = _components(volume=PENDING)
    assert research_eligible(c, cfg) is False
    assert research_eligible(c, CONFIG) is True  # shared CONFIG unaffected
    assert CONFIG == frozen_before  # never mutated


def test_eligible_defaults_cfg_parameter_to_shared_config():
    c = _components()
    assert research_eligible(c) == research_eligible(c, CONFIG)


# ── Component statuses stay independent ──────────────────────────────────────


def test_pattern_components_default_to_pending_and_pit_unverified():
    c = PatternComponents()
    assert c.geometry is PENDING
    assert c.price is PENDING
    assert c.volume is PENDING
    assert c.volatility is PENDING
    assert c.market is PENDING
    assert c.sector is PENDING
    assert c.data_quality is DataQualityStatus.PIT_UNVERIFIED


def test_no_composite_or_derived_field_exists_on_pattern_components():
    field_names = {f.name for f in dataclasses.fields(PatternComponents)}
    assert field_names == {"geometry", "price", "volume", "volatility", "market", "sector", "data_quality"}
    for banned in ("score", "confidence", "composite", "overall", "status"):
        assert banned not in field_names


@pytest.mark.parametrize("field_name", ["geometry", "price", "volume", "volatility", "market", "sector"])
def test_mutating_one_component_leaves_every_other_field_untouched(field_name):
    c = PatternComponents()
    other_fields = [f.name for f in dataclasses.fields(c) if f.name != field_name]
    before = {name: getattr(c, name) for name in other_fields}

    setattr(c, field_name, CONFIRMED if field_name != "data_quality" else DataQualityStatus.VALID)

    after = {name: getattr(c, name) for name in other_fields}
    assert before == after


def test_mutating_data_quality_leaves_every_other_field_untouched():
    c = PatternComponents()
    other_fields = [f.name for f in dataclasses.fields(c) if f.name != "data_quality"]
    before = {name: getattr(c, name) for name in other_fields}
    c.data_quality = DataQualityStatus.STALE
    after = {name: getattr(c, name) for name in other_fields}
    assert before == after


def test_all_seven_components_can_be_set_independently_in_every_combination():
    # A small but genuine sweep: set every component to a distinct value and check
    # every field holds exactly what was assigned to it (no cross-talk).
    c = PatternComponents(
        geometry=CONFIRMED,
        price=FAILED,
        volume=PENDING,
        volatility=CONFIRMED,
        market=FAILED,
        sector=PENDING,
        data_quality=DataQualityStatus.STALE,
    )
    assert c.geometry is CONFIRMED
    assert c.price is FAILED
    assert c.volume is PENDING
    assert c.volatility is CONFIRMED
    assert c.market is FAILED
    assert c.sector is PENDING
    assert c.data_quality is DataQualityStatus.STALE


# ── Enum completeness (guards against a typo silently dropping a PRD state) ──


def test_lifecycle_state_matches_prd_11():
    assert {s.value for s in LifecycleState} == {
        "CANDIDATE", "FORMING", "GEOMETRY_VALID", "BREAKOUT_ATTEMPT", "PRICE_CONFIRMED",
        "VOLUME_CONFIRMED", "CONTEXT_VALIDATED", "RESEARCH_ELIGIBLE",
        "FAILED", "INVALIDATED", "EXPIRED", "DATA_BLOCKED", "UNRESOLVED",
    }


def test_retest_state_matches_prd_13_9():
    assert {s.value for s in RetestState} == {
        "BREAKOUT_CONFIRMED", "RETEST_PENDING", "RETEST_SUCCESSFUL", "RETEST_FAILED", "BREAKOUT_FAILED",
    }


def test_failure_reason_matches_prd_17_3():
    assert {r.value for r in FailureReason} == {
        "FALSE_BREAKOUT", "FAILED_RETEST", "LOW_VOLUME_FAILURE", "GAP_FAILURE",
        "MARKET_REVERSAL", "SECTOR_REVERSAL", "DATA_FAILURE", "UNRESOLVED",
    }


def test_data_quality_status_matches_prd_9_2():
    assert {s.value for s in DataQualityStatus} == {
        "VALID", "PARTIAL", "STALE", "INVALID", "PIT_UNVERIFIED", "BLOCKED",
    }


# ── Lifecycle transitions: deterministic, primary chain + G-2 skip edges ─────


@pytest.mark.parametrize(
    "current,target",
    [
        (LifecycleState.CANDIDATE, LifecycleState.FORMING),
        (LifecycleState.FORMING, LifecycleState.GEOMETRY_VALID),
        (LifecycleState.GEOMETRY_VALID, LifecycleState.BREAKOUT_ATTEMPT),
        (LifecycleState.BREAKOUT_ATTEMPT, LifecycleState.PRICE_CONFIRMED),
        (LifecycleState.PRICE_CONFIRMED, LifecycleState.VOLUME_CONFIRMED),
        (LifecycleState.VOLUME_CONFIRMED, LifecycleState.CONTEXT_VALIDATED),
        (LifecycleState.CONTEXT_VALIDATED, LifecycleState.RESEARCH_ELIGIBLE),
        # G-2 skip edges: the chain is the maximum state reached, not mandatory.
        (LifecycleState.PRICE_CONFIRMED, LifecycleState.CONTEXT_VALIDATED),
        (LifecycleState.PRICE_CONFIRMED, LifecycleState.RESEARCH_ELIGIBLE),
        (LifecycleState.VOLUME_CONFIRMED, LifecycleState.RESEARCH_ELIGIBLE),
    ],
)
def test_transition_allows_primary_chain_and_skip_edges(current, target):
    assert transition(current, target) == target


@pytest.mark.parametrize("live_state", [
    LifecycleState.CANDIDATE, LifecycleState.FORMING, LifecycleState.GEOMETRY_VALID,
    LifecycleState.BREAKOUT_ATTEMPT, LifecycleState.PRICE_CONFIRMED,
    LifecycleState.VOLUME_CONFIRMED, LifecycleState.CONTEXT_VALIDATED,
])
@pytest.mark.parametrize("terminal", [
    LifecycleState.FAILED, LifecycleState.INVALIDATED, LifecycleState.EXPIRED,
    LifecycleState.DATA_BLOCKED, LifecycleState.UNRESOLVED,
])
def test_transition_allows_any_live_state_to_any_terminal_state(live_state, terminal):
    assert transition(live_state, terminal) == terminal


@pytest.mark.parametrize("terminal", [
    LifecycleState.FAILED, LifecycleState.INVALIDATED, LifecycleState.EXPIRED,
    LifecycleState.DATA_BLOCKED, LifecycleState.UNRESOLVED, LifecycleState.RESEARCH_ELIGIBLE,
])
def test_terminal_states_have_no_outgoing_transitions(terminal):
    assert ALLOWED_TRANSITIONS[terminal] == frozenset()
    for target in LifecycleState:
        if target == terminal:
            continue
        with pytest.raises(ValueError):
            transition(terminal, target)


def test_transition_rejects_skipping_ahead_of_the_chain_illegally():
    # CANDIDATE cannot jump straight to BREAKOUT_ATTEMPT -- geometry must validate first.
    with pytest.raises(ValueError):
        transition(LifecycleState.CANDIDATE, LifecycleState.BREAKOUT_ATTEMPT)


def test_transition_rejects_self_transition():
    with pytest.raises(ValueError):
        transition(LifecycleState.FORMING, LifecycleState.FORMING)


def test_transition_is_pure_and_deterministic():
    results = {transition(LifecycleState.CANDIDATE, LifecycleState.FORMING) for _ in range(50)}
    assert results == {LifecycleState.FORMING}


def test_transition_accepts_string_values_too():
    assert transition("CANDIDATE", "FORMING") == LifecycleState.FORMING


# ── Retest transitions (§13.9) ────────────────────────────────────────────────


def test_retest_confirmation_is_optional_breakout_confirmed_can_fail_directly():
    # §12.5: "Retest confirmation must be optional because requiring a retest can
    # miss breakouts that continue without one."
    assert retest_transition(RetestState.BREAKOUT_CONFIRMED, RetestState.BREAKOUT_FAILED) == RetestState.BREAKOUT_FAILED
    assert retest_transition(RetestState.BREAKOUT_CONFIRMED, RetestState.RETEST_PENDING) == RetestState.RETEST_PENDING


def test_retest_pending_resolves_to_success_or_failure():
    assert retest_transition(RetestState.RETEST_PENDING, RetestState.RETEST_SUCCESSFUL) == RetestState.RETEST_SUCCESSFUL
    assert retest_transition(RetestState.RETEST_PENDING, RetestState.RETEST_FAILED) == RetestState.RETEST_FAILED


@pytest.mark.parametrize("terminal", [RetestState.RETEST_SUCCESSFUL, RetestState.RETEST_FAILED, RetestState.BREAKOUT_FAILED])
def test_retest_terminal_states_have_no_outgoing_transitions(terminal):
    assert RETEST_ALLOWED_TRANSITIONS[terminal] == frozenset()
    for target in RetestState:
        if target == terminal:
            continue
        with pytest.raises(ValueError):
            retest_transition(terminal, target)


def test_retest_transition_rejects_illegal_edge():
    with pytest.raises(ValueError):
        retest_transition(RetestState.RETEST_SUCCESSFUL, RetestState.RETEST_PENDING)


# ── PatternEvent record (§23.2) ───────────────────────────────────────────────


def test_pattern_event_carries_the_required_fields():
    event = PatternEvent(
        event_type="PRICE_CONFIRMATION",
        event_index=16,
        event_date=pd.Timestamp("2024-02-01"),
        rule_id="BULLISH_CLOSE_ABOVE_BREAKOUT_LEVEL",
        rule_result=RuleResult.PASS,
        observed_values={"close": 111.0, "breakout_level": 110.5},
    )
    assert event.event_type == "PRICE_CONFIRMATION"
    assert event.event_index == 16
    assert event.rule_id == "BULLISH_CLOSE_ABOVE_BREAKOUT_LEVEL"
    assert event.rule_result is RuleResult.PASS
    assert event.observed_values == {"close": 111.0, "breakout_level": 110.5}
    assert event.config_hash == config_hash()  # default factory ties to shared CONFIG
    assert len(event.config_hash) == 64


def test_pattern_event_config_hash_can_be_overridden_for_a_frozen_variant_cfg():
    variant = dict(CONFIG, require_volume_confirmation=True)
    event = PatternEvent(
        event_type="VOLUME_CONFIRMATION",
        event_index=16,
        event_date=pd.Timestamp("2024-02-01"),
        rule_id="RELATIVE_VOLUME_ABOVE_SUPPORTING",
        rule_result=RuleResult.FAIL,
        observed_values={"relative_volume": 0.90, "threshold": 1.00},
        config_hash=config_hash(variant),
    )
    assert event.config_hash == config_hash(variant)
    assert event.config_hash != config_hash(CONFIG)


def test_pattern_event_is_immutable():
    event = PatternEvent(
        event_type="X", event_index=0, event_date=pd.Timestamp("2024-01-01"),
        rule_id="R", rule_result=RuleResult.PASS, observed_values={},
    )
    with pytest.raises(dataclasses.FrozenInstanceError):
        event.event_type = "Y"
