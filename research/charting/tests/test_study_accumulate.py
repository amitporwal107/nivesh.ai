"""Step 4 of the study-v2 storage redesign: PROVE the accumulator reproduces the row-level result.

`docs/ai_research/CHARTING_STUDY_V2_STORAGE_REDESIGN.md` argues that the persisted control artefacts
are write-only, so what is persisted can change without any reported number changing. That is an
argument. This file is the proof, and nothing downstream may switch row persistence off until it
passes.

**The invariant under test** (owner, 2026-09-23) — same seeds, same input rows, same config, same
outcome calculation, down two paths:

    rows  ──> report.comparison_block(...)                     (the existing implementation)
    rows  ──> accumulate.group_summary(...) ──> accumulate.comparison_block_from_summaries(...)

must produce the same comparison block. The test compares the FINAL COMPARISON BLOCK, not a few
intermediate counters.

**Floating-point tolerance: none. The assertion is exact equality**, and that is a design property,
not luck. A seed's summary holds `report.return_stats`' own output, computed in memory while that
seed's rows exist — not a running sum that would have to be re-averaged. `statistics.fmean` is
exactly rounded, so re-deriving a mean from stored sums would differ in the last bits; storing the
statistic avoids the question entirely. If a future change makes exactness unattainable, the
tolerance has to be argued for here in writing, not slipped in as an `approx`.
"""
from __future__ import annotations

import json

import pytest

from research.charting.events import controls, extraction, writer
from research.charting.study import accumulate, report
from research.charting.tests._events_helpers import confirmed_rectangle_with_runway

HORIZONS = (1, 3, 5, 10, 20)


N_SYMBOLS = 12


@pytest.fixture(scope="module")
def pipeline():
    """The real controls pipeline over a MULTI-SYMBOL universe — the TC-113 shape in miniature.

    Multi-symbol is not decoration. The ATR-decile control matches within a signal date, so with one
    symbol every event's candidate pool is itself, every event is skipped, and the group comes back
    EMPTY — which is how the first version of this file passed its ATR-decile assertions vacuously.
    The universe is built the way `test_events_atr_decile_control._multi_symbol_same_date_universe`
    builds its own: copies of one fixture scaled by a constant, so every copy shares the calendar
    while ATR%(t) differs (ATR scales linearly with price), spreading the copies across deciles.

    The guards at the end are the point. A step-4 equivalence gate that compares two empty results
    proves nothing, so this fixture refuses to hand one over.
    """
    base = confirmed_rectangle_with_runway(tail_len=40)
    bars_by_symbol = {}
    for i in range(N_SYMBOLS):
        scaled = base.copy()
        factor = 1.0 + 0.05 * i
        for c in ("open", "high", "low", "close"):
            scaled[c] = scaled[c] * factor
        bars_by_symbol[f"SYM{i:02d}"] = scaled

    events = [ev for sym, b in bars_by_symbol.items() for ev in extraction.extract_events(b, sym)]
    eligible = [(sym, i) for sym in bars_by_symbol for i in range(20, 35)]

    out = {
        "bars_by_symbol": bars_by_symbol,
        "pattern_rows": events,
        "random_batch": controls.random_control_batch(bars_by_symbol, eligible, n=len(events), seeds=tuple(range(10))),
        "atr_decile_rows": controls.atr_decile_control_rows(bars_by_symbol, events, eligible, seed=0),
        "buy_next_open_rows": controls.buy_next_open_baseline_rows(bars_by_symbol, events),
    }

    # Non-vacuity guards — an empty group would make the gate below meaningless.
    assert out["pattern_rows"], "no pattern events: the equivalence gate would compare nothing"
    assert out["atr_decile_rows"], "ATR-decile control is empty: needs >=2 same-date candidates"
    assert out["buy_next_open_rows"], "buy-next-open baseline is empty"
    assert any(rows for rows in out["random_batch"].values()), "every random seed drew nothing"
    # and the gate must see rows that are actually PRICED at the horizon it asserts on
    assert accumulate.row_net_vector(out["atr_decile_rows"], 5, "base"), "no priced ATR-decile rows at h=5"
    return out


