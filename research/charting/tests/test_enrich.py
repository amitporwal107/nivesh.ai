"""Research enrichment layer tests -- `research/charting/enrich.py`.

Central to this test file: the owner's course-correction requires enrichment to be a
non-mutating, separate layer on top of `patterns.py`'s output, never a change to
`patterns.py` itself. Every test here either proves that boundary directly (non-mutation,
`detect_as_of` output unchanged) or exercises `enrich_pattern`'s own added value (breakout
metrics, trend class, research_state) against realistic pattern dicts.
"""
from __future__ import annotations

import copy
import json

import pandas as pd
import pytest

from research.charting import enrich, states
from research.charting.config import CONFIG
from research.charting.lifecycle import LifecycleState
from research.charting.patterns import detect_as_of
from research.charting.series import atr as atr_series_fn
from research.charting.series import relative_volume as relvol_series_fn
from research.charting.tests import synth

_SAFE_START = "2019-01-02"  # well before the sealed 2023-01-01..2024-07-31 window


def _confirmed_rectangle_dict(*, start_date: str | None = None) -> tuple[dict, pd.DataFrame]:
    """A REAL `detect_as_of` output: RECT-1 + fixture #2 (low-volume breakout, still
    PRICE_CONFIRMED -- see test_patterns.py's own use of this exact fixture), optionally
    with its calendar shifted outside the sealed window (detection logic itself has no
    date-arithmetic dependency, only formatting -- shifting dates does not change which
    patterns are detected, only what regime.py later says about their trend context)."""
    bars = synth.fixture_02_low_volume_breakout(synth.rect1())
    if start_date is not None:
        bars = bars.copy()
        bars["date"] = pd.bdate_range(start_date, periods=len(bars))
    t = len(bars) - 1
    pats = detect_as_of(bars, t, symbol="SYN1")
    rects = [p for p in pats if p.pattern_type == "RECTANGLE" and p.status == LifecycleState.PRICE_CONFIRMED.value]
    assert len(rects) == 1
    return rects[0].to_dict(), bars


def _synthetic_benchmark(n: int = 300, start_date: str = _SAFE_START) -> pd.DataFrame:
    closes = [200 + 0.2 * i + (i % 5) * 0.3 for i in range(n)]
    return synth.bars_from_closes(closes, start_date=start_date, wick=0.5)


# ── Non-mutation contract (the owner's course-correction) ───────────────────────────────


def test_enrich_pattern_never_mutates_the_input_dict():
    pattern_dict, bars = _confirmed_rectangle_dict(start_date=_SAFE_START)
    before = json.dumps(pattern_dict, sort_keys=True, default=str)
    snapshot = copy.deepcopy(pattern_dict)

    enrich.enrich_pattern(pattern_dict, bars, benchmark_df=_synthetic_benchmark())

    after = json.dumps(pattern_dict, sort_keys=True, default=str)
    assert before == after
    assert pattern_dict == snapshot


def test_detect_as_of_output_is_unchanged_by_importing_and_running_enrichment():
    """Proves the separation the owner asked for holds end-to-end: running
    `enrich_pattern` (which imports `regime`/`states`, never `patterns`) must not change
    what a FRESH `detect_as_of` call on the SAME fixture produces afterwards."""
    bars = synth.fixture_02_low_volume_breakout(synth.rect1())
    t = len(bars) - 1

    before = [p.to_dict() for p in detect_as_of(bars, t, symbol="SYN1")]

    pattern_dict, enrich_bars = _confirmed_rectangle_dict(start_date=_SAFE_START)
    enrich.enrich_pattern(pattern_dict, enrich_bars, benchmark_df=_synthetic_benchmark())

    after = [p.to_dict() for p in detect_as_of(bars, t, symbol="SYN1")]
    assert before == after


def test_enrich_pattern_returns_a_brand_new_dict_not_a_view():
    pattern_dict, bars = _confirmed_rectangle_dict(start_date=_SAFE_START)
    result = enrich.enrich_pattern(pattern_dict, bars, benchmark_df=_synthetic_benchmark())
    assert result is not pattern_dict
    assert set(result) & set(pattern_dict) <= {"pattern_id"}  # disjoint field namespaces, only pattern_id in common


# ── research_state wiring ────────────────────────────────────────────────────────────────


