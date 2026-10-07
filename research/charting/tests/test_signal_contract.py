"""Phase 1 signal/alert contract (§36, Amendment E position 1).

These tests pin the things that would be expensive to discover later: that the contract's states
agree with the module that already derives them, that the transition table cannot drift into a
backwards edge, that the Amendment E removals really are absent, and that the timestamp rule that
keeps look-ahead out is actually enforced.
"""
import datetime as dt

import pytest

from research.charting import signal_contract as c
from research.charting import states


# ── states ──────────────────────────────────────────────────────────────────────────────────────
def test_every_state_has_a_transition_entry_and_vice_versa():
    assert set(c.SIGNAL_STATES) == set(c.TRANSITIONS)
    for frm, tos in c.TRANSITIONS.items():
        for to in tos:
            assert to in c.TRANSITIONS, f"{frm} -> {to} targets an undeclared state"


def test_the_research_states_match_states_py_exactly():
    """The canonical names live in states.py; this contract must not fork them.

    Until 2026-09-23 states.py carried six and the contract's extra two were NOT_TRIGGERED and
    INCONCLUSIVE, pending owner decision #110. #110 is now wired, so the two sets are equal and
    the gap this test used to document is closed."""
    assert set(c.SIGNAL_STATES) == set(states.RESEARCH_STATES)
    assert {c.NOT_TRIGGERED, c.INCONCLUSIVE} <= set(states.RESEARCH_STATES)


def test_terminal_states_have_no_successors():
    for s in c.TERMINAL_STATES:
        assert c.TRANSITIONS[s] == frozenset(), f"{s} is terminal but has successors"
        assert c.is_terminal(s)


def test_the_forward_path_never_goes_backwards():
    order = [c.FORMING, c.EARLY_SIGNAL, c.BREAKOUT_CANDIDATE, c.CONFIRMED_BREAKOUT]
    rank = {s: i for i, s in enumerate(order)}
    for frm, tos in c.TRANSITIONS.items():
        if frm not in rank:
            continue
        for to in tos:
            if to in rank:
                assert rank[to] > rank[frm], f"{frm} -> {to} is a backwards edge"


# ── transitions ─────────────────────────────────────────────────────────────────────────────────
def test_a_legal_transition_passes():
    c.validate_transition(c.FORMING, c.EARLY_SIGNAL)
    c.validate_transition(c.BREAKOUT_CANDIDATE, c.CONFIRMED_BREAKOUT)
    c.validate_transition(c.CONFIRMED_BREAKOUT, c.FAILED_BREAKOUT)


def test_a_state_does_not_transition_to_itself():
    with pytest.raises(c.InvalidTransition, match="does not transition to itself"):
        c.validate_transition(c.FORMING, c.FORMING)


def test_a_terminal_state_cannot_be_left():
    with pytest.raises(c.InvalidTransition, match="terminal"):
        c.validate_transition(c.FAILED_BREAKOUT, c.FORMING)


def test_skipping_confirmation_is_rejected():
    """EARLY_SIGNAL must not jump to CONFIRMED_BREAKOUT: an unconfirmed pattern is never a breakout."""
    with pytest.raises(c.InvalidTransition):
        c.validate_transition(c.EARLY_SIGNAL, c.CONFIRMED_BREAKOUT)


def test_unknown_state_is_rejected_rather_than_ignored():
    with pytest.raises(ValueError, match="unknown signal state"):
        c.validate_transition("BREAKOUT", c.FORMING)


# ── the PRD mapping ─────────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("prd,research", [
    ("WATCH", c.FORMING), ("READY", c.EARLY_SIGNAL),
    ("TRIGGERED", c.BREAKOUT_CANDIDATE), ("CONFIRMED", c.CONFIRMED_BREAKOUT),
])
def test_prd_names_map_to_research_names(prd, research):
    assert c.prd_state(prd) == research
    assert c.prd_state(prd.lower()) == research


def test_prd_invalidated_refuses_to_merge_two_distinct_states():
    """Amendment E: INVALIDATED and FAILED_BREAKOUT 'must not be merged'."""
    with pytest.raises(ValueError, match="must not be merged"):
        c.prd_state("INVALIDATED")