@pytest.fixture(scope="module")
def summaries(pipeline):
    return {
        "random": accumulate.random_control_summaries(pipeline["random_batch"]),
        "atr": accumulate.group_summary(pipeline["atr_decile_rows"]),
        "bno": accumulate.group_summary(pipeline["buy_next_open_rows"]),
    }


def _row_based(pipeline, horizon, scenario="base"):
    return report.comparison_block(
        pipeline["pattern_rows"], horizon,
        random_batch=pipeline["random_batch"],
        atr_decile_rows=pipeline["atr_decile_rows"],
        buy_next_open_rows=pipeline["buy_next_open_rows"],
        nifty_500_return=0.005,
        scenario=scenario,
    )


def _summary_based(pipeline, summaries, horizon, scenario="base"):
    return accumulate.comparison_block_from_summaries(
        pipeline["pattern_rows"], horizon,
        random_summaries=summaries["random"],
        atr_decile_summary=summaries["atr"],
        buy_next_open_summary=summaries["bno"],
        nifty_500_return=0.005,
        scenario=scenario,
    )


# ── the gate ────────────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("horizon", HORIZONS)
@pytest.mark.parametrize("scenario", accumulate.DEFAULT_SCENARIOS)
def test_the_comparison_block_is_identical_from_rows_and_from_summaries(pipeline, summaries, horizon, scenario):
    """THE step-4 gate. Every horizon x every cost scenario, exact equality."""
    assert _summary_based(pipeline, summaries, horizon, scenario) == _row_based(pipeline, horizon, scenario)


@pytest.mark.parametrize("horizon", HORIZONS)
def test_the_serialised_block_is_byte_identical(pipeline, summaries, horizon):
    """Dict equality treats 1 and 1.0 as equal; the study writes JSON, so compare the bytes too."""
    def blob(block):
        return json.dumps(report.to_json_dict(block), sort_keys=True, allow_nan=False).encode()
    assert blob(_summary_based(pipeline, summaries, horizon)) == blob(_row_based(pipeline, horizon))


def test_the_gate_can_actually_fail_negative_control(pipeline, summaries):
    """Mandatory negative control: a comparison that cannot detect a difference proves nothing.

    Perturb ONE seed's stored mean by one ulp-ish amount and the gate must catch it."""
    import copy
    poisoned = copy.deepcopy(summaries)
    first_seed = sorted(poisoned["random"])[0]
    cell = poisoned["random"][first_seed]["stats"][5]["base"]["net_return"]
    if cell["mean"] is None:
        pytest.skip("this fixture's first seed drew no priced rows at horizon 5")
    cell["mean"] = cell["mean"] + 1e-12

    assert _summary_based(pipeline, poisoned, 5) != _row_based(pipeline, 5)


# ── the properties the redesign depends on ──────────────────────────────────────────────────────

def test_a_seed_that_drew_nothing_is_still_counted(pipeline, summaries):
    """`n_seeds_total` is `len(random_batch)` (report.py:356). If empty seeds were dropped from the
    summaries, the denominator would silently shrink and every seed percentile would move."""
    assert len(summaries["random"]) == len(pipeline["random_batch"])
    block = _summary_based(pipeline, summaries, 5)
    assert block["random_200_seed"]["n_seeds_total"] == len(pipeline["random_batch"])


def test_the_random_summary_holds_two_numbers_per_seed_that_the_report_reads(summaries):
    """The whole 6.4 TB collapse rests on this: the report reads `n` and mean net, nothing else."""
    st = next(iter(summaries["random"].values()))["stats"][5]["base"]
    assert st["n"] is not None and "mean" in st["net_return"]
    # and the per-row scalars are NOT retained for the random control -- its distribution is per-seed
    assert "net_vectors" not in next(iter(summaries["random"].values()))


def test_the_atr_decile_percentile_still_needs_and_has_its_per_row_vector(pipeline, summaries):
    """The ATR-decile distribution is per-ROW by frozen design, so the vector is retained in full."""
    kept = summaries["atr"]["net_vectors"][5]["base"]
    assert kept == accumulate.row_net_vector(pipeline["atr_decile_rows"], 5, "base")


