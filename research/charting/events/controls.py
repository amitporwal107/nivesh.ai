"""Comparison-group hooks -- docs/charting.md S18.3 "Required comparison groups" and the
CHARTING_PREREGISTRATION_V1 S7.6 study spec: a fixed-seed random-selection control from the
same eligible universe/dates (S7.6.ii, run as a 200-seed batch), a buy-at-next-open baseline
(S7.6.iii), and an ATR-decile-matched control (S7.6.iv).

All three produce rows in the SAME nested shape `extraction.py` produces (`entry` / `outcomes`
/ `outcomes_alt_close_entry` / `liquidity` / `costs`, via the identical
`extraction.build_outcome_cost_block` helper), so a downstream comparison never has to
reconcile two different row shapes -- only `pattern_type`/`pattern_id`/`direction` differ.

Per the task brief, this module is INFRASTRUCTURE ONLY -- "Build and test them; do not run
them for results." Nothing here is ever invoked over real bars in this session; see
`research/charting/tests/test_events_controls.py` (synthetic fixtures only) and
`pipeline.py`, which never calls these functions.

-- ATR-decile-matched control (S7.6.iv) -----------------------------------------------------
"draw control rows from the same universe on the same signal date whose ATR%(t) is in the
same decile as the event's (deciles computed per date across the eligible universe from data
<= t only), seeded and reproducible; same row schema and stop rule as the other controls
(Layer-2 ATR stop)."

`ATR%(t)` here is `ATR(cfg["atr_period"]) / close`, evaluated with the SAME point-in-time
discipline every other ATR reading in this package uses (`bars.iloc[:idx+1]` only -- see
`_atr_pct_at`). Deciles are computed FRESH for each (event, its own signal date) pair, over
whichever (symbol, bar_index) rows in the caller's own `eligible` population share that exact
date -- never a single global cross-sectional decile table reused across dates (a decile
computed on 2021-03-01 from 2021-03-01's own eligible population has no business ranking a
2022-11-04 event). The event's own (symbol, bar_index) always participates in the population
its own decile is computed from (it IS one of that date's eligible signals), then is EXCLUDED
from the pool of CANDIDATES a control may be drawn from (a pattern is never its own control).
Determinism: the RNG for one event is seeded from `(seed, event_id)` via a SHA-256 digest
(not Python's own tuple-seeding, which is not a documented stable contract across
implementations) -- reproducible for the same `(seed, event_id)` pair regardless of what
order events/eligible rows are supplied in, and regardless of `eligible`'s own input order
(the candidate pool is sorted before sampling, same discipline as `random_control_rows`).
"""
from __future__ import annotations

import hashlib
import multiprocessing
import random
from typing import Mapping, Optional, Sequence

import numpy as np
import pandas as pd

from research.charting.config import CONFIG, ENGINE_VERSION, PROFILE_NAME, config_hash
from research.charting.events import costs_bridge, schema
from research.charting.events.extraction import build_outcome_cost_block
from research.charting.series import atr as atr_series_fn

RANDOM_CONTROL_PATTERN_TYPE = "RANDOM_CONTROL"
BUY_NEXT_OPEN_BASELINE_PATTERN_TYPE = "BUY_NEXT_OPEN_BASELINE"
ATR_DECILE_CONTROL_PATTERN_TYPE = "ATR_DECILE_CONTROL"

# S7.6.ii: "a random selection from the same eligible universe and dates, 200 seeds."
RANDOM_CONTROL_SEED_COUNT = 200
RANDOM_CONTROL_SEEDS: tuple = tuple(range(RANDOM_CONTROL_SEED_COUNT))
# Both baselines are long-only "if you had simply bought" comparisons (the S18.3 wording
# itself: "Random selection from the same eligible universe", "Buy-at-next-open baseline" --
# neither implies a short leg), so `direction="BULLISH"` for every row either produces.
_BASELINE_DIRECTION = "BULLISH"


def _iso(bars: pd.DataFrame, idx: int) -> str:
    return schema.iso_date(bars["date"].iloc[idx])


