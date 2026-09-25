"""`study/pattern_table.py` — the columnar layout for pattern-event rows.

The layout is the contract between the writer and every reader, so these tests pin the decisions
that would silently corrupt a result if they drifted: which dtype holds which kind of value, that
absence stays distinguishable from a label, and that every field the report reads has a column.
"""
from __future__ import annotations

import numpy as np
import pytest

from research.charting.study import accumulate, report
from research.charting.study.pattern_table import (
    CONTEXT_KEYS, NO_CONTEXT, Dictionary, PatternLayout,
)


@pytest.fixture(scope="module")
def layout():
    return PatternLayout(accumulate.DEFAULT_HORIZONS, accumulate.DEFAULT_SCENARIOS,
                         report.DEFAULT_TARGET_NAMES)


# ── dictionary encoding ─────────────────────────────────────────────────────────────────────────

def test_codes_round_trip_exactly():
    d = Dictionary()
    for v in ("RECTANGLE", "HH_HL", "SUPPORT_RESISTANCE", "RECTANGLE"):
        assert d.value(d.code(v)) == v
    assert len(d) == 3, "a repeated value must reuse its code, not add one"


def test_absence_is_a_real_code_not_a_silent_blank():
    """`report.context_label` returns NO_CONTEXT when the block is missing. If absence encoded as
    an empty string or shared a code with a real label, a row with no context would be counted in
    some other bucket — a silent miscount, not a visible gap."""
    d = Dictionary()
    none_code = d.code(None)
    assert d.value(none_code) == NO_CONTEXT
    real_code = d.code("BULLISH_TREND")
    assert none_code != real_code
    assert d.value(d.code(NO_CONTEXT)) == NO_CONTEXT
    assert d.code(NO_CONTEXT) == none_code, "explicit NO_CONTEXT and None must share one code"


def test_an_unknown_code_decodes_to_no_context_rather_than_raising():
    """A corrupt or out-of-range code must degrade to the visible 'absent' label, not crash a
    report that is otherwise fine."""
    d = Dictionary()
    d.code("X")
    assert d.value(99) == NO_CONTEXT
    assert d.value(-1) == NO_CONTEXT


# ── the dtype split ─────────────────────────────────────────────────────────────────────────────

def test_mfe_and_mae_are_float64_because_auc_is_tie_sensitive(layout):
    """float32 rounding would MANUFACTURE ties that do not exist in the data, changing an AUC
    silently. They belong with the money columns, not the flags."""
    for h in layout.horizons:
        for field in ("mfe", "mae", "dir_return"):
            assert ("out", h, field) in layout.money_index
            assert ("out", h, field) not in layout.flag_index
    assert not any("dir_mfe" in str(k) for k in layout.money_index), (
        "dir_mfe/dir_mae are never read — report.bearish_directional_report takes MFE/MAE from "
        "forward_returns like every other row. A dead column invites a wrong join.")


def test_every_rupee_amount_is_float64(layout):
    """float32 carries ~7 decimal digits; an earlier version of the control layout lost 2e-8 on
    avg_cost by storing rupee values in it."""
    for h in layout.horizons:
        for s in layout.scenarios:
            for field in ("gross", "cost", "slip", "win", "loss"):
                assert ("cost", h, s, field) in layout.money_index
    for field in ("atr_at_t", "entry_price", "adv_inr_at_t"):
        assert ("row", field) in layout.money_index


def test_flags_hold_only_values_exact_in_float32(layout):
    """0/1 indicators, exit codes (1-4) and holding periods (0..20) are small integers, which
    float32 represents exactly — so this costs nothing."""
    for key in layout.flag_index:
        assert key[-1] in {"available", "is_win", "is_loss", "present", "code", "has_exit",
                           "hold", "net_hit", "fwd_available", "dir_available", "has_adv",
                           "priceable"}, key
    for v in [0, 1, 2, 3, 4] + list(range(21)):
        assert float(np.float32(v)) == float(v)