def test_the_digest_is_the_hash_write_run_would_have_recorded(pipeline):
    """Reproducibility without the rows: the digest must equal the sha256 of the bytes the writer
    would have produced, or an auditor cannot check a regenerated seed against it."""
    rows = pipeline["atr_decile_rows"]
    import hashlib
    assert accumulate.rows_digest(rows)["sha256"] == hashlib.sha256(writer._dump_jsonl(rows)).hexdigest()
    assert accumulate.rows_digest(rows)["row_count"] == len(rows)


def test_every_row_passes_the_row_check_so_a_sealed_gate_can_move_inside(pipeline):
    """`assert_no_sealed_rows_in_dataset` is the only §8 probe that touches control rows. When rows
    are summarised and discarded, it must run per row at generation time — so `group_summary` has to
    offer every single row to the check, not a sample and not only the priced ones."""
    seen: list = []
    accumulate.group_summary(pipeline["atr_decile_rows"], row_check=seen.append)
    assert len(seen) == len(pipeline["atr_decile_rows"])

    def reject(row):
        raise ValueError("sealed row")
    with pytest.raises(ValueError, match="sealed row"):
        accumulate.group_summary(pipeline["atr_decile_rows"][:1], row_check=reject)


def test_the_real_sealed_window_gate_runs_clean_through_the_hook(pipeline):
    """Not a stand-in: the actual §8 function, wired as the per-row check."""
    from research.charting.study import integrity
    accumulate.group_summary(
        pipeline["buy_next_open_rows"],
        row_check=lambda row: integrity.assert_no_sealed_rows_in_dataset([row]),
    )


# ── owner decisions S-1, S-2, S-3 ───────────────────────────────────────────────────────────────

def test_s1_all_four_cost_scenarios_are_accumulated_not_just_base(summaries):
    """Item 9 needs cost sensitivity for every headline net number, and width cannot be added once
    the rows are gone."""
    assert set(summaries["atr"]["stats"][5]) == set(accumulate.DEFAULT_SCENARIOS)
    assert set(summaries["atr"]["hit_rates"][5]["pct_2"]) == set(accumulate.DEFAULT_SCENARIOS)


@pytest.mark.parametrize("horizon", HORIZONS)
def test_s1_hit_rates_are_kept_for_the_comparison_groups(pipeline, summaries, horizon):
    """Item 2 extended to the comparison groups: the stored cell must equal the row-level one."""
    assert summaries["atr"]["hit_rates"][horizon]["pct_2"]["base"] == report.hit_rate_table(
        pipeline["atr_decile_rows"], "pct_2", horizon
    )


def test_s1_the_holding_period_histogram_reproduces_the_median_exactly(summaries):
    """Item 4. Asserted at h=10, where this fixture's controls actually RESOLVE — at h=5 nothing
    exits, so the histogram is empty and `None == None` would prove nothing about the statistic.

    The histogram is the exact sufficient statistic, so its median must equal the row-level median
    rather than approximate it: holding period is a bounded small integer, so nothing is lost.
    """
    import statistics
    got = summaries["atr"]["hit_rates"][10]["pct_2"]["base"]
    hist = summaries["atr"]["holding_period_histograms"][10]["pct_2"]

    assert sum(hist.values()) > 0, "no resolved exits at h=10: this assertion would be vacuous"
    assert got["median_holding_period"] is not None
    expanded = [k for k, count in sorted(hist.items()) for _ in range(count)]
    assert got["median_holding_period"] == statistics.median(expanded)
    assert sum(hist.values()) == got["counts"]["target_first"] + got["counts"]["stop_first"]


