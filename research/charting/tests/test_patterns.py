"""P0 pattern detectors — test-plan.md Part A fixtures #1-#5b, #10, #12 (with the corrected
levels: RECT-1's measured Wilder ATR-14 is ~2.4997, not 2.0, so 110.50/99.50 are never
hardcoded below — every expected level is derived from the fixture's own measured ATR).

Each fixture asserts its exact expected state/reason code AND that the non-expected states
did NOT occur (a fixture that only checks the happy path can't tell "right for the wrong
reason" from "right").
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from research.charting import validate
from research.charting.config import CONFIG, config_hash, relative_volume_band
from research.charting.lifecycle import LifecycleState
from research.charting.patterns import PatternSnapshot, detect_as_of
from research.charting.series import atr as atr_series_fn
from research.charting.tests import synth


def _rectangles(bars: pd.DataFrame, t: int | None = None, **kwargs) -> list[PatternSnapshot]:
    if t is None:
        t = len(bars) - 1
    pats = detect_as_of(bars, t, symbol="SYN1", **kwargs)
    return [p for p in pats if p.pattern_type == "RECTANGLE"]


def _event_types(pattern: PatternSnapshot) -> list[str]:
    return [e["event_type"] for e in pattern.events]


def _measured_atr_at(bars: pd.DataFrame, idx: int) -> float:
    return float(atr_series_fn(bars, period=CONFIG["atr_period"]).iloc[idx])


# ── CRITICAL fixture caveat: RECT-1's measured ATR is ~2.4997, not 2.0 ───────


def test_rect1_measured_atr_is_not_the_test_plans_nominal_2point0():
    """Guards every fixture below against silently reverting to the wrong hardcoded
    110.50/99.50 levels: the real breakout/breakdown levels must be derived from THIS
    number, not the test-plan's nominal ~2.0."""
    bars = synth.rect1()
    a = _measured_atr_at(bars, len(bars) - 1)
    assert a == pytest.approx(2.4997, abs=0.001)
    breakout_level = synth.RECT1_RESISTANCE + CONFIG["breakout_buffer_atr"] * a
    breakdown_level = synth.RECT1_SUPPORT - CONFIG["breakout_buffer_atr"] * a
    assert breakout_level != pytest.approx(110.50, abs=0.001)
    assert breakdown_level != pytest.approx(99.50, abs=0.001)
    assert breakout_level == pytest.approx(110.625, abs=0.01)
    assert breakdown_level == pytest.approx(99.375, abs=0.01)


# ── #1 — wick-only breakout ───────────────────────────────────────────────────


def test_fixture_01_wick_only_breakout_is_attempt_never_confirmed():
    bars = synth.fixture_01_wick_only_breakout(synth.rect1())
    rects = _rectangles(bars)
    assert len(rects) == 1
    rect = rects[0]

    assert rect.status == LifecycleState.BREAKOUT_ATTEMPT.value
    assert "PRICE_CONFIRMED" not in _event_types(rect)  # PASS condition: no PRICE_CONFIRMED event for bar16
    assert "WICK_BREACH_UPPER" in [e["rule_id"] for e in rect.events]
    assert rect.components["price"] == "PENDING"


# ── #2 — low-volume breakout ──────────────────────────────────────────────────


def test_fixture_02_low_volume_breakout_confirms_but_followthrough_volume_fails():
    bars = synth.fixture_02_low_volume_breakout(synth.rect1())
    rects = _rectangles(bars)
    assert len(rects) == 1
    rect = rects[0]

    assert rect.status == LifecycleState.PRICE_CONFIRMED.value
    assert "PRICE_CONFIRMED" in _event_types(rect)
    assert rect.components["price"] == "PASS"
    assert rect.components["volume"] == "FAIL"

    vol_rules = [r for r in rect.rules if r["rule_id"] == "FOLLOWTHROUGH_VOLUME_BELOW_MIN"]
    assert len(vol_rules) == 1
    assert vol_rules[0]["result"] == "FAIL"
    # Fix 5 (review 2026-09-22): `observed` is now a dict carrying both the raw relative-volume
    # reading and its descriptive WEAK/NORMAL/SUPPORTING/STRONG band (config.relative_volume_band)
    # — previously a bare float. The band is purely descriptive: it does not change this FAIL.
    assert vol_rules[0]["observed"]["relative_volume"] == pytest.approx(0.90)
    assert vol_rules[0]["observed"]["band"] == relative_volume_band(0.90)
    assert vol_rules[0]["threshold"] == pytest.approx(1.00)

    # PASS condition: never RESEARCH_ELIGIBLE via this bar (this package never emits that
    # status at all — see patterns.py module docstring's scope boundary).
    assert rect.status != LifecycleState.RESEARCH_ELIGIBLE.value


def test_followthrough_volume_rule_pass_also_records_the_band_descriptively():
    """Fix 5 (review 2026-09-22): config.relative_volume_band had no production caller.
    Wired into the follow-through volume rule's `observed` for BOTH the PASS and FAIL
    branches — bar16's rel-vol here is 1.20 (120k/100k), which clears the min-rel-volume
    gate (PASS) and bands as SUPPORTING."""
    bars = synth.fixture_03_close_back_inside(synth.rect1())
    rects = _rectangles(bars)
    vol_rules = [r for r in rects[0].rules if r["rule_id"] == "FOLLOWTHROUGH_VOLUME_BAND"]
    assert len(vol_rules) == 1
    assert vol_rules[0]["result"] == "PASS"
    assert vol_rules[0]["observed"]["relative_volume"] == pytest.approx(1.20)
    assert vol_rules[0]["observed"]["band"] == relative_volume_band(1.20)


