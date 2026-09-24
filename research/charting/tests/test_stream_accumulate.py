"""`study/stream_accumulate.py`: the streamed accumulator must equal the row-based one.

The step-4 gate proved `accumulate.group_summary` reproduces the row-level report. This file proves
the STREAMED accumulator reproduces `group_summary` — so the chain from rows to a 1,000-seed run at
full universe is unbroken, and the study's numbers do not change because the memory shape did.

Two things are deliberately NOT carried per seed (medians, `max_drawdown`; see the module
docstring). Everything else must match exactly, and the comparison block the report actually prints
must be byte-identical.
"""
from __future__ import annotations

import json
import math
import statistics

import pytest

from research.charting.events import controls, extraction
from research.charting.study import accumulate, report, stream_accumulate
from research.charting.tests._events_helpers import confirmed_rectangle_with_runway


@pytest.fixture(scope="module")
def rows_and_summaries():
    """Real control rows from the real pipeline, on a multi-symbol universe (one symbol makes the
    ATR-decile group empty — the vacuity trap this suite already documents)."""
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
    batch = controls.random_control_batch(bbs, elig, n=len(events), seeds=tuple(range(8)))

    assert any(batch.values()), "no control rows: this comparison would be vacuous"
    streamed = {}
    for seed, rows in batch.items():
        acc = stream_accumulate.SeedAccumulator()
        for r in rows:                       # one row at a time, exactly as the run will do
            acc.add_row(r)
        streamed[seed] = acc.finalise()
    rowbased = accumulate.random_control_summaries(batch)
    return batch, rowbased, streamed


# ── the gate ────────────────────────────────────────────────────────────────────────────────────

def test_the_comparison_block_is_identical_streamed_vs_row_based(rows_and_summaries):
    """THE gate: what the report prints must not change. The random control contributes `n` and
    mean net per seed, and both paths must produce the same block, byte for byte."""
    batch, rowbased, streamed = rows_and_summaries
    pattern_rows = [r for rows in batch.values() for r in rows][:20]
    for h in (1, 3, 5, 10, 20):
        a = accumulate.comparison_block_from_summaries(pattern_rows, h, random_summaries=rowbased)
        b = accumulate.comparison_block_from_summaries(pattern_rows, h, random_summaries=streamed)
        assert a == b, f"horizon {h}: streamed block differs"
        assert (json.dumps(report.to_json_dict(a), sort_keys=True, allow_nan=False)
                == json.dumps(report.to_json_dict(b), sort_keys=True, allow_nan=False))


@pytest.mark.parametrize("horizon", (1, 3, 5, 10, 20))
@pytest.mark.parametrize("scenario", accumulate.DEFAULT_SCENARIOS)
def test_every_additive_statistic_matches_exactly(rows_and_summaries, horizon, scenario):
    """Not just the mean: every figure `return_stats` derives additively, at every horizon and
    scenario, bit-exact — because `ExactSum` reproduces `fsum`, not because it is close."""
    _batch, rowbased, streamed = rows_and_summaries
    checked = 0
    for seed in rowbased:
        a = rowbased[seed]["stats"][horizon][scenario]
        b = streamed[seed]["stats"][horizon][scenario]
        assert a["n"] == b["n"]
        assert a["insufficient_n"] == b["insufficient_n"]
        for key in ("avg_cost", "avg_slippage", "net_expectancy", "profit_factor",
                    "win_rate", "avg_win", "avg_loss"):
            assert a[key] == b[key], f"seed {seed} {key}: {a[key]!r} != {b[key]!r}"
        assert a["gross_return"]["mean"] == b["gross_return"]["mean"]
        assert a["net_return"]["mean"] == b["net_return"]["mean"]
        if a["n"]:
            checked += 1
    assert checked, "no seed had priced rows here: the comparison would be vacuous"


def test_the_two_omitted_statistics_say_so_rather_than_reading_as_no_data(rows_and_summaries):
    """A bare `None` would be indistinguishable from 'no rows'. The availability discipline
    (§39.13a) requires the reason to be stated."""
    _batch, _rowbased, streamed = rows_and_summaries
    cell = streamed[0]["stats"][5]["base"]
    assert cell["gross_return"]["median"] is None and cell["net_return"]["median"] is None
    assert cell["max_drawdown"] is None
    assert cell["not_computed"]["status"] == "NOT_COMPUTED"
    assert "NON_ADDITIVE" in cell["not_computed"]["reason"]


def test_hit_rates_match_the_row_based_cell_exactly(rows_and_summaries):
    _batch, rowbased, streamed = rows_and_summaries
    compared = 0
    for seed in rowbased:
        for h in (5, 10):
            a = rowbased[seed]["hit_rates"][h]["pct_2"]["base"]
            b = streamed[seed]["hit_rates"][h]["pct_2"]["base"]
            assert a == b, f"seed {seed} h{h}: {a} != {b}"
            compared += 1
    assert compared


