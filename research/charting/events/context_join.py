"""Context join -- CHARTING_PREREGISTRATION_V1 §6 "Context at t": "each event row gets a
`context` block from `regime.features_at(...)` (stock and NIFTY 500 trend class, N§12 regime,
RS 5/20/50/100, VIX, breadth) and a `research` block from `enrich.enrich_pattern(...)`
(research_state, breakout_threshold_pct/atr, breakout_volume_ratio), both evaluated at t with
bars ≤ t. Never mutate the pattern dict."

This module never edits `regime.py`/`enrich.py`/`patterns.py` -- it only calls their public
functions, the same "additive, read-only import" discipline `extraction.py` already uses for
`patterns.detect_as_of`/`replay.replay`. Every function here returns a NEW dict; the caller's
`row` (an `extraction.py`/`controls.py` event row) and `bars` are only ever read, matching the
non-mutation contract `enrich.py`'s own module docstring documents for `pattern_dict`.

-- Why this is a SEPARATE, opt-in module rather than wired straight into
   `extraction._build_event_row` / `controls._build_baseline_row` -----------------------------
`extraction.py`/`controls.py` already have ~30 passing tests asserting an EXACT top-level key
set on every row they build (`test_events_extraction.py::_EXPECTED_TOP_KEYS`,
`test_events_controls.py::_EXPECTED_KEYS`), and every one of those tests builds rows from tiny
synthetic fixtures with no real NIFTY 500 / India VIX / breadth history behind their (shifted,
often out-of-real-coverage) dates. Silently adding a `context`/`research` join inside the row
builders themselves would force every existing extraction/control test to also become a
regime/enrich/index-history test (real CSV I/O per call) and would risk turning a currently
fast, fully self-contained unit-test suite into one with a hidden dependency on
`research/index_history/data/*.csv` file coverage for whatever dates a fixture happens to
use. Instead, this module's `attach_to_event_row`/`attach_to_rows` are a SEPARATE, explicit
step a caller opts into -- exactly what `study/run.py` (the study driver) does when it builds
the full research dataset the prereg describes, and exactly what this module's own tests
exercise directly (synthetic `symbol_bars` + synthetic `benchmark_df`/`vix_df`/`breadth_df`,
matching `test_regime_market.py`'s own established convention of testing `regime.py` against
synthetic benchmark frames rather than the real committed index CSVs).

-- `research` is only ever built for a REAL pattern event row -------------------------------
`enrich.enrich_pattern` requires a CONFIRMED-population `PatternSnapshot.to_dict()` (it raises
`ValueError` without `status`/`pattern_id` -- see its own module docstring). A control row
(§7.6 comparison groups: random / buy-next-open / ATR-decile) has no pattern at all, so it
never gets a `research` block (`None`, not a fabricated one) -- `attach_to_event_row`'s
`pattern_dict=None` branch below.

-- Recovering the pattern_dict for a row extraction.py already built ------------------------
`extraction.py`'s own row (`_build_event_row`'s output) does not itself retain the
`PatternSnapshot` object it was built from (only the flat scalar fields extraction.py's row
schema needs). `pattern_dict_for_event` recovers it the SAME way `extraction.py`'s own module
docstring documents recovering `direction`/`levels`: "a second, PURE, deterministic call given
the same (bars, t, cfg, symbol), not a new source of look-ahead" -- calling
`patterns.detect_as_of` again at the row's own `confirmation_bar_index`, over the identical
point-in-time view, and picking out the matching `pattern_id`. This mirrors extraction.py's
own precedent exactly rather than inventing a second convention, and keeps `extraction.py`'s
own return shape (and its ~30 passing tests) completely untouched.
"""
from __future__ import annotations

import gc
import logging
import multiprocessing
from typing import Any, Mapping, Optional

import pandas as pd

from research.charting import enrich, patterns, regime
from research.charting.config import CONFIG


def _json_safe_scalar(v: Any) -> Any:
    """`regime.features_at`'s own output carries two raw `pd.Timestamp` values (`date`,
    `data_cutoff_date` -- see its own docstring/source) alongside every other field, which
    `flatten()` already reduces to a plain float/str/int/None. This package's rows are written
    to strict JSON by `events.writer` (`events.py` never edits `regime.py` to change its
    return shape), so every Timestamp is converted to an ISO date string HERE, at the join
    boundary -- generically, not by hardcoding the two known keys, so a future field added to
    `features_at` is safe by construction rather than by remembering to update this list."""
    if isinstance(v, pd.Timestamp):
        return v.date().isoformat()
    return v