# ── #3 — close back inside ────────────────────────────────────────────────────


def test_fixture_03_close_back_inside_is_false_breakout():
    bars = synth.fixture_03_close_back_inside(synth.rect1())
    rects = _rectangles(bars)
    assert len(rects) == 1
    rect = rects[0]

    assert rect.status == LifecycleState.FAILED.value
    failed = [e for e in rect.events if e["event_type"] == "FAILED"]
    assert len(failed) == 1
    assert failed[0]["rule_id"] == "FALSE_BREAKOUT"
    assert "RETEST_SUCCESSFUL" not in _event_types(rect)
    assert "RETEST_PENDING" not in _event_types(rect)  # never entered a retest zone (105 is deep inside)

    # transition happens at bar17, one bar after the bar16 confirmation.
    assert failed[0]["date"] > rect.formation_end


# ── #4 — false retest ──────────────────────────────────────────────────────────


def test_fixture_04_false_retest_is_failed_retest():
    bars = synth.fixture_04_false_retest(synth.rect1())
    rects = _rectangles(bars)
    assert len(rects) == 1
    rect = rects[0]

    assert rect.status == LifecycleState.FAILED.value
    types = _event_types(rect)
    assert "RETEST_PENDING" in types  # bars 17-18 DID enter the retest zone
    assert "RETEST_SUCCESSFUL" not in types  # PASS condition
    failed = [e for e in rect.events if e["event_type"] == "FAILED"]
    assert len(failed) == 1
    assert failed[0]["rule_id"] == "FAILED_RETEST"  # not FALSE_BREAKOUT, since a retest was pending


# ── Fix 2 (review 2026-09-22): retest_window_bars wiring ─────────────────────────────────
# `retest_window_bars` was hashed in CONFIG but read by no code. Wired into
# `_walk_retest_and_failure`: a pullback only counts as a retest if it FIRST re-enters the
# broken level within `retest_window_bars` bars of confirmation; the separate failure rule
# (failure_buffer_atr/failure_window_bars, NI-2 frozen) is untouched.


def test_retest_recognised_within_the_configured_window():
    cfg = dict(CONFIG, retest_window_bars=2)
    bars = synth._append(
        synth.rect1(),
        [
            (109.0, 111.3, 108.8, 111.0, 120_000.0),  # bar16 breakout -> PRICE_CONFIRMED (confirm_index)
            (111.0, 111.2, 110.9, 111.2, 100_000.0),  # bar17 holds above (i-confirm=1, inside the window)
            (111.2, 111.3, 109.6, 109.8, 100_000.0),  # bar18 dip into the zone (i-confirm=2, still inside)
        ],
    )
    rects = _rectangles(bars, cfg=cfg)
    assert len(rects) == 1
    assert rects[0].status == LifecycleState.PRICE_CONFIRMED.value
    assert "RETEST_PENDING" in _event_types(rects[0])


def test_retest_after_the_configured_window_is_not_a_retest():
    """Same pullback shape as above, delayed one bar past retest_window_bars=2: no
    RETEST_PENDING is ever opened -- the breakout is treated as holding, quietly, with no
    retest tracked at all (PASS condition: the pullback itself does not breach the failure
    buffer either, so nothing else fires)."""
    cfg = dict(CONFIG, retest_window_bars=2)
    bars = synth._append(
        synth.rect1(),
        [
            (109.0, 111.3, 108.8, 111.0, 120_000.0),  # bar16 breakout -> PRICE_CONFIRMED
            (111.0, 111.2, 110.9, 111.2, 100_000.0),  # bar17 holds (i-confirm=1, inside the window)
            (111.2, 111.3, 110.9, 111.1, 100_000.0),  # bar18 still holds (i-confirm=2, inside the window)
            (111.1, 111.2, 109.6, 109.8, 100_000.0),  # bar19 dip into the zone (i-confirm=3, PAST the window)
        ],
    )
    rects = _rectangles(bars, cfg=cfg)
    assert len(rects) == 1
    assert "RETEST_PENDING" not in _event_types(rects[0])  # PASS condition
    assert rects[0].status == LifecycleState.PRICE_CONFIRMED.value  # holding, not failed


def test_retest_window_does_not_change_the_separate_failure_rule():
    """A hard failure that lands AFTER the (small, custom) retest window but still inside the
    default failure_window_bars=5 must still fire, unaffected -- and, since RETEST_PENDING was
    never opened (the window already closed), the reason is FALSE_BREAKOUT, not FAILED_RETEST."""
    cfg = dict(CONFIG, retest_window_bars=2)
    bars = synth._append(
        synth.rect1(),
        [
            (109.0, 111.3, 108.8, 111.0, 120_000.0),  # bar16 breakout -> PRICE_CONFIRMED (confirm_index)
            (111.0, 111.2, 110.9, 111.2, 100_000.0),  # bar17 holds (i-confirm=1, inside retest window)
            (111.2, 111.3, 110.9, 111.1, 100_000.0),  # bar18 holds (i-confirm=2, inside retest window)
            (111.1, 111.2, 108.0, 108.2, 100_000.0),  # bar19 hard failure (i-confirm=3, past retest window, inside failure_window_bars=5)
        ],
    )
    rects = _rectangles(bars, cfg=cfg)
    assert len(rects) == 1
    assert rects[0].status == LifecycleState.FAILED.value
    assert "RETEST_PENDING" not in _event_types(rects[0])
    failed = [e for e in rects[0].events if e["event_type"] == "FAILED"]
    assert len(failed) == 1
    assert failed[0]["rule_id"] == "FALSE_BREAKOUT"