def test_s2_control_context_segmentation_is_unavailable_not_an_empty_looking_table(summaries):
    """The availability discipline: a control row has no context block, so trend/regime segmentation
    must SAY it is unavailable. `report.segment_rows` would bucket every row into "NO_CONTEXT" and
    produce a table that looks complete -- exactly the silent omission §39.13a forbids."""
    seg = summaries["atr"]["segmentation"][5]
    for dim in accumulate.CONTEXT_DIMENSIONS:
        assert seg[dim] == {"status": "UNAVAILABLE", "reason": "CONTROL_CONTEXT_NOT_GENERATED"}
        assert "NO_CONTEXT" not in seg[dim]
    # the two dimensions a control row CAN answer are reported normally
    for dim in ("liquidity_bucket", "atr_bucket"):
        assert isinstance(seg[dim], dict) and "status" not in seg[dim]


def test_s2_the_random_controls_omitted_segmentation_is_stated_not_silent(summaries):
    """Segmentation is off by default for the per-seed random summaries. That choice is recorded in
    the summary, so a reader sees a reason rather than a missing key."""
    one = next(iter(summaries["random"].values()))
    assert one["segmentation"] == {
        "status": "NOT_COMPUTED",
        "reason": "RANDOM_CONTROL_ENTERS_REPORT_AS_PER_SEED_MEANS",
    }


def _ambiguous_row(event_id: str):
    """A row whose pct_2 block is the REAL output of `stops.target_outcome_by_horizon` on the bar
    sequence `test_events_stops.test_walk_ambiguous_same_bar_both_touched...` pins: one bar whose
    high reaches the target AND whose low reaches the stop, with no gap — so the walk cannot know
    which came first. Not a hand-built stub: the legs and their costs are really computed."""
    from research.charting.events import stops
    from research.charting.tests._events_helpers import raw_bars
    bars = raw_bars([
        (100.0, 104.0, 98.0, 102.0, 1e5),   # offset 0, entry
        (102.0, 112.0, 93.0, 105.0, 1e5),   # offset 1, high >= target AND low <= stop, no gap
        (105.0, 106.0, 104.0, 105.0, 1e5),
    ], start_date="2021-03-01")
    by_horizon = stops.target_outcome_by_horizon(
        bars, 0, 100.0, target_price=110.0, stop_price=95.0, qty=10, adv_inr=1e9,
    )
    return {"event_id": event_id, "signal_date": "2021-03-01",
            "targets": {"pct_2": {"by_horizon": by_horizon}}}


def test_s3_the_ambiguity_legs_survive_the_rows():
    """The one accepted data loss in the scope, which the owner chose to keep.

    Run against rows that really are AMBIGUOUS — the pipeline fixture happens to produce none, and a
    `0 == 0` assertion would prove nothing about whether the legs are preserved.
    """
    rows = [_ambiguous_row(f"AMB{i}") for i in range(3)]
    legs = accumulate.ambiguity_leg_terms(rows, "pct_2", 5, "base")
    rowwise = report.hit_rate_table(rows, "pct_2", 5)

    assert rowwise["counts"]["ambiguous"] == 3          # the fixture really is ambiguous
    assert legs["n_ambiguous"] == 3
    assert legs["as_if_target"]["n"] == 3 and legs["as_if_stop"]["n"] == 3
    # the target leg is the profitable reading, the stop leg the losing one -- both preserved
    assert legs["as_if_target"]["n_positive"] == 3 and legs["as_if_stop"]["n_positive"] == 0
    assert legs["as_if_target"]["sum_net"] > 0 > legs["as_if_stop"]["sum_net"]

    # and the sums are the legs' own net figures, not a re-derivation
    leg_block = rows[0]["targets"]["pct_2"]["by_horizon"][5]
    one_target = leg_block["as_if_target"]["costs"]["scenarios"]["base"]["net_before_tax"]
    assert legs["as_if_target"]["sum_net"] == pytest.approx(3 * one_target)


def test_s3_the_legs_are_carried_through_the_group_summary():
    """Not just the helper: the summary that replaces the rows must hold them."""
    summary = accumulate.group_summary([_ambiguous_row("AMB0")], horizons=(5,), scenarios=("base",))
    legs = summary["ambiguity_legs"][5]["pct_2"]["base"]
    assert legs["n_ambiguous"] == 1
    for leg in ("as_if_target", "as_if_stop"):
        assert set(legs[leg]) == {"n", "sum_net", "n_positive"}
        assert legs[leg]["n"] == 1


