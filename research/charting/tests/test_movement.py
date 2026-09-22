"""Movement-vs-direction measurement tests — CHART-S35, package D.

Two layers, deliberately kept separate:
  1. `auc_from_scores_and_labels` — the AUC math itself, verified against known cases
     (perfect discriminator -> 1.0, anti-correlated -> 0.0, tied/no-signal -> 0.5) and the
     honest single-class / insufficient-n edge cases, independent of any pattern/bars
     machinery.
  2. `movement_vs_direction_report` — the grouping/plumbing: real `patterns.py` +
     `replay.py` output wired through end-to-end (confirms the PRICE_CONFIRMED extraction
     actually works against the real detector, reusing `tests/synth.py`'s RECT-1 fixture),
     plus hand-built synthetic populations (full control over price/volume paths) proving
     per-(family, horizon) grouping is correct and never leaks data across symbols or
     across pattern families.
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest

from research.charting import movement, patterns, replay, research_window
from research.charting.movement import (
    AucResult,
    auc_from_scores_and_labels,
    movement_vs_direction_report,
    report_to_rows,
)
from research.charting.tests import synth

# `synth.py`'s fixtures are anchored at `_START_DATE` (2024-01-02), which falls inside the
# project-wide sealed 2023-01-01..2024-07-31 out-of-sample block (see test_early_scoring.py's
# own note on this). `movement_vs_direction_report`/`replay.replay` now refuse (fix 1,
# research_window.SealedWindowError) to evaluate a confirmed event dated inside that block, so
# every fixture actually fed to them in this file uses a safe, pre-2023 start date instead.
_SAFE_START_DATE = "2021-01-04"


def _shift_outside_sealed_window(bars: pd.DataFrame) -> pd.DataFrame:
    """Shift every date back by 3 years, landing safely in 2021 -- same helper as
    test_replay.py's, for fixtures built via `synth.rect1()`/`fixture_04_false_retest`
    (which have no `start_date` override, unlike `synth.bars_from_closes`)."""
    shifted = bars.copy()
    shifted["date"] = shifted["date"] - pd.DateOffset(years=3)
    return shifted


# ── Layer 1: AUC math ─────────────────────────────────────────────────────────────────────


def test_auc_perfect_discriminator_is_1():
    # Every positive scores strictly above every negative -> perfect separation.
    scores = [10, 11, 12, 13, 14, 0, 1, 2, 3, 4]
    labels = [1, 1, 1, 1, 1, 0, 0, 0, 0, 0]
    result = auc_from_scores_and_labels(scores, labels, min_n=1)
    assert result.auc == pytest.approx(1.0)
    assert result.n == 10
    assert result.reason is None


def test_auc_anti_correlated_is_0():
    # Every positive scores strictly below every negative -> perfectly wrong ranking.
    scores = [0, 1, 2, 3, 4, 10, 11, 12, 13, 14]
    labels = [1, 1, 1, 1, 1, 0, 0, 0, 0, 0]
    result = auc_from_scores_and_labels(scores, labels, min_n=1)
    assert result.auc == pytest.approx(0.0)
    assert result.n == 10


def test_auc_all_tied_scores_is_exactly_half():
    # No discriminative power at all: every instance has the identical score, regardless
    # of label -> AUC must land exactly on 0.5 (the average-rank tie formula), not merely
    # "close to" 0.5.
    scores = [5.0] * 12
    labels = [1, 0, 1, 0, 1, 0, 1, 0, 1, 0, 1, 0]
    result = auc_from_scores_and_labels(scores, labels, min_n=1)
    assert result.auc == pytest.approx(0.5)
    assert result.n == 12


def test_auc_no_signal_random_labels_is_near_half():
    # A score with genuinely no relationship to the label: shuffle a balanced 0/1 label
    # vector against scores 0..199 with a fixed seed. At n=200 the law of large numbers
    # keeps a truly unrelated pairing close to 0.5; the seed is fixed so this is a
    # deterministic regression check, not a flaky random test.
    rng = np.random.RandomState(42)
    n = 200
    scores = list(range(n))
    labels = [0] * (n // 2) + [1] * (n // 2)
    rng.shuffle(labels)
    result = auc_from_scores_and_labels(scores, labels, min_n=1)
    assert result.auc == pytest.approx(0.5, abs=0.08)
    assert result.n == n


def test_auc_hand_computed_small_case():
    # scores=[1,2,3,4], labels=[0,1,0,1] -> ranks [1,2,3,4] (no ties).
    # positives are indices 1,3 -> ranks 2 and 4 -> sum=6; n_pos=2,n_neg=2.
    # U = 6 - 2*3/2 = 3; AUC = 3/(2*2) = 0.75 (positive #1 (rank2) beats 1 of 2 negatives,
    # positive #2 (rank4) beats both -> (1+2)/(2*2) = 0.75).
    result = auc_from_scores_and_labels([1, 2, 3, 4], [0, 1, 0, 1], min_n=1)
    assert result.auc == pytest.approx(0.75)


def test_auc_single_class_all_positive_is_none_with_reason():
    result = auc_from_scores_and_labels([1, 2, 3], [1, 1, 1], min_n=1)
    assert result.auc is None
    assert result.reason == "single_class"
    assert result.n == 3  # still reported, even though undefined


def test_auc_single_class_all_negative_is_none_with_reason():
    result = auc_from_scores_and_labels([1, 2, 3], [0, 0, 0], min_n=1)
    assert result.auc is None
    assert result.reason == "single_class"
    assert result.n == 3


def test_auc_single_class_never_silently_returns_half_or_one():
    # The specific footgun requirement 4 calls out: a same-label population must not come
    # back looking like a confident, numerically-valid 0.5 or 1.0.
    result = auc_from_scores_and_labels([1, 2, 3, 4, 5], [1, 1, 1, 1, 1], min_n=1)
    assert result.auc is None


def test_auc_insufficient_n_is_none_with_reason():
    # Both classes present (mathematically defined) but far below the default floor.
    result = auc_from_scores_and_labels([1, 2], [0, 1])  # default min_n=10, n=2
    assert result.auc is None
    assert result.reason == "insufficient_n"
    assert result.n == 2


def test_auc_exactly_at_min_n_is_computed():
    scores = list(range(10))
    labels = [0] * 5 + [1] * 5
    result = auc_from_scores_and_labels(scores, labels, min_n=10)
    assert result.n == 10
    assert result.auc is not None
    assert result.reason is None


def test_auc_rejects_mismatched_lengths():
    with pytest.raises(ValueError):
        auc_from_scores_and_labels([1, 2, 3], [0, 1])


# ── Layer 2a: wired against the REAL patterns.py + replay.py output ─────────────────────


def test_confirmed_event_extraction_against_real_rectangle_pattern():
    """RECT-1 + fixture #4 (breakout, retest, hard failure) confirms a RECTANGLE at bar16
    with 3 more bars afterwards (dates shifted outside the sealed window — see
    _shift_outside_sealed_window). Running the real detector must produce a PatternSnapshot
    whose `.events` carries a PRICE_CONFIRMED entry — `movement_vs_direction_report` must
    find it and compute horizon=1 (the fixture has one bar past bar16)."""
    bars = _shift_outside_sealed_window(synth.fixture_04_false_retest(synth.rect1()))
    snaps = patterns.detect_as_of(bars, len(bars) - 1, symbol="SYN1")
    rectangles = [s for s in snaps if s.pattern_type == "RECTANGLE"]
    assert rectangles, "expected the RECTANGLE to still be detected"
    assert any(e["event_type"] == "PRICE_CONFIRMED" for e in rectangles[0].events)

    report = movement_vs_direction_report(rectangles, {"SYN1": bars}, horizons=(1,))
    assert ("RECTANGLE", 1) in report
    cell = report[("RECTANGLE", 1)]
    # Only one confirmed event exists in this tiny fixture -> honestly reported as
    # under-powered, never a fabricated AUC number.
    assert cell.move.n == 1
    assert cell.move.auc is None
    assert cell.move.reason == "single_class"


def test_never_confirmed_pattern_is_excluded_from_report():
    """RECT-1 alone (no breakout appended) never reaches PRICE_CONFIRMED for any pattern —
    detect_as_of may still return GEOMETRY_VALID candidates, none of which belong in this
    report."""
    bars = synth.rect1()
    snaps = patterns.detect_as_of(bars, len(bars) - 1, symbol="SYN1")
    assert not any(any(e["event_type"] == "PRICE_CONFIRMED" for e in s.events) for s in snaps), (
        "test fixture assumption broken: RECT-1 alone should not confirm anything"
    )
    report = movement_vs_direction_report(snaps, {"SYN1": bars}, horizons=(1, 3, 5))
    assert report == {}


def test_confirmed_events_via_replay_transitions_and_direct_detect_agree_on_confirmation_date():
    """Sanity-check the module's chosen definition of "confirmed pattern event" against
    replay.py's own independent notion of the same moment: the PRICE_CONFIRMED transition
    replay.py records must fall on the same date as the PRICE_CONFIRMED event inside the
    final snapshot's `.events` that this module reads."""
    bars = _shift_outside_sealed_window(synth.fixture_04_false_retest(synth.rect1()))
    result = replay.replay(bars, symbol="SYN1")
    rect_confirms = [t for t in result.transitions if t.pattern_type == "RECTANGLE" and t.new_status == "PRICE_CONFIRMED"]
    assert rect_confirms

    snaps = patterns.detect_as_of(bars, len(bars) - 1, symbol="SYN1")
    rectangles = [s for s in snaps if s.pattern_type == "RECTANGLE"]
    assert rectangles
    snap_confirm_dates = {e["date"] for e in rectangles[0].events if e["event_type"] == "PRICE_CONFIRMED"}
    assert {t.event_date for t in rect_confirms} == snap_confirm_dates