def test_research_state_matches_direct_states_call():
    pattern_dict, bars = _confirmed_rectangle_dict(start_date=_SAFE_START)
    result = enrich.enrich_pattern(pattern_dict, bars, benchmark_df=_synthetic_benchmark())

    volume = pattern_dict["components"]["volume"]
    expected = states.derive_research_state(pattern_dict["status"], None, pattern_dict["direction"], volume_status=volume)
    assert result["research_state"] == expected
    assert result["research_state_basis"] == {"lifecycle_state": pattern_dict["status"], "volume_component": volume}
    # PRICE_CONFIRMED is a CONFIRMED_BREAKOUT only with a confirmed volume component, else a BREAKOUT_CANDIDATE
    assert result["research_state"] == (states.CONFIRMED_BREAKOUT if str(volume).upper() in ("PASS", "CONFIRMED")
                                        else states.BREAKOUT_CANDIDATE)


def test_unconfirmed_pattern_never_reports_confirmed_breakout_research_state():
    """fixture #1: wick-only breach, status BREAKOUT_ATTEMPT -- section 37.6's own rule."""
    bars = synth.fixture_01_wick_only_breakout(synth.rect1())
    bars = bars.copy()
    bars["date"] = pd.bdate_range(_SAFE_START, periods=len(bars))
    t = len(bars) - 1
    pats = detect_as_of(bars, t, symbol="SYN1")
    attempt = next(p for p in pats if p.pattern_type == "RECTANGLE" and p.status == LifecycleState.BREAKOUT_ATTEMPT.value)

    result = enrich.enrich_pattern(attempt.to_dict(), bars, benchmark_df=_synthetic_benchmark())
    assert result["research_state"] == states.EARLY_SIGNAL  # wick only: no close beyond the level
    assert result["research_state"] != states.CONFIRMED_BREAKOUT


# ── Breakout metrics -- "where applicable" ───────────────────────────────────────────────


def test_breakout_metrics_present_and_hand_cross_checked_for_a_confirmed_pattern():
    pattern_dict, bars = _confirmed_rectangle_dict(start_date=_SAFE_START)
    result = enrich.enrich_pattern(pattern_dict, bars, benchmark_df=_synthetic_benchmark())

    confirm_event = next(e for e in pattern_dict["events"] if e["event_type"] == "PRICE_CONFIRMED")
    confirm_close = confirm_event["observed_values"]["close"]
    level = confirm_event["observed_values"]["breakout_level"]
    confirm_idx = bars.index[bars["date"] == pd.Timestamp(confirm_event["date"])][0]

    assert result["breakout_level"] == pytest.approx(level)
    assert result["breakout_threshold_pct"] == pytest.approx(abs(confirm_close - level) / level * 100.0)

    expected_atr = float(atr_series_fn(bars, period=CONFIG["atr_period"]).iloc[confirm_idx])
    assert result["breakout_threshold_atr"] == pytest.approx(abs(confirm_close - level) / expected_atr)
    # `level` here is the event's own stored "breakout_level", which is already the
    # ATR-buffered trigger (resistance + breakout_buffer_atr * ATR at the confirming bar --
    # see patterns.py's `_walk_rectangle_lifecycle`), not the raw resistance price. The
    # confirmation rule only guarantees close > level (a strictly positive distance), not
    # any particular multiple of ATR beyond it -- so the one thing provable here is that
    # the sign/magnitude is a real positive distance, cross-checked against direct
    # recomputation above, not against `breakout_buffer_atr` itself.
    assert result["breakout_threshold_atr"] > 0

    expected_relvol = float(relvol_series_fn(bars, n=CONFIG["volume_baseline_bars"]).iloc[confirm_idx])
    assert result["breakout_volume_ratio"] == pytest.approx(expected_relvol)


def test_breakout_metrics_are_none_when_pattern_never_confirmed():
    bars = synth.fixture_01_wick_only_breakout(synth.rect1())
    bars = bars.copy()
    bars["date"] = pd.bdate_range(_SAFE_START, periods=len(bars))
    t = len(bars) - 1
    pats = detect_as_of(bars, t, symbol="SYN1")
    attempt = next(p for p in pats if p.pattern_type == "RECTANGLE" and p.status == LifecycleState.BREAKOUT_ATTEMPT.value)

    result = enrich.enrich_pattern(attempt.to_dict(), bars, benchmark_df=_synthetic_benchmark())
    assert result["breakout_level"] is None
    assert result["breakout_threshold_pct"] is None
    assert result["breakout_threshold_atr"] is None
    assert result["breakout_volume_ratio"] is None