def test_retest_window_bars_change_is_hashed():
    changed = dict(CONFIG, retest_window_bars=99)
    assert config_hash(changed) != config_hash(CONFIG)


# ── #5 — gap-through invalidation (corrected, C1) ────────────────────────────


def test_fixture_05_gap_through_invalidation_is_gap_failure():
    bars = synth.fixture_05_gap_through_invalidation(synth.rect1())
    rects = _rectangles(bars)
    assert len(rects) == 1
    rect = rects[0]

    assert rect.status == LifecycleState.FAILED.value
    failed = [e for e in rect.events if e["event_type"] == "FAILED"]
    assert len(failed) == 1
    assert failed[0]["rule_id"] == "GAP_FAILURE"
    # inside the failure window (bar17 is confirm_bar+1, well inside failure_window_bars=5)
    assert (pd.Timestamp(failed[0]["date"]) - pd.Timestamp(rect.formation_end)).days <= 10


# ── #5b — gap breakdown control (added, C1) ──────────────────────────────────


def test_fixture_05b_gap_breakdown_control_is_a_valid_bearish_confirmation():
    """A first-ever gap below the breakdown level, with NO prior confirmed breakout, must be
    a normal bearish PRICE_CONFIRMED — GAP_FAILURE only ever applies to invalidating an
    ALREADY-confirmed breakout (orchestrator correction C1)."""
    bars = synth.fixture_05b_gap_breakdown_control(synth.rect1())
    rects = _rectangles(bars)
    assert len(rects) == 1
    rect = rects[0]

    assert rect.status == LifecycleState.PRICE_CONFIRMED.value
    assert rect.direction == "BEARISH"
    assert "GAP_FAILURE" not in [e["rule_id"] for e in rect.events]  # PASS condition
    assert "FAILED" not in _event_types(rect)
    confirmed = [e for e in rect.events if e["event_type"] == "PRICE_CONFIRMED"]
    assert len(confirmed) == 1
    assert confirmed[0]["rule_id"] == "CLOSE_BELOW_BREAKDOWN"


# ── #12 — incomplete candle ───────────────────────────────────────────────────


def test_fixture_12_incomplete_candle_never_confirms():
    """Orchestrator caveat: the test-plan's stated running close (110.6) does NOT clear the
    real measured breakout level, so this test builds its own running-close scenario (using
    RECT-1 with NO prior breakout, so the incomplete bar is the only thing that could
    confirm) with a close clearly above the computed level, and asserts the level really is
    crossed — a guard against the test going vacuous again.
    """
    completed = synth.rect1()
    t = len(completed) - 1
    a = _measured_atr_at(completed, t)
    breakout_level = synth.RECT1_RESISTANCE + CONFIG["breakout_buffer_atr"] * a

    running_date = pd.bdate_range(start=completed["date"].iloc[-1] + pd.tseries.offsets.BDay(1), periods=1)[0]
    incomplete_bar = {
        "date": running_date, "open": 109.0, "high": 111.5, "low": 108.8, "close": 111.2,
        "volume": 120_000.0, "is_complete": False,
    }
    # Guard against a vacuous test (test-plan's original 110.6 would NOT have crossed here).
    assert incomplete_bar["close"] > breakout_level, "fixture is vacuous: running close does not cross the measured breakout level"

    before = _rectangles(completed, t)
    assert len(before) == 1
    assert before[0].status == LifecycleState.GEOMETRY_VALID.value  # no breakout yet from completed bars alone

    after = _rectangles(completed, t, incomplete_bar=incomplete_bar)
    assert len(after) == 1
    rect = after[0]
    assert rect.status != LifecycleState.PRICE_CONFIRMED.value  # PASS condition: never confirms
    assert rect.status == LifecycleState.BREAKOUT_ATTEMPT.value
    assert "PRICE_CONFIRMED" not in _event_types(rect)
    blocked = [r for r in rect.rules if r["rule_id"] == "INCOMPLETE_CANDLE_CONFIRMATION_BLOCKED"]
    assert len(blocked) == 1
    assert blocked[0]["result"] == "FAIL"
    assert blocked[0]["observed"] == pytest.approx(111.2)


def test_fixture_12_finalisation_then_confirms_exactly_once_and_is_idempotent():
    """'fires exactly once after finalisation; idempotent': once the running candle becomes
    a real completed row (close 111.2, clearing the level), detect_as_of shows PRICE_CONFIRMED
    exactly once, and calling it again on the same finalized frame gives byte-identical output.
    """
    completed = synth.rect1()
    running_date = pd.bdate_range(start=completed["date"].iloc[-1] + pd.tseries.offsets.BDay(1), periods=1)[0]
    finalized_row = pd.DataFrame([{
        "date": running_date, "open": 109.0, "high": 111.5, "low": 108.8, "close": 111.2, "volume": 120_000.0,
    }])
    finalized = pd.concat([completed, finalized_row], ignore_index=True)
    t = len(finalized) - 1

    run_a = _rectangles(finalized, t)
    run_b = _rectangles(finalized, t)
    assert len(run_a) == 1
    assert run_a[0].status == LifecycleState.PRICE_CONFIRMED.value
    confirmed_events = [e for e in run_a[0].events if e["event_type"] == "PRICE_CONFIRMED"]
    assert len(confirmed_events) == 1  # fires exactly once

    assert [p.to_dict() for p in run_a] == [p.to_dict() for p in run_b]  # idempotent