# ── Layer 2b: synthetic populations — grouping, n counts, no cross-symbol/family leakage ─


def _build_symbol(*, entry_idx: int, n_bars: int, jump_pct: float, drift_pct: float, volume_multiplier_at_entry: float, price_seed: float = 0.0):
    """A single-symbol bars frame with one clean, fully-controlled "event": price is flat
    (aside from the constant OHLC wick) through `entry_idx`, then (for a "hot" symbol)
    jumps by `jump_pct` on the very next bar and stays there, or (for a "cold" symbol)
    drifts by a tiny constant `drift_pct` per bar forever. Volume is a constant baseline
    everywhere except a single spike/dip exactly at `entry_idx` (`volume_multiplier_at_entry`),
    which `relative_volume`'s own `shift(1)` baseline correctly excludes from its own
    average. Returns (bars, entry_date_iso)."""
    price = 100.0 + price_seed
    closes = []
    for i in range(n_bars):
        price = price * (1.0 + drift_pct)
        if i == entry_idx + 1:
            price = price * (1.0 + jump_pct)
        closes.append(price)
    baseline_volume = 100_000.0
    volumes = [baseline_volume] * n_bars
    volumes[entry_idx] = baseline_volume * volume_multiplier_at_entry
    bars = synth.bars_from_closes(closes, volume=volumes, wick=0.30, start_date=_SAFE_START_DATE)
    entry_date = bars["date"].iloc[entry_idx].date().isoformat()
    return bars, entry_date