def test_s3_pipeline_rows_report_zero_legs_honestly(pipeline, summaries):
    """The pipeline fixture produces no ambiguous outcomes. That must show up as a real zero that
    agrees with the row-level count, not as a missing key."""
    legs = summaries["atr"]["ambiguity_legs"][5]["pct_2"]["base"]
    rowwise = report.hit_rate_table(pipeline["atr_decile_rows"], "pct_2", 5)
    assert legs["n_ambiguous"] == rowwise["counts"]["ambiguous"] == 0


def test_the_summary_is_json_serialisable(summaries):
    """It has to be writable as the artefact that replaces events.jsonl."""
    for name, summary in (("atr", summaries["atr"]), ("bno", summaries["bno"])):
        json.dumps(report.to_json_dict(summary), sort_keys=True, allow_nan=False), name


# ── step 5: the streaming path ──────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def draws_and_priced(pipeline):
    """The draw/price split `execute.build_family_comparison_groups` uses, so the streaming test
    runs on the same inputs the real study would hand it."""
    from research.charting.events import controls as c
    from research.charting.study import execute
    eligible = execute.eligible_population(pipeline["bars_by_symbol"])
    draws = c.random_control_draws(eligible, n=len(pipeline["pattern_rows"]), seeds=tuple(range(10)))
    pairs = {p for picks in draws.values() for p in picks}
    priced = c.price_signals(pipeline["bars_by_symbol"], pairs)
    return draws, priced


def test_streaming_summaries_equal_the_batch_summaries(pipeline, draws_and_priced):
    """Step 5's own gate: summarising seed-by-seed must give exactly what summarising the
    materialised batch gives. Exact equality, same reasoning as the step-4 gate."""
    from research.charting.events import controls as c
    draws, priced = draws_and_priced
    batch = c.assemble_random_control_batch(pipeline["bars_by_symbol"], draws, priced)

    assert accumulate.stream_random_control_summaries(
        pipeline["bars_by_symbol"], draws, priced
    ) == accumulate.random_control_summaries(batch)


def test_streaming_never_materialises_more_than_one_seed(pipeline, draws_and_priced, monkeypatch):
    """The whole point of the streaming path. If it ever assembled the full batch it would defeat
    itself silently — peak memory would be unchanged and only a profiler would notice — so this
    watches the draws dict every assemble call receives."""
    from research.charting.events import controls as c
    draws, priced = draws_and_priced
    seen_sizes: list = []
    real = c.assemble_random_control_batch

    def spy(bars_by_symbol, d, p, **kw):
        seen_sizes.append(len(d))
        return real(bars_by_symbol, d, p, **kw)

    monkeypatch.setattr(c, "assemble_random_control_batch", spy)
    accumulate.stream_random_control_summaries(pipeline["bars_by_symbol"], draws, priced)

    assert seen_sizes, "the streaming path never assembled anything"
    assert set(seen_sizes) == {1}, f"a call assembled more than one seed: {sorted(set(seen_sizes))}"
    assert len(seen_sizes) == len(draws)


def test_streaming_runs_the_real_sealed_gate_on_every_control_row(pipeline, draws_and_priced):
    """§8 coverage must not shrink when the rows stop being kept. The real gate, per row, and a
    count proving every generated row went through it."""
    from research.charting.study import integrity
    draws, priced = draws_and_priced
    checked: list = []

    def gate(row):
        integrity.assert_no_sealed_rows_in_dataset([row])
        checked.append(row["event_id"])

    summaries = accumulate.stream_random_control_summaries(
        pipeline["bars_by_symbol"], draws, priced, row_check=gate
    )
    assert len(checked) == sum(len(picks) for picks in draws.values())
    assert len(checked) > 0
    assert sum(s["n_rows"] for s in summaries.values()) == len(checked)


# ── step 5: the flag, end to end through execute_study ──────────────────────────────────────────