# ── PERFORMANCE ONLY: cross-seed / cross-family / cross-control-type memoization ────────────
#
# `docs/ai_research/CHARTING_PREREGISTRATION_V1.md` §7.6.ii asks for the random control as a
# 200-SEED batch, and `study.execute.build_family_comparison_groups` builds all three control
# families (random / ATR-decile / buy-next-open) for every pattern family in a segment from the
# SAME `bars_by_symbol` and the SAME `eligible` population. Profiling this module's own
# `random_control_batch` (cProfile, 5 real symbols x 5 seeds, PERF-CONTROLS package) found two
# large, purely-mechanical costs, both eliminated here WITHOUT changing a single output field:
#
#   1. `series.atr` was re-sliced (`bars.iloc[:idx+1]`) and recomputed FROM SCRATCH for every
#      row, even though `series.atr` is purely causal -- its Wilder recursion at index i only
#      ever reads index <= i (see series.py's own module docstring / `_wilder_smoothing`'s own
#      "no negative indexing, so it cannot wrap" guarantee). So `atr_series_fn(bars)[idx]` and
#      the old `atr_series_fn(bars.iloc[:idx+1])[idx]` are the SAME computation on the SAME
#      elements -- `_atr_series_for_symbol` below computes the FULL series once per symbol and
#      caches it, turning an O(bar_index) recompute into an O(1) lookup, never changing a value.
#   2. A baseline row's own "priced" fields (`atr_at_t` + everything `build_outcome_cost_block`
#      returns) depend ONLY on `(symbol, bar_index, cfg, cost_cfg)` -- NEVER on which control
#      family/type/seed/source-event drew this particular (symbol, bar_index) pick. Verified
#      directly below: `_build_baseline_row` calls `build_outcome_cost_block` with
#      `pattern_type=None, levels=None, level_broken_value=None` on EVERY call site (random
#      control, ATR-decile control, buy-next-open baseline all go through this one function), so
#      two rows built for the same (symbol, bar_index) are byte-identical in every field this
#      cache stores. `_priced_signal_fields` memoizes that computation by `(symbol, bar_index)`.
#
# `ControlPriceCache` bundles both caches. A fresh, empty instance is created locally whenever a
# caller does not supply one (every public function below defaults `cache=None`), so a caller
# that builds one control group in isolation -- e.g. this module's own tests, including the
# poisoned-future probes that intentionally build TWO DIFFERENT `bars_by_symbol` dicts reusing
# the SAME symbol strings -- sees no behaviour change at all: nothing is shared across separate
# top-level calls unless the caller explicitly passes the SAME `ControlPriceCache` instance in.
# `study.execute.build_family_comparison_groups` does exactly that: one `ControlPriceCache` per
# segment, passed to every family's every control-group call, since all of them share the SAME
# `bars_by_symbol` object for that segment (the one invariant that makes a `symbol`-string-keyed
# cache safe: it must never be reused across two DIFFERENT `bars_by_symbol` dicts that happen to
# share a symbol name -- see `ControlPriceCache`'s own docstring).
class ControlPriceCache:
    """Per-run memoization for baseline control-row construction. Two independent caches, both
    keyed by the plain `symbol` string (safe ONLY when every call sharing one instance also
    shares the same `bars_by_symbol` object for that symbol -- see module docstring above):

      - `atr_by_symbol`: symbol -> the full-length `series.atr(cfg["atr_period"])` Series for
        that symbol's bars.
      - `priced_signal`: (symbol, bar_index) -> the `atr_at_t` field plus every key
        `build_outcome_cost_block` returns, for that (symbol, bar_index) BULLISH baseline
        signal.

    Both caches carry NO `cfg`/`cost_cfg` in their key, so an instance is only safe to share
    across calls that also all pass the SAME `cfg` and the SAME `cost_cfg` -- true for every
    caller in this codebase today (`random_control_batch` shares one cache across its own 200
    seeds under one `cfg`/`cost_cfg`; `study.execute.build_family_comparison_groups` shares one
    cache across every family in a segment under that segment's single `cfg`/`cost_cfg`). A
    future caller that reuses ONE `ControlPriceCache` across two DIFFERENT `cfg`/`cost_cfg`
    values would silently get stale results -- never do that; construct a fresh
    `ControlPriceCache` per distinct `(cfg, cost_cfg)` instead.

    Never mutated by anything except `_atr_series_for_symbol` / `_atr_pct_at_cached` /
    `_priced_signal_fields` below.
    """

    __slots__ = ("atr_by_symbol", "priced_signal")

    def __init__(self) -> None:
        self.atr_by_symbol: dict = {}
        self.priced_signal: dict = {}


def _atr_series_for_symbol(bars: pd.DataFrame, symbol: str, cfg: dict, cache: ControlPriceCache) -> pd.Series:
    """The full-length `series.atr(cfg["atr_period"])` Series for `symbol`'s `bars`, computed
    once and memoized in `cache.atr_by_symbol` -- see the "PERFORMANCE ONLY" block above for why
    this is byte-identical to the old per-row slice-and-recompute. `bars` must be `symbol`'s own
    frame every time this cache is shared across calls (see `ControlPriceCache`'s docstring)."""
    series = cache.atr_by_symbol.get(symbol)
    if series is None:
        series = atr_series_fn(bars, period=cfg["atr_period"])
        cache.atr_by_symbol[symbol] = series
    return series


def _atr_pct_at_cached(bars_by_symbol: dict, symbol: str, idx: int, cfg: dict, cache: ControlPriceCache) -> Optional[float]:
    """The exact same value/contract as `_atr_pct_at(bars_by_symbol[symbol], idx, cfg)` (`None`
    on warmup or a non-finite/non-positive close), read from the cached full-length ATR series
    instead of re-slicing and recomputing on every call. Kept as a SEPARATE function from
    `_atr_pct_at` (never called by it, never calls it) rather than adding an optional cache
    parameter there, so `_atr_pct_at`'s own tested direct-call contract
    (`test_atr_pct_at_only_reads_bars_up_to_and_including_idx` et al., which call it with no
    cache argument at all) is untouched by this performance work."""
    bars = bars_by_symbol[symbol]
    if idx < 0 or idx >= len(bars):
        return None
    atr_val = _atr_series_for_symbol(bars, symbol, cfg, cache).iloc[idx]
    close_val = float(bars["close"].iloc[idx])
    if pd.isna(atr_val) or not np.isfinite(close_val) or close_val <= 0:
        return None
    return float(atr_val) / close_val


