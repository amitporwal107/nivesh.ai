"""Top-level orchestration for the historical pattern event dataset -- docs/charting.md S35.2
"Historical event dataset" and the task brief's own segment split: "The dataset is built
separately for the two development segments: pre-sealed (bars <= 2022-12-31) and post-sealed
(bars >= 2024-08-01, fresh history -- do not feed sealed bars as lookback)."

`build_event_dataset` is the entry point a caller should use rather than calling
`extraction.extract_events` directly per symbol, because it ALSO enforces the segment bound on
every symbol's bars frame before extraction runs at all (not merely relying on
`replay.replay`'s own sealed-window guard, which only refuses a window that OVERLAPS the sealed
block -- a frame that ends on, say, 2023-06-01 would pass that guard by itself while still
violating "the dataset is built separately for the two segments", since post-sealed rows must
never be built from a frame containing pre-sealed history as lookback either). This is this
module's OWN, additional guard, on top of (not instead of) `research_window`'s.
"""
from __future__ import annotations

import gc
import gzip
import hashlib
import json
import multiprocessing
import pickle
from datetime import datetime
from pathlib import Path
from typing import Optional, Sequence

import pandas as pd

from research.charting.config import CONFIG
from research.charting.events import costs_bridge, extraction, schema, writer
from research.charting.research_window import SealedWindowError


def assert_segment_bounds(bars: pd.DataFrame, segment: str, *, symbol: str = "UNKNOWN") -> None:
    """Raise `SealedWindowError` unless every bar in `bars` falls inside `segment`'s own bound
    (task item 6). `segment` must be one of `schema.SEGMENTS`."""
    if segment not in schema.SEGMENTS:
        raise ValueError(f"unknown segment {segment!r}; expected one of {schema.SEGMENTS}")
    if bars.empty:
        return
    min_d, max_d = pd.Timestamp(bars["date"].min()), pd.Timestamp(bars["date"].max())
    max_allowed = schema.SEGMENT_MAX_DATE.get(segment)
    min_allowed = schema.SEGMENT_MIN_DATE.get(segment)
    if max_allowed is not None and max_d > max_allowed:
        raise SealedWindowError(
            f"{symbol}: segment={segment!r} requires every bar <= {max_allowed.date()}, "
            f"but the frame's last bar is {max_d.date()}"
        )
    if min_allowed is not None and min_d < min_allowed:
        raise SealedWindowError(
            f"{symbol}: segment={segment!r} requires every bar >= {min_allowed.date()}, "
            f"but the frame's first bar is {min_d.date()}"
        )


# PERF-PARALLEL: forked-process-pool entry for the per-symbol extraction loop below.
#
# `extraction.extract_events` is called independently per symbol -- one symbol's replay/pattern
# walk never reads another symbol's bars -- so extracting symbols across a process pool is
# embarrassingly parallel. `multiprocessing.get_context("fork")` + a module-global context dict
# (`_EXTRACT_CTX`), set in the parent BEFORE the pool is created, so every forked worker inherits
# `bars_by_symbol` via ordinary copy-on-write memory rather than pickling it through the task
# queue -- only the lightweight `symbol` string per task is ever pickled (and that symbol's own
# extracted rows back) -- the same pattern `events.controls.price_signals` and
# `study.execute.build_family_comparison_groups`'s own (removed) per-family pool used.
_EXTRACT_CTX: dict = {}


def _extract_worker(symbol: str) -> tuple:
    """Runs inside a forked worker process (see the block above): the exact per-symbol body of
    the serial loop below (segment-bound guard, then `extraction.extract_events`) -- returns
    `(symbol, rows)`."""
    ctx = _EXTRACT_CTX
    bars = ctx["bars_by_symbol"][symbol]
    assert_segment_bounds(bars, ctx["segment"], symbol=symbol)
    return symbol, extraction.extract_events(bars, symbol, cfg=ctx["cfg"], cost_cfg=ctx["cost_cfg"])