# ── Mutual exclusivity: a bar can never be both a valid breakout and a valid failure ──


@pytest.mark.parametrize(
    "fixture_fn",
    [
        synth.fixture_01_wick_only_breakout, synth.fixture_02_low_volume_breakout,
        synth.fixture_03_close_back_inside, synth.fixture_04_false_retest,
        synth.fixture_05_gap_through_invalidation, synth.fixture_05b_gap_breakdown_control,
        synth.fixture_09_future_volume_contamination,
    ],
)
def test_no_bar_is_both_a_valid_breakout_and_a_valid_failure(fixture_fn):
    bars = fixture_fn(synth.rect1())
    rects = _rectangles(bars)
    for rect in rects:
        by_date: dict[str, set[str]] = {}
        for e in rect.events:
            by_date.setdefault(e["date"], set()).add(e["event_type"])
        for date, kinds in by_date.items():
            confirming = {"PRICE_CONFIRMED", "RETEST_SUCCESSFUL"} & kinds
            failing = {"FAILED"} & kinds
            assert not (confirming and failing), f"{rect.pattern_id} bar {date} is both confirming ({confirming}) and failing ({failing})"


# ── Determinism (§21, §24.3) ──────────────────────────────────────────────────


@pytest.mark.parametrize(
    "fixture_fn",
    [
        lambda b: b, synth.fixture_01_wick_only_breakout, synth.fixture_02_low_volume_breakout,
        synth.fixture_03_close_back_inside, synth.fixture_04_false_retest,
        synth.fixture_05_gap_through_invalidation, synth.fixture_05b_gap_breakdown_control,
    ],
)
def test_detect_as_of_is_deterministic(fixture_fn):
    bars = fixture_fn(synth.rect1())
    t = len(bars) - 1
    a = detect_as_of(bars, t, symbol="SYN1")
    b = detect_as_of(bars, t, symbol="SYN1")
    a_dicts = [p.to_dict() for p in a]
    b_dicts = [p.to_dict() for p in b]
    assert a_dicts == b_dicts


# ── SNAPSHOT_SCHEMA.md shape ───────────────────────────────────────────────────


def test_pattern_snapshot_matches_documented_shape():
    bars = synth.fixture_02_low_volume_breakout(synth.rect1())
    rects = _rectangles(bars)
    assert rects
    d = rects[0].to_dict()
    expected_keys = {
        "pattern_id", "pattern_type", "direction", "population", "status", "stage",
        "formation_start", "formation_end", "levels", "pivots", "components", "rules", "events", "scores",
        # NOTE: no `retest_quality` here -- CANDLE-MOVE (2026-09-22, docs/charting.md §38.18
        # decisions-log #93/#110) moved it (and candle quality) into the research enrichment
        # record (research/charting/enrich.py), out of this production snapshot. See
        # test_patterns_retest_quality.py / test_enrich.py.
    }
    assert set(d.keys()) == expected_keys
    assert d["population"] == "CONFIRMED"
    assert d["stage"] is None
    assert d["scores"] is None
    assert set(d["components"].keys()) == {"geometry", "price", "volume", "volatility", "market", "sector", "data_quality"}
    for rule in d["rules"]:
        assert set(rule.keys()) == {"rule_id", "result", "observed", "threshold"}
        assert rule["result"] in ("PASS", "FAIL")
    for event in d["events"]:
        assert {"date", "event_type", "rule_id"} <= set(event.keys())
    for pivot in d["pivots"]:
        assert set(pivot.keys()) == {"date", "price", "kind", "confirmed_date"}


def test_pattern_id_is_json_serializable_and_stable():
    import json
    bars = synth.fixture_02_low_volume_breakout(synth.rect1())
    rects = _rectangles(bars)
    payload = json.dumps([r.to_dict() for r in rects], default=float)
    assert isinstance(payload, str) and len(payload) > 0


# ── E-5: wiring lifecycle.research_eligible() (sub-task c) ──────────────────────


def test_research_eligibility_not_evaluated_by_default():
    """Baseline control: without `evaluate_research_eligibility`, a cleanly-confirmed
    pattern stays PRICE_CONFIRMED exactly as before E-5 — the default must not change any
    pre-existing caller's output (see module docstring's E-5 note)."""
    bars = synth.fixture_05b_gap_breakdown_control(synth.rect1())
    rects = _rectangles(bars)
    assert len(rects) == 1
    assert rects[0].status == LifecycleState.PRICE_CONFIRMED.value


def test_pattern_meeting_every_research_eligible_criterion_reaches_research_eligible():
    """With the opt-in flag, a pattern whose components satisfy every
    `lifecycle.research_eligible()` criterion (geometry+price CONFIRMED, data_quality VALID,
    and every `require_*` flag the config sets is satisfied — all true here under default
    CONFIG) is promoted PRICE_CONFIRMED -> RESEARCH_ELIGIBLE."""
    bars = synth.fixture_05b_gap_breakdown_control(synth.rect1())
    t = len(bars) - 1
    pats = detect_as_of(bars, t, symbol="SYN1", evaluate_research_eligibility=True)
    rects = [p for p in pats if p.pattern_type == "RECTANGLE"]
    assert len(rects) == 1
    assert rects[0].status == LifecycleState.RESEARCH_ELIGIBLE.value
    assert rects[0].components["geometry"] == "PASS"
    assert rects[0].components["price"] == "PASS"


