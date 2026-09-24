"""Per-seed sufficient statistics for the comparison groups — the study-v2 storage redesign.

`docs/ai_research/CHARTING_STUDY_V2_STORAGE_REDESIGN.md` is the scope; this module is its step 4,
the part that has to be proved before anything stops being written.

**Why this exists.** TC-113 measured the pre-registered run at ≈6.4 TB of random-control rows at 200
seeds against ~9 GB of free disk, and V-3 raises the seed count to 1,000. V-3 is an approved study
parameter and is not reduced; the run's OUTPUT SHAPE changes instead.

**Why it is safe.** The persisted control artefacts are write-only: nothing reads `events.jsonl`
back, and `study/execute.py` builds the report from the in-memory comparison groups. So what is
persisted can change without any reported number changing — and `tests/test_study_accumulate.py`
proves exactly that, by asserting `comparison_block_from_summaries` is byte-identical to
`report.comparison_block` on the real controls pipeline.

**Why the summaries hold statistics rather than sums.** `report.return_stats` means with
`statistics.fmean`, which is exactly rounded; a naive running sum would not reproduce it bit for bit,
and a redesign that changes reported figures in the 15th decimal place is not a storage change. So a
seed's summary IS `return_stats`' own output, computed in memory while that seed's rows exist and
kept after they are dropped. The raw sums and counters travel alongside as reversibility insurance
(§5 of the scope) — see `_pooling_terms`, which documents what they can and cannot reconstruct.

**What is deliberately kept per row.** The ATR-decile control's percentile is a PER-ROW distribution
by frozen design (`report.comparison_block`'s own docstring: it is matched 1:1, "not resampled"), so
its net-return scalar vector is retained in full — 8 bytes a row, not 143 KB. Keeping the whole
vector rather than one quantile leaves every reading of V-2 open.
"""
from __future__ import annotations

import hashlib
import math
from typing import Callable, Iterable, Mapping, Optional, Sequence

from research.charting.events import writer
from research.charting.study import report

SUMMARY_VERSION = "1.0.0"

#: The horizons and scenarios a summary covers by default. Four scenarios, not just `base`: v1 §7
#: item 9 requires cost sensitivity for every headline net number, and the accumulator's width is the
#: one thing that cannot be widened after the rows are gone (scope §4).
DEFAULT_HORIZONS: tuple = tuple(report.HORIZONS)
DEFAULT_SCENARIOS: tuple = tuple(report.DEFAULT_COST_SCENARIOS)


# ── the per-row scalars that survive ────────────────────────────────────────────────────────────

def row_net_vector(rows: Sequence[Mapping], horizon: int, scenario: str = "base") -> list:
    """The `net_before_tax` scalars `report.comparison_block` builds its ATR-decile percentile from,
    in the same order it builds them (input order, skipping rows with no available block at that
    horizon) — `report.py:365-369`. Retaining this vector is what keeps the percentile computable
    once the rows themselves are gone."""
    out = []
    for row in rows:
        scen = report._horizon_cost_scenario(row, horizon, scenario) or {}
        value = scen.get("net_before_tax")
        if value is not None:
            out.append(value)
    return out


def _pooling_terms(rows: Sequence[Mapping], horizon: int, scenario: str) -> dict:
    """Raw sums and counters, kept as reversibility insurance (scope §5), NOT as the reproduction
    path.

    They can reconstruct a POOLED mean/win-rate/profit-factor across seeds, which nothing computes
    today. They cannot reconstruct a pooled median or drawdown, and a pooled mean built from them is
    equal to a direct `fmean` only to within float rounding, because `fmean` is exactly rounded and a
    sum of exactly-rounded sums is not. Every figure the report actually prints comes from `stats`
    below, never from these.
    """
    gross, net, cost, slip = [], [], [], []
    for row in rows:
        scen = report._horizon_cost_scenario(row, horizon, scenario)
        if scen is None:
            continue
        gross.append(scen["gross"])
        net.append(scen["net_before_tax"])
        cost.append(scen["total_cost"])
        slip.append((scen.get("entry_slippage") or 0.0) + (scen.get("exit_slippage") or 0.0))
    wins = [v for v in net if v > 0]
    losses = [v for v in net if v < 0]
    return {
        "n": len(net),
        "sum_gross": math.fsum(gross), "sum_net": math.fsum(net),
        "sum_cost": math.fsum(cost), "sum_slippage": math.fsum(slip),
        "n_wins": len(wins), "sum_wins": math.fsum(wins),
        "n_losses": len(losses), "sum_losses": math.fsum(losses),
    }