# ── completeness against what the report reads ──────────────────────────────────────────────────

def test_every_cost_cell_the_report_reads_has_a_column(layout):
    for h in layout.horizons:
        for s in layout.scenarios:
            assert (h, s) in layout.exact_index                    # net_before_tax, the exact one
            assert ("cost", h, s, "available") in layout.flag_index


def test_every_target_cell_the_report_reads_has_a_column(layout):
    """8 targets x 5 horizons for the hit-rate table, plus a net-hit flag per scenario."""
    assert len(layout.targets) == 8
    for t in layout.targets:
        for h in layout.horizons:
            for field in ("present", "code", "has_exit", "hold"):
                assert ("tgt", t, h, field) in layout.flag_index
            for s in layout.scenarios:
                assert ("tgt", t, h, s, "net_hit") in layout.flag_index


def test_the_three_segmentation_dimensions_are_encoded(layout):
    """§7.7 segments on these. `report.context_label` reads exactly these keys."""
    for key in CONTEXT_KEYS:
        assert key in layout.code_index
    assert "pattern_type" in layout.code_index and "direction" in layout.code_index


def test_the_bearish_directional_path_has_columns(layout):
    """§7.8 reports BEARISH rows from forward_returns_directional — a separate block from
    forward_returns, and easy to omit because bullish rows never use it."""
    for h in layout.horizons:
        assert ("out", h, "dir_return") in layout.money_index
        assert ("out", h, "dir_available") in layout.flag_index


# ── the layout itself ───────────────────────────────────────────────────────────────────────────

def test_column_indices_are_dense_and_unique(layout):
    for name, idx in (("money", layout.money_index), ("flag", layout.flag_index)):
        values = sorted(idx.values())
        assert values == list(range(len(idx))), f"{name} indices are not dense 0..n-1"
        assert len(set(idx)) == len(idx), f"{name} has duplicate keys"


def test_the_row_is_small_enough_to_fit_the_dataset_in_memory(layout):
    """The whole point: 188 KB/row of nested dicts made 133,743 pre-sealed rows cost 25.7 GB, which
    no machine we have could hold. Under ~4 KB/row the segment fits in well under 1 GB."""
    b = layout.bytes_per_row()
    assert b < 4096, f"{b} B/row — too large; the dataset would not fit"
    assert 133_743 * b < 1_000_000_000, "pre-sealed must fit in under 1 GB"


def test_the_layout_is_deterministic(layout):
    """Two instances must agree, or a table written by one is unreadable by the other."""
    other = PatternLayout(accumulate.DEFAULT_HORIZONS, accumulate.DEFAULT_SCENARIOS,
                          report.DEFAULT_TARGET_NAMES)
    assert other.money_index == layout.money_index
    assert other.flag_index == layout.flag_index
    assert other.exact_index == layout.exact_index
    assert other.code_columns == layout.code_columns


# ── equivalence: the columnar path must reproduce the row path exactly ──────────────────────────