def test_pattern_missing_a_required_component_does_not_reach_research_eligible():
    """Same opt-in flag, but with `require_volume_confirmation=True` in the effective cfg
    and fixture #2's low-volume breakout (volume component FAILS) — research_eligible()
    must return False, so the pattern stays PRICE_CONFIRMED, never RESEARCH_ELIGIBLE."""
    cfg = {**CONFIG, "require_volume_confirmation": True}
    bars = synth.fixture_02_low_volume_breakout(synth.rect1())
    t = len(bars) - 1
    pats = detect_as_of(bars, t, cfg=cfg, symbol="SYN1", evaluate_research_eligibility=True)
    rects = [p for p in pats if p.pattern_type == "RECTANGLE"]
    assert len(rects) == 1
    assert rects[0].components["volume"] == "FAIL"
    assert rects[0].status == LifecycleState.PRICE_CONFIRMED.value  # PASS condition: not promoted


# ── confirmation_window_bars expiry (sub-task b) ────────────────────────────────


def test_wick_only_attempt_expires_after_confirmation_window_elapses():
    """A wick-only BREAKOUT_ATTEMPT (fixture #1's bar16 shape) followed by
    `confirmation_window_bars` (=3) quiet bars with no close-confirmation: the ATTEMPT expires
    on the next bar (it must not sit BREAKOUT_ATTEMPT forever) — but the rectangle itself stays
    live at GEOMETRY_VALID; §13.3 does not invalidate a rectangle for an unconfirmed wick."""
    assert CONFIG["confirmation_window_bars"] == 3  # guard: fixture below is tuned to this
    bars = synth._append(
        synth.rect1(),
        [
            (108.0, 112.0, 107.0, 109.8, 100_000.0),  # bar A: wick touch (attempt_index)
            (109.8, 110.0, 108.0, 108.5, 100_000.0),  # A+1: quiet, still pending
            (108.5, 109.0, 107.5, 108.0, 100_000.0),  # A+2: quiet, still pending
            (108.0, 108.5, 107.0, 107.5, 100_000.0),  # A+3: quiet, still pending (== window)
            (107.5, 108.0, 106.5, 107.0, 100_000.0),  # A+4: > window, unconfirmed -> EXPIRED
        ],
    )
    rects = _rectangles(bars)
    assert len(rects) == 1
    rect = rects[0]
    assert rect.status == LifecycleState.GEOMETRY_VALID.value  # attempt retired, rectangle live
    expired = [e for e in rect.events if e["event_type"] == "BREAKOUT_ATTEMPT_EXPIRED"]
    assert len(expired) == 1
    assert expired[0]["rule_id"] == "BREAKOUT_ATTEMPT_WINDOW_EXPIRED"
    assert expired[0]["observed_values"]["bars_since_attempt"] == 4
    assert "PRICE_CONFIRMED" not in _event_types(rect)  # never confirmed
    assert "EXPIRED" not in _event_types(rect)  # the rectangle itself did not expire


def test_genuine_breakout_after_an_expired_attempt_still_confirms():
    """Regression (review of package 3, 2026-09-22): ADANIPOWER's rectangle wicked above its
    breakout level on 2026-03-25 and closed above it on 2026-04-02 — the first bar after the
    attempt's window. The expiry used to end the whole pattern and was checked before the
    confirmation, so the real breakout was recorded as EXPIRED. The attempt must expire and the
    same-bar genuine close must still confirm."""
    assert CONFIG["confirmation_window_bars"] == 3
    bars = synth._append(
        synth.rect1(),
        [
            (108.0, 112.0, 107.0, 109.8, 100_000.0),  # bar A: wick touch (attempt_index)
            (109.8, 110.0, 108.0, 108.5, 100_000.0),  # A+1
            (108.5, 109.0, 107.5, 108.0, 100_000.0),  # A+2
            (108.0, 108.5, 107.0, 107.5, 100_000.0),  # A+3 (== window), still unconfirmed
            (107.5, 113.5, 107.5, 113.0, 150_000.0),  # A+4: attempt expires AND a real close breaks out
        ],
    )
    rects = _rectangles(bars)
    assert len(rects) == 1
    rect = rects[0]
    types = _event_types(rect)
    assert "BREAKOUT_ATTEMPT_EXPIRED" in types
    assert rect.status == LifecycleState.PRICE_CONFIRMED.value
    assert "EXPIRED" not in types
    confirmed = [e for e in rect.events if e["event_type"] == "PRICE_CONFIRMED"]
    assert len(confirmed) == 1 and confirmed[0]["rule_id"] == "CLOSE_ABOVE_BREAKOUT"
    assert confirmed[0]["observed_values"]["close"] > confirmed[0]["observed_values"]["breakout_level"]  # guard: non-vacuous


