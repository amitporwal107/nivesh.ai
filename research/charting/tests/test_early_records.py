"""Stage 1-3 population separation — docs/charting.md §34.2, §34.3, SNAPSHOT_SCHEMA.md's
`"population": "CONFIRMED | EARLY"` contract."""
from __future__ import annotations

import dataclasses

import pandas as pd
import pytest

from research.charting import patterns
from research.charting.early.records import (
    POPULATION,
    EarlyFormationRecord,
    build_record_as_of,
    checkpoint_record,
    find_range_candidate_as_of,
    first_detection_index_for,
)
from research.charting.tests import synth


# ── Requirement 3: population separation from patterns.py ───────────────────


def test_population_constant_is_early():
    assert POPULATION == "EARLY"


def test_early_record_population_is_always_early():
    bars = synth.rect1()
    rec = build_record_as_of(bars, 19, symbol="SYN1", direction="BULLISH")
    assert rec is not None
    assert rec.population == "EARLY"


def test_confirmed_patterns_population_is_never_early():
    """patterns.py's own CONFIRMED population must never say "EARLY" -- the two
    detectors are separate code paths and neither should be able to produce the
    other's tag."""
    bars = synth.fixture_03_close_back_inside(synth.rect1())
    confirmed = patterns.detect_as_of(bars, 20, symbol="SYN1")
    assert confirmed  # sanity: the CONFIRMED detector actually found something here
    for p in confirmed:
        assert p.population == "CONFIRMED"
        assert p.population != POPULATION


def test_early_formation_record_has_no_research_eligible_or_confirmed_fields():
    """§34.2: Stage 1-3 detections are "not eligible for §11's RESEARCH_ELIGIBLE state
    and must never be reported as confirmed patterns." Statically confirm the record
    type carries no §11 lifecycle-state field that could be mistaken for one."""
    field_names = {f.name for f in dataclasses.fields(EarlyFormationRecord)}
    assert "status" not in field_names  # patterns.PatternSnapshot's §11 LifecycleState field
    assert "stage" not in field_names  # patterns.PatternSnapshot's §11 "stage" field (always None there)
    assert "formation_stage" in field_names  # §34.3's own label lives under its own name instead
    assert "research_eligible" not in field_names


# ── Candidate detection sanity (RECT-1) ──────────────────────────────────────


def test_find_range_candidate_matches_rect1_support_resistance():
    bars = synth.rect1()
    cand = find_range_candidate_as_of(bars, 19)
    assert cand is not None
    assert cand.support == pytest.approx(synth.RECT1_SUPPORT)
    assert cand.resistance == pytest.approx(synth.RECT1_RESISTANCE)
    assert cand.trigger_level > cand.resistance
    assert cand.invalidation_level < cand.support


def test_no_candidate_before_both_boundaries_have_a_confirmed_touch():
    bars = synth.rect1()
    for t in range(0, 10):
        assert find_range_candidate_as_of(bars, t) is None


def test_first_detection_index_is_stable_and_never_after_t():
    bars = synth.rect1()
    fdi_19 = first_detection_index_for(bars, 19)
    fdi_17 = first_detection_index_for(bars, 17)
    assert fdi_19 is not None and fdi_17 is not None
    assert fdi_19 <= 19
    assert fdi_17 <= 17
    # Once detectable, the SAME structure's first-detection bar does not move as more
    # bars arrive -- it is a fact about the past, not re-estimated on every new bar.
    assert fdi_19 == fdi_17


# ── build_record_as_of ───────────────────────────────────────────────────────


def test_build_record_as_of_returns_none_before_a_candidate_exists():
    bars = synth.rect1()
    assert build_record_as_of(bars, 5, symbol="SYN1", direction="BULLISH") is None


