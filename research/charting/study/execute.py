"""Study execution -- CHARTING_PREREGISTRATION_V1 (FROZEN, `docs/ai_research/
CHARTING_PREREGISTRATION_V1.md`) end to end, one entry point: `execute_study`.

BUILD ONLY in this session (task hard rule: "Do not run the full pre-registered study --
that run is done by the orchestrator after review"). Every function here is written and
tested against synthetic fixtures (`research/charting/tests/test_study_execute.py`); the
only real-data invocation this session performs is a <=10-symbol wiring smoke run whose
output directory is deleted afterward and whose own report never prints an outcome number
(hit rate, return, AUC, expectancy, ...) -- see this package's own final report for that
run's structural-only results.

Assembles, per §9's own listed pieces (all already built by other sessions/PRs; this
module only wires them together in the order §3/§7/§8 require):

  1. `research.charting.bars.load_all`/`load_symbol` (all symbols, or the given subset) +
     `bars.provenance()` (§2 "the sha256 of every input file") + the sealed ETF list
     (`research.charting.universe.load_etf_symbols`, read without a header, §3).
  2. Per segment (pre-sealed, post-sealed): `study.run.build_pre_sealed_segment` /
     `build_post_sealed_segment`, with the REAL §37.5 demerger hooks plugged in
     (`research.corporate_actions.regime.regime_break_mask`/`regime_segments` --
     `study.run`'s own module docstring names these as the hooks it deliberately never
     imports itself), `attach_context=True` (§6), and `input_file_hashes` from step 1.
  3. Per segment x family (§7.6): the four comparison groups -- 200-seed random control,
     ATR-decile-matched control, buy-at-next-open baseline (all three via
     `events.controls`, built from the SAME filtered frames `build_segment` itself used
     -- `result["bars_by_symbol"]` -- and the SAME point-in-time eligible population,
     `eligible_population()` below), and NIFTY 500 over the same holding periods
     (`_benchmark_forward_returns`, this module's own small addition -- no existing
     helper computes an INDEX's own forward return over a set of entry dates). Each
     group is written as its own hashed artifact next to `events.jsonl`
     (`_write_family_comparison_artifacts`).
  4. `study.report.build_report` per segment, with every family's comparison groups wired
     in; `report.json` (strict JSON) + `report.md` per segment, and a top-level
     `study_manifest.json` (§2's own extended manifest fields, at the STUDY level: both
     segments' own manifest paths, the prereg sha256, the §2 frozen-config-hash check
     result, the worktree's git commit if resolvable, and run start/end times).
  5. The §8 integrity gate, BEFORE the report is written (`_run_integrity_gate`): the
     kill switch (§8 bullet 1 -- two independent builds of the SAME segment inputs must
     produce identical `pattern_id` sets and identical `events.jsonl` bytes; a
     `kill_switch=False` escape hatch exists for this module's OWN tests only -- the real
     run must leave it `True`, its default, and a skipped check is recorded loudly, never
     silently treated as a pass), the sealed-window check (§8 bullet 3, re-run here across
     EVERY row this module built for the segment -- pattern rows AND every comparison-
     group row, per `study.integrity.assert_no_sealed_rows_in_dataset`'s own docstring),
     and `study.integrity.recompute_sample` (§8 bullet 4 / TC-40) on the segment's own
     pattern rows. Any failure, in either segment, blocks BOTH segments' reports (§8's own
     heading: "before ANY number is reported" -- not "before this segment's numbers") and
     writes `INTEGRITY_FAILED.md` with the full detail instead.
  6. A CLI (`python -m research.charting.study.execute --out <dir> [--symbols A,B,C]`) that
     only ever prints the run's status and output directory -- never a metric -- so a
     future invocation of this exact file can never accidentally leak an outcome number to
     a terminal or log.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import math
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Mapping, Optional, Sequence

import pandas as pd

from research.charting import bars as bars_mod
from research.charting import context, regime
from research.charting import universe as universe_mod
from research.charting.config import CONFIG
from research.charting.events import controls, costs_bridge, schema, writer
from research.charting.research_window import SealedWindowError
from research.charting.study import accumulate, heartbeat as hb_mod, integrity
from research.charting.study import pair_table as pt_mod
from research.charting.study import remote_store, report
from research.charting.study import run as study_run
from research.corporate_actions.regime import regime_break_mask, regime_segments

# §3's own universe caveats -- reproduced verbatim (not re-derived), restated in every
# report per item 10 ("The universe caveats in §3 ... are stated"), independent of
# whatever this particular run's own numbers turn out to be.
UNIVERSE_CAVEATS: tuple = (
    "Universe: symbols with >= 250 bars, minus the sealed ETF list "
    "(research/sealed/etf_symbols_kite_20260919.csv, read without a header) -- "
    "2,132 symbols, 291 ETFs removed (prereg §3).",
    "The sealed ETF list is known to exclude some real equities (BHARATFORG, "
    "BHARATGEAR-BE, BHARATRAS, BHARATWIRE, DALBHARAT; suspected FIRSTCRY, SENCO, LGHL) "
    "-- every report states this (prereg §3).",
    "A point-in-time ETF universe is parked on the to-do list (owner, decisions-log #89).",
)

DEFAULT_RECOMPUTE_HORIZON = 5
DEFAULT_RECOMPUTE_SAMPLE_SIZE = 50  # §8 bullet 4: "a sample of rows"


# ── Step 1: bars, provenance, sealed ETF list ────────────────────────────────────────────


def _load_bars(symbols: Optional[Sequence[str]], kite_dir) -> dict:
    """§3: "all symbols by default, or the given subset". A requested symbol with no bars
    under `kite_dir` contributes an empty frame from `bars.load_symbol` -- dropped here
    (never silently padded/fabricated) so the universe rule downstream sees only symbols
    that actually have data, the same as `load_all`'s own contract."""
    if symbols is None:
        return dict(bars_mod.load_all(kite_dir))
    out: dict = {}
    for symbol in symbols:
        b = bars_mod.load_symbol(symbol, kite_dir)
        if not b.empty:
            out[symbol] = b
    return out