@pytest.fixture(scope="module")
def real_rows():
    """Real pattern-event rows from the real pipeline — extraction AND the context join.

    Hand-built rows would test the encoder against my own idea of a row's shape, which is exactly
    the mistake that let `outcomes.forward_returns_directional` go missing from the first draft of
    the layout. The universe is deliberately mixed, because a uniform one makes the equivalence
    gate below pass without exercising anything: the first version used one bullish shape and so
    compared BEARISH, context-label and STOP-exit paths that were all empty.

      rect_up     bullish breakout, rising tail  -> TARGET-first exits
      rect_fall   same breakout, FALLING tail    -> STOP-first exits
      rect_bear   gap breakdown                  -> BEARISH rows (priced by nobody, §37.4)
      sr, hhhl    other families                 -> more than one pattern_type to group by
      ambiguous   a real `stops` walk where one bar touches target AND stop

    The guards at the end are the point, and they are asserted as SPREADS, not just non-zero: a
    fixture that drifts back to one direction or one label would make this file green and useless.
    """
    from collections import Counter
    from research.charting.events import context_join, extraction
    from research.charting.tests import _events_helpers as H
    from research.charting.tests.test_study_accumulate import _ambiguous_row

    anchor = float(H.confirmed_rectangle_with_runway(tail_len=1)["close"].iloc[-2])
    specs = [
        H.confirmed_rectangle_with_runway(tail_len=40),
        H.confirmed_rectangle_with_runway(tail_closes=[anchor - 0.9 * i for i in range(1, 41)]),
        H.confirmed_rectangle_bearish_with_runway(tail_len=40),
        H.confirmed_support_resistance_with_runway(tail_len=40),
        H.confirmed_hh_hl_with_runway(tail_len=40),
    ]
    rows = []
    for j, bars in enumerate(specs):
        for i in range(2):                      # price-scaled copies: same calendar, different ATR%
            scaled = bars.copy()
            for c in ("open", "high", "low", "close"):
                scaled[c] = scaled[c] * (1.0 + 0.05 * i)
            for r in extraction.extract_events(scaled, f"SYM{j}{i}"):
                rows.append(context_join.attach_to_event_row(
                    r, scaled, context_join.pattern_dict_for_event(scaled, r)))
    rows.append(_ambiguous_row("AMBIG-1"))

    directions = Counter(r.get("direction") for r in rows)
    assert directions["BULLISH"] and directions["BEARISH"], f"one-sided universe: {directions}"
    assert len({r.get("pattern_type") for r in rows}) > 1, "only one pattern_type to group by"
    labels = {report.context_label(r, "trend_class_class") for r in rows}
    assert labels - {NO_CONTEXT}, "every context label is NO_CONTEXT — segmentation untested"
    priced = [r for r in rows if (r.get("costs") or {}).get("by_horizon")]
    assert priced and len(priced) < len(rows), (
        "need both priced and unpriced rows, or the `priceable` flag proves nothing")
    exits = Counter()
    for t in report.DEFAULT_TARGET_NAMES:
        for h in accumulate.DEFAULT_HORIZONS:
            exits.update(report.hit_rate_table(rows, t, h)["counts"])
    for kind in ("target_first", "stop_first", "ambiguous", "neither"):
        assert exits[kind], f"no {kind} exit in the universe — that exit code is never encoded"
    return rows


@pytest.fixture(scope="module")
def real_table(real_rows, layout):
    from research.charting.study.pattern_table import PatternTable
    return PatternTable.from_rows(real_rows, layout)


def test_return_stats_match_the_row_path_bit_for_bit(real_rows, real_table, layout):
    """Every §7.3 figure, every horizon, every cost scenario. `==` not `approx`: the encoding
    changes how values are STORED, never what they are, so any difference is a defect."""
    from research.charting.study.pattern_table import table_return_stats

    compared = 0
    for h in layout.horizons:
        for s in layout.scenarios:
            expected = report.return_stats(real_rows, h, scenario=s)
            got = table_return_stats(real_table, h, scenario=s)
            assert got == expected, f"horizon={h} scenario={s}"
            compared += expected["n"]
    assert compared > 0, "every cell had n=0 — this gate compared nothing"


def test_hit_rate_tables_match_the_row_path(real_rows, real_table, layout):
    from research.charting.study.pattern_table import table_hit_rate_table

    compared = 0
    for t in layout.targets:
        for h in layout.horizons:
            for s in layout.scenarios:
                expected = report.hit_rate_table(real_rows, t, h, scenario=s)
                assert table_hit_rate_table(real_table, t, h, scenario=s) == expected
                compared += expected["n"]
    assert compared > 0, "no target cell had any row — vacuous"


def test_mfe_mae_matches_the_row_path(real_rows, real_table, layout):
    """MFE/MAE is the float64 case that matters: AUC is tie-sensitive, so a value that only
    matches to float32 would be a real defect, not a rounding detail."""
    from research.charting.study.pattern_table import table_mfe_mae_stats

    compared = 0
    for h in layout.horizons:
        expected = report.mfe_mae_stats(real_rows, h)
        assert table_mfe_mae_stats(real_table, h) == expected, f"horizon={h}"
        compared += expected["n"]
    assert compared > 0, "no row had a forward-return block — vacuous"