def build_event_dataset(
    bars_by_symbol: dict, *, segment: str, cfg: dict = CONFIG,
    cost_cfg: Optional[costs_bridge.CostConfig] = None, out_dir=None, now: Optional[datetime] = None,
    max_workers: int = 1, cache_dir=None, progress=None,
) -> dict:
    """Extract events for every symbol in `bars_by_symbol` (sorted order), enforcing the S35
    segment bound per symbol BEFORE any extraction runs (so a single mis-scoped symbol's frame
    fails loudly rather than silently narrowing the run). Optionally writes the run via
    `writer.write_run` when `out_dir` is given. Returns
    `{"rows", "segment", "symbols", "manifest"}` ("manifest" is `None` when `out_dir` is `None`).

    `max_workers` (PERFORMANCE ONLY, default 1 = serial, byte-identical to this function's
    behaviour before the PERF-PARALLEL performance work -- see the block above `_EXTRACT_CTX`):
    with `max_workers > 1`, each symbol's `assert_segment_bounds` + `extraction.extract_events`
    runs in a forked worker process instead of this one, but `rows` is still assembled by
    iterating `sorted(bars_by_symbol)` and extending in that exact order -- identical row order,
    and (since a `SealedWindowError` from any symbol still propagates, just possibly from a
    worker instead of this process) identical failure behaviour for a mis-scoped symbol.
    """
    symbols = sorted(bars_by_symbol)

    if cache_dir is not None:
        rows = _extract_with_cache(
            bars_by_symbol, symbols, segment=segment, cfg=cfg, cost_cfg=cost_cfg,
            max_workers=max_workers, cache_dir=cache_dir, progress=progress,
        )
    elif max_workers <= 1 or len(symbols) <= 1:
        rows: list[dict] = []
        for symbol in symbols:
            bars = bars_by_symbol[symbol]
            assert_segment_bounds(bars, segment, symbol=symbol)
            rows.extend(extraction.extract_events(bars, symbol, cfg=cfg, cost_cfg=cost_cfg))
    else:
        global _EXTRACT_CTX
        _EXTRACT_CTX = dict(bars_by_symbol=bars_by_symbol, segment=segment, cfg=cfg, cost_cfg=cost_cfg)
        try:
            ctx = multiprocessing.get_context("fork")
            with ctx.Pool(processes=min(max_workers, len(symbols))) as pool:
                results = dict(pool.map(_extract_worker, symbols))
        finally:
            _EXTRACT_CTX = {}
        rows = []
        for symbol in symbols:
            rows.extend(results[symbol])

    manifest = None
    if out_dir is not None:
        cost_versions = {r["versioning"]["cost_rule_version"] for r in rows if r["versioning"]["cost_rule_version"]}
        tax_versions = {r["versioning"]["tax_rule_version"] for r in rows if r["versioning"]["tax_rule_version"]}
        manifest = writer.write_run(
            rows, out_dir, segment=segment, symbols=list(bars_by_symbol.keys()), cfg=cfg,
            cost_rule_versions=cost_versions, tax_rule_versions=tax_versions, now=now,
        )
    return {"rows": rows, "segment": segment, "symbols": sorted(bars_by_symbol), "manifest": manifest}


# ── per-symbol extraction cache (2026-09-25) ────────────────────────────────────────────────────
#
# Extraction is the longest stage of a study run (~3 h at full universe) and, before this, it
# persisted NOTHING until the whole segment finished: `pool.map` collected every symbol's rows in
# memory and the writer ran once at the end. Two consequences, both of which bit on 2026-09-24/25:
#
#   * an interruption -- two GCE reboots and one OOM kill in a few hours -- threw away every minute
#     of it, three times over;
#   * holding all rows plus all worker results at once is a large part of the memory that got the
#     run OOM-killed.
#
# Each symbol's rows are now written as they are produced and dropped from memory. A restart loads
# what is already on disk and extracts only the remainder, so the cost of an interruption is one
# symbol rather than the whole segment.
#
# Row ORDER is unchanged: rows are re-read in `sorted(bars_by_symbol)` order, which is the order the
# non-cached path assembles them in. That matters because `writer._dump_jsonl` preserves row order
# and the §8 kill switch compares the resulting bytes.

_CACHE_VERSION = "2"


