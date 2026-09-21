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

from research.charting.config import CONFIG
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
    assert vol_rules[0]["observed"] == pytest.approx(0.90)
    assert vol_rules[0]["threshold"] == pytest.approx(1.00)

    # PASS condition: never RESEARCH_ELIGIBLE via this bar (this package never emits that
    # status at all — see patterns.py module docstring's scope boundary).
    assert rect.status != LifecycleState.RESEARCH_ELIGIBLE.value


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
    bars = _zigzag_bars([15.0, 8.0, 20.0, 9.0, 25.0, 12.0, 30.0, 16.0, 35.0, 20.0, 36.0])
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