def context_block_at(
    bars: pd.DataFrame, t: Any, *, symbol: Optional[str] = None,
    benchmark_df: Optional[pd.DataFrame] = None, vix_df: Optional[pd.DataFrame] = None,
    breadth_df: Optional[pd.DataFrame] = None,
) -> dict:
    """The prereg §6 "context" block: `regime.features_at(bars, t, ...)`. `bars` is handed to
    `features_at` WHOLE (never pre-truncated a second time here) -- `regime.py`'s own functions
    each do their own point-in-time windowing internally (`_window_check`/`_segment_of`, with
    the project-wide sealed-gap guard baked in), the same trust-the-callee convention
    `enrich.enrich_pattern` already documents for its own calls into `regime.trend_classification`.

    JSON-safe on return (see `_json_safe_scalar`): `features_at`'s own `date`/`data_cutoff_date`
    fields are raw `pd.Timestamp` objects, which strict JSON (this package's own `events.writer`)
    cannot serialise.
    """
    raw = regime.features_at(bars, t, symbol=symbol, benchmark_df=benchmark_df, vix_df=vix_df, breadth_df=breadth_df)
    return {k: _json_safe_scalar(v) for k, v in raw.items()}


def research_block_for(
    pattern_dict: dict, bars: pd.DataFrame, t: Any, *, benchmark_df: Optional[pd.DataFrame] = None,
) -> dict:
    """The prereg §6 "research" block: `enrich.enrich_pattern(pattern_dict, bars, t, ...)`.
    Only meaningful for a real pattern event (a CONFIRMED-population
    `PatternSnapshot.to_dict()`) -- see module docstring for why a control row never calls
    this."""
    return enrich.enrich_pattern(pattern_dict, bars, t, benchmark_df=benchmark_df)


def pattern_dict_for_event(bars: pd.DataFrame, event_row: dict, *, cfg: dict = CONFIG) -> Optional[dict]:
    """Recover the `PatternSnapshot.to_dict()` an `extraction.py` event row was built from --
    see module docstring. `None` if the pattern can no longer be found at that exact bar
    (should not happen for a row `extraction.extract_events` itself produced; defensive, never
    a guess, mirrors `extraction._build_event_row`'s own identical fallback)."""
    t_idx = event_row["confirmation_bar_index"]
    if t_idx < 0 or t_idx >= len(bars):
        return None
    view = bars.iloc[: t_idx + 1].reset_index(drop=True)
    snaps = patterns.detect_as_of(view, t_idx, cfg=cfg, symbol=event_row["symbol"])
    snap = next((s for s in snaps if s.pattern_id == event_row["pattern_id"]), None)
    return snap.to_dict() if snap is not None else None


def attach_to_event_row(
    row: dict, bars: pd.DataFrame, pattern_dict: Optional[dict], *,
    benchmark_df: Optional[pd.DataFrame] = None, vix_df: Optional[pd.DataFrame] = None,
    breadth_df: Optional[pd.DataFrame] = None,
) -> dict:
    """A NEW row (`row`/`bars`/`pattern_dict` only ever READ, never mutated) with `context` and
    `research` attached, both evaluated at the row's own `signal_date` (prereg §6 "at t" -- t
    is the pattern's confirmation bar, already a real bar date in `bars` by construction of
    `extraction.py`/`controls.py`). `research` is `None` when `pattern_dict` is `None` (a
    control row -- see module docstring); `context` is always attached, real pattern event or
    control alike (§6 says "each event row", and `regime.features_at` needs no pattern at all,
    only a (bars, t) pair, so a control row's own market/regime context is just as meaningful
    and just as computable as a real event's).
    """
    t = row["signal_date"]
    context = context_block_at(bars, t, symbol=row.get("symbol"), benchmark_df=benchmark_df, vix_df=vix_df, breadth_df=breadth_df)
    research = research_block_for(pattern_dict, bars, t, benchmark_df=benchmark_df) if pattern_dict is not None else None
    return {**row, "context": context, "research": research}