def test_bearish_directional_matches_the_row_path(real_rows, real_table, layout):
    from research.charting.study.pattern_table import table_bearish_directional_report

    for h in layout.horizons:
        expected = report.bearish_directional_report(real_rows, h)
        assert table_bearish_directional_report(real_table, h) == expected, f"horizon={h}"


def test_segmentation_inputs_survive_the_encoding(real_rows, real_table, layout):
    """§7.7 segments on labels and two derived buckets. The labels must decode to what
    `report.context_label` reads, and the ATR/liquidity numbers must still produce the same bucket."""
    for i, row in enumerate(real_rows):
        for key in ["trend_class_class", "market_trend_class_class", "regime_regime"]:
            assert real_table.labels(key)[i] == report.context_label(row, key)
        # `.get` semantics, matching `Dictionary.code(None)`: the ambiguity row is a partial row
        # straight from the stops walker, with no pattern_type/direction of its own.
        assert real_table.labels("pattern_type")[i] == (row.get("pattern_type") or NO_CONTEXT)
        assert real_table.labels("direction")[i] == (row.get("direction") or NO_CONTEXT)

        atr = real_table.money[i, layout.money_index[("row", "atr_at_t")]]
        price = real_table.money[i, layout.money_index[("row", "entry_price")]]
        expected_atr_pct = report.atr_pct_for_row(row)
        got = None if (np.isnan(atr) or np.isnan(price) or price <= 0) else float(atr) / float(price)
        assert got == expected_atr_pct, f"row {i}"

        adv = (row.get("liquidity") or {}).get("adv_inr_at_t")
        has_adv = real_table.flag[i, layout.flag_index[("row", "has_adv")]] == 1.0
        assert has_adv == (adv is not None)
        if adv is not None:
            assert real_table.money[i, layout.money_index[("row", "adv_inr_at_t")]] == float(adv)


def test_equal_weight_order_matches_the_row_path(real_rows, real_table):
    """max_drawdown is a property of this sequence, so the order is part of the result."""
    expected = [r.get("event_id") for r in
                sorted(real_rows, key=lambda r: (r.get("signal_date") or "", r.get("event_id") or ""))]
    assert [real_table.event_id[i] for i in real_table.order()] == expected


def test_priceable_flag_is_not_the_per_horizon_available_flag(real_rows, real_table, layout):
    """`assert_statistics_are_not_vacuous` counts rows with ANY by_horizon map. A row can have one
    in which every horizon is unavailable, so this flag cannot be derived from the others."""
    got = int(real_table.flag[:len(real_table), layout.flag_index[("row", "priceable")]].sum())
    assert got == sum(1 for r in real_rows if (r.get("costs") or {}).get("by_horizon"))


def test_absent_values_read_as_nan_not_zero(layout):
    """A reader that forgets the `available` flag must get a loud NaN, not a silent 0.0 that would
    drag a mean toward it."""
    from research.charting.study.pattern_table import PatternTable

    table = PatternTable(layout, 1)
    table.add({"event_id": "E1", "symbol": "S", "pattern_id": "P", "signal_date": "2024-08-01",
               "pattern_type": "RECTANGLE", "direction": "BULLISH"})
    assert np.isnan(table.exact[0]).all()
    assert np.isnan(table.money[0]).all()
    assert (table.flag[0] == 0.0).all(), "flags default to 0.0 = 'not observed'"


# ── persistence and the per-symbol split ────────────────────────────────────────────────────────