def holding_period_histogram(rows: Sequence[Mapping], target_name: str, horizon: int) -> dict:
    """`{holding_period_sessions: count}` — an EXACT sufficient statistic for the median holding
    period (`report.hit_rate_table`'s `median_holding_period`), because the holding period is a
    bounded small integer. A stored median would not be poolable; this is."""
    hist: dict = {}
    for row in rows:
        block = report._target_horizon_block(row, target_name, horizon)
        if block is None:
            continue
        exit_ = block.get("exit")
        if exit_ is not None:
            key = exit_["holding_period_sessions"]
            hist[key] = hist.get(key, 0) + 1
    return hist


def ambiguity_leg_terms(rows: Sequence[Mapping], target_name: str, horizon: int, scenario: str) -> dict:
    """The `as_if_target` / `as_if_stop` legs of AMBIGUOUS outcomes (owner decision S-3, 2026-09-23).

    S-3 says "keep two counters". A bare count would record that ambiguity happened but not what it
    was worth, which is the information the decision is protecting — so each leg keeps a small
    accumulator instead: `n`, `sum_net` and `n_positive`. Six numbers per (target, horizon,
    scenario), and enough to price ambiguity either way later. Nothing reads these today; they exist
    because the rows they live in are about to stop being written.
    """
    out = {
        "n_ambiguous": 0,
        "as_if_target": {"n": 0, "sum_net": 0.0, "n_positive": 0},
        "as_if_stop": {"n": 0, "sum_net": 0.0, "n_positive": 0},
    }
    target_nets: list = []
    stop_nets: list = []
    for row in rows:
        block = report._target_horizon_block(row, target_name, horizon)
        if block is None or block.get("first_exit_event") != "AMBIGUOUS":
            continue
        out["n_ambiguous"] += 1
        for leg_name, bucket in (("as_if_target", target_nets), ("as_if_stop", stop_nets)):
            leg = block.get(leg_name)
            if leg is None:
                continue
            scen = ((leg.get("costs") or {}).get("scenarios") or {}).get(scenario)
            value = (scen or {}).get("net_before_tax")
            if value is None:
                continue
            bucket.append(value)
            out[leg_name]["n"] += 1
            if value > 0:
                out[leg_name]["n_positive"] += 1
    out["as_if_target"]["sum_net"] = math.fsum(target_nets)
    out["as_if_stop"]["sum_net"] = math.fsum(stop_nets)
    return out


# ── segmentation of the comparison groups (owner decisions S-1 and S-2) ─────────────────────────

#: The three §7.7 dimensions a control row cannot answer. `attach_context` runs inside
#: `study/run.py: build_segment` on PATTERN rows only, and the controls are built afterwards
#: (`execute.py:536-540`), so a control row has no `context` block at all.
CONTEXT_DIMENSIONS: tuple = ("stock_trend_class", "market_trend_class", "regime")
CONTROL_CONTEXT_UNAVAILABLE: dict = {
    "status": "UNAVAILABLE",
    "reason": "CONTROL_CONTEXT_NOT_GENERATED",
}