def attach_to_rows(
    triples, *, benchmark_df: Optional[pd.DataFrame] = None, vix_df: Optional[pd.DataFrame] = None,
    breadth_df: Optional[pd.DataFrame] = None,
) -> list[dict]:
    """Batch form of `attach_to_event_row` over an iterable of `(row, bars, pattern_dict)`
    triples. `benchmark_df`/`vix_df`/`breadth_df` are loaded ONCE (real committed CSVs, via
    `regime.load_index_history`/`regime.load_breadth_universe`) when not already supplied, and
    reused across every row -- matching `regime.features_at`'s own "a caller processing many
    (symbol, t) pairs should load each once" convention rather than re-reading the same files
    off disk per row.
    """
    if benchmark_df is None:
        benchmark_df = regime.load_index_history(regime.FEATURE_CONFIG["market_benchmark"])
    if vix_df is None:
        vix_df = regime.load_index_history("INDIA VIX")
    if breadth_df is None:
        breadth_df = regime.load_breadth_universe()
    return [
        attach_to_event_row(row, bars, pattern_dict, benchmark_df=benchmark_df, vix_df=vix_df, breadth_df=breadth_df)
        for row, bars, pattern_dict in triples
    ]


def attach_to_event_rows_for_symbol(
    rows: list, bars: pd.DataFrame, *, cfg: dict = CONFIG, benchmark_df: Optional[pd.DataFrame] = None,
    vix_df: Optional[pd.DataFrame] = None, breadth_df: Optional[pd.DataFrame] = None,
) -> list[dict]:
    """Convenience wrapper for the common case (`study/run.py`'s own usage): `rows` are ALL
    real pattern events for ONE symbol's `bars` (`extraction.extract_events(bars, symbol)`'s
    own output) -- `pattern_dict_for_event` is resolved per row automatically, then
    `attach_to_rows` is called once for the whole batch."""
    triples = [(row, bars, pattern_dict_for_event(bars, row, cfg=cfg)) for row in rows]
    return attach_to_rows(triples, benchmark_df=benchmark_df, vix_df=vix_df, breadth_df=breadth_df)


# ── PERF-PARALLEL: batching entry for many symbols at once ───────────────────────────────
#
# `study.run.build_segment`'s own `attach_context` step calls `attach_to_event_rows_for_symbol`
# once per symbol that has any pattern-event rows -- for a real, multi-thousand-symbol universe
# that is thousands of independent calls, each one (with no `benchmark_df`/`vix_df`/`breadth_df`
# supplied, `build_segment`'s own call site never passes them) re-reading the same three real
# CSVs off disk via `attach_to_rows`' own "load when not supplied" branch. Two symbols' own joins
# never read or write each other's rows/bars, so joining many symbols is embarrassingly parallel
# -- `attach_to_event_rows_by_symbol` below is the batched/parallel entry point: it loads
# `benchmark_df`/`vix_df`/`breadth_df` ONCE (deterministic, pure reads of static committed
# files -- reusing them across symbols changes no value) and then either loops in this process
# (`max_workers <= 1`, the default, IDENTICAL to calling `attach_to_event_rows_for_symbol` once
# per symbol with those three frames pinned) or dispatches one task per symbol across a forked
# process pool (`max_workers > 1`) -- same `fork` + module-global-context pattern as
# `events.pipeline`'s `_EXTRACT_CTX` / `events.controls`' `_PRICE_CTX`, so `bars_by_symbol` is
# inherited via copy-on-write rather than pickled through the task queue.


logger = logging.getLogger(__name__)

_JOIN_CTX: dict = {}


def _join_worker(symbol: str) -> tuple:
    """Runs inside a forked worker process (see the block above): `attach_to_event_rows_for_symbol`
    for one symbol, using the SAME already-loaded `benchmark_df`/`vix_df`/`breadth_df` (inherited
    via fork, never re-read from disk in the worker) -- returns `(symbol, enriched_rows)`."""
    ctx = _JOIN_CTX
    rows = ctx["rows_by_symbol"][symbol]
    bars = ctx["bars_by_symbol"][symbol]
    enriched = attach_to_event_rows_for_symbol(
        rows, bars, cfg=ctx["cfg"], benchmark_df=ctx["benchmark_df"], vix_df=ctx["vix_df"], breadth_df=ctx["breadth_df"],
    )
    return symbol, enriched