def test_save_load_round_trips_every_array_exactly(real_table, layout, tmp_path):
    from research.charting.study.pattern_table import load_table, save_table

    loaded = load_table(save_table(real_table, tmp_path / "t.npz"), layout)
    assert len(loaded) == len(real_table)
    for name in ("exact", "money", "flag", "codes"):
        a, b = getattr(real_table, name), getattr(loaded, name)
        assert np.array_equal(a[:len(real_table)], b[:len(loaded)], equal_nan=True), name
    for name in ("event_id", "symbol", "pattern_id", "signal_date"):
        assert list(getattr(loaded, name)) == list(getattr(real_table, name)), name
    for column in layout.code_index:
        assert loaded.labels(column) == real_table.labels(column)


def test_save_is_atomic_so_a_killed_run_leaves_no_half_file(real_table, tmp_path):
    """Six run attempts died to OOM kills and GCE reboots. A half-written file that resume mistakes
    for a complete one would corrupt the result rather than fail."""
    from research.charting.study.pattern_table import save_table

    path = save_table(real_table, tmp_path / "t.npz")
    assert path.exists() and not list(tmp_path.glob("*.tmp"))
    assert not list(tmp_path.glob("*.npz.npz")), "np.savez appended its own extension again"


def test_concat_remaps_codes_instead_of_relabelling_rows(layout):
    """Each worker numbers its own dictionary in first-seen order, so the SAME label is a different
    code in different parts. A concat that just stacked the columns would silently relabel rows —
    BULLISH counted as BEARISH — and every downstream number would still look plausible.
    """
    from research.charting.study.pattern_table import PatternTable, concat_tables

    def one(direction, pattern_type):
        t = PatternTable(layout, 1)
        t.add({"event_id": f"E-{direction}", "symbol": "S", "pattern_id": "P",
               "signal_date": "2024-08-01", "pattern_type": pattern_type, "direction": direction})
        return t

    a, b = one("BULLISH", "RECTANGLE"), one("BEARISH", "HH_HL")
    # the pre-condition that makes this test meaningful: the same column, opposite code order
    assert a.dicts["direction"].code("BULLISH") == b.dicts["direction"].code("BEARISH") == 0

    merged = concat_tables([a, b], layout)
    assert merged.labels("direction") == ["BULLISH", "BEARISH"]
    assert merged.labels("pattern_type") == ["RECTANGLE", "HH_HL"]
    assert merged.event_id == ["E-BULLISH", "E-BEARISH"]


def test_per_symbol_encode_write_load_concat_equals_the_row_path(real_rows, layout, tmp_path):
    """The end-to-end shape the run will actually use: each symbol encoded and written on its own,
    the parent holding only PATHS, then merged. This is what the row path could not do — it held
    every symbol's nested dicts at once and died at 53 GB.
    """
    from research.charting.study.pattern_table import (
        PatternTable, concat_tables, load_table, save_table, table_hit_rate_table,
        table_mfe_mae_stats, table_return_stats,
    )

    by_symbol: dict = {}
    for row in real_rows:
        by_symbol.setdefault(row.get("symbol"), []).append(row)
    assert len(by_symbol) > 1, "a single-symbol split would not exercise the merge"

    paths = [save_table(PatternTable.from_rows(rows, layout), tmp_path / f"{sym}.npz")
             for sym, rows in sorted(by_symbol.items(), key=lambda kv: str(kv[0]))]
    merged = concat_tables([load_table(p, layout) for p in paths], layout)
    assert len(merged) == len(real_rows)

    # Same rows, so the same statistics — the split must be invisible to the result.
    ordered = sorted(real_rows, key=lambda r: (str(r.get("symbol")), 0))
    compared = 0
    for h in layout.horizons:
        for s in layout.scenarios:
            expected = report.return_stats(ordered, h, scenario=s)
            assert table_return_stats(merged, h, scenario=s) == expected, f"h={h} s={s}"
            compared += expected["n"]
        assert table_mfe_mae_stats(merged, h) == report.mfe_mae_stats(ordered, h)
        for t in layout.targets:
            assert table_hit_rate_table(merged, t, h) == report.hit_rate_table(ordered, t, h)
    assert compared > 0, "the merged table priced nothing — vacuous"
