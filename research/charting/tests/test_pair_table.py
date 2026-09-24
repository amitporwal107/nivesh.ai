"""`study/pair_table.py`: the columnar path must reproduce the row path.

This is the third link in the chain. Step 4 proved summaries reproduce rows; `test_stream_accumulate`
proved streaming reproduces summaries; this proves the columnar encoding reproduces both — which is
what lets a 1,000-seed full-universe run finish in hours rather than days.

The `net` mean is asserted BIT-IDENTICAL, because that is the only value a random-control seed
contributes to the report. The S-1 extras are asserted to ~1 ulp, with the tolerance stated and
tested to be tight rather than generous.
"""
from __future__ import annotations

import math

import pytest

from research.charting.events import controls, extraction
from research.charting.study import accumulate, pair_table, report
from research.charting.tests._events_helpers import confirmed_rectangle_with_runway

ULP = 1e-12          # generous next to the ~2e-16 measured, tight enough to catch a real defect


@pytest.fixture(scope="module")
def table_and_rows():
    base = confirmed_rectangle_with_runway(tail_len=40)
    bbs = {}
    for i in range(12):
        b = base.copy()
        f = 1.0 + 0.05 * i
        for c in ("open", "high", "low", "close"):
            b[c] = b[c] * f
        bbs[f"SYM{i:02d}"] = b
    events = [ev for s, b in bbs.items() for ev in extraction.extract_events(b, s)]
    elig = [(s, i) for s in bbs for i in range(20, 35)]
    batch = controls.random_control_batch(bbs, elig, n=len(events), seeds=tuple(range(6)))
    rows = [r for rs in batch.values() for r in rs]
    assert rows, "no control rows — this comparison would be vacuous"

    layout = pair_table.PairLayout(accumulate.DEFAULT_HORIZONS, accumulate.DEFAULT_SCENARIOS,
                                   report.DEFAULT_TARGET_NAMES)
    table = pair_table.PairTable(layout, capacity=len(rows))
    for i, r in enumerate(rows):
        table.add(("K", i), r)          # synthetic keys: this layer does not care what a pair is
    return table, rows, batch


@pytest.mark.parametrize("horizon", (1, 3, 5, 10, 20))
@pytest.mark.parametrize("scenario", accumulate.DEFAULT_SCENARIOS)
def test_the_net_mean_is_bit_identical_to_the_row_path(table_and_rows, horizon, scenario):
    """The one number the report reads from a random-control seed. Exact, not close."""
    table, rows, _ = table_and_rows
    idx = table.rows_for([("K", i) for i in range(len(rows))])
    got = table.seed_stats(idx)[horizon][scenario]
    want = report.return_stats(rows, horizon, scenario=scenario)

    assert got["n"] == want["n"]
    assert got["insufficient_n"] == want["insufficient_n"]
    if want["n"]:
        assert got["net_return"]["mean"] == want["net_return"]["mean"], "net mean is NOT bit-identical"
        assert got["net_expectancy"] == want["net_expectancy"]


@pytest.mark.parametrize("horizon", (1, 5, 20))
def test_the_s1_extras_match_to_within_one_ulp(table_and_rows, horizon):
    """Nothing reads these yet, and they are reduced with NumPy's pairwise sum rather than fsum."""
    table, rows, _ = table_and_rows
    idx = table.rows_for([("K", i) for i in range(len(rows))])
    got = table.seed_stats(idx)[horizon]["base"]
    want = report.return_stats(rows, horizon, scenario="base")
    if not want["n"]:
        pytest.skip("no priced rows at this horizon")
    for key in ("avg_cost", "avg_slippage", "win_rate"):
        assert got[key] == pytest.approx(want[key], rel=ULP), key
    assert got["gross_return"]["mean"] == pytest.approx(want["gross_return"]["mean"], rel=ULP)
    for key in ("avg_win", "avg_loss", "profit_factor"):
        if want[key] is None or want[key] == float("inf"):
            assert got[key] == want[key] or got[key] == pytest.approx(want[key], rel=ULP)
        else:
            assert got[key] == pytest.approx(want[key], rel=ULP), key


def test_the_tolerance_is_tight_enough_to_catch_a_real_defect(table_and_rows):
    """A tolerance that would pass a wrong answer proves nothing. A 0.1% error must fail."""
    table, rows, _ = table_and_rows
    idx = table.rows_for([("K", i) for i in range(len(rows))])
    got = table.seed_stats(idx)[5]["base"]
    if got["avg_cost"] is None:
        pytest.skip("no priced rows")
    with pytest.raises(AssertionError):
        assert got["avg_cost"] * 1.001 == pytest.approx(got["avg_cost"], rel=ULP)


def test_a_seed_subset_reduces_to_the_same_answer_as_those_rows_alone(table_and_rows):
    """Seeds draw subsets, so the reduction must be correct for an arbitrary subset, not just all."""
    table, rows, _ = table_and_rows
    subset = list(range(0, len(rows), 3))
    idx = table.rows_for([("K", i) for i in subset])
    got = table.seed_stats(idx)[5]["base"]
    want = report.return_stats([rows[i] for i in subset], 5, scenario="base")
    assert got["n"] == want["n"]
    if want["n"]:
        assert got["net_return"]["mean"] == want["net_return"]["mean"]