def control_segmentation(rows: Sequence[Mapping], horizon: int, *, target_name: Optional[str] = None) -> dict:
    """§7.7 segmentation for a comparison group (owner decision S-1: the §7 measures apply to every
    comparison group).

    Two of the five dimensions are computable from a control row — `liquidity_bucket` reads
    `liquidity.adv_inr_at_t` and `atr_bucket` reads `atr_at_t` — and those are reported normally.

    The other three are **not**, and this is where the availability discipline applies (owner
    decision S-2). `report.segment_rows` would happily bucket every control row into `"NO_CONTEXT"`
    and produce a table that LOOKS complete, which is exactly the silent omission §39.13a forbids.
    So those three dimensions report `{"status": "UNAVAILABLE", "reason":
    "CONTROL_CONTEXT_NOT_GENERATED"}` instead of a table. Unavailable is stated, never implied, and
    never an invisible pass — the same rule the detectors already follow.
    """
    out: dict = {}
    for dim in report.SEGMENTATION_DIMENSIONS:
        if dim in CONTEXT_DIMENSIONS:
            out[dim] = dict(CONTROL_CONTEXT_UNAVAILABLE)
            continue
        dim_out: dict = {}
        for label, bucket_rows in report.segment_rows(rows, dimension=dim).items():
            cell = {"returns": report.return_stats(bucket_rows, horizon)}
            if target_name is not None:
                cell["hit_rate"] = report.hit_rate_table(bucket_rows, target_name, horizon)
            dim_out[label] = cell
        out[dim] = dim_out
    return out


# ── digests: reproducibility without the rows ───────────────────────────────────────────────────

def rows_digest(rows: Sequence[Mapping]) -> dict:
    """`{"sha256": …, "row_count": n}` over the bytes `writer.write_run` WOULD have written.

    This is the §8 kill-switch property ("would writing produce identical bytes",
    `integrity.py:41-46`) preserved at ~64 bytes per seed instead of ~15 MB per symbol per seed. The
    bytes are produced and hashed, never stored. Because every draw is exactly regenerable — 
    `controls._random_control_picks` is `sorted(set(eligible))` → `random.Random(seed)` → `sample` →
    `sorted`, and the ATR-decile draw uses a SHA-256-derived per-event RNG — an auditor can rebuild
    any seed on demand and check this hash.
    """
    content = writer._dump_jsonl(list(rows))
    return {"sha256": hashlib.sha256(content).hexdigest(), "row_count": len(rows)}


def picks_digest(picks: Iterable) -> str:
    """sha256 over a seed's drawn `(symbol, bar_index)` pairs, so which rows a seed drew stays
    checkable without storing them (scope §5, item 9)."""
    payload = "\n".join(f"{sym}\t{idx}" for sym, idx in picks).encode()
    return hashlib.sha256(payload).hexdigest()


# ── the summaries ───────────────────────────────────────────────────────────────────────────────

def group_summary(
    rows: Sequence[Mapping], *,
    horizons: Sequence[int] = DEFAULT_HORIZONS,
    scenarios: Sequence[str] = DEFAULT_SCENARIOS,
    target_names: Sequence[str] = report.DEFAULT_TARGET_NAMES,
    keep_net_vectors: bool = True,
    segment: bool = True,
    row_check: Optional[Callable[[Mapping], None]] = None,
    digest: bool = True,
) -> dict:
    """Everything the report can ever need from one control-row set, computed while the rows exist.

    `row_check` is called on every row before anything is accumulated. That is how a per-row gate
    moves INSIDE the generation loop: `integrity.assert_no_sealed_rows_in_dataset` is the only §8
    probe that touches control rows (`execute.py:399-410`), and if rows are summarised and dropped
    without it, its coverage silently shrinks from "every row" to "pattern rows" with nothing
    failing (scope §5).

    `keep_net_vectors` retains the per-row `net_before_tax` scalars — required for the ATR-decile
    control's percentile, unnecessary for the random control, whose distribution is per-seed.
    """
    rows = list(rows)
    if row_check is not None:
        for row in rows:
            row_check(row)

    stats: dict = {}
    pooling: dict = {}
    net_vectors: dict = {}
    hit_rates: dict = {}
    holding: dict = {}
    ambiguity: dict = {}
    segmentation: dict = {}
    for horizon in horizons:
        h_stats, h_pool, h_vec = {}, {}, {}
        for scenario in scenarios:
            h_stats[scenario] = report.return_stats(rows, horizon, scenario=scenario)
            h_pool[scenario] = _pooling_terms(rows, horizon, scenario)
            if keep_net_vectors:
                h_vec[scenario] = row_net_vector(rows, horizon, scenario)
        stats[horizon] = h_stats
        pooling[horizon] = h_pool
        if keep_net_vectors:
            net_vectors[horizon] = h_vec

        # Item 2 (hit rates) and item 4 (holding period) for the comparison groups. v1 computes
        # these for pattern rows only; v2 §7 says the measures are v1's "including every comparison
        # group" (decision S-1). They are accumulated regardless, because the fields live only in
        # the rows and a counter cannot be added retroactively.
        for target in target_names:
            for scenario in scenarios:
                hit_rates.setdefault(horizon, {}).setdefault(target, {})[scenario] = (
                    report.hit_rate_table(rows, target, horizon, scenario=scenario)
                )
                ambiguity.setdefault(horizon, {}).setdefault(target, {})[scenario] = (
                    ambiguity_leg_terms(rows, target, horizon, scenario)
                )
            holding.setdefault(horizon, {})[target] = holding_period_histogram(rows, target, horizon)

        # Item 7, per owner decision S-1. The three context dimensions come back as an explicit
        # UNAVAILABLE rather than a NO_CONTEXT bucket (S-2) -- see `control_segmentation`.
        if segment:
            segmentation[horizon] = control_segmentation(rows, horizon, target_name=target_names[0] if target_names else None)

    out = {
        "summary_version": SUMMARY_VERSION,
        "n_rows": len(rows),
        "stats": stats,
        "pooling_terms": pooling,
        "hit_rates": hit_rates,
        "holding_period_histograms": holding,
        "ambiguity_legs": ambiguity,
    }
    if segment:
        out["segmentation"] = segmentation
    if keep_net_vectors:
        out["net_vectors"] = net_vectors
    if digest:
        out["digest"] = rows_digest(rows)
    return out