def _priced_signal_fields(bars: pd.DataFrame, symbol: str, t_idx: int, cfg: dict,
                           cost_cfg: Optional[costs_bridge.CostConfig], cache: ControlPriceCache,
                           with_targets: bool = True) -> dict:
    """`{"atr_at_t": ..., **build_outcome_cost_block(...)}` for one (symbol, bar_index) BULLISH
    baseline signal -- memoized in `cache.priced_signal` by `(symbol, t_idx)` (see the
    "PERFORMANCE ONLY" block above for why this is safe to share across every control
    family/type/seed/source-event)."""
    # The cache key carries `with_targets`: a lean row and a full row for the same (symbol, bar)
    # are different objects, and returning one where the other was asked for would either lose the
    # target blocks or silently undo the speedup.
    key = (symbol, t_idx, with_targets)
    cached = cache.priced_signal.get(key)
    if cached is not None:
        return cached
    atr_val = _atr_series_for_symbol(bars, symbol, cfg, cache).iloc[t_idx]
    atr_at_t = float(atr_val) if pd.notna(atr_val) else None
    result = {"atr_at_t": atr_at_t}
    result.update(build_outcome_cost_block(
        bars, t_idx, _BASELINE_DIRECTION, cfg=cfg, cost_cfg=cost_cfg, atr_at_t=atr_at_t,
        with_targets=with_targets,
    ))  # pattern_type/levels/level_broken_value default to None -- Layer 2 ATR stop only (item 7)
    cache.priced_signal[key] = result
    return result


def _assemble_priced_baseline_row(
    bars: pd.DataFrame, symbol: str, t_idx: int, priced: Mapping, *, pattern_type: str, pattern_id: str,
    cfg: dict, source_event_id: Optional[str] = None,
) -> dict:
    """One baseline row, built from an ALREADY-PRICED `(symbol, t_idx)` result (`priced` --
    `_priced_signal_fields`'s own return shape, e.g. `price_signals()[(symbol, t_idx)]`) --
    the ASSEMBLE half of the "draw/price/assemble" split (module docstring: `random_control_draws`
    / `atr_decile_control_draws` / `buy_next_open_baseline_draws` are the DRAW half, `price_signals`
    is the PRICE half). Field-for-field identical to `_build_baseline_row`'s own row shape --
    `_build_baseline_row` below is now a thin wrapper over this function plus a single-pair
    `_priced_signal_fields` lookup, so there is exactly one place this row shape is assembled,
    not two that could silently drift apart.
    """
    atr_at_t = priced["atr_at_t"]
    row: dict = {
        # `pattern_id` (built by the caller) already carries the "{symbol}:{pattern_type}:..."
        # prefix -- do not prepend `symbol` again.
        "event_id": f"{pattern_id}:{_iso(bars, t_idx)}",
        "symbol": symbol,
        "pattern_id": pattern_id,
        "pattern_type": pattern_type,
        "direction": _BASELINE_DIRECTION,
        "signal_date": _iso(bars, t_idx),
        "confirmation_bar_index": t_idx,
        "level_broken": None,
        "level_broken_field": None,
        "atr_at_t": atr_at_t,
        "relative_volume_at_t": None,
        "config_hash": config_hash(cfg),
        "engine_version": ENGINE_VERSION,
        "profile": PROFILE_NAME,
        "dataset_version": schema.EVENTS_SCHEMA_VERSION,
        "source_event_id": source_event_id,
        "versioning": {
            "signal_timestamp": _iso(bars, t_idx),
            "data_cutoff_timestamp": _iso(bars, t_idx),
            "config_hash": config_hash(cfg),
            "engine_version": ENGINE_VERSION,
            "cost_rule_version": None,
            "tax_rule_version": None,
            "slippage_model_version": None,
            "dataset_version": schema.EVENTS_SCHEMA_VERSION,
        },
    }
    row.update({k: v for k, v in priced.items() if k != "atr_at_t"})
    costs_by_horizon = (row.get("costs") or {}).get("by_horizon") or {}
    resolved = next((b for b in costs_by_horizon.values() if b.get("available")), None)
    if resolved is not None:
        row["versioning"]["cost_rule_version"] = resolved.get("cost_rule_version")
        row["versioning"]["tax_rule_version"] = resolved.get("tax_rule_version")
    return row


def _build_baseline_row(
    bars: pd.DataFrame, symbol: str, t_idx: int, *, pattern_type: str, pattern_id: str, cfg: dict,
    cost_cfg: Optional[costs_bridge.CostConfig], source_event_id: Optional[str] = None,
    cache: Optional[ControlPriceCache] = None,
) -> dict:
    # A control has no pattern -- no "broken level" and no Layer 1 structural stop -- but §37
    # task item 7 ("the random-selection and buy-at-next-open controls need a stop: use the
    # Layer 2 ATR stop for them") still needs a real ATR(cfg["atr_period"]) reading at t_idx
    # (surfaced at the row's own top-level `atr_at_t` field too), computed via
    # `_priced_signal_fields` -- point-in-time identical to the original per-row
    # `bars.iloc[:idx+1]` slice-and-recompute (see the "PERFORMANCE ONLY" block above), just
    # memoized across every caller that shares this `cache`.
    cache = cache if cache is not None else ControlPriceCache()
    priced = _priced_signal_fields(bars, symbol, t_idx, cfg, cost_cfg, cache)
    return _assemble_priced_baseline_row(
        bars, symbol, t_idx, priced, pattern_type=pattern_type, pattern_id=pattern_id, cfg=cfg,
        source_event_id=source_event_id,
    )