@pytest.fixture(scope="module")
def two_runs(tmp_path_factory):
    """`execute_study` run twice over identical inputs — once keeping control rows, once
    summarising them. This is the step-5 gate: the flag must not change the study's own output."""
    from research.charting.study import execute
    # Reuse `test_study_execute`'s own end-to-end universe rather than inventing one. A fixture built
    # here first came back with ZERO families in both segments -- the synth frames are anchored at
    # 2024-01-02, inside the sealed block -- and this gate would then have compared two empty reports
    # and passed. That harness is already known to produce three families in both segments.
    from research.charting.tests.test_study_execute import (
        _mixed_segment_universe, _write_etf_list, _write_kite_dir,
    )

    setup = tmp_path_factory.mktemp("study_inputs")
    kwargs = {
        "kite_dir": _write_kite_dir(setup),
        "etf_list_path": _write_etf_list(setup),
        "bars_by_symbol": _mixed_segment_universe(),
        "random_control_seeds": (0, 1, 2, 3, 4),
        "kill_switch": False,          # orchestration gate, not a power study
        "recompute_sample_size": 5,
    }

    out = {}
    for mode, flag in (("rows", False), ("summaries", True)):
        d = tmp_path_factory.mktemp(f"study_{mode}")
        out[mode] = execute.execute_study(d, summarise_controls=flag, **kwargs)
        out[mode + "_dir"] = d

    # Non-vacuity guard: without comparison groups there is nothing for this gate to compare.
    built = {seg: sorted(g) for seg, g in out["summaries"]["comparison_groups"].items()}
    assert any(built.values()), f"no comparison groups were built, the step-5 gate would be vacuous: {built}"
    return out


def test_step5_the_report_is_identical_with_and_without_summarised_controls(two_runs):
    """THE step-5 gate: the same study, run both ways, must produce the same report.json bytes."""
    compared = 0
    for segment in ("pre_sealed", "post_sealed"):
        a = (two_runs["rows_dir"] / segment / "report.json")
        b = (two_runs["summaries_dir"] / segment / "report.json")
        if not a.is_file() and not b.is_file():
            continue
        assert a.is_file() and b.is_file(), f"{segment}: one path wrote a report and the other did not"
        assert a.read_bytes() == b.read_bytes(), f"{segment}: report.json differs between the two paths"
        assert b"comparisons" in a.read_bytes(), f"{segment}: the report carries no comparison block"
        compared += 1
    assert compared, "neither segment produced a report: this gate compared nothing"


def test_step5_the_sealed_gate_checked_the_same_number_of_rows_both_ways(two_runs):
    """§8 coverage must not shrink. The summarised run checks its control rows at generation, so
    its `n_rows_checked` must still account for every one of them."""
    for segment in ("pre_sealed", "post_sealed"):
        rows_chk = two_runs["rows"]["integrity"][segment]["sealed_window_check"]
        summ_chk = two_runs["summaries"]["integrity"][segment]["sealed_window_check"]
        assert rows_chk["n_rows_checked"] == summ_chk["n_rows_checked"]
        assert summ_chk["control_rows_checked_at_generation"] > 0
        assert rows_chk["passed"] and summ_chk["passed"]


def test_step5_the_manifest_says_which_output_shape_was_used(two_runs):
    assert two_runs["rows"]["study_manifest"]["control_output"]["mode"] == "rows"
    assert two_runs["summaries"]["study_manifest"]["control_output"]["mode"] == "summaries"


def test_step5_the_summarised_run_writes_no_control_rows_at_all(two_runs):
    """The point of the exercise: no `events.jsonl` under any comparison group, and summaries there
    instead. The segment's own PATTERN events.jsonl stays — only the controls change shape."""
    summ_dir = two_runs["summaries_dir"]
    control_row_files = list(summ_dir.glob("*/comparisons/*/**/events.jsonl"))
    assert control_row_files == [], f"summarised run still wrote control rows: {control_row_files}"
    assert list(summ_dir.glob("*/comparisons/*/random_control/summaries.jsonl")), "no seed summaries written"
    assert list(summ_dir.glob("*/comparisons/*/*/summary.json")), "no group summaries written"

    rows_dir = two_runs["rows_dir"]
    assert list(rows_dir.glob("*/comparisons/*/*/events.jsonl")), "the row path should still write rows"