def test_retest_and_continuation_are_events_not_states():
    for e in c.ROW_EVENTS:
        assert e not in c.SIGNAL_STATES
    assert any("RETEST" in e for e in c.ROW_EVENTS)
    assert "CONTINUATION" in c.ROW_EVENTS


# ── Amendment E removals ────────────────────────────────────────────────────────────────────────
def test_there_is_no_headline_score_field():
    """Position 2: the seven component bars stay, the single 0-100 number goes."""
    assert "score" not in c.SIGNAL_FIELDS
    assert "signal_score" not in c.SIGNAL_FIELDS
    assert "score_components" in c.SIGNAL_FIELDS


def test_setup_fields_are_reserved_but_flagged_owner_only():
    """Position 3: entry/stop/targets stay behind the owner allowlist until NI-1a is answered."""
    for f in ("entry", "stop", "targets"):
        assert f in c.SIGNAL_FIELDS
        assert f in c.OWNER_ONLY_FIELDS
        assert "OWNER-ONLY" in c.SIGNAL_FIELDS[f]


# ── timestamps ──────────────────────────────────────────────────────────────────────────────────
def test_valid_timestamps_pass():
    bar = dt.datetime(2026, 9, 23, 14, 45)
    c.validate_timestamps(bar, bar + dt.timedelta(minutes=15), bar + dt.timedelta(minutes=16))


def test_a_signal_known_at_its_bar_open_is_rejected():
    """The look-ahead guard: a bar is known at its close, never its open."""
    bar = dt.datetime(2026, 9, 23, 14, 45)
    with pytest.raises(ValueError, match="known at its close"):
        c.validate_timestamps(bar, bar, bar + dt.timedelta(minutes=1))


def test_publishing_before_knowing_is_rejected():
    bar = dt.datetime(2026, 9, 23, 14, 45)
    with pytest.raises(ValueError, match="publish before knowing"):
        c.validate_timestamps(bar, bar + dt.timedelta(minutes=15), bar + dt.timedelta(minutes=5))


def test_missing_timestamps_are_rejected():
    with pytest.raises(ValueError, match="all required"):
        c.validate_timestamps(dt.datetime(2026, 9, 23), None, dt.datetime(2026, 9, 23))


# ── alerts ──────────────────────────────────────────────────────────────────────────────────────
def test_dedupe_key_is_stable_for_the_same_bar():
    bar = dt.datetime(2026, 9, 23, 14, 45)
    a = c.dedupe_key("RELIANCE", "15minute", "RECTANGLE", c.CONFIRMED_BREAKOUT, bar)
    b = c.dedupe_key("RELIANCE", "15minute", "RECTANGLE", c.CONFIRMED_BREAKOUT, bar)
    assert a == b


def test_dedupe_key_separates_timeframes_and_bars():
    bar = dt.datetime(2026, 9, 23, 14, 45)
    base = c.dedupe_key("RELIANCE", "15minute", "RECTANGLE", c.CONFIRMED_BREAKOUT, bar)
    assert base != c.dedupe_key("RELIANCE", "60minute", "RECTANGLE", c.CONFIRMED_BREAKOUT, bar)
    assert base != c.dedupe_key("RELIANCE", "15minute", "RECTANGLE", c.CONFIRMED_BREAKOUT, bar + dt.timedelta(minutes=15))


def test_dedupe_key_rejects_an_unknown_timeframe():
    with pytest.raises(ValueError, match="unknown timeframe"):
        c.dedupe_key("RELIANCE", "1W", "RECTANGLE", c.FORMING, dt.datetime(2026, 9, 23))


def test_every_alert_type_names_a_real_state_or_event():
    joined = " ".join(c.ALERT_TYPES.values())
    assert c.CONFIRMED_BREAKOUT in joined and c.FAILED_BREAKOUT in joined
    assert "timeframe" in c.ALERT_FIELDS  # §17: every alert displays its timeframe


# ── versioning ──────────────────────────────────────────────────────────────────────────────────
def test_contract_hash_is_deterministic():
    assert c.contract_hash() == c.contract_hash()
    assert len(c.contract_hash()) == 64


def test_serialisable_is_json_round_trippable():
    import json
    assert json.loads(json.dumps(c.serialisable()))["version"] == c.CONTRACT_VERSION