def random_control_summaries(
    random_batch: Mapping[int, Sequence[Mapping]], **kwargs
) -> dict:
    """One summary per seed, INCLUDING seeds that drew nothing — `n_seeds_total` in the report is
    `len(random_batch)` (`report.py:356`), so a seed with no usable rows still has to be counted.

    The random control's distribution is per-seed, so its per-row scalars are not retained; this is
    the collapse from ≈6.4 TB to two numbers a seed that the whole redesign turns on.
    """
    kwargs.setdefault("keep_net_vectors", False)
    segment = kwargs.setdefault("segment", False)
    summaries = {seed: group_summary(rows, **kwargs) for seed, rows in random_batch.items()}
    if not segment:
        # S-1 says the §7 measures cover every comparison group "where §7 specifies those outputs".
        # Item 7 segments a REPORT CELL, and the random control enters a cell as a distribution of
        # per-seed means, not as a cell of its own -- so segmenting each of 1,000 seeds is not what
        # §7 asks for, and it is the most expensive thing in the accumulator. It is therefore off by
        # default and SAID SO in the summary, rather than being quietly absent. Turning it on later
        # means regenerating the seeds, so this is a real choice, recorded where a reader will see it.
        for summary in summaries.values():
            summary["segmentation"] = {
                "status": "NOT_COMPUTED",
                "reason": "RANDOM_CONTROL_ENTERS_REPORT_AS_PER_SEED_MEANS",
            }
    return summaries