def _cache_key(symbol: str, segment: str, cfg: dict) -> str:
    """A cached symbol is only reusable for the same segment AND the same config. Reusing rows
    across a config change would silently mix two engines' output in one dataset."""
    from research.charting.config import config_hash
    digest = hashlib.sha256(f"{_CACHE_VERSION}|{segment}|{config_hash(cfg)}|{symbol}".encode()).hexdigest()[:16]
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in symbol)
    return f"{safe}_{digest}.pkl.gz"


def _reclaim_if_over(threshold_fraction: float = 0.5) -> None:
    """Drop what the interpreter is holding once the run passes `threshold_fraction` of its cgroup
    budget. Cheap insurance: a gc pass costs milliseconds, an OOM kill costs hours."""
    try:
        with open("/sys/fs/cgroup/memory.current") as f:
            used = int(f.read().strip())
        with open("/sys/fs/cgroup/memory.max") as f:
            raw = f.read().strip()
        if raw == "max":
            return
        if used / int(raw) >= threshold_fraction:
            gc.collect()
    except (OSError, ValueError, ZeroDivisionError):
        return


def _extract_with_cache(bars_by_symbol: dict, symbols, *, segment: str, cfg: dict,
                        cost_cfg, max_workers: int, cache_dir, progress=None) -> list:
    cache = Path(cache_dir)
    cache.mkdir(parents=True, exist_ok=True)

    todo = [s for s in symbols if not (cache / _cache_key(s, segment, cfg)).is_file()]
    done_already = len(symbols) - len(todo)
    if progress is not None:
        progress(done_already, len(symbols), "symbols (resumed)" if done_already else "symbols")

    def _persist(symbol: str, sym_rows: list) -> None:
        # PICKLE, not JSON. A JSON round trip turns the INTEGER horizon keys of
        # `costs.by_horizon` / `targets[t].by_horizon` into strings, and
        # `report._horizon_cost_scenario` looks them up with an int -- so every lookup would miss
        # and the whole study would quietly compute empty statistics from a full dataset. Caught by
        # `test_the_cached_path_produces_identical_rows_to_the_uncached_one`. This cache is a
        # private, same-process artefact, so pickle's exact round trip is the right tool; the
        # published dataset is still JSONL via `writer.write_run`.
        path = cache / _cache_key(symbol, segment, cfg)
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_bytes(gzip.compress(pickle.dumps(sym_rows, protocol=pickle.HIGHEST_PROTOCOL), 6))
        tmp.replace(path)          # atomic: a half-written symbol is never resumed from

    if todo:
        if max_workers <= 1 or len(todo) <= 1:
            for i, symbol in enumerate(todo, 1):
                bars = bars_by_symbol[symbol]
                assert_segment_bounds(bars, segment, symbol=symbol)
                _persist(symbol, extraction.extract_events(bars, symbol, cfg=cfg, cost_cfg=cost_cfg))
                _reclaim_if_over()
                if progress is not None:
                    progress(done_already + i, len(symbols), "symbols")
        else:
            global _EXTRACT_CTX
            _EXTRACT_CTX = dict(bars_by_symbol=bars_by_symbol, segment=segment, cfg=cfg, cost_cfg=cost_cfg)
            try:
                ctx = multiprocessing.get_context("fork")
                with ctx.Pool(processes=min(max_workers, len(todo))) as pool:
                    # imap_unordered, NOT map: results are written and released one at a time
                    # instead of every symbol's rows being held until the last one lands.
                    for i, (symbol, sym_rows) in enumerate(
                            pool.imap_unordered(_extract_worker, todo, chunksize=1), 1):
                        _persist(symbol, sym_rows)
                        del sym_rows
                        _reclaim_if_over()
                        if progress is not None:
                            progress(done_already + i, len(symbols), "symbols")
            finally:
                _EXTRACT_CTX = {}

    rows: list = []
    for symbol in symbols:                       # sorted order -- identical to the non-cached path
        path = cache / _cache_key(symbol, segment, cfg)
        rows.extend(pickle.loads(gzip.decompress(path.read_bytes())))
        _reclaim_if_over()
    return rows