def random_control_rows(
    bars_by_symbol: dict, eligible: Sequence[tuple], *, n: int, seed: int, cfg: dict = CONFIG,
    cost_cfg: Optional[costs_bridge.CostConfig] = None, cache: Optional[ControlPriceCache] = None,
) -> list[dict]:
    """A fixed-seed random draw of `n` (symbol, bar_index) pairs from `eligible` -- the SAME
    eligible universe/dates population the caller has already screened (this module does not
    itself define "eligible"; S18.3 says "from the same eligible universe", which is the
    caller's own screen, e.g. a real pattern-event population's own dates/symbols). Each pick
    produces a row via the identical entry/outcome/cost pipeline real events use.

    Deterministic: `random.Random(seed)` and a stable sort of `eligible` BEFORE sampling, so the
    same call reproduces byte-identical output regardless of `eligible`'s own input order.

    `cache` (PERFORMANCE ONLY, see the block above `ControlPriceCache`): an optional shared
    `ControlPriceCache`, e.g. passed by `random_control_batch` across its own 200 seeds, or by
    `study.execute.build_family_comparison_groups` across every family/control-type in a
    segment. Defaults to a fresh, call-local cache -- output is identical either way.
    """
    ordered = sorted(set(eligible))
    rng = random.Random(seed)
    picks = rng.sample(ordered, k=min(n, len(ordered)))
    cache = cache if cache is not None else ControlPriceCache()
    rows = []
    for symbol, idx in sorted(picks):
        bars = bars_by_symbol[symbol]
        pattern_id = f"{symbol}:{RANDOM_CONTROL_PATTERN_TYPE}:{_iso(bars, idx)}"
        rows.append(_build_baseline_row(
            bars, symbol, idx, pattern_type=RANDOM_CONTROL_PATTERN_TYPE, pattern_id=pattern_id,
            cfg=cfg, cost_cfg=cost_cfg, cache=cache,
        ))
    return rows


def buy_next_open_baseline_rows(
    bars_by_symbol: dict, events: Sequence[dict], *, cfg: dict = CONFIG,
    cost_cfg: Optional[costs_bridge.CostConfig] = None, cache: Optional[ControlPriceCache] = None,
) -> list[dict]:
    """One baseline row per pattern EVENT (`extraction.extract_events`'s own output rows), at
    the identical (symbol, confirmation_bar_index) -- "if you had simply bought the next open on
    every date a pattern confirmed, regardless of the pattern's own BULLISH/BEARISH call".

    `cache`: see `random_control_rows`' own docstring -- PERFORMANCE ONLY, defaults to a fresh
    call-local `ControlPriceCache` when not given.
    """
    cache = cache if cache is not None else ControlPriceCache()
    rows = []
    for ev in events:
        symbol = ev["symbol"]
        idx = ev["confirmation_bar_index"]
        bars = bars_by_symbol[symbol]
        pattern_id = f"{ev['pattern_id']}:BASELINE"
        rows.append(_build_baseline_row(
            bars, symbol, idx, pattern_type=BUY_NEXT_OPEN_BASELINE_PATTERN_TYPE, pattern_id=pattern_id,
            cfg=cfg, cost_cfg=cost_cfg, source_event_id=ev["event_id"], cache=cache,
        ))
    return rows


# ── ATR-decile-matched control (§7.6.iv) ─────────────────────────────────────────────────


def _atr_pct_at(bars: pd.DataFrame, idx: int, cfg: dict = CONFIG) -> Optional[float]:
    """ATR(cfg["atr_period"]) / close at bar `idx`, using only `bars.iloc[:idx+1]` (the same
    "view up to and including idx" discipline every other ATR reading in this package uses).
    `None` when ATR is still in warmup or `close` is non-positive/non-finite -- never a
    fabricated ratio."""
    if idx < 0 or idx >= len(bars):
        return None
    view = bars.iloc[: idx + 1].reset_index(drop=True)
    atr_val = atr_series_fn(view, period=cfg["atr_period"]).iloc[idx]
    close_val = float(bars["close"].iloc[idx])
    if pd.isna(atr_val) or not np.isfinite(close_val) or close_val <= 0:
        return None
    return float(atr_val) / close_val


def _decile_indices(values: np.ndarray, n_deciles: int = 10) -> np.ndarray:
    """0-based decile index (0..n_deciles-1) for every value in `values`, from `values`' OWN
    `n_deciles - 1` internal quantile boundaries (10th/20th/.../90th percentile for the
    default decile case) -- plain `numpy.quantile` + `searchsorted`, not `pandas.qcut` (qcut's
    duplicate-edge handling is unpredictable for a small or degenerate same-value
    cross-section, which a single calendar date's eligible population often is). A boundary
    value falls into the LOWER bucket (`side="right"`), matching `numpy.digitize`'s own
    right-inclusive convention for an ascending, non-decreasing edge array."""
    if len(values) == 0:
        return np.array([], dtype=int)
    edges = np.quantile(values, [i / n_deciles for i in range(1, n_deciles)])
    return np.searchsorted(edges, values, side="right")