def _input_file_hashes(kite_dir) -> list:
    """§2: "the sha256 of every input file" -- `bars.provenance()`'s own per-part-file
    manifest, ALWAYS over the full source directory regardless of any `symbols` subset
    (provenance answers "what data could this run have drawn from", not "what a narrowed
    subset happened to touch" -- the same discipline `study.run.build_segment`'s own
    docstring documents for why `input_file_hashes` is accepted rather than recomputed
    per call)."""
    prov = bars_mod.provenance(kite_dir)
    return [{"path": f.path, "sha256": f.sha256, "row_count": f.row_count} for f in prov.files]


def eligible_population(bars_by_symbol: Mapping[str, pd.DataFrame]) -> list:
    """§7.6.ii/iv: "the same eligible universe and dates" -- every (symbol, bar_index) in
    the segment's own already-filtered/windowed frames (`build_segment`'s own
    `result["bars_by_symbol"]`, post universe/data-quality/demerger filtering) that has a
    bar to enter on (`idx + 1 < len(bars)`, matching `outcomes.primary_entry`'s own "open
    of bar t+1" requirement) -- point in time, the whole segment's own population, shared
    across every family and every comparison group built from it (never re-scoped smaller
    per family: "the same eligible universe" for all of them)."""
    return [(symbol, idx) for symbol, bars in bars_by_symbol.items() for idx in range(max(len(bars) - 1, 0))]


# ── §7.6.v: NIFTY 500 over the same holding periods (no existing helper computes this) ──


def _benchmark_forward_returns(rows: Sequence[Mapping], benchmark_df: pd.DataFrame, horizons: Sequence[int]) -> dict:
    """Per horizon: the mean forward close return of `benchmark_df` (§7.6.v "NIFTY 500"),
    starting from the SAME entry date as each BULLISH row's own primary entry
    (`row["entry"]["primary"]["date"]`, "open of bar t+1" -- §5) and held the SAME number
    of sessions. `benchmark_df`'s own row position for that date stands in for "the
    benchmark's own bar t+1" -- a date with no benchmark row (a rare index/stock calendar
    mismatch) or with fewer than `h` benchmark bars remaining simply does not contribute a
    value for that horizon (never fabricated, matching every other "unavailable" contract
    in this package). Returns `{horizon: {"mean": float | None, "n": int}}`.
    """
    bullish = [r for r in rows if r.get("direction") == "BULLISH"]
    dates = benchmark_df["date"].to_numpy()
    closes = benchmark_df["close"].to_numpy(dtype=float)
    pos_by_date = {pd.Timestamp(d).normalize(): i for i, d in enumerate(dates)}

    entry_positions: list = []
    for row in bullish:
        entry = (row.get("entry") or {}).get("primary")
        if not entry or entry.get("date") is None:
            continue
        pos = pos_by_date.get(pd.Timestamp(entry["date"]).normalize())
        if pos is not None:
            entry_positions.append(pos)

    out: dict = {}
    for h in horizons:
        rets: list = []
        for pos in entry_positions:
            if pos + h >= len(closes):
                continue
            base = closes[pos]
            if base is None or not math.isfinite(base) or base <= 0:
                continue
            rets.append((closes[pos + h] - base) / base)
        out[h] = {"mean": (sum(rets) / len(rets)) if rets else None, "n": len(rets)}
    return out


def _collect_unverified_cost_rates(rows: Sequence[Mapping]) -> list:
    """§7.10: "the unverified cost rates listed by the cost engine" -- the union of every
    `unverified_rates_used` (S36.5) recorded on any horizon's cost block across `rows`,
    computed here rather than hand-listed so a future cost-rule-file change is reflected
    automatically."""
    out: set = set()
    for row in rows:
        for block in ((row.get("costs") or {}).get("by_horizon") or {}).values():
            if block and block.get("available"):
                out.update(block.get("unverified_rates_used") or [])
    return sorted(out)


# ── §7.6: per-segment, per-family comparison groups ──────────────────────────────────────
#
# PERF-PARALLEL replaces the earlier PERF-CONTROLS per-FAMILY worker pool (one task per pattern
# family -- only 3 families ever exist, so at most 3-way parallel, and every worker had to
# rebuild its own `ControlPriceCache` from scratch, losing the cross-family ATR/pricing reuse
# the serial path got for free -- measured to give no real speedup) with the draw/price/assemble
# split `events.controls` now exposes (see that module's own "draw / price / assemble split"
# block): draws (which (symbol, bar_index) pairs each control group needs) are cheap and stay
# serial; the union of every draw's pairs, ACROSS EVERY FAMILY in the segment, is priced EXACTLY
# ONCE via `controls.price_signals` (grouped by symbol when `max_workers > 1`, so a symbol's own
# ATR series and rule-file cache are never rebuilt twice and no reuse is ever lost to a process
# boundary); assembly (pure dict lookups into the priced result) stays serial.