def _fake_snapshot(symbol: str, family: str, direction: str, confirm_date: str) -> dict:
    return {
        "pattern_id": f"{symbol}:{family}:{confirm_date}:X",
        "pattern_type": family,
        "direction": direction,
        "events": [{"date": confirm_date, "event_type": "PRICE_CONFIRMED", "rule_id": "TEST", "observed_values": {}}],
    }


_ENTRY_IDX = 25
_N_BARS = 40


@pytest.fixture
def hot_cold_population():
    """6 "hot" symbols (big up-jump right after confirmation + high relative volume AT
    confirmation -> movement label 1, direction BULLISH matching the up-move) and 6 "cold"
    symbols (tiny, consistently-signed drift + low relative volume -> movement label 0,
    direction BEARISH matching the (tiny) down-drift). By construction the movement
    predictor (relative volume) and the direction predictor (the pattern's own call)
    should each PERFECTLY separate their respective labels -> AUC == 1.0 if (and only if)
    the report correctly keeps every symbol's data to itself.
    """
    bars_by_symbol: dict[str, pd.DataFrame] = {}
    events: list[dict] = []
    hot_symbols, cold_symbols = [], []

    for i in range(6):
        sym = f"HOT{i}"
        bars, entry_date = _build_symbol(
            entry_idx=_ENTRY_IDX, n_bars=_N_BARS, jump_pct=0.30, drift_pct=0.0,
            volume_multiplier_at_entry=3.0, price_seed=float(i),
        )
        bars_by_symbol[sym] = bars
        events.append(_fake_snapshot(sym, "F", "BULLISH", entry_date))
        hot_symbols.append(sym)

    for i in range(6):
        sym = f"COLD{i}"
        bars, entry_date = _build_symbol(
            entry_idx=_ENTRY_IDX, n_bars=_N_BARS, jump_pct=0.0, drift_pct=-0.0005,
            volume_multiplier_at_entry=0.3, price_seed=float(i),
        )
        bars_by_symbol[sym] = bars
        events.append(_fake_snapshot(sym, "F", "BEARISH", entry_date))
        cold_symbols.append(sym)

    return {"bars_by_symbol": bars_by_symbol, "events": events, "hot": hot_symbols, "cold": cold_symbols}