def _seeded_rng(seed: int, key: str) -> random.Random:
    """A `random.Random` deterministically seeded from `(seed, key)` via a SHA-256 digest --
    NOT Python's own `random.Random((seed, key))` tuple-seeding, whose exact algorithm for
    non-int/str/bytes seeds is a CPython implementation detail, not a documented stable
    contract (see `random.seed`'s own docs)."""
    digest = hashlib.sha256(f"{seed}:{key}".encode("utf-8")).hexdigest()
    return random.Random(int(digest[:16], 16))


def atr_decile_control_rows(
    bars_by_symbol: dict, events: Sequence[dict], eligible: Sequence[tuple], *, seed: int,
    n_per_event: int = 1, n_deciles: int = 10, cfg: dict = CONFIG,
    cost_cfg: Optional[costs_bridge.CostConfig] = None, cache: Optional[ControlPriceCache] = None,
) -> list[dict]:
    """The §7.6.iv ATR-decile-matched control: for each row in `events` (real pattern event
    rows, `extraction.extract_events`' own output shape -- needs `event_id`/`symbol`/
    `confirmation_bar_index`/`signal_date`/`pattern_id`), draw `n_per_event` control(s) from
    `eligible` (the SAME (symbol, bar_index) population shape `random_control_rows` takes --
    the caller's own already-screened eligible universe/dates) whose ATR%(t) falls in the same
    decile as the event's, computed ONLY from the subset of `eligible` sharing the event's own
    `signal_date` (see module docstring).

    An event is silently SKIPPED (no row fabricated, no exception) when: its own ATR%(t) could
    not be computed, or fewer than 2 total (symbol, bar_index) pairs share its signal date
    (nothing to rank against), or its own decile bucket has no OTHER candidate once the event
    itself is excluded. This mirrors `random_control_rows`' own "capped at population size"
    honesty (never over-draws, never fabricates) rather than raising for a data-sparse date --
    a caller building a full dataset should check `len(...)` against `len(events)` itself, the
    same shortfall-visibility convention `errors`-as-silence already avoids elsewhere in this
    package (e.g. `extraction.extract_events`' own defensive `continue`, never a swallowed
    row).

    `cache`: see `random_control_rows`' own docstring -- PERFORMANCE ONLY, defaults to a fresh
    call-local `ControlPriceCache` when not given. Also used (via `_atr_pct_at_cached`, never
    `_atr_pct_at` itself) for the decile-ranking ATR%(t) scan below, not only for pricing the
    drawn control rows.
    """
    cache = cache if cache is not None else ControlPriceCache()
    by_date: dict = {}
    for symbol, idx in sorted(set(eligible)):
        bars = bars_by_symbol[symbol]
        if idx < 0 or idx >= len(bars):
            continue
        d = _iso(bars, idx)
        by_date.setdefault(d, []).append((symbol, idx))

    rows: list[dict] = []
    for ev in sorted(events, key=lambda e: e["event_id"]):
        symbol, idx, date_iso = ev["symbol"], ev["confirmation_bar_index"], ev["signal_date"]
        pool = sorted(set(by_date.get(date_iso, ())) | {(symbol, idx)})

        atr_pcts: dict = {}
        for s, i in pool:
            v = _atr_pct_at_cached(bars_by_symbol, s, i, cfg, cache)
            if v is not None:
                atr_pcts[(s, i)] = v
        if (symbol, idx) not in atr_pcts or len(atr_pcts) < 2:
            continue  # no ATR%(t) for the event itself, or nothing to rank it against

        keys = sorted(atr_pcts)  # deterministic order, independent of `eligible`'s own order
        values = np.array([atr_pcts[k] for k in keys])
        deciles = _decile_indices(values, n_deciles)
        event_decile = deciles[keys.index((symbol, idx))]
        candidates = [k for j, k in enumerate(keys) if deciles[j] == event_decile and k != (symbol, idx)]
        if not candidates:
            continue

        rng = _seeded_rng(seed, ev["event_id"])
        picks = sorted(rng.sample(candidates, k=min(n_per_event, len(candidates))))
        for cs, ci in picks:
            bars = bars_by_symbol[cs]
            pattern_id = f"{cs}:{ATR_DECILE_CONTROL_PATTERN_TYPE}:{_iso(bars, ci)}:for:{ev['pattern_id']}"
            rows.append(_build_baseline_row(
                bars, cs, ci, pattern_type=ATR_DECILE_CONTROL_PATTERN_TYPE, pattern_id=pattern_id,
                cfg=cfg, cost_cfg=cost_cfg, source_event_id=ev["event_id"], cache=cache,
            ))
    return rows


# ── Random-control 200-seed batch (§7.6.ii) ──────────────────────────────────────────────


def random_control_batch(
    bars_by_symbol: dict, eligible: Sequence[tuple], *, n: int, seeds: Sequence[int] = RANDOM_CONTROL_SEEDS,
    cfg: dict = CONFIG, cost_cfg: Optional[costs_bridge.CostConfig] = None,
    cache: Optional[ControlPriceCache] = None,
) -> dict:
    """§7.6.ii: "a random selection from the same eligible universe and dates, 200 seeds" --
    one independent `random_control_rows` draw per seed (default the pre-registered
    `RANDOM_CONTROL_SEEDS`, 0..199). Returns `{seed: rows}`, never flattened/merged: the
    study report's own requirement ("the pattern rows' percentile within the random ...
    distribution", prereg §7.6) needs the PER-SEED population of outcomes (200 independent
    draws), not one pooled 200x-n sample.

    `cache` (PERFORMANCE ONLY): one `ControlPriceCache`, created here when not given, shared
    across EVERY seed's draw -- the 200 seeds sample from the SAME `eligible` population, so the
    same (symbol, bar_index) pick recurs across seeds; the recurring pick's priced fields are
    computed once and reused (see `ControlPriceCache`'s own docstring for why this never changes
    a row's content). Passing a `cache` already used for other families/control-types in the
    same segment (as `study.execute.build_family_comparison_groups` does) extends that reuse
    further still, with no further change to what any of them return.
    """
    cache = cache if cache is not None else ControlPriceCache()
    return {seed: random_control_rows(bars_by_symbol, eligible, n=n, seed=seed, cfg=cfg, cost_cfg=cost_cfg, cache=cache)
            for seed in seeds}


