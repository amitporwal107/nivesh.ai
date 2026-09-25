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


# ── with_targets=False: the random-control fast path (2026-09-24) ───────────────────────────────

def _lean_universe():
    from research.charting.tests._events_helpers import confirmed_rectangle_with_runway
    base = confirmed_rectangle_with_runway(tail_len=40)
    bbs = {}
    for i in range(6):
        b = base.copy()
        f = 1.0 + 0.05 * i
        for c in ("open", "high", "low", "close"):
            b[c] = b[c] * f
        bbs[f"SYM{i:02d}"] = b
    pairs = [(s, i) for s in bbs for i in range(20, 30)]
    return bbs, pairs


def test_skipping_the_target_walk_leaves_every_cost_figure_bit_identical():
    """The whole justification for the fast path: `report.comparison_block` reads
    `costs.by_horizon[h].scenarios[s].net_before_tax`, which must not move by a single bit when the
    target walk is skipped. If this fails, the speedup is changing the study's numbers."""
    import json
    bbs, pairs = _lean_universe()
    full = controls.price_signals(bbs, set(pairs), with_targets=True)
    lean = controls.price_signals(bbs, set(pairs), with_targets=False)

    assert set(full) == set(lean) and full, "the two paths priced different pairs"
    for key in full:
        a, b = full[key], lean[key]
        assert json.dumps(a["costs"], sort_keys=True, default=str) == \
               json.dumps(b["costs"], sort_keys=True, default=str), f"{key}: costs differ"
        assert a["atr_at_t"] == b["atr_at_t"]
        assert json.dumps(a["outcomes"], sort_keys=True, default=str) == \
               json.dumps(b["outcomes"], sort_keys=True, default=str), f"{key}: outcomes differ"
        assert json.dumps(a["entry"], sort_keys=True, default=str) == \
               json.dumps(b["entry"], sort_keys=True, default=str)


def test_the_lean_path_marks_targets_absent_rather_than_faking_them():
    """`targets: None` is the value a BEARISH row already carries, so every consumer treats it as
    "absent". A zeroed target block would instead read as "no target was hit", which is a different
    and wrong claim."""
    bbs, pairs = _lean_universe()
    lean = controls.price_signals(bbs, set(pairs), with_targets=False)
    one = next(iter(lean.values()))
    assert one["targets"] is None
    assert one["stop"]["stop_layer"] == "not_computed"
    assert "TARGET_WALK_SKIPPED" in one["stop"]["reason"]

    from research.charting.study import report
    assert report._target_horizon_block(one, "pct_2", 5) is None   # reads as absent, not as a miss


def test_the_full_path_remains_the_default():
    """Only the random control opts out. Pattern events and the other control groups must be
    unaffected, or the study loses its hit-rate tables."""
    bbs, pairs = _lean_universe()
    default = controls.price_signals(bbs, set(pairs))
    one = next(iter(default.values()))
    assert one["targets"] is not None and one["stop"]["stop_layer"] != "not_computed"


def test_the_fast_path_is_actually_faster():
    """A flag that does not speed anything up would be pure risk. Measured 8.1x; asserted at 3x to
    stay robust on a loaded box."""
    import time
    bbs, pairs = _lean_universe()
    controls.price_signals(bbs, set(pairs[:3]))                      # warm caches
    t = time.time(); controls.price_signals(bbs, set(pairs), with_targets=True); full = time.time() - t
    t = time.time(); controls.price_signals(bbs, set(pairs), with_targets=False); lean = time.time() - t
    assert full / lean > 3.0, f"only {full/lean:.1f}x faster — the target walk was not the cost"


# ── event projection: the control phase must not pin whole pattern rows ─────────────────────────


def _projection_universe():
    """Real multi-symbol pattern events — the ATR-decile draw needs >= 2 same-date candidates, so a
    single symbol would make every assertion below vacuous."""
    from research.charting.events import extraction
    from research.charting.tests._events_helpers import confirmed_rectangle_with_runway

    base = confirmed_rectangle_with_runway(tail_len=40)
    bars_by_symbol, events = {}, []
    for i in range(6):
        scaled = base.copy()
        for c in ("open", "high", "low", "close"):
            scaled[c] = scaled[c] * (1.0 + 0.05 * i)
        sym = f"SYM{i:02d}"
        bars_by_symbol[sym] = scaled
        events.extend(extraction.extract_events(scaled, sym))
    eligible = [(s, i) for s in bars_by_symbol for i in range(20, 35)]
    assert events, "no events — the projection gate would compare nothing"
    return bars_by_symbol, events, eligible


def test_a_projection_carries_nothing_a_pattern_row_reports_on():
    """A projection is deliberately NOT a pattern row. If it quietly carried costs or outcomes it
    could be passed to the report by mistake and produce a plausible, wrong answer."""
    _bars, events, _eligible = _projection_universe()
    proj = controls.event_projection(events[0])
    for absent in ("costs", "outcomes", "targets", "context", "research", "liquidity", "versioning"):
        assert absent not in proj, f"projection leaked {absent!r}"
    assert set(proj) == set(controls.DRAW_FIELDS) | {"entry"}


def test_draws_and_assembly_are_identical_on_projections_and_full_rows():
    """The gate on DRAW_FIELDS: if any draw or assembly step reads a field the projection omits,
    this fails instead of the projection silently changing a control row."""
    bars_by_symbol, events, eligible = _projection_universe()
    projected = [controls.event_projection(e) for e in events]

    full_atr = controls.atr_decile_control_draws(bars_by_symbol, events, eligible, seed=0)
    proj_atr = controls.atr_decile_control_draws(bars_by_symbol, projected, eligible, seed=0)
    assert [picks for _ev, picks in full_atr] == [picks for _ev, picks in proj_atr]
    assert full_atr, "ATR-decile draw is empty — needs >= 2 same-date candidates"

    full_bno = controls.buy_next_open_baseline_draws(events)
    proj_bno = controls.buy_next_open_baseline_draws(projected)
    assert [pick for _ev, pick in full_bno] == [pick for _ev, pick in proj_bno]

    pairs = {p for _ev, picks in full_atr for p in picks} | {p for _ev, p in full_bno}
    priced = controls.price_signals(bars_by_symbol, pairs)
    for assemble, full_draws, proj_draws in (
        (controls.assemble_atr_decile_control_rows, full_atr, proj_atr),
        (controls.assemble_buy_next_open_baseline_rows, full_bno, proj_bno),
    ):
        from_full = assemble(bars_by_symbol, full_draws, priced)
        from_proj = assemble(bars_by_symbol, proj_draws, priced)
        assert from_full == from_proj, assemble.__name__
        assert from_full, f"{assemble.__name__} produced nothing — vacuous"


def test_a_projection_is_far_smaller_than_the_row_it_stands_in_for():
    """The whole point. The draws hold one reference per drawn event for the entire pricing phase."""
    import sys

    def deep(o, seen=None):
        seen = seen if seen is not None else set()
        if id(o) in seen:
            return 0
        seen.add(id(o))
        n = sys.getsizeof(o)
        if isinstance(o, dict):
            for k, v in o.items():
                n += deep(k, seen) + deep(v, seen)
        elif isinstance(o, (list, tuple, set)):
            for v in o:
                n += deep(v, seen)
        return n

    _bars, events, _eligible = _projection_universe()
    row_bytes = deep(events[0])
    proj_bytes = deep(controls.event_projection(events[0]))
    assert proj_bytes * 50 < row_bytes, (
        f"projection {proj_bytes} B vs row {row_bytes} B — not worth the indirection")