def test_report_perfectly_separates_hot_and_cold_symbols_at_every_horizon(hot_cold_population):
    report = movement_vs_direction_report(
        hot_cold_population["events"], hot_cold_population["bars_by_symbol"], horizons=(1, 3, 5)
    )
    for h in (1, 3, 5):
        cell = report[("F", h)]
        assert cell.move.n == 12, f"horizon {h}: expected all 12 confirmed events to resolve"
        assert cell.move.auc == pytest.approx(1.0), f"horizon {h}: relative-volume should perfectly rank movement"
        assert cell.direction.n == 12
        assert cell.direction.auc == pytest.approx(1.0), f"horizon {h}: BULLISH/BEARISH call should perfectly match sign"


def test_report_does_not_leak_when_one_symbols_bars_are_missing(hot_cold_population):
    """Drop one hot symbol's bars entirely. Its event must be silently excluded (not
    crash, not fall back to some other symbol's bars) -- n drops by exactly one and the
    remaining, still-perfectly-separable population keeps AUC == 1.0. A bug that matched
    events to bars positionally (e.g. by iteration order) rather than by symbol key would
    very likely misalign at least one of the remaining symbols here and break this."""
    bars_by_symbol = dict(hot_cold_population["bars_by_symbol"])
    del bars_by_symbol["HOT0"]

    report = movement_vs_direction_report(hot_cold_population["events"], bars_by_symbol, horizons=(3,))
    cell = report[("F", 3)]
    assert cell.move.n == 11
    assert cell.direction.n == 11
    assert cell.move.auc == pytest.approx(1.0)
    assert cell.direction.auc == pytest.approx(1.0)


def test_report_keeps_families_and_horizons_independent(hot_cold_population):
    """A second family "G", reusing 2 hot + 2 cold symbols (same bars, same confirmation
    dates -- entirely plausible in reality, e.g. two different detectors both confirming
    on the same symbol/date), must land in its OWN (family, horizon) cells without
    disturbing family "F"'s counts, and must independently report its own small-n edge
    case (n=4 < the default floor of 10 -> insufficient_n) rather than being silently
    merged into -- or silently omitted from -- the report."""
    mixed_symbols = hot_cold_population["hot"][:2] + hot_cold_population["cold"][:2]
    directions = {**{s: "BULLISH" for s in hot_cold_population["hot"][:2]}, **{s: "BEARISH" for s in hot_cold_population["cold"][:2]}}
    g_events = []
    for sym in mixed_symbols:
        # Re-derive this symbol's own confirmation date from its own bars (never another
        # symbol's) -- the same _ENTRY_IDX used to build every symbol in the fixture.
        entry_date = hot_cold_population["bars_by_symbol"][sym]["date"].iloc[_ENTRY_IDX].date().isoformat()
        g_events.append(_fake_snapshot(sym, "G", directions[sym], entry_date))

    all_events = hot_cold_population["events"] + g_events
    report = movement_vs_direction_report(all_events, hot_cold_population["bars_by_symbol"], horizons=(3,))

    # Family F is completely unaffected by G's extra events.
    assert report[("F", 3)].move.n == 12
    assert report[("F", 3)].move.auc == pytest.approx(1.0)

    # Family G gets its own honestly-small-n cell -- present, not fabricated, not merged.
    g_cell = report[("G", 3)]
    assert g_cell.move.n == 4
    assert g_cell.move.reason == "insufficient_n"
    assert g_cell.move.auc is None
    assert g_cell.direction.n == 4
    assert g_cell.direction.reason == "insufficient_n"