# ── PERF-PARALLEL: draw / price / assemble split ──────────────────────────────────────────
#
# `study.execute.build_family_comparison_groups` builds THREE control groups (random-batch,
# ATR-decile, buy-next-open) for EVERY pattern family in a segment, from the SAME `bars_by_symbol`
# and the SAME `eligible` population -- and the 200-seed random batch alone draws from that same
# population 200 times. Profiling (PERF-PARALLEL, real 8-symbol subset) confirms the earlier
# PERF-CONTROLS finding still holds at symbol scale: almost all of this module's own cost is
# `_priced_signal_fields` (the full `build_outcome_cost_block` -- stops, targets, per-horizon
# costs) for whichever (symbol, bar_index) pairs actually get drawn; WHICH pairs get drawn (the
# RNG sampling itself, and the ATR%(t) decile ranking that picks a matched candidate) is cheap by
# comparison -- pure index selection plus a cached-ATR-series lookup, no cost engine involved.
#
# So the three functions below (`random_control_draws`, `atr_decile_control_draws`,
# `buy_next_open_baseline_draws`) are the DRAW half: for a given seed/event, WHICH (symbol,
# bar_index) pairs would be priced -- computed serially, deterministically, exactly reproducing
# the picks `random_control_rows`/`atr_decile_control_rows`/`buy_next_open_baseline_rows` already
# make (same RNG, same seeding, same candidate pools), just without ever calling
# `_priced_signal_fields`. `price_signals` is the PRICE half: given the UNION of every (symbol,
# bar_index) pair any draw (across every control type, AND every family in the segment -- the
# caller's choice, this function only sees whatever `pairs` it is handed) actually needs priced,
# it prices each pair EXACTLY ONCE (`_priced_signal_fields`, byte-identical output to the cached
# single-process path) and, when `max_workers > 1`, does so across a forked process pool grouped
# BY SYMBOL -- every pair for a given symbol always goes to the SAME task, so a worker computes
# that symbol's full-length ATR series once and reuses it for every pair it owns (never split
# across workers, so the per-symbol ATR-series win is never lost, unlike the old per-FAMILY
# worker split this replaces, which forced every worker to duplicate every symbol's ATR series).
# The three `assemble_*` functions are the ASSEMBLE half: given a draw result and `price_signals`'
# own output, build the exact same rows `random_control_batch`/`atr_decile_control_rows`/
# `buy_next_open_baseline_rows` would -- pure dict lookups + `_assemble_priced_baseline_row`, no
# further computation, always run serially (cheap enough that parallelising it would only add
# overhead).
#
# `multiprocessing.get_context("fork")` + a module-global context dict (`_PRICE_CTX`), set in the
# parent BEFORE the pool is created so every forked worker inherits `bars_by_symbol` via ordinary
# copy-on-write memory rather than pickling it through the task queue -- the same pattern
# `study.execute.build_family_comparison_groups`'s own (now-removed) per-family pool used.


def _random_control_picks(eligible: Sequence[tuple], *, n: int, seed: int) -> list:
    """The exact `sorted(picks)` list `random_control_rows` draws for one seed -- factored out
    so the DRAW can run standalone from pricing (see the "draw / price / assemble split" block
    above). No `bars`/`cfg`/`cost_cfg` at all: a pure (symbol, bar_index) selection."""
    ordered = sorted(set(eligible))
    rng = random.Random(seed)
    picks = rng.sample(ordered, k=min(n, len(ordered)))
    return sorted(picks)


def random_control_draws(eligible: Sequence[tuple], *, n: int, seeds: Sequence[int] = RANDOM_CONTROL_SEEDS) -> dict:
    """`{seed: [(symbol, bar_index), ...]}` -- the DRAW half of `random_control_batch`, one
    `_random_control_picks` per seed. PERFORMANCE ONLY; see the block above."""
    return {seed: _random_control_picks(eligible, n=n, seed=seed) for seed in seeds}


