"""controls.py: S18.3 comparison-group hooks -- fixed-seed random control and buy-next-open
baseline. Infrastructure only (task brief: "Build and test them; do not run them for
results") -- these tests check shape/determinism, never a performance number."""
from __future__ import annotations

import pytest

from research.charting.events import controls, extraction
from research.charting.tests._events_helpers import confirmed_rectangle_with_runway

_EXPECTED_KEYS = {
    "event_id", "symbol", "pattern_id", "pattern_type", "direction", "signal_date",
    "confirmation_bar_index", "level_broken", "level_broken_field", "atr_at_t",
    "relative_volume_at_t", "config_hash", "engine_version", "profile", "dataset_version",
    "source_event_id", "versioning", "entry", "outcomes", "outcomes_alt_close_entry",
    "liquidity", "costs", "stop", "targets", "tradability", "action", "unavailable_reason",
}


def test_random_control_rows_same_schema_as_pattern_events():
    bars = confirmed_rectangle_with_runway()
    eligible = [("SYN1", i) for i in range(5, 20)]
    rows = controls.random_control_rows({"SYN1": bars}, eligible, n=3, seed=1)
    assert len(rows) == 3
    for r in rows:
        assert set(r.keys()) == _EXPECTED_KEYS
        assert r["pattern_type"] == controls.RANDOM_CONTROL_PATTERN_TYPE
        assert r["direction"] == "BULLISH"
        assert r["level_broken"] is None  # no pattern -- no level was "broken"
        assert r["tradability"] == "LONG_ACTIONABLE"
        assert r["action"] == "CONSIDER_LONG"


def test_random_control_rows_stop_is_layer_2_only_no_structural_stop():
    """§37 task item 7: a control has no pattern, so no Layer 1 structural stop is possible --
    only the Layer 2 ATR floor, documented as `stop_layer == "layer2_only"`. `eligible` starts
    at index 20 (well past ATR(14)'s own `period + 1` = 15-bar warmup -- `series.atr`'s own
    documented contract) so every pick here has a real ATR(t) reading, not a warmup NaN."""
    bars = confirmed_rectangle_with_runway()
    eligible = [("SYN1", i) for i in range(20, 35)]
    rows = controls.random_control_rows({"SYN1": bars}, eligible, n=3, seed=1)
    assert len(rows) == 3
    for r in rows:
        assert r["atr_at_t"] is not None
        assert r["entry"]["primary"] is not None  # runway tail guarantees a t+1 bar here
        assert r["stop"]["structural_stop"] is None
        assert r["stop"]["stop_layer"] == "layer2_only"
        assert r["stop"]["final_stop"] is not None
        assert r["stop"]["final_stop"] < r["entry"]["primary"]["price"]
        assert r["targets"] is not None
        assert set(r["targets"].keys()) == {"pct_2", "pct_3", "pct_5", "pct_10", "r_1_0", "r_1_5", "r_2_0", "r_3_0"}


def test_random_control_rows_deterministic_for_the_same_seed():
    bars = confirmed_rectangle_with_runway()
    eligible = [("SYN1", i) for i in range(5, 20)]
    a = controls.random_control_rows({"SYN1": bars}, eligible, n=4, seed=99)
    b = controls.random_control_rows({"SYN1": bars}, eligible, n=4, seed=99)
    assert [r["event_id"] for r in a] == [r["event_id"] for r in b]


def test_random_control_rows_differ_for_a_different_seed():
    bars = confirmed_rectangle_with_runway()
    eligible = [("SYN1", i) for i in range(5, 20)]
    a = controls.random_control_rows({"SYN1": bars}, eligible, n=4, seed=1)
    b = controls.random_control_rows({"SYN1": bars}, eligible, n=4, seed=2)
    assert [r["event_id"] for r in a] != [r["event_id"] for r in b]


def test_random_control_rows_independent_of_eligible_input_order():
    bars = confirmed_rectangle_with_runway()
    eligible = [("SYN1", i) for i in range(5, 20)]
    a = controls.random_control_rows({"SYN1": bars}, eligible, n=4, seed=7)
    b = controls.random_control_rows({"SYN1": bars}, list(reversed(eligible)), n=4, seed=7)
    assert [r["event_id"] for r in a] == [r["event_id"] for r in b]


def test_random_control_rows_capped_at_the_eligible_population_size():
    bars = confirmed_rectangle_with_runway()
    eligible = [("SYN1", i) for i in range(5, 8)]  # only 3 eligible
    rows = controls.random_control_rows({"SYN1": bars}, eligible, n=100, seed=1)
    assert len(rows) == 3


def test_buy_next_open_baseline_one_row_per_event_same_confirmation_bar():
    bars = confirmed_rectangle_with_runway()
    events = extraction.extract_events(bars, "SYN1")
    baselines = controls.buy_next_open_baseline_rows({"SYN1": bars}, events)
    assert len(baselines) == len(events)
    for ev, bl in zip(events, baselines):
        assert bl["confirmation_bar_index"] == ev["confirmation_bar_index"]
        assert bl["pattern_type"] == controls.BUY_NEXT_OPEN_BASELINE_PATTERN_TYPE
        assert bl["direction"] == "BULLISH"
        assert bl["source_event_id"] == ev["event_id"]
        # Same entry convention (open of t+1) as the real event it baselines against.
        assert bl["entry"]["primary"]["index"] == ev["entry"]["primary"]["index"]
        assert bl["entry"]["primary"]["price"] == pytest.approx(ev["entry"]["primary"]["price"])


def test_buy_next_open_baseline_empty_for_no_events():
    bars = confirmed_rectangle_with_runway()
    assert controls.buy_next_open_baseline_rows({"SYN1": bars}, []) == []