def test_breakout_metrics_are_none_when_t_is_before_the_confirming_bar():
    """Point-in-time: an explicit `t` earlier than the pattern's own confirming bar must
    not reveal that future breakout's metrics, even though `pattern_dict["status"]`
    already (honestly) says PRICE_CONFIRMED as of the detector's own later `t`."""
    pattern_dict, bars = _confirmed_rectangle_dict(start_date=_SAFE_START)
    confirm_event = next(e for e in pattern_dict["events"] if e["event_type"] == "PRICE_CONFIRMED")
    confirm_date = pd.Timestamp(confirm_event["date"])
    earlier_t = confirm_date - pd.tseries.offsets.BDay(1)

    result = enrich.enrich_pattern(pattern_dict, bars, t=earlier_t, benchmark_df=_synthetic_benchmark())
    assert result["breakout_level"] is None
    assert result["breakout_threshold_pct"] is None
    assert result["breakout_threshold_atr"] is None
    assert result["breakout_volume_ratio"] is None


# ── Trend class wiring (section 37.1, via regime.py) ─────────────────────────────────────


def test_trend_class_fields_present_with_ok_status_on_a_long_clean_fixture():
    """A hand-built minimal CONFIRMED-shaped dict (enrich_pattern's contract is the SHAPE,
    not any one specific detector run -- see module docstring) over a long, clean,
    outside-the-sealed-window bars frame, long enough for slope AND ADX(14) to both
    resolve OK."""
    closes = [100 + 0.3 * i + (i % 7) * 0.4 for i in range(300)]
    bars = synth.bars_from_closes(closes, start_date=_SAFE_START, wick=0.5)
    last_date = bars["date"].iloc[-1]

    pattern_dict = {
        "pattern_id": "TEST:RECTANGLE:hand-built",
        "pattern_type": "RECTANGLE",
        "direction": "BULLISH",
        "population": "CONFIRMED",
        "status": LifecycleState.PRICE_CONFIRMED.value,
        "formation_end": last_date.date().isoformat(),
        "events": [{
            "date": last_date.date().isoformat(),
            "event_type": "PRICE_CONFIRMED",
            "rule_id": "CLOSE_ABOVE_BREAKOUT",
            "observed_values": {"close": float(bars["close"].iloc[-1]), "breakout_level": float(bars["close"].iloc[-1]) - 1.0},
        }],
    }

    result = enrich.enrich_pattern(pattern_dict, bars, benchmark_df=_synthetic_benchmark())

    assert result["stock_trend_class_slope_pct_per_day_status"] == "OK"
    assert result["stock_trend_class_adx_14_status"] == "OK"
    assert result["stock_trend_class_class_status"] == "OK"
    assert result["market_trend_class_slope_pct_per_day_status"] == "OK"
    assert result["market_trend_class_adx_14_status"] == "OK"
    assert result["market_trend_class_class_status"] == "OK"
    assert result["stock_trend_class_class"] in (
        "STRONG_BULL", "BULL", "BEAR", "STRONG_BEAR", "SIDEWAYS",
    )


def test_trend_class_fields_are_sealed_gap_unavailable_inside_the_sealed_window():
    """RECT-1's DEFAULT dates (unshifted) sit inside the sealed 2023-01-01..2024-07-31
    window (see test_regime_trend.py's own note on this) -- proves the sealed-window
    guard is respected end-to-end through enrich.py, not bypassed."""
    pattern_dict, bars = _confirmed_rectangle_dict(start_date=None)  # default (sealed) dates
    result = enrich.enrich_pattern(pattern_dict, bars, benchmark_df=_synthetic_benchmark())

    assert result["stock_trend_class_slope_pct_per_day_status"] == "UNAVAILABLE"
    assert result["stock_trend_class_slope_pct_per_day_reason"] == "SEALED_GAP"
    assert result["market_trend_class_slope_pct_per_day_status"] == "UNAVAILABLE"
    assert result["market_trend_class_slope_pct_per_day_reason"] == "SEALED_GAP"


# ── Input-shape validation ───────────────────────────────────────────────────────────────


def test_enrich_pattern_rejects_a_dict_missing_the_confirmed_population_shape():
    early_shaped = {"symbol": "SYN1", "formation_stage": "EARLY_FORMATION", "direction": "BULLISH"}
    with pytest.raises(ValueError):
        enrich.enrich_pattern(early_shaped, _synthetic_benchmark(), benchmark_df=_synthetic_benchmark())