def test_wick_only_attempt_confirmed_within_window_is_not_expired():
    """Same wick-only touch, but this time a close clears the breakout level exactly at
    the edge of the confirmation window (3 bars after the touch) — must confirm normally,
    not be incorrectly expired."""
    assert CONFIG["confirmation_window_bars"] == 3
    bars = synth._append(
        synth.rect1(),
        [
            (108.0, 112.0, 107.0, 109.8, 100_000.0),  # bar A: wick touch (attempt_index)
            (109.8, 110.0, 108.0, 108.5, 100_000.0),  # A+1: quiet, still pending
            (108.5, 109.0, 107.5, 108.0, 100_000.0),  # A+2: quiet, still pending
            (108.0, 113.5, 107.5, 113.0, 150_000.0),  # A+3 (== window): confirms
        ],
    )
    rects = _rectangles(bars)
    assert len(rects) == 1
    rect = rects[0]
    assert rect.status == LifecycleState.PRICE_CONFIRMED.value  # PASS condition: not EXPIRED
    assert "EXPIRED" not in _event_types(rect)
    assert "BREAKOUT_ATTEMPT_EXPIRED" not in _event_types(rect)  # confirmed inside the window
    confirmed = [e for e in rect.events if e["event_type"] == "PRICE_CONFIRMED"]
    assert len(confirmed) == 1
    assert confirmed[0]["rule_id"] == "CLOSE_ABOVE_BREAKOUT"


# ── §13.3 "No unresolved data gaps" (sub-task a) ───────────────────────────────


def test_rect1_unaffected_when_gap_dates_not_supplied():
    """Baseline control: RECT-1 with an interior calendar gap, called WITHOUT
    `unresolved_gap_dates` (the default), still forms the rectangle exactly as before —
    the gap gate must be a no-op unless a caller explicitly opts in."""
    bars = synth.rect1()
    gapped = bars.drop(index=2).reset_index(drop=True)  # drop one interior warm-up bar
    rects = _rectangles(gapped)
    assert len(rects) == 1
    assert rects[0].levels["resistance"] == pytest.approx(110.0)
    assert rects[0].levels["support"] == pytest.approx(100.0)
    assert not any(r["rule_id"] == "RECT_NO_UNRESOLVED_DATA_GAPS" for r in rects[0].rules)


def test_rect1_with_unresolved_gap_in_formation_window_is_not_formed():
    """The same gapped bars, but this time the caller supplies the real MISSING_CANDLE
    finding for the missing date (computed via validate.py against the true, ungapped
    calendar — exactly how a whole-universe caller would derive it). §13.3 lists "No
    unresolved data gaps" as a Formation requirement alongside minimum touches, flat
    boundaries, etc. — every one of those siblings is already a hard reject in
    `_rectangle_candidates`, so a candidate whose formation window contains this gap is
    rejected the same way, not merely flagged."""
    bars = synth.rect1()
    gapped = bars.drop(index=2).reset_index(drop=True)

    calendar = validate.build_trading_calendar([bars])  # the true (ungapped) calendar
    findings = validate.validate_symbol(gapped, calendar=calendar)
    gap_dates = frozenset(f.date for f in findings if f.rule_id == "MISSING_CANDLE")
    assert gap_dates, "fixture sanity: the drop must actually produce a MISSING_CANDLE finding"

    t = len(gapped) - 1
    pats = detect_as_of(gapped, t, symbol="SYN1", unresolved_gap_dates=gap_dates)
    rects = [p for p in pats if p.pattern_type == "RECTANGLE"]
    assert rects == []  # PASS condition: the gapped formation window produces no rectangle


def test_rect1_gap_outside_formation_window_still_forms():
    """Control: a gap date that does NOT fall inside [formation_start, formation_end]
    must not reject the candidate — the gate is scoped to the formation window, not "any
    gap anywhere in the symbol's history"."""
    bars = synth.rect1()
    far_future_gap = frozenset({bars["date"].iloc[-1] + pd.tseries.offsets.BDay(500)})
    t = len(bars) - 1
    pats = detect_as_of(bars, t, symbol="SYN1", unresolved_gap_dates=far_future_gap)
    rects = [p for p in pats if p.pattern_type == "RECTANGLE"]
    assert len(rects) == 1
    assert any(r["rule_id"] == "RECT_NO_UNRESOLVED_DATA_GAPS" and r["result"] == "PASS" for r in rects[0].rules)


# ── HH/HL structure (§13.1) ────────────────────────────────────────────────────


def _zigzag_bars(turns: list[float], bars_per_leg: int = 5, wick: float = 0.05) -> pd.DataFrame:
    closes: list[float] = []
    for i in range(len(turns) - 1):
        seg = list(np.linspace(turns[i], turns[i + 1], bars_per_leg))[:-1]
        closes.extend(seg)
    closes.append(turns[-1])
    return synth.bars_from_closes(closes, wick=wick)


def test_hh_hl_bullish_structure_geometry_valid_before_confirmation():
    bars = _zigzag_bars([15.0, 8.0, 20.0, 9.0, 25.0, 12.0, 30.0, 16.0, 35.0, 20.0])
    t = len(bars) - 1
    hh = [p for p in detect_as_of(bars, t, symbol="ZZ") if p.pattern_type == "HH_HL"]
    assert len(hh) == 1
    assert hh[0].direction == "BULLISH"
    assert hh[0].status == LifecycleState.GEOMETRY_VALID.value


def test_hh_hl_bullish_continuation_confirms_on_close_above_prior_high():
    # Final turn bumped from the pre-fix-3 36.0 to 40.0: HH_HL confirmation now requires
    # clearing the prior high by breakout_buffer_atr * ATR (fix 3, review 2026-09-22), and
    # this fixture's measured ATR (~3.9-4.2) makes 36.0 fall just short of the buffered
    # level (~36.03) -- 40.0 clears it with comfortable margin (see test_hh_hl_close_
    # beyond_breakout_buffer_confirms for the buffer boundary itself).
    bars = _zigzag_bars([15.0, 8.0, 20.0, 9.0, 25.0, 12.0, 30.0, 16.0, 35.0, 20.0, 40.0])
    t = len(bars) - 1
    hh = [p for p in detect_as_of(bars, t, symbol="ZZ") if p.pattern_type == "HH_HL"]
    assert len(hh) == 1
    assert hh[0].status == LifecycleState.PRICE_CONFIRMED.value
    confirmed = [e for e in hh[0].events if e["event_type"] == "PRICE_CONFIRMED"]
    assert len(confirmed) == 1
    assert confirmed[0]["rule_id"] == "CLOSE_ABOVE_PRIOR_HIGH"