def test_build_record_as_of_produces_a_valid_stage_label():
    bars = synth.rect1()
    rec = build_record_as_of(bars, 19, symbol="SYN1", direction="BULLISH")
    assert rec.formation_stage in ("EARLY_FORMATION", "PATTERN_DEVELOPING", "BREAKOUT_READINESS")
    assert rec.detection_timestamp <= rec.as_of_date
    assert rec.first_detection_index <= rec.as_of_index


def test_build_record_as_of_live_maturity_grows_with_more_bars():
    bars = synth.rect1()
    fdi = first_detection_index_for(bars, 19)
    rec_early = build_record_as_of(bars, fdi, symbol="SYN1", direction="BULLISH", first_detection_index=fdi)
    rec_later = build_record_as_of(bars, 19, symbol="SYN1", direction="BULLISH", first_detection_index=fdi)
    assert rec_early.live_maturity.maturity == 0.0
    assert rec_later.live_maturity.maturity > rec_early.live_maturity.maturity


# ── checkpoint_record: no t_end-derived field on the record ──────────────────


def _extend_range_bound(bars: pd.DataFrame, n_quiet: int, breakout_close: float) -> pd.DataFrame:
    """Local synthetic extension (does not modify tests/synth.py): `n_quiet` byte-
    identical flat bars -- guaranteed to create no new swing pivots, so the RECT-1
    100/110 levels stay the ones `find_range_candidate_as_of` selects at every later
    `t` -- followed by one decisive breakout bar closing at `breakout_close`."""
    from research.charting.config import BARS_COLUMNS

    last_date = pd.Timestamp(bars["date"].iloc[-1])
    dates = pd.bdate_range(start=last_date + pd.tseries.offsets.BDay(1), periods=n_quiet + 1)
    rows = [(dates[i], 105.0, 105.6, 104.4, 105.2, 100_000.0) for i in range(n_quiet)]
    rows.append((dates[n_quiet], 105.2, breakout_close + 1.0, 104.7, breakout_close, 250_000.0))
    ext = pd.DataFrame(rows, columns=list(BARS_COLUMNS))
    return pd.concat([bars, ext], ignore_index=True)


def test_checkpoint_record_has_no_t_end_final_length_or_bars_to_breakout_field():
    bars = _extend_range_bound(synth.rect1(), n_quiet=20, breakout_close=113.0)
    t_start, t_end = 14, len(bars) - 1
    ck, rec = checkpoint_record(bars, t_start=t_start, t_end=t_end, fraction=0.4, symbol="SYN1", direction="BULLISH")
    assert ck.t_end == t_end  # the checkpoint metadata is allowed to know t_end...
    field_names = {f.name for f in dataclasses.fields(EarlyFormationRecord)}
    assert "t_end" not in field_names  # ...but the RECORD itself must not carry it anywhere
    assert "final_length" not in field_names
    assert "bars_to_breakout" not in field_names
    assert rec.as_of_index == ck.t_ck
    assert rec.population == "EARLY"


def test_checkpoint_record_all_four_fractions_stay_pre_trigger_in_this_fixture():
    """Sanity check on the fixture used by the lookahead probes: all four checkpoints
    fall before the breakout bar, so confirmation_score is NOT_YET_TRIGGERED at every
    one of them -- the interesting case for THIS package (Stage 1-3 scoring)."""
    from research.charting.config import CONFIG

    bars = _extend_range_bound(synth.rect1(), n_quiet=20, breakout_close=113.0)
    t_start, t_end = 14, len(bars) - 1
    for f in CONFIG["early_maturity_checkpoints"]:
        ck, rec = checkpoint_record(bars, t_start=t_start, t_end=t_end, fraction=f, symbol="SYN1", direction="BULLISH")
        assert ck.t_ck < t_end
        assert rec.scores.confirmation_score.status == "NOT_YET_TRIGGERED"


def test_checkpoint_record_raises_when_no_candidate_exists_at_t_ck():
    bars = synth.rect1()
    with pytest.raises(ValueError):
        checkpoint_record(bars, t_start=0, t_end=5, fraction=0.5, symbol="SYN1", direction="BULLISH")