def stream_random_control_summaries(
    bars_by_symbol: Mapping, draws: Mapping, priced: Mapping, *,
    cfg: Optional[Mapping] = None, row_check: Optional[Callable[[Mapping], None]] = None, **kwargs
) -> dict:
    """The same summaries as `random_control_summaries`, but never holding more than ONE seed's rows.

    `random_control_summaries` takes a materialised `{seed: rows}` batch, which is the thing that
    does not fit: at V-3's 1,000 seeds that batch is the ≈32 TB object. This assembles one seed,
    summarises it, and drops it, so peak memory is one seed rather than all of them.

    Row identity is not re-implemented — each seed goes through
    `controls.assemble_random_control_batch` itself, with a one-entry draws dict — so a streamed
    seed's rows are the same objects the batch path would have produced, by construction rather than
    by assertion. `priced` is shared and bounded by the number of DISTINCT (symbol, bar_index) pairs,
    not by the seed count, so it is not what grows with V-3.

    `row_check` runs per row at generation time: this is where
    `integrity.assert_no_sealed_rows_in_dataset` moves to, so its coverage does not silently shrink
    to pattern rows when the control rows stop being kept (scope §5).
    """
    from research.charting.events import controls

    cfg_kwargs = {} if cfg is None else {"cfg": cfg}
    kwargs.setdefault("keep_net_vectors", False)
    segment = kwargs.setdefault("segment", False)

    summaries: dict = {}
    for seed in sorted(draws):
        one = controls.assemble_random_control_batch(
            bars_by_symbol, {seed: draws[seed]}, priced, **cfg_kwargs
        )
        summaries[seed] = group_summary(one[seed], row_check=row_check, **kwargs)
        del one  # the seed's rows go here, and nowhere else
    if not segment:
        for summary in summaries.values():
            summary["segmentation"] = {
                "status": "NOT_COMPUTED",
                "reason": "RANDOM_CONTROL_ENTERS_REPORT_AS_PER_SEED_MEANS",
            }
    return summaries


# ── rebuilding the report block from summaries ──────────────────────────────────────────────────

def comparison_block_from_summaries(
    pattern_rows: Sequence[Mapping], horizon: int, *,
    random_summaries: Optional[Mapping[int, Mapping]] = None,
    atr_decile_summary: Optional[Mapping] = None,
    buy_next_open_summary: Optional[Mapping] = None,
    nifty_500_return: Optional[float] = None,
    scenario: str = "base",
) -> dict:
    """`report.comparison_block` rebuilt from summaries instead of rows.

    Deliberately mirrors that function statement for statement, including the order keys are
    inserted in, so the equivalence test compares two dicts that were built the same way and any
    difference is a real difference. The pattern rows themselves are NOT summarised — only the
    comparison groups are; pattern events stay row-level.
    """
    pattern_stats = report.return_stats(pattern_rows, horizon, scenario=scenario)
    out: dict = {"pattern": pattern_stats}

    if random_summaries:
        seed_means: list = []
        for _seed, summary in random_summaries.items():
            st = summary["stats"][horizon][scenario]
            if st["n"] > 0:
                seed_means.append(st["net_return"]["mean"])
        out["random_200_seed"] = {
            "n_seeds_with_data": len(seed_means),
            "n_seeds_total": len(random_summaries),
            "mean_of_seed_means": report._mean(seed_means),
            "median_of_seed_means": report._median(seed_means),
            "pattern_percentile_within_seed_distribution": (
                report.percentile_rank(pattern_stats["net_return"]["mean"], seed_means)
                if pattern_stats["n"] else None
            ),
        }

    if atr_decile_summary is not None:
        atr_stats = atr_decile_summary["stats"][horizon][scenario]
        atr_row_net_returns = atr_decile_summary["net_vectors"][horizon][scenario]
        out["atr_decile_matched"] = {
            **atr_stats,
            "pattern_percentile_within_distribution": (
                report.percentile_rank(pattern_stats["net_return"]["mean"], atr_row_net_returns)
                if pattern_stats["n"] else None
            ),
        }

    if buy_next_open_summary is not None:
        out["buy_next_open"] = buy_next_open_summary["stats"][horizon][scenario]

    if nifty_500_return is not None:
        out["nifty_500"] = {"return": nifty_500_return}

    return out


def summary_comparison_builder(bullish_rows: Sequence[Mapping], horizon: int, cg: Mapping) -> dict:
    """The summary-based counterpart to `report.default_comparison_builder`, injected into
    `report.build_report` by `study/execute.py` when a run summarises its controls.

    Same signature, same return shape; the difference is only where the comparison groups' numbers
    come from. `test_study_accumulate.py` proves the two produce identical blocks.
    """
    return comparison_block_from_summaries(
        bullish_rows, horizon,
        random_summaries=cg.get("random_summaries"),
        atr_decile_summary=cg.get("atr_decile_summary"),
        buy_next_open_summary=cg.get("buy_next_open_summary"),
        nifty_500_return=(cg.get("nifty_500_return_by_horizon") or {}).get(horizon),
    )