def test_hh_hl_bullish_structure_invalidated_on_close_below_prior_low():
    bars = _zigzag_bars([15.0, 8.0, 20.0, 9.0, 25.0, 12.0, 30.0, 16.0, 35.0, 20.0, 10.0])
    t = len(bars) - 1
    hh = [p for p in detect_as_of(bars, t, symbol="ZZ") if p.pattern_type == "HH_HL"]
    assert len(hh) == 1
    assert hh[0].status == LifecycleState.INVALIDATED.value


def test_hh_hl_no_structure_when_highs_and_lows_disagree():
    # Rising highs (15->20->25->30, an HH sequence) but FALLING lows (5->3->1->0.5, an LL
    # sequence) -- no consistent trend, must not classify as either bullish or bearish.
    bars = _zigzag_bars([15.0, 5.0, 20.0, 3.0, 25.0, 1.0, 30.0, 0.5])
    t = len(bars) - 1
    hh = [p for p in detect_as_of(bars, t, symbol="ZZ") if p.pattern_type == "HH_HL"]
    assert hh == []


# ── Fix 3 (review 2026-09-22): HH_HL confirmation now requires the same breakout buffer ──
# ── every other P0 family already applies (close beyond the level ± breakout_buffer_atr*ATR)


def _hh_hl_pre_confirmation_fixture() -> pd.DataFrame:
    return _zigzag_bars([15.0, 8.0, 20.0, 9.0, 25.0, 12.0, 30.0, 16.0, 35.0, 20.0])


def test_hh_hl_close_inside_breakout_buffer_does_not_confirm():
    base = _hh_hl_pre_confirmation_fixture()
    t0 = len(base) - 1
    hh0 = [p for p in detect_as_of(base, t0, symbol="ZZ") if p.pattern_type == "HH_HL"]
    assert len(hh0) == 1 and hh0[0].status == LifecycleState.GEOMETRY_VALID.value
    prior_high = hh0[0].levels["prior_high"]

    # Close just 0.05 above the raw prior high -- inside the buffer for any plausible ATR
    # here (checked below against the frame's own, causally-measured ATR).
    bars = synth._append(base, [(prior_high, prior_high + 0.20, prior_high - 1.0, prior_high + 0.05, 100_000.0)])
    t = len(bars) - 1
    a = float(atr_series_fn(bars, period=CONFIG["atr_period"]).iloc[t])
    buf = CONFIG["breakout_buffer_atr"] * a
    assert 0 < 0.05 < buf, "fixture is vacuous: the chosen close offset is not inside the measured buffer"

    hh = [p for p in detect_as_of(bars, t, symbol="ZZ") if p.pattern_type == "HH_HL"]
    assert len(hh) == 1
    assert hh[0].status == LifecycleState.GEOMETRY_VALID.value  # PASS condition: does NOT confirm
    assert "PRICE_CONFIRMED" not in _event_types(hh[0])


def test_hh_hl_close_beyond_breakout_buffer_confirms():
    base = _hh_hl_pre_confirmation_fixture()
    t0 = len(base) - 1
    hh0 = [p for p in detect_as_of(base, t0, symbol="ZZ") if p.pattern_type == "HH_HL"]
    prior_high = hh0[0].levels["prior_high"]

    bars = synth._append(base, [(prior_high, prior_high + 3.5, prior_high - 1.0, prior_high + 3.0, 100_000.0)])
    t = len(bars) - 1
    a = float(atr_series_fn(bars, period=CONFIG["atr_period"]).iloc[t])
    buf = CONFIG["breakout_buffer_atr"] * a
    assert 3.0 > buf, "fixture is vacuous: the chosen close offset does not clear the measured buffer"

    hh = [p for p in detect_as_of(bars, t, symbol="ZZ") if p.pattern_type == "HH_HL"]
    assert len(hh) == 1
    assert hh[0].status == LifecycleState.PRICE_CONFIRMED.value
    confirmed = [e for e in hh[0].events if e["event_type"] == "PRICE_CONFIRMED"]
    assert len(confirmed) == 1
    assert confirmed[0]["rule_id"] == "CLOSE_ABOVE_PRIOR_HIGH"


# ── Generalized retest/failure state machine for S/R and HH_HL (sub-task d) ─────