def build_family_comparison_groups(
    rows: Sequence[Mapping], bars_by_symbol: Mapping[str, pd.DataFrame], *, cfg: dict = CONFIG,
    cost_cfg: Optional[costs_bridge.CostConfig] = None, random_seeds: Sequence[int] = controls.RANDOM_CONTROL_SEEDS,
    atr_decile_seed: int = 0, benchmark_df: pd.DataFrame, horizons: Sequence[int] = schema.HORIZONS,
    max_workers: int = 1, summarise_controls: bool = False,
    control_row_check: Optional[Callable[[Mapping], None]] = None,
    columnar: bool = False, checkpoint_dir=None, heartbeat=None,
) -> dict:
    """One segment's §7.6 comparison groups, per pattern family present in `rows`:
    `{family: {"random_batch", "atr_decile_rows", "buy_next_open_rows",
    "nifty_500_return_by_horizon", "nifty_500_detail_by_horizon"}}` -- the last key is this
    module's own bookkeeping (n counts, for the artifact write) and is harmlessly ignored
    by `study.report.comparison_block` (which reads only the other four).

    Random control size: `len(bullish)` per family -- a matched-size comparison against
    the population actually being tested (§7.6.ii names "200 seeds", not a size; matching
    the family's own signal count is the documented, standard resampling choice made
    here). ATR-decile control and the NIFTY 500 comparison are likewise built from the
    family's BULLISH events only (the only rows §1/§7.6 actually prices a trade for --
    BEARISH rows are validated separately, §7.8). Buy-at-next-open is built from EVERY
    family event regardless of direction (`controls.buy_next_open_baseline_rows`'s own
    docstring: "regardless of the pattern's own BULLISH/BEARISH call").

    Three phases (see the block above this function): (1) DRAW every family's random-batch/
    ATR-decile/buy-next-open picks, serially, deterministically -- identical RNG/seeding/
    candidate-pool logic to the original per-family functions, just without pricing anything
    yet; (2) the UNION of every (symbol, bar_index) pair any draw needs, across EVERY family,
    priced exactly once via `controls.price_signals` (`max_workers` forwarded there -- see its
    own docstring for the by-symbol pool); (3) ASSEMBLE every family's rows from that one shared
    priced result. Row CONTENT is identical field-for-field to what the original per-family
    `random_control_batch`/`atr_decile_control_rows`/`buy_next_open_baseline_rows` calls would
    build for the same inputs (draw order preserved exactly through assembly), and the returned
    dict is built in `sorted(families)` order -- byte-identical and independent of `max_workers`
    or of which worker, if any, finished a given symbol first.
    """
    eligible = eligible_population(bars_by_symbol)
    # Every draw below returns `(event, picks)` and so keeps its event REFERENCED for the whole
    # pricing phase. A pattern row is ~219 KB live against ~2.7 KB of real data, so holding the
    # rows themselves pins most of the segment in memory until pricing finishes -- one of the
    # retentions behind the v2 run's 53 GB. Projecting first keeps the same seven fields the draw
    # and assembly steps actually read (`controls.DRAW_FIELDS`, pinned by its own equivalence
    # test) and lets the rows go. Nothing downstream of here reports on a row's own results.
    rows = [controls.event_projection(r) for r in rows]
    families = sorted({r["pattern_type"] for r in rows})
    if not families:
        return {}

    # Phase 1 -- draw (cheap, deterministic, always serial: see block above). `draw_cache` is
    # shared across every family's ATR-decile draw (its `atr_by_symbol` half only -- ranking
    # ATR%(t) needs a full-series read, never the heavier `priced_signal` half, which this phase
    # never touches at all).
    draw_cache = controls.ControlPriceCache()
    per_family_draws: dict = {}
    nifty_detail_by_family: dict = {}
    for family in families:
        family_rows = [r for r in rows if r["pattern_type"] == family]
        bullish = [r for r in family_rows if r.get("direction") == "BULLISH"]
        per_family_draws[family] = {
            "random": controls.random_control_draws(eligible, n=len(bullish), seeds=random_seeds),
            "atr_decile": controls.atr_decile_control_draws(
                bars_by_symbol, bullish, eligible, seed=atr_decile_seed, cfg=cfg, cache=draw_cache,
            ),
            "buy_next_open": controls.buy_next_open_baseline_draws(family_rows),
        }
        nifty_detail_by_family[family] = _benchmark_forward_returns(bullish, benchmark_df, horizons)

    # Phase 2 -- price the UNION of every pair any family's draw needs, exactly once, optionally
    # across a by-symbol worker pool (see block above / `controls.price_signals`'s own docstring).
    random_pairs: set = set()
    other_pairs: set = set()
    for draws in per_family_draws.values():
        for picks in draws["random"].values():
            random_pairs.update(picks)
        for _ev, picks in draws["atr_decile"]:
            other_pairs.update(picks)
        for _ev, pick in draws["buy_next_open"]:
            other_pairs.add(pick)

    if columnar:
        # Only the random control's union saturates the eligible population (~100% at 1,000 seeds,
        # measured), so it is the only group that cannot be a dict of priced signals. It goes
        # through the columnar table -- chunked, encoded, fat objects dropped -- and WITHOUT the
        # target walk, which is 88% of pricing and feeds only figures nothing reads. The other two
        # groups are bounded by the family's own event count, so they are priced normally and keep
        # their full blocks.
        layout = pt_mod.PairLayout(schema.HORIZONS, accumulate.DEFAULT_SCENARIOS,
                                   report.DEFAULT_TARGET_NAMES)
        if heartbeat is not None:
            heartbeat.stage("pricing random control (columnar)")
            heartbeat.note("random_control_pairs", len(random_pairs))
        table = pt_mod.build_table(
            bars_by_symbol, random_pairs, layout, cfg=cfg, cost_cfg=cost_cfg,
            max_workers=max_workers, row_check=control_row_check, with_targets=False,
            checkpoint_dir=checkpoint_dir,
            progress=(lambda d, n: (heartbeat.progress(d, n, "pairs"), heartbeat.check_resources()))
            if heartbeat is not None else None,
        )
        if heartbeat is not None:
            heartbeat.stage("pricing atr-decile + buy-next-open")
            heartbeat.note("other_control_pairs", len(other_pairs))
        priced = controls.price_signals(bars_by_symbol, other_pairs, cfg=cfg, cost_cfg=cost_cfg,
                                        max_workers=max_workers)
    else:
        table = None
        all_pairs = random_pairs | other_pairs
        priced = controls.price_signals(bars_by_symbol, all_pairs, cfg=cfg, cost_cfg=cost_cfg,
                                        max_workers=max_workers)

    # Phase 3 -- assemble (pure dict lookups, always serial: see block above).
    #
    # `summarise_controls` is the study-v2 storage redesign (docs/ai_research/
    # CHARTING_STUDY_V2_STORAGE_REDESIGN.md). OFF by default, so the v1 row path is unchanged and
    # stays re-runnable for the equivalence comparison; ON, the random control is summarised one
    # seed at a time and its rows are never all held at once -- the ~6.4 TB (~32 TB at V-3's 1,000
    # seeds) object simply does not come into existence. `study/accumulate.py` proves the two paths
    # produce identical comparison blocks.
    #
    # `control_row_check` runs on EVERY generated control row before it is summarised. That is where
    # `integrity.assert_no_sealed_rows_in_dataset` moves to: it is the only §8 probe that touches
    # control rows, and if the rows are summarised and dropped without it, its coverage silently
    # shrinks to pattern rows with nothing failing.
    results: dict = {}
    for family in families:
        draws = per_family_draws[family]
        common = {
            "nifty_500_return_by_horizon": {h: d["mean"] for h, d in nifty_detail_by_family[family].items()},
            "nifty_500_detail_by_horizon": nifty_detail_by_family[family],
        }
        atr_rows = controls.assemble_atr_decile_control_rows(bars_by_symbol, draws["atr_decile"], priced, cfg=cfg)
        bno_rows = controls.assemble_buy_next_open_baseline_rows(bars_by_symbol, draws["buy_next_open"], priced, cfg=cfg)
        if columnar:
            results[family] = {
                **common,
                "random_summaries": {seed: pt_mod.seed_summary(table, picks)
                                     for seed, picks in sorted(draws["random"].items())},
                "atr_decile_summary": accumulate.group_summary(atr_rows, row_check=control_row_check),
                "buy_next_open_summary": accumulate.group_summary(bno_rows, row_check=control_row_check),
            }
        elif summarise_controls:
            results[family] = {
                **common,
                "random_summaries": accumulate.stream_random_control_summaries(
                    bars_by_symbol, draws["random"], priced, cfg=cfg, row_check=control_row_check,
                ),
                # Both of these are bounded by the family's own event count, not by the seed count,
                # so they are summarised but not streamed -- and they keep their per-row net vectors,
                # which the ATR-decile percentile needs.
                "atr_decile_summary": accumulate.group_summary(atr_rows, row_check=control_row_check),
                "buy_next_open_summary": accumulate.group_summary(bno_rows, row_check=control_row_check),
            }
        else:
            results[family] = {
                **common,
                "random_batch": controls.assemble_random_control_batch(bars_by_symbol, draws["random"], priced, cfg=cfg),
                "atr_decile_rows": atr_rows,
                "buy_next_open_rows": bno_rows,
            }
    return {family: results[family] for family in families}