def test_report_excludes_events_whose_horizon_overruns_available_bars(hot_cold_population):
    """A symbol whose bars stop just short of horizon 5 (but comfortably cover 1 and 3)
    must be excluded ONLY at horizon 5 -- n at horizons 1/3 includes it, n at horizon 5
    does not, and nothing crashes."""
    short_bars, short_entry_date = _build_symbol(
        entry_idx=_ENTRY_IDX, n_bars=_ENTRY_IDX + 4, jump_pct=0.30, drift_pct=0.0,  # reaches entry+3, not entry+5
        volume_multiplier_at_entry=3.0, price_seed=99.0,
    )
    bars_by_symbol = dict(hot_cold_population["bars_by_symbol"])
    bars_by_symbol["HOTSHORT"] = short_bars
    events = hot_cold_population["events"] + [_fake_snapshot("HOTSHORT", "F", "BULLISH", short_entry_date)]

    report = movement_vs_direction_report(events, bars_by_symbol, horizons=(1, 3, 5))
    assert report[("F", 1)].move.n == 13
    assert report[("F", 3)].move.n == 13
    assert report[("F", 5)].move.n == 12  # HOTSHORT excluded: entry_idx+5 is out of range


def test_tuple_form_and_pattern_id_parsing_form_agree(hot_cold_population):
    """`(symbol, snapshot)` explicit tuples must behave identically to bare snapshots whose
    symbol is parsed from `pattern_id` — both are documented, supported input shapes."""
    events = hot_cold_population["events"]
    tuple_events = [(e["pattern_id"].split(":", 1)[0], e) for e in events]

    bare_report = movement_vs_direction_report(events, hot_cold_population["bars_by_symbol"], horizons=(3,))
    tuple_report = movement_vs_direction_report(tuple_events, hot_cold_population["bars_by_symbol"], horizons=(3,))

    assert bare_report[("F", 3)].to_dict() == tuple_report[("F", 3)].to_dict()


def test_report_to_rows_is_sorted_and_matches_report():
    bars, entry_date = _build_symbol(entry_idx=_ENTRY_IDX, n_bars=_N_BARS, jump_pct=0.3, drift_pct=0.0, volume_multiplier_at_entry=2.0)
    events = [_fake_snapshot("ZZZ", "RECTANGLE", "BULLISH", entry_date), _fake_snapshot("ZZZ", "HH_HL", "BULLISH", entry_date)]
    report = movement_vs_direction_report(events, {"ZZZ": bars}, horizons=(1, 3))
    rows = report_to_rows(report)
    assert [ (r["family"], r["horizon"]) for r in rows ] == sorted(report.keys())
    assert len(rows) == len(report)


# ── Fix 1: sealed-window guard on the research path (review 2026-09-22, defect #1) ──────


def test_movement_report_refuses_a_confirmed_event_dated_inside_the_sealed_window():
    """`movement_vs_direction_report` is a RESEARCH evaluation path, so a confirmed event
    whose own entry (confirmation) date falls inside the sealed 2023-01-01..2024-07-31
    out-of-sample block must be refused outright, not silently included."""
    bars, _ = _build_symbol(entry_idx=_ENTRY_IDX, n_bars=_N_BARS, jump_pct=0.3, drift_pct=0.0, volume_multiplier_at_entry=2.0)
    poisoned_event = _fake_snapshot("ZZZ", "F", "BULLISH", "2023-06-15")
    assert research_window.is_sealed_gap("2023-06-15")  # sanity: the poisoned date really is sealed
    with pytest.raises(research_window.SealedWindowError):
        movement_vs_direction_report([poisoned_event], {"ZZZ": bars}, horizons=(1,))


def test_movement_report_over_events_outside_the_sealed_window_is_unaffected():
    """Control: the same call shape, but every confirmed event's entry date sits safely
    outside the sealed window (as every other test in this file now does) — must run
    normally, proving the guard above is checking dates, not raising unconditionally."""
    bars, entry_date = _build_symbol(entry_idx=_ENTRY_IDX, n_bars=_N_BARS, jump_pct=0.3, drift_pct=0.0, volume_multiplier_at_entry=2.0)
    assert not research_window.is_sealed_gap(entry_date)
    events = [_fake_snapshot("ZZZ", "F", "BULLISH", entry_date)]
    report = movement_vs_direction_report(events, {"ZZZ": bars}, horizons=(1,))
    assert ("F", 1) in report