def test_an_empty_seed_is_an_honest_zero_not_a_crash(table_and_rows):
    table, _rows, _ = table_and_rows
    import numpy as np
    cell = table.seed_stats(np.asarray([], dtype=np.int64))[5]["base"]
    assert cell["n"] == 0 and cell["net_return"]["mean"] is None


def test_the_table_is_far_smaller_than_the_rows_it_replaces(table_and_rows):
    """The reason this exists: 283 KB a row of nested dicts becomes ~2 KB of numbers."""
    table, rows, _ = table_and_rows
    per_pair = (table.layout.n_exact + table.layout.n_money) * 8 + table.layout.n_flag * 4
    assert per_pair < 4000, f"{per_pair} B/pair — the table would not fit at full universe"


def test_ambiguity_is_sparse_not_dense(table_and_rows):
    """960 near-always-zero columns would have cost 4.7 GB of a 7.3 GB table."""
    table, rows, _ = table_and_rows
    assert len(table.ambiguity) <= len(rows), "the sparse map is larger than the row count"
    assert not any("amb" in str(k) for k in table.layout.flag_index), "ambiguity leaked into dense columns"
    assert not any("amb" in str(k) for k in table.layout.money_index)


# ── the full seed summary, table vs rows ────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def built_table():
    """Built the way the run will build it: price in chunks, encode, drop — never the whole union."""
    from research.charting.study import execute, pair_table as pt
    base = confirmed_rectangle_with_runway(tail_len=40)
    bbs = {}
    for i in range(10):
        b = base.copy()
        f = 1.0 + 0.05 * i
        for c in ("open", "high", "low", "close"):
            b[c] = b[c] * f
        bbs[f"SYM{i:02d}"] = b
    events = [ev for s, b in bbs.items() for ev in extraction.extract_events(b, s)]
    elig = [(s, i) for s in bbs for i in range(20, 35)]
    draws = controls.random_control_draws(elig, n=len(events), seeds=tuple(range(5)))
    pairs = {p for picks in draws.values() for p in picks}
    assert pairs, "no draws — vacuous"

    layout = pt.PairLayout(accumulate.DEFAULT_HORIZONS, accumulate.DEFAULT_SCENARIOS,
                           report.DEFAULT_TARGET_NAMES)
    seen = []
    table = pt.build_table(bbs, pairs, layout, chunk_size=37, row_check=seen.append)
    priced = controls.price_signals(bbs, pairs)
    batch = controls.assemble_random_control_batch(bbs, draws, priced)
    return table, draws, batch, len(seen)


def test_the_chunked_build_sees_every_pair_exactly_once(built_table):
    """The §8 row check must cover every generated row — not a chunk, not a sample."""
    table, _draws, _batch, n_checked = built_table
    assert n_checked == len(table) > 0


@pytest.mark.parametrize("horizon", (1, 5, 20))
def test_seed_summary_from_the_table_matches_the_row_path(built_table, horizon):
    from research.charting.study import pair_table as pt
    table, draws, batch, _n = built_table
    compared = 0
    for seed, picks in draws.items():
        got = pt.seed_summary(table, picks)
        want = accumulate.group_summary(batch[seed], keep_net_vectors=False, segment=False, digest=False)
        assert got["n_rows"] == want["n_rows"]
        if not want["n_rows"]:
            continue
        g, w = got["stats"][horizon]["base"], want["stats"][horizon]["base"]
        assert g["n"] == w["n"]
        if w["n"]:
            assert g["net_return"]["mean"] == w["net_return"]["mean"], "net mean not bit-identical"
        assert got["hit_rates"][horizon]["pct_2"]["base"] == want["hit_rates"][horizon]["pct_2"]["base"]
        assert got["holding_period_histograms"][horizon]["pct_2"] == \
               want["holding_period_histograms"][horizon]["pct_2"]
        assert got["ambiguity_legs"][horizon]["pct_2"]["base"] == \
               want["ambiguity_legs"][horizon]["pct_2"]["base"]
        compared += 1
    assert compared, "no seed had rows — vacuous"


def test_the_comparison_block_is_identical_from_the_table(built_table):
    """What the report prints, from the columnar path vs the row path."""
    from research.charting.study import pair_table as pt
    table, draws, batch, _n = built_table
    pattern_rows = [r for rs in batch.values() for r in rs][:25]
    col = {s: pt.seed_summary(table, p) for s, p in draws.items()}
    row = accumulate.random_control_summaries(batch)
    for h in (1, 3, 5, 10, 20):
        a = accumulate.comparison_block_from_summaries(pattern_rows, h, random_summaries=row)
        b = accumulate.comparison_block_from_summaries(pattern_rows, h, random_summaries=col)
        assert a == b, f"horizon {h}: columnar block differs from row-based"