# ── Hashed comparison-group artifacts, next to events.jsonl ─────────────────────────────


def _sha256_file(path: Path) -> Optional[str]:
    if not Path(path).is_file():
        return None
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _write_rows_artifact(rows: Sequence[dict], out_dir, *, segment: str, symbols: Sequence[str], cfg: dict, compress: bool = False) -> dict:
    """`events.jsonl` + `manifest.json` for a comparison-group row set, via the SAME hashed
    writer real pattern events use (`events.writer.write_run`) -- one shape for every
    artifact this package writes."""
    cost_versions = {r["versioning"]["cost_rule_version"] for r in rows if r.get("versioning", {}).get("cost_rule_version")}
    tax_versions = {r["versioning"]["tax_rule_version"] for r in rows if r.get("versioning", {}).get("tax_rule_version")}
    return writer.write_run(
        rows, out_dir, segment=segment, symbols=symbols, cfg=cfg,
        cost_rule_versions=cost_versions, tax_rule_versions=tax_versions, compress=compress,
    )


def _write_nifty_artifact(fam_dir: Path, detail_by_horizon: Mapping, *, segment: str, family: str, benchmark_path) -> dict:
    fam_dir = Path(fam_dir)
    fam_dir.mkdir(parents=True, exist_ok=True)
    path = fam_dir / "nifty_500_returns.json"
    payload = {
        "segment": segment,
        "family": family,
        "market_benchmark": regime.FEATURE_CONFIG["market_benchmark"],
        "return_by_horizon": {str(h): d["mean"] for h, d in detail_by_horizon.items()},
        "n_by_horizon": {str(h): d["n"] for h, d in detail_by_horizon.items()},
        "source_file": str(benchmark_path),
        "source_file_sha256": _sha256_file(benchmark_path),
    }
    content = (json.dumps(payload, sort_keys=True, indent=2) + "\n").encode("utf-8")
    path.write_bytes(content)
    return {"path": "nifty_500_returns.json", "sha256": hashlib.sha256(content).hexdigest()}


def _write_summary_artifact(summary: Mapping, out_dir, *, segment: str, family: str, group_name: str, compress: bool = False) -> dict:
    """`summary.json` -- what replaces a comparison group's `events.jsonl` under the v2 storage
    redesign. It carries the group's own row digest (`sha256` + `row_count` over the bytes the
    writer WOULD have produced), so the §8 kill-switch property survives at ~64 bytes per seed."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema": "comparison_group_summary",
        "summary_version": accumulate.SUMMARY_VERSION,
        "segment": segment, "family": family, "group": group_name,
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "summary": report.to_json_dict(summary),
    }
    blob = (json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode()
    if compress:
        path = out_dir / "summary.json.gz"
        path.write_bytes(writer._gzip_bytes(blob))
    else:
        path = out_dir / "summary.json"
        path.write_bytes(blob)
    return {
        "path": str(path), "sha256": writer._sha256_bytes(blob), "compressed": bool(compress),
        "stored_sha256": _sha256_file(path), "rows_summarised": summary.get("n_rows"),
    }


def _write_seed_summaries_artifact(summaries: Mapping, out_dir, *, segment: str, family: str, compress: bool = False) -> dict:
    """The random control's per-seed summaries as ONE compact `summaries.jsonl`, a line per seed.

    Deliberately not a file per seed: at V-3's 1,000 seeds across ~40 reporting units that is 80,000
    files per segment, and `indent=2` alone doubled the payload (measured: 149.8 KB -> 73.1 KB a seed
    for the identical content). Both are encoding choices and neither drops a field.
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    lines = []
    for seed, summary in sorted(summaries.items()):
        lines.append(json.dumps(
            {"segment": segment, "family": family, "group": "random_control", "control_seed": seed,
             "summary_version": accumulate.SUMMARY_VERSION, "summary": report.to_json_dict(summary)},
            sort_keys=True, separators=(",", ":"), allow_nan=False,
        ))
    blob = ("\n".join(lines) + ("\n" if lines else "")).encode()
    if compress:
        # The summaries are what REPLACE the rows, so they get the same treatment: measured 29.0x,
        # the highest ratio of any artefact here (one line per seed, every line the same key set).
        path = out_dir / "summaries.jsonl.gz"
        path.write_bytes(writer._gzip_bytes(blob))
    else:
        path = out_dir / "summaries.jsonl"
        path.write_bytes(blob)
    return {
        "path": str(path), "sha256": writer._sha256_bytes(blob), "compressed": bool(compress),
        "stored_sha256": _sha256_file(path), "n_seeds": len(summaries),
        "bytes": len(blob), "stored_bytes": path.stat().st_size,
        "rows_summarised": sum(s.get("n_rows", 0) for s in summaries.values()),
    }