def atr_decile_control_draws(
    bars_by_symbol: dict, events: Sequence[dict], eligible: Sequence[tuple], *, seed: int,
    n_per_event: int = 1, n_deciles: int = 10, cfg: dict = CONFIG, cache: Optional[ControlPriceCache] = None,
) -> list:
    """`[(event, [(symbol, bar_index), ...picks]), ...]`, in the exact iteration order and with
    the exact skip semantics `atr_decile_control_rows` uses -- the DRAW half (see the block
    above): every candidate-pool / decile-ranking / seeded-sample step `atr_decile_control_rows`
    performs, WITHOUT ever calling `_priced_signal_fields` (no stop/target/cost computation).

    `cache`: only its `atr_by_symbol` half is ever touched (via `_atr_pct_at_cached`, for the
    ATR%(t) ranking itself) -- `priced_signal` is never read or written here, since no row is
    priced by this function. PERFORMANCE ONLY, defaults to a fresh cache when not given.
    """
    cache = cache if cache is not None else ControlPriceCache()
    by_date: dict = {}
    for symbol, idx in sorted(set(eligible)):
        bars = bars_by_symbol[symbol]
        if idx < 0 or idx >= len(bars):
            continue
        d = _iso(bars, idx)
        by_date.setdefault(d, []).append((symbol, idx))

    draws: list = []
    for ev in sorted(events, key=lambda e: e["event_id"]):
        symbol, idx, date_iso = ev["symbol"], ev["confirmation_bar_index"], ev["signal_date"]
        pool = sorted(set(by_date.get(date_iso, ())) | {(symbol, idx)})

        atr_pcts: dict = {}
        for s, i in pool:
            v = _atr_pct_at_cached(bars_by_symbol, s, i, cfg, cache)
            if v is not None:
                atr_pcts[(s, i)] = v
        if (symbol, idx) not in atr_pcts or len(atr_pcts) < 2:
            continue  # no ATR%(t) for the event itself, or nothing to rank it against

        keys = sorted(atr_pcts)  # deterministic order, independent of `eligible`'s own order
        values = np.array([atr_pcts[k] for k in keys])
        deciles = _decile_indices(values, n_deciles)
        event_decile = deciles[keys.index((symbol, idx))]
        candidates = [k for j, k in enumerate(keys) if deciles[j] == event_decile and k != (symbol, idx)]
        if not candidates:
            continue

        rng = _seeded_rng(seed, ev["event_id"])
        picks = sorted(rng.sample(candidates, k=min(n_per_event, len(candidates))))
        draws.append((ev, picks))
    return draws


def buy_next_open_baseline_draws(events: Sequence[dict]) -> list:
    """`[(event, (symbol, bar_index)), ...]`, one per event, in `events`' own given order
    (never sorted -- matching `buy_next_open_baseline_rows`, which is itself RNG-free: every
    event's own confirmation bar IS its baseline pick, nothing to draw). The DRAW half; see the
    block above."""
    return [(ev, (ev["symbol"], ev["confirmation_bar_index"])) for ev in events]


#: The ONLY fields of a pattern-event row the control draw/assemble path ever reads. Derived by
#: enumerating `atr_decile_control_draws`, `buy_next_open_baseline_draws`,
#: `assemble_atr_decile_control_rows` and `assemble_buy_next_open_baseline_rows` -- and pinned by
#: `test_events_controls.py`, so adding a read without adding it here fails rather than silently
#: working on full rows and breaking on projected ones.
DRAW_FIELDS: tuple = ("event_id", "pattern_id", "symbol", "signal_date",
                      "confirmation_bar_index", "pattern_type", "direction")


def event_projection(row: Mapping) -> dict:
    """A light stand-in for a pattern-event row, carrying only what the control phase reads.

    WHY THIS EXISTS
    ---------------
    `atr_decile_control_draws` and `buy_next_open_baseline_draws` return `(event, picks)` pairs, so
    every drawn event stays REFERENCED for as long as the draws do -- and a pattern row is ~219 KB
    live against ~2.7 KB of real data. Across every family in a segment that pins most of the
    dataset in memory through the whole pricing phase, which is one of the retentions that put the
    v2 run at 53 GB.

    The seven fields below plus the primary entry DATE are the whole of it. `entry.primary.date`
    keeps its nested shape so `study.execute._benchmark_forward_returns` reads a projection exactly
    as it reads a real row, rather than growing a second code path.

    A projection is NOT a pattern row: it carries no costs, outcomes, targets or context, and must
    never be passed anywhere that reports on a row's own results.
    """
    entry_date = ((row.get("entry") or {}).get("primary") or {}).get("date")
    out = {k: row.get(k) for k in DRAW_FIELDS}
    out["entry"] = {"primary": {"date": entry_date}}
    return out


_PRICE_CTX: dict = {}


def _price_worker(symbol: str) -> tuple:
    """Runs inside a forked worker process (see the block above): prices EVERY (symbol,
    bar_index) pair this worker owns for `symbol`, sharing one fresh `ControlPriceCache` across
    them (so `symbol`'s own ATR series is computed once, inside this worker, and reused for
    every pair) -- returns `(symbol, {bar_index: priced_fields})`."""
    ctx = _PRICE_CTX
    bars = ctx["bars_by_symbol"][symbol]
    cache = ControlPriceCache()
    out = {
        idx: _priced_signal_fields(bars, symbol, idx, ctx["cfg"], ctx["cost_cfg"], cache,
                                   ctx.get("with_targets", True))
        for idx in ctx["pairs_by_symbol"][symbol]
    }
    return symbol, out