def test_hh_hl_retest_after_confirmation_succeeds():
    """Once HH_HL confirms (close beyond the prior high), a pullback into the broken level
    followed by a close back above it must resolve as a successful retest — the SAME §13.9
    state machine RECTANGLE already had, now generalized to HH_HL. Status stays
    PRICE_CONFIRMED (mirrors RECTANGLE: a successful retest does not introduce a new
    LifecycleState of its own — see RETEST_SUCCESSFUL's event-only nature)."""
    # Final turn bumped from 36.0 to 40.0 (fix 3's breakout buffer -- see the comment in
    # test_hh_hl_bullish_continuation_confirms_on_close_above_prior_high); the broken level
    # retested below is still the prior high (~35.05), unaffected by how high the confirming
    # close itself needed to be.
    bars = _zigzag_bars([15.0, 8.0, 20.0, 9.0, 25.0, 12.0, 30.0, 16.0, 35.0, 20.0, 40.0])
    bars = synth._append(
        bars,
        [
            (40.0, 40.2, 34.8, 35.0, 100_000.0),  # dip into the broken prior-high (retest zone)
            (35.0, 38.0, 34.9, 37.5, 100_000.0),  # close back above -> RETEST_SUCCESSFUL
        ],
    )
    t = len(bars) - 1
    hh = [p for p in detect_as_of(bars, t, symbol="ZZ") if p.pattern_type == "HH_HL"]
    assert len(hh) == 1
    assert hh[0].status == LifecycleState.PRICE_CONFIRMED.value
    types = [e["event_type"] for e in hh[0].events]
    assert types == ["PRICE_CONFIRMED", "RETEST_PENDING", "RETEST_SUCCESSFUL"]


def test_hh_hl_retest_after_confirmation_fails():
    """Same confirmed HH_HL, but the pullback keeps falling hard instead of holding — must
    resolve FAILED (FAILED_RETEST, since a retest was already pending), exactly like
    RECTANGLE's fixture #4."""
    # Final turn bumped from 36.0 to 40.0 -- see the sibling "succeeds" test's comment.
    bars = _zigzag_bars([15.0, 8.0, 20.0, 9.0, 25.0, 12.0, 30.0, 16.0, 35.0, 20.0, 40.0])
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
    assert hh[0].status == LifecycleState.FAILED.value
    failed = [e for e in hh[0].events if e["event_type"] == "FAILED"]
    assert len(failed) == 1
    assert failed[0]["rule_id"] == "FAILED_RETEST"


def _sr_resistance_base_bars() -> pd.DataFrame:
    """A standalone RESISTANCE level at ~110.1-110.2 with 3 confirmed touches (>=
    level_min_touches=3), well clear of forming a RECTANGLE (the pull-backs go all the way
    down to ~95-100 each leg, so no matching flat support boundary exists)."""
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


def test_sr_level_geometry_valid_before_any_breakout():
    bars = _sr_resistance_base_bars()
    t = len(bars) - 1
    sr = [p for p in detect_as_of(bars, t, symbol="SYN2") if p.pattern_type == "SUPPORT_RESISTANCE" and p.direction == "BULLISH"]
    assert len(sr) == 1
    assert sr[0].status == LifecycleState.GEOMETRY_VALID.value
    assert sr[0].levels["level"] == pytest.approx(110.15)


def test_sr_level_retest_after_confirmation_succeeds():
    """Once a standalone S/R level confirms, a pullback into the level followed by a close
    back above it must resolve as a successful retest — E-4's RECTANGLE-only retest state
    machine, generalized here to SUPPORT_RESISTANCE (sub-task d)."""
    bars = synth._append(
        _sr_resistance_base_bars(),
        [
            (100.0, 114.0, 99.8, 113.5, 150_000.0),   # confirms (close well above trigger)
            (113.5, 113.6, 109.8, 110.0, 100_000.0),  # dip into the level (retest zone)
            (110.0, 113.0, 109.9, 112.5, 100_000.0),  # close back above -> RETEST_SUCCESSFUL
        ],
    )
    t = len(bars) - 1
    sr = [p for p in detect_as_of(bars, t, symbol="SYN2") if p.pattern_type == "SUPPORT_RESISTANCE" and p.direction == "BULLISH"]
    assert len(sr) == 1
    assert sr[0].status == LifecycleState.PRICE_CONFIRMED.value
    types = [e["event_type"] for e in sr[0].events]
    assert "RETEST_PENDING" in types
    assert "RETEST_SUCCESSFUL" in types
    assert "FAILED" not in types


def test_sr_level_retest_after_confirmation_fails():
    """Same confirmed level, but the pullback keeps falling hard — must resolve FAILED
    (FAILED_RETEST)."""
    bars = synth._append(
        _sr_resistance_base_bars(),
        [
            (100.0, 114.0, 99.8, 113.5, 150_000.0),   # confirms
            (113.5, 113.6, 109.8, 110.0, 100_000.0),  # dip into the level (retest zone)
            (110.0, 110.2, 105.0, 106.0, 100_000.0),  # hard failure
        ],
    )
    t = len(bars) - 1
    sr = [p for p in detect_as_of(bars, t, symbol="SYN2") if p.pattern_type == "SUPPORT_RESISTANCE" and p.direction == "BULLISH"]
    assert len(sr) == 1
    assert sr[0].status == LifecycleState.FAILED.value
    failed = [e for e in sr[0].events if e["event_type"] == "FAILED"]
    assert len(failed) == 1
    assert failed[0]["rule_id"] == "FAILED_RETEST"


def test_rectangle_retest_state_machine_unchanged_by_the_generalization():
    """Control: RECTANGLE's own retest/failure output (fixture #4, false retest -> FAILED)
    must be byte-identical after the shared-helper refactor — same event sequence, same
    reason code."""
    bars = synth.fixture_04_false_retest(synth.rect1())
    rects = _rectangles(bars)
    assert len(rects) == 1
    assert rects[0].status == LifecycleState.FAILED.value
    types = _event_types(rects[0])
    assert types == ["PRICE_CONFIRMED", "RETEST_PENDING", "FAILED"]
    failed = [e for e in rects[0].events if e["event_type"] == "FAILED"]
    assert failed[0]["rule_id"] == "FAILED_RETEST"