def _write_family_comparison_artifacts(
    comparisons_dir: Path, family: str, segment: str, group: Mapping, *, cfg: dict,
    symbols: Sequence[str], benchmark_path, compress: bool = False,
) -> dict:
    fam_dir = Path(comparisons_dir) / family
    if "random_summaries" in group:
        # v2 storage redesign: summaries, not rows. The random control writes one summary per seed
        # under `random_control/`, which is what turns ~6.4 TB into a few MB.
        out = {"random_control": _write_seed_summaries_artifact(
            group["random_summaries"], fam_dir / "random_control", segment=segment, family=family,
            compress=compress,
        )}
        for key, group_name in (("atr_decile_summary", "atr_decile_control"), ("buy_next_open_summary", "buy_next_open")):
            out[group_name] = _write_summary_artifact(
                group[key], fam_dir / group_name, segment=segment, family=family, group_name=group_name,
                compress=compress,
            )
        out["nifty_500"] = _write_nifty_artifact(
            fam_dir, group["nifty_500_detail_by_horizon"], segment=segment, family=family, benchmark_path=benchmark_path,
        )
        return out

    flattened_random = [
        {**row, "control_seed": seed} for seed in sorted(group["random_batch"]) for row in group["random_batch"][seed]
    ]
    return {
        "random_control": _write_rows_artifact(flattened_random, fam_dir / "random_control", segment=segment, symbols=symbols, cfg=cfg, compress=compress),
        "atr_decile_control": _write_rows_artifact(group["atr_decile_rows"], fam_dir / "atr_decile_control", segment=segment, symbols=symbols, cfg=cfg, compress=compress),
        "buy_next_open": _write_rows_artifact(group["buy_next_open_rows"], fam_dir / "buy_next_open", segment=segment, symbols=symbols, cfg=cfg, compress=compress),
        "nifty_500": _write_nifty_artifact(fam_dir, group["nifty_500_detail_by_horizon"], segment=segment, family=family, benchmark_path=benchmark_path),
    }


# ── §7 report per segment ─────────────────────────────────────────────────────────────────


def _build_segment_report(
    segment_result: Mapping, comparison_groups_by_family: Mapping, *, prereg_sha: str,
    input_hashes: Mapping, build_comparisons: Optional[Callable] = None,
) -> dict:
    rows = segment_result["rows"]
    dq = segment_result["data_quality_exclusions"]
    demerger = segment_result["demerger_regimes"]
    exclusion_counts = {
        "data_quality": dq.get("events_excluded", 0),
        # §37.5: sessions trimmed around a demerger's ex-date, summed across every symbol
        # this segment covers -- "insufficient forward bars"/"AMBIGUOUS" stay per-horizon
        # (report.exclusion_table's own docstring: never duplicated here).
        "demerger_window": sum(v.get("sessions_excluded", 0) for v in demerger.values()),
    }
    return report.build_report(
        segment=segment_result["segment"], pattern_rows=rows, bars_by_symbol=segment_result["bars_by_symbol"],
        exclusion_counts=exclusion_counts, comparison_groups_by_family=comparison_groups_by_family,
        universe_caveats=UNIVERSE_CAVEATS, unverified_cost_rates=_collect_unverified_cost_rates(rows),
        input_hashes=input_hashes, prereg_sha256=prereg_sha, build_comparisons=build_comparisons,
    )


# ── §8 integrity gate ──────────────────────────────────────────────────────────────────────