def attach_to_event_rows_by_symbol(
    rows_by_symbol: Mapping[str, list], bars_by_symbol: Mapping[str, pd.DataFrame], *, cfg: dict = CONFIG,
    benchmark_df: Optional[pd.DataFrame] = None, vix_df: Optional[pd.DataFrame] = None,
    breadth_df: Optional[pd.DataFrame] = None, max_workers: int = 1, consume: bool = False,
) -> dict:
    """`{symbol: enriched_rows}` for every symbol in `rows_by_symbol` (only symbols that HAVE
    rows -- a symbol absent from `rows_by_symbol` is never looked up in `bars_by_symbol` and
    never contributes an entry, matching the "if symbol_rows" skip `study.run.build_segment`'s
    own per-symbol loop used before this function existed). Each symbol's own rows are enriched
    via `attach_to_event_rows_for_symbol`, byte-identical to calling that function once per
    symbol directly -- see the "batching" block above for why sharing one already-loaded
    `benchmark_df`/`vix_df`/`breadth_df` across every symbol never changes a value.

    `max_workers` (PERFORMANCE ONLY, default 1 = serial): with `max_workers > 1`, symbols are
    dispatched one-per-task across a forked process pool instead of looped over in this process
    -- see the block above.
    """
    if benchmark_df is None:
        benchmark_df = regime.load_index_history(regime.FEATURE_CONFIG["market_benchmark"])
    if vix_df is None:
        vix_df = regime.load_index_history("INDIA VIX")
    if breadth_df is None:
        breadth_df = regime.load_breadth_universe()

    symbols = sorted(rows_by_symbol)
    if max_workers <= 1 or len(symbols) <= 1:
        return {
            symbol: attach_to_event_rows_for_symbol(
                rows_by_symbol[symbol], bars_by_symbol[symbol], cfg=cfg,
                benchmark_df=benchmark_df, vix_df=vix_df, breadth_df=breadth_df,
            )
            for symbol in symbols
        }

    # MEMORY (measured 2026-09-25, after two OOM kills at a 50 GB peak on a 62 GB host):
    #
    # The previous shape held every original row alive for the whole join and then materialised
    # every enriched row before returning, so both sets coexisted:
    #   * `_JOIN_CTX` kept `rows_by_symbol` in a MODULE GLOBAL until the `finally` -- a reference no
    #     caller could drop, which defeated dropping the caller's own references;
    #   * `pool.map` collected all results before `dict()` ran.
    #
    # Now the parent hands ownership over symbol by symbol (`pop`) and consumes results as they
    # arrive, so an original is freed once its enriched replacement exists. `consume=True` is opt-in
    # because it EMPTIES `rows_by_symbol`; callers that still need it pass the default.
    global _JOIN_CTX
    source = rows_by_symbol if consume else dict(rows_by_symbol)
    _JOIN_CTX = dict(
        rows_by_symbol=source, bars_by_symbol=bars_by_symbol, cfg=cfg,
        benchmark_df=benchmark_df, vix_df=vix_df, breadth_df=breadth_df,
    )
    results: dict = {}
    try:
        ctx = multiprocessing.get_context("fork")
        # Inherited objects are never collected in the children, and a GC pass would write to their
        # headers and copy-on-write the pages. Freezing before the fork keeps them shared.
        gc.freeze()
        try:
            with ctx.Pool(processes=min(max_workers, len(symbols))) as pool:
                done = 0
                for symbol, enriched in pool.imap_unordered(_join_worker, symbols, chunksize=1):
                    results[symbol] = enriched
                    if consume:
                        source.pop(symbol, None)     # the parent's copy of the originals goes here
                    done += 1
                    if done % 200 == 0:
                        gc.collect()
                        logger.debug("context join: %d/%d symbols enriched", done, len(symbols))
        finally:
            gc.unfreeze()
    finally:
        _JOIN_CTX = {}
    logger.info("context join: %d symbols enriched, %d rows",
                len(results), sum(len(v) for v in results.values()))
    return results


def attach_to_control_rows(
    rows: list, bars_by_symbol: dict, *, benchmark_df: Optional[pd.DataFrame] = None,
    vix_df: Optional[pd.DataFrame] = None, breadth_df: Optional[pd.DataFrame] = None,
) -> list[dict]:
    """Convenience wrapper for control rows (`controls.py`'s own output, any symbol mix): no
    `pattern_dict` for any of them (`research` stays `None` on every row -- see module
    docstring)."""
    triples = [(row, bars_by_symbol[row["symbol"]], None) for row in rows]
    return attach_to_rows(triples, benchmark_df=benchmark_df, vix_df=vix_df, breadth_df=breadth_df)