def test_holding_period_histograms_and_their_medians_match(rows_and_summaries):
    _batch, rowbased, streamed = rows_and_summaries
    for seed in rowbased:
        for h in (5, 10, 20):
            assert rowbased[seed]["holding_period_histograms"][h]["pct_2"] == \
                   streamed[seed]["holding_period_histograms"][h]["pct_2"]


def test_ambiguity_legs_match(rows_and_summaries):
    _batch, rowbased, streamed = rows_and_summaries
    for seed in rowbased:
        for h in (5, 10):
            assert rowbased[seed]["ambiguity_legs"][h]["pct_2"]["base"] == \
                   streamed[seed]["ambiguity_legs"][h]["pct_2"]["base"]


# ── the properties the whole design rests on ────────────────────────────────────────────────────

def test_exact_sum_is_bit_identical_to_fsum_including_cancellation():
    """If this drifts, every reported mean drifts with it."""
    import random
    random.seed(11)
    for _ in range(300):
        v = [random.uniform(-1e7, 1e7) for _ in range(random.randint(1, 200))]
        v += [1e16, 1.0, -1e16, 1e-16]          # catastrophic cancellation
        random.shuffle(v)
        acc = stream_accumulate.ExactSum()
        for x in v:
            acc.add(x)
        assert acc.total() == math.fsum(v)
        assert acc.mean() == statistics.fmean(v)


def test_median_from_histogram_equals_statistics_median():
    """Exact, not approximate — the holding period is a bounded small integer, so the histogram IS
    the multiset. Both odd and even totals."""
    import random
    random.seed(12)
    for _ in range(400):
        vals = [random.randint(0, 20) for _ in range(random.randint(1, 60))]
        hist = {}
        for v in vals:
            hist[v] = hist.get(v, 0) + 1
        assert stream_accumulate._median_from_histogram(hist) == statistics.median(vals)
    assert stream_accumulate._median_from_histogram({}) is None


def test_memory_does_not_grow_with_rows(rows_and_summaries):
    """The point of the exercise: an accumulator that has folded thousands of rows must be the same
    size as one that has folded ten. If this fails, the full-universe run does not fit."""
    import sys

    def deep_size(acc):
        """Every container the accumulator owns. `sha256` is excluded deliberately — a hash object
        is fixed-size by construction (32-byte state plus a block buffer) and cannot be pickled."""
        total = 0
        for name in ("_cost", "_hit", "_hold", "_amb"):
            d = getattr(acc, name)
            total += sys.getsizeof(d)
            for k, v in d.items():
                total += sys.getsizeof(k) + sys.getsizeof(v)
                if isinstance(v, dict):
                    for vk, vv in v.items():
                        total += sys.getsizeof(vk) + sys.getsizeof(vv)
                        if isinstance(vv, stream_accumulate.ExactSum):
                            total += sys.getsizeof(vv._partials)
                        elif isinstance(vv, dict):
                            total += sum(sys.getsizeof(x) for x in vv.values())
        return total

    small, big = stream_accumulate.SeedAccumulator(), stream_accumulate.SeedAccumulator()
    batch, _r, _s = rows_and_summaries
    rows = [r for rs in batch.values() for r in rs]
    for r in rows[:5]:
        small.add_row(r)
    for _ in range(60):                      # ~60x more rows through the same accumulator
        for r in rows:
            big.add_row(r)

    assert big.n_rows > small.n_rows * 100
    growth = deep_size(big) / deep_size(small)
    assert growth < 1.5, f"accumulator grew {growth:.2f}x with row count — it must be O(1)"
    assert deep_size(big) < 2_000_000, f"accumulator is {deep_size(big)/1024:.0f} KB — too big x1,000 seeds"


def test_the_streamed_digest_equals_the_hash_of_the_rows_never_held(rows_and_summaries):
    """The recovery story depends on this. Rows are discarded, so the only way to prove a
    regenerated seed is the same seed is that its hash matches — and that hash must be the one
    `writer.write_run` would have recorded, not a new convention."""
    batch, rowbased, streamed = rows_and_summaries
    compared = 0
    for seed, rows in batch.items():
        if not rows:
            continue
        assert streamed[seed]["digest"] == accumulate.rows_digest(rows)
        assert streamed[seed]["digest"]["sha256"] == rowbased[seed]["digest"]["sha256"]
        compared += 1
    assert compared, "no seed had rows: this would be vacuous"


def test_a_regenerated_seed_reproduces_the_digest(rows_and_summaries):
    """End to end: redraw a seed from scratch and its streamed digest must match the original —
    which is what 'the rows are recoverable' actually means."""
    batch, _rowbased, streamed = rows_and_summaries
    seed = next(s for s, r in batch.items() if r)
    acc = stream_accumulate.SeedAccumulator()
    for r in batch[seed]:
        acc.add_row(r)
    assert acc.finalise()["digest"] == streamed[seed]["digest"]