def _run_integrity_gate(
    segment_results: Mapping[str, dict], comparison_groups: Mapping[str, dict], *,
    bars_by_symbol: Mapping[str, pd.DataFrame], build_fns: Mapping[str, Callable], segment_kwargs: dict,
    kill_switch: bool, recompute_sample_size: int, recompute_seed: int, recompute_horizon: int,
    cfg: dict, cost_cfg: Optional[costs_bridge.CostConfig],
) -> dict:
    """§8, run BEFORE any report is written. Per segment: the kill switch (bullet 1, on the
    segment's own PATTERN rows -- "identical event files" is `events.jsonl`, the pattern
    dataset; comparison-group reproducibility is not part of §8's own wording and is not
    checked here), the sealed-window re-check (bullet 3, across pattern rows AND every
    comparison-group row this run built -- `integrity.assert_no_sealed_rows_in_dataset`'s
    own documented scope), and `integrity.recompute_sample` (bullet 4 / TC-40) on the
    segment's own pattern rows. `passed` is `True` only when every one of these is `True`
    for BOTH segments.
    """
    out: dict = {}
    all_passed = True
    for segment, result in segment_results.items():
        seg_out: dict = {}

        if kill_switch:
            # The duplicate build is DIGESTED, never materialised. §8 asks whether two runs would
            # write byte-identical event files, and both halves of that evidence -- the sha256 over
            # `writer._dump_jsonl` and the pattern-id set -- fold one symbol at a time. Holding the
            # second dataset instead cost a full extra copy of the segment at ~200 KB live per row,
            # on top of the copy the report is already using, which is what made the peak
            # unsurvivable on a 62 GB host.
            dup_digest = integrity.RunDigest()
            build_fns[segment](bars_by_symbol, out_dir=None,
                               row_sink=lambda _symbol, rows: dup_digest.update(rows),
                               **segment_kwargs)
            own_digest = integrity.RunDigest()
            own_digest.update(result["rows"])
            ks = integrity.kill_switch_check_digests(own_digest, dup_digest)
        else:
            ks = {
                "skipped": True, "passed": True,
                "reason": "kill_switch=False -- tests only; the real run must use True per prereg §8",
            }
        seg_out["kill_switch"] = ks

        # Bullet 3. The control rows are checked WHERE THEY EXIST. In the v1 row path they are all
        # still in memory, so they are gathered here as before. Under the v2 storage redesign they
        # were checked one at a time as each was generated (`control_row_check`, wired in
        # `execute_study`), because by now they are gone -- so this adds their counts rather than
        # re-reading rows that no longer exist. Either way `n_rows_checked` covers every row, which
        # is the number that would otherwise silently shrink to the pattern rows alone.
        all_rows: list = list(result["rows"])
        summarised_rows_checked = 0
        for group in comparison_groups[segment].values():
            if "random_summaries" in group:
                summarised_rows_checked += sum(s["n_rows"] for s in group["random_summaries"].values())
                summarised_rows_checked += group["atr_decile_summary"]["n_rows"]
                summarised_rows_checked += group["buy_next_open_summary"]["n_rows"]
                continue
            for seed_rows in group["random_batch"].values():
                all_rows.extend(seed_rows)
            all_rows.extend(group["atr_decile_rows"])
            all_rows.extend(group["buy_next_open_rows"])
        n_checked = len(all_rows) + summarised_rows_checked
        try:
            integrity.assert_no_sealed_rows_in_dataset(all_rows)
            sealed_check = {"passed": True, "error": None, "n_rows_checked": n_checked}
        except SealedWindowError as exc:
            sealed_check = {"passed": False, "error": str(exc), "n_rows_checked": n_checked}
        if summarised_rows_checked:
            sealed_check["control_rows_checked_at_generation"] = summarised_rows_checked
        seg_out["sealed_window_check"] = sealed_check

        rc = integrity.recompute_sample(
            result["bars_by_symbol"], result["rows"], horizon=recompute_horizon,
            sample_size=recompute_sample_size, seed=recompute_seed, cfg=cfg, cost_cfg=cost_cfg,
        )
        seg_out["recompute_sample"] = rc

        seg_out["passed"] = bool(ks.get("passed", True) and sealed_check["passed"] and rc["passed"])
        all_passed = all_passed and seg_out["passed"]
        out[segment] = seg_out

    out["passed"] = all_passed
    return out


def _write_integrity_failed(out_dir: Path, integrity_result: Mapping) -> None:
    lines = [
        "# INTEGRITY GATE FAILED",
        "",
        "CHARTING_PREREGISTRATION_V1 §8: no report is written until every check below passes "
        "for BOTH segments. See the per-segment detail; this file replaces report.json/report.md "
        "for this run.",
        "",
    ]
    for segment, seg in integrity_result.items():
        if segment == "passed":
            continue
        lines.append(f"## {segment} -- passed={seg['passed']}")
        lines.append(f"- kill_switch: {json.dumps(seg['kill_switch'], sort_keys=True, default=str)}")
        lines.append(f"- sealed_window_check: {json.dumps(seg['sealed_window_check'], sort_keys=True, default=str)}")
        rc = seg["recompute_sample"]
        lines.append(
            f"- recompute_sample: passed={rc['passed']} n_rows={rc['n_rows']} "
            f"mismatched_event_ids={rc['mismatched_event_ids']}"
        )
        lines.append("")
    (Path(out_dir) / "INTEGRITY_FAILED.md").write_text("\n".join(lines) + "\n")


# ── git commit (best-effort, read-only) ──────────────────────────────────────────────────


#: Set when the study runs from an exported tree rather than a git checkout -- e.g. a purpose-built
#: VM that received the code as a tarball. Without it the manifest records `git_commit: null`, which
#: leaves a pre-registered run unable to say which code produced it. The value is the upstream SHA
#: the tree was exported from, and it is only consulted when git itself cannot answer.
GIT_COMMIT_ENV = "CHARTING_GIT_COMMIT"


def _git_commit(repo_root: Optional[Path] = None) -> Optional[str]:
    root = repo_root or Path(__file__).resolve().parents[3]
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=str(root), capture_output=True, text=True, timeout=10,
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
    except Exception:
        pass
    return os.environ.get(GIT_COMMIT_ENV) or None


# ── Top-level entry point ────────────────────────────────────────────────────────────────