def price_signals(
    bars_by_symbol: dict, pairs: Sequence[tuple], *, cfg: dict = CONFIG,
    cost_cfg: Optional[costs_bridge.CostConfig] = None, cache: Optional[ControlPriceCache] = None,
    max_workers: int = 1, with_targets: bool = True,
) -> dict:
    """`{(symbol, bar_index): priced_fields}` for every UNIQUE pair in `pairs` -- the PRICE half
    of the draw/price/assemble split (see the block above). `priced_fields` is exactly
    `_priced_signal_fields`'s own return shape (`{"atr_at_t", **build_outcome_cost_block(...)}`),
    byte-identical regardless of `max_workers` or how many other pairs share this call.

    `max_workers` (PERFORMANCE ONLY, default 1 = serial, sharing one `cache` -- or a fresh one
    when `cache` is None -- across every pair, exactly `ControlPriceCache`'s existing cross-pair
    reuse contract): with `max_workers > 1`, `pairs` is partitioned BY SYMBOL (`cache`, if given,
    is then ignored -- a `ControlPriceCache` cannot cross a process boundary; each worker builds
    its own, scoped to the symbols it owns) and priced across a forked process pool, one task per
    symbol, so a symbol's own ATR series is computed at most once per call regardless of how many
    (symbol, bar_index) pairs it contributes and regardless of worker count.
    """
    unique_pairs = sorted(set(pairs))
    if not unique_pairs:
        return {}
    pairs_by_symbol: dict = {}
    for symbol, idx in unique_pairs:
        pairs_by_symbol.setdefault(symbol, []).append(idx)

    if max_workers <= 1 or len(pairs_by_symbol) <= 1:
        cache = cache if cache is not None else ControlPriceCache()
        return {
            (symbol, idx): _priced_signal_fields(bars_by_symbol[symbol], symbol, idx, cfg, cost_cfg,
                                                 cache, with_targets)
            for symbol, idxs in pairs_by_symbol.items() for idx in idxs
        }

    global _PRICE_CTX
    _PRICE_CTX = dict(bars_by_symbol=bars_by_symbol, pairs_by_symbol=pairs_by_symbol, cfg=cfg,
                      cost_cfg=cost_cfg, with_targets=with_targets)
    try:
        ctx = multiprocessing.get_context("fork")
        symbols = sorted(pairs_by_symbol)
        with ctx.Pool(processes=min(max_workers, len(symbols))) as pool:
            results = pool.map(_price_worker, symbols)
    finally:
        _PRICE_CTX = {}

    out: dict = {}
    for symbol, priced_by_idx in results:
        for idx, fields in priced_by_idx.items():
            out[(symbol, idx)] = fields
    return out


def assemble_random_control_batch(bars_by_symbol: dict, draws: Mapping, priced: Mapping, *, cfg: dict = CONFIG) -> dict:
    """`{seed: [rows]}` -- the ASSEMBLE half for the random-control batch: `draws` is
    `random_control_draws`'s own output, `priced` is `price_signals`'s own output covering every
    pair `draws` contains. Row-for-row (and byte-for-byte) identical to what
    `random_control_batch(..., seeds=draws.keys())` builds for the same inputs."""
    out: dict = {}
    for seed, picks in draws.items():
        rows = []
        for symbol, idx in sorted(picks):
            bars = bars_by_symbol[symbol]
            pattern_id = f"{symbol}:{RANDOM_CONTROL_PATTERN_TYPE}:{_iso(bars, idx)}"
            rows.append(_assemble_priced_baseline_row(
                bars, symbol, idx, priced[(symbol, idx)], pattern_type=RANDOM_CONTROL_PATTERN_TYPE,
                pattern_id=pattern_id, cfg=cfg,
            ))
        out[seed] = rows
    return out


def assemble_atr_decile_control_rows(bars_by_symbol: dict, draws: Sequence[tuple], priced: Mapping, *, cfg: dict = CONFIG) -> list:
    """`[rows]` -- the ASSEMBLE half for the ATR-decile control: `draws` is
    `atr_decile_control_draws`'s own output, `priced` is `price_signals`'s own output covering
    every pick `draws` contains. Row-for-row identical to `atr_decile_control_rows` for the same
    inputs."""
    rows = []
    for ev, picks in draws:
        for cs, ci in picks:
            bars = bars_by_symbol[cs]
            pattern_id = f"{cs}:{ATR_DECILE_CONTROL_PATTERN_TYPE}:{_iso(bars, ci)}:for:{ev['pattern_id']}"
            rows.append(_assemble_priced_baseline_row(
                bars, cs, ci, priced[(cs, ci)], pattern_type=ATR_DECILE_CONTROL_PATTERN_TYPE,
                pattern_id=pattern_id, cfg=cfg, source_event_id=ev["event_id"],
            ))
    return rows


def assemble_buy_next_open_baseline_rows(bars_by_symbol: dict, draws: Sequence[tuple], priced: Mapping, *, cfg: dict = CONFIG) -> list:
    """`[rows]` -- the ASSEMBLE half for the buy-next-open baseline: `draws` is
    `buy_next_open_baseline_draws`'s own output, `priced` is `price_signals`'s own output
    covering every pick `draws` contains. Row-for-row identical to `buy_next_open_baseline_rows`
    for the same inputs."""
    rows = []
    for ev, (symbol, idx) in draws:
        bars = bars_by_symbol[symbol]
        pattern_id = f"{ev['pattern_id']}:BASELINE"
        rows.append(_assemble_priced_baseline_row(
            bars, symbol, idx, priced[(symbol, idx)], pattern_type=BUY_NEXT_OPEN_BASELINE_PATTERN_TYPE,
            pattern_id=pattern_id, cfg=cfg, source_event_id=ev["event_id"],
        ))
    return rows