def execute_study(
    out_dir,
    *,
    symbols: Optional[Sequence[str]] = None,
    kite_dir=None,
    etf_list_path=None,
    bars_by_symbol: Optional[Mapping[str, pd.DataFrame]] = None,
    cfg: dict = CONFIG,
    cost_cfg: Optional[costs_bridge.CostConfig] = None,
    kill_switch: bool = True,
    recompute_sample_size: int = DEFAULT_RECOMPUTE_SAMPLE_SIZE,
    recompute_seed: int = 0,
    recompute_horizon: int = DEFAULT_RECOMPUTE_HORIZON,
    random_control_seeds: Sequence[int] = controls.RANDOM_CONTROL_SEEDS,
    atr_decile_seed: int = 0,
    now: Optional[datetime] = None,
    max_workers: int = 1,
    summarise_controls: bool = False,
    compress_events: bool = False,
    upload_to: Optional[str] = None,
    columnar: bool = False,
    checkpoint_dir=None,
    observe: bool = False,
) -> dict:
    """Run the whole CHARTING_PREREGISTRATION_V1 study end to end into `out_dir` (module
    docstring lists the six steps). `bars_by_symbol` is a test-only seam: when given, step 1's
    real `bars.load_all`/`load_symbol` call is skipped and this frame is used directly (still
    combined with a real/synthetic `bars.provenance(kite_dir)` for `input_file_hashes`, per §2)
    -- production/CLI callers never pass it, letting the real Kite universe load per `symbols`.

    `max_workers` (PERFORMANCE ONLY, default 1 = serial, byte-identical output to this
    function's behaviour before the PERF-PARALLEL performance work for any value -- see the
    proof this package's own final report gives, hashing a real subset run at `max_workers=1`
    against `max_workers=4`): forwarded, per segment, to `study.run.build_segment` (per-symbol
    event extraction AND per-symbol context join -- via `segment_kwargs`, so the §8 kill-switch's
    own duplicate build gets it too, remaining two GENUINELY independent full builds, each
    parallel) and to `build_family_comparison_groups` (per-symbol comparison-group pricing, the
    union of every family's draws in the segment) -- see each function's own docstring. Left at
    the safe default of 1 unless a caller opts in (the CLI's own `--max-workers`, default 4).

    Returns `{"status": "COMPLETE" | "INTEGRITY_FAILED", "out_dir", "study_manifest_path",
    "study_manifest", "segment_results", "comparison_groups", "integrity"}`.
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    started_at = now or datetime.now(timezone.utc)

    # §2: fail fast, before anything else runs, if the run is invalid under the frozen prereg.
    config_hash_value = study_run.assert_frozen_config_hash(cfg)

    if bars_by_symbol is None:
        bars_by_symbol = _load_bars(symbols, kite_dir)
    input_file_hashes = _input_file_hashes(kite_dir)
    etf_symbols = universe_mod.load_etf_symbols(etf_list_path)

    benchmark_name = regime.FEATURE_CONFIG["market_benchmark"]
    benchmark_df = regime.load_index_history(benchmark_name)
    benchmark_path = context.index_history_path(benchmark_name)

    hb = hb_mod.Heartbeat(out_dir) if observe else None
    if hb is not None:
        hb.note("summarise_controls", summarise_controls)
        hb.note("columnar", columnar)
        hb.note("compress_events", compress_events)
        hb.note("random_control_seeds", len(random_control_seeds))
        hb.note("max_workers", max_workers)

    segment_kwargs = dict(
        cfg=cfg, cost_cfg=cost_cfg, etf_symbols=etf_symbols,
        exclusion_mask=regime_break_mask, segmenter=regime_segments, exclusion_mask_is_default=False,
        attach_context=True, input_file_hashes=input_file_hashes, now=started_at, max_workers=max_workers,
        compress_events=compress_events,
    )
    build_fns = {
        schema.SEGMENT_PRE_SEALED: study_run.build_pre_sealed_segment,
        schema.SEGMENT_POST_SEALED: study_run.build_post_sealed_segment,
    }

    segment_results: dict = {}
    comparison_groups: dict = {}
    for segment, build_fn in build_fns.items():
        if hb is not None:
            hb.stage(f"extraction {segment}")
        # Per-symbol extraction cache: the stage persists as it goes and a restart resumes, instead
        # of throwing away up to 3 h. Its own directory per segment, keyed inside by segment+config.
        seg_kwargs = dict(segment_kwargs)
        if checkpoint_dir is not None:
            seg_kwargs["extraction_cache_dir"] = Path(checkpoint_dir) / segment / "extract"
        if hb is not None:
            seg_kwargs["progress"] = lambda d, n, u="symbols": (hb.progress(d, n, u),
                                                                hb.check_resources())
        result = build_fn(bars_by_symbol, out_dir=out_dir / segment, **seg_kwargs)
        segment_results[segment] = result

        # §8 bullet 3, moved to the point each control row exists (v2 storage redesign). In the row
        # path the gate still runs in `_run_integrity_gate` over the retained rows; here it runs per
        # row at generation, so a summarised run keeps identical coverage. A sealed row raises
        # `SealedWindowError` out of generation, which is the same failure, earlier.
        control_row_check = (
            (lambda row: integrity.assert_no_sealed_rows_in_dataset([row])) if summarise_controls else None
        )
        if hb is not None:
            # Fail fast: a segment with no events or no families cannot produce a report, and
            # discovering that at hour 4 wastes the run. Recorded either way.
            fams = sorted({r["pattern_type"] for r in result["rows"]})
            hb.require(f"{segment}: events present", bool(result["rows"]),
                       f"{len(result['rows']):,} rows")
            hb.require(f"{segment}: families present", bool(fams), ", ".join(fams) or "none")
            hb.check_resources()

        groups = build_family_comparison_groups(
            result["rows"], result["bars_by_symbol"], cfg=cfg, cost_cfg=cost_cfg,
            random_seeds=random_control_seeds, atr_decile_seed=atr_decile_seed, benchmark_df=benchmark_df,
            max_workers=max_workers, summarise_controls=summarise_controls,
            control_row_check=control_row_check,
            columnar=columnar,
            checkpoint_dir=(None if checkpoint_dir is None else Path(checkpoint_dir) / segment),
            heartbeat=hb,
        )
        comparison_groups[segment] = groups

        symbols_for_manifest = sorted(result["bars_by_symbol"])
        for family, group in groups.items():
            _write_family_comparison_artifacts(
                out_dir / segment / "comparisons", family, segment, group,
                cfg=cfg, symbols=symbols_for_manifest, benchmark_path=benchmark_path,
                compress=compress_events,
            )

    if hb is not None:
        hb.stage("integrity gate")
    integrity_result = _run_integrity_gate(
        segment_results, comparison_groups, bars_by_symbol=bars_by_symbol, build_fns=build_fns,
        segment_kwargs=segment_kwargs, kill_switch=kill_switch,
        recompute_sample_size=recompute_sample_size, recompute_seed=recompute_seed,
        recompute_horizon=recompute_horizon, cfg=cfg, cost_cfg=cost_cfg,
    )

    prereg_sha = study_run.prereg_sha256()
    input_hashes_map = {h["path"]: h["sha256"] for h in input_file_hashes}
    status = "COMPLETE" if integrity_result["passed"] else "INTEGRITY_FAILED"

    if hb is not None:
        hb.stage("report")
    if integrity_result["passed"]:
        for segment, result in segment_results.items():
            rep = _build_segment_report(
                result, comparison_groups[segment], prereg_sha=prereg_sha, input_hashes=input_hashes_map,
                build_comparisons=(accumulate.summary_comparison_builder
                                   if (summarise_controls or columnar) else None),
            )
            safe = report.to_json_dict(rep)
            (out_dir / segment / "report.json").write_text(
                json.dumps(safe, sort_keys=True, indent=2, allow_nan=False) + "\n"
            )
            (out_dir / segment / "report.md").write_text(report.render_markdown(rep))
    else:
        _write_integrity_failed(out_dir, integrity_result)

    ended_at = datetime.now(timezone.utc)
    study_manifest = {
        "prereg_sha256": prereg_sha,
        "config_hash_check": {"passed": True, "config_hash": config_hash_value},
        "git_commit": _git_commit(),
        "run_started_at": started_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "run_ended_at": ended_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "symbols_requested": list(symbols) if symbols is not None else "ALL",
        "n_symbols_loaded": len(bars_by_symbol),
        "input_file_hashes": input_file_hashes,
        # Which output shape this run used. A reader must be able to tell a run that kept its
        # control rows from one that summarised them, without inspecting the directory tree.
        "control_output": {
            "mode": "summaries" if summarise_controls else "rows",
            "compressed": bool(compress_events),
            "columnar": bool(columnar),
            "summary_version": accumulate.SUMMARY_VERSION if summarise_controls else None,
            "random_control_seeds": len(random_control_seeds),
        },
        "segments": {
            segment: {
                "manifest_path": str(out_dir / segment / "manifest.json"),
                "row_count": len(result["rows"]),
                "families": sorted({r["pattern_type"] for r in result["rows"]}),
                "universe_included_count": len(result["universe"].included),
                "universe_excluded_count": len(result["universe"].excluded),
            }
            for segment, result in segment_results.items()
        },
        "integrity": integrity_result,
        "status": status,
    }
    (out_dir / "study_manifest.json").write_text(
        json.dumps(study_manifest, sort_keys=True, indent=2, default=str) + "\n"
    )

    # The finished run, off the host. gzip already made it small; this makes it durable and removes
    # the local-disk ceiling entirely. Deliberately AFTER the manifest is written, so what is
    # uploaded is the complete run. A failure raises -- an upload that quietly did not happen would
    # be worse than not offering the option.
    if upload_to:
        upload = remote_store.upload_run(out_dir, prefix=upload_to)
        verification = remote_store.verify_uploaded_run(upload)
        if not verification["passed"]:
            raise remote_store.RemoteStoreError(
                f"uploaded run failed verification: {verification['missing']} missing, "
                f"{verification['mismatched']} mismatched"
            )
        result_upload = {
            "uri": upload.uri, "n_objects": upload.n_objects, "bytes": upload.bytes_uploaded,
            "verified": verification,
        }
    else:
        result_upload = None

    return {
        "status": status,
        "out_dir": str(out_dir),
        "study_manifest_path": str(out_dir / "study_manifest.json"),
        "study_manifest": study_manifest,
        "segment_results": segment_results,
        "comparison_groups": comparison_groups,
        "integrity": integrity_result,
        "upload": result_upload,
    }


# ── CLI ───────────────────────────────────────────────────────────────────────────────────


def _parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Execute the CHARTING_PREREGISTRATION_V1 study end to end (§3-§8).",
    )
    parser.add_argument("--out", required=True, help="output directory for the study's artifacts")
    parser.add_argument(
        "--symbols", default=None,
        help="comma-separated symbol subset (omit for the full >=250-bar, non-ETF universe)",
    )
    parser.add_argument(
        "--max-workers", type=int, default=4,
        help="PERFORMANCE ONLY: parallel worker processes, by SYMBOL, for per-symbol event "
             "extraction, per-symbol context join, and per-symbol comparison-group pricing "
             "(PERF-PARALLEL; see execute_study's own docstring) -- default 4 (this machine's "
             "core count) for a real run; pass 1 for the fully serial path this file used "
             "before PERF-CONTROLS/PERF-PARALLEL. Output is byte-identical for any value.",
    )
    parser.add_argument(
        "--summarise-controls", action="store_true",
        help="write per-seed SUMMARIES for the comparison groups instead of their rows "
             "(study-v2 storage redesign). The reported numbers are identical -- proved by "
             "tests/test_study_accumulate.py -- but the ~6.4 TB random-control tree becomes a few MB.",
    )
    parser.add_argument(
        "--compress-events", action="store_true",
        help="write events.jsonl.gz instead of events.jsonl (measured 24.8x on real rows). The "
             "manifest's sha256 still hashes the UNCOMPRESSED bytes, so §8's kill switch is unaffected.",
    )
    parser.add_argument(
        "--upload-to", default=None, metavar="PREFIX",
        help=f"after the run completes, upload it to gs://{remote_store.DEFAULT_BUCKET}/<PREFIX>/<run dir name> "
             f"and verify every object by re-reading it (default prefix: {remote_store.DEFAULT_PREFIX}). "
             "Uses Application Default Credentials; no token is read or passed here.",
    )
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    """Never prints a metric -- only the run's status and output directory (module
    docstring, step 6): a hit rate/return/AUC/expectancy belongs in `report.json`/
    `report.md`, read deliberately, never in a CLI's stdout."""
    args = _parse_args(argv)
    symbols = [s.strip() for s in args.symbols.split(",") if s.strip()] if args.symbols else None
    result = execute_study(
        args.out, symbols=symbols, max_workers=args.max_workers,
        summarise_controls=args.summarise_controls, compress_events=args.compress_events,
        upload_to=args.upload_to,
    )
    out = {"status": result["status"], "out_dir": result["out_dir"]}
    if result.get("upload"):
        out["uploaded_to"] = result["upload"]["uri"]
        out["objects_uploaded"] = result["upload"]["n_objects"]
    print(json.dumps(out, indent=2))
    return 0 if result["status"] == "COMPLETE" else 1


if __name__ == "__main__":
    raise SystemExit(main())
