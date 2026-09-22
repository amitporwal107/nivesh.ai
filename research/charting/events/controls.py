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
import random
from typing import Optional, Sequence

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


def _build_baseline_row(
    bars: pd.DataFrame, symbol: str, t_idx: int, *, pattern_type: str, pattern_id: str, cfg: dict,
    cost_cfg: Optional[costs_bridge.CostConfig], source_event_id: Optional[str] = None,
) -> dict:
    # A control has no pattern -- no "broken level" and no Layer 1 structural stop -- but §37
    # task item 7 ("the random-selection and buy-at-next-open controls need a stop: use the
    # Layer 2 ATR stop for them") still needs a real ATR(cfg["atr_period"]) reading at t_idx, so
    # it is computed here exactly like extraction.py's own per-row ATR (view = bars up to and
    # including t_idx only -- no look-ahead), and surfaced at the row's own top-level
    # `atr_at_t` field too (previously always `None` here, since nothing used it yet).
    view = bars.iloc[: t_idx + 1].reset_index(drop=True)
    atr_val = atr_series_fn(view, period=cfg["atr_period"]).iloc[t_idx]
    atr_at_t = float(atr_val) if pd.notna(atr_val) else None

    row: dict = {
        # `pattern_id` (built by the two public functions below) already carries the
        # "{symbol}:{pattern_type}:..." prefix -- do not prepend `symbol` again.
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
    row.update(build_outcome_cost_block(
        bars, t_idx, _BASELINE_DIRECTION, cfg=cfg, cost_cfg=cost_cfg, atr_at_t=atr_at_t,
    ))  # pattern_type/levels/level_broken_value default to None -- Layer 2 ATR stop only (item 7)
    costs_by_horizon = (row.get("costs") or {}).get("by_horizon") or {}
    resolved = next((b for b in costs_by_horizon.values() if b.get("available")), None)
    if resolved is not None:
        row["versioning"]["cost_rule_version"] = resolved.get("cost_rule_version")
        row["versioning"]["tax_rule_version"] = resolved.get("tax_rule_version")
    return row


def random_control_rows(
    bars_by_symbol: dict, eligible: Sequence[tuple], *, n: int, seed: int, cfg: dict = CONFIG,
    cost_cfg: Optional[costs_bridge.CostConfig] = None,
) -> list[dict]:
    """A fixed-seed random draw of `n` (symbol, bar_index) pairs from `eligible` -- the SAME
    eligible universe/dates population the caller has already screened (this module does not
    itself define "eligible"; S18.3 says "from the same eligible universe", which is the
    caller's own screen, e.g. a real pattern-event population's own dates/symbols). Each pick
    produces a row via the identical entry/outcome/cost pipeline real events use.

    Deterministic: `random.Random(seed)` and a stable sort of `eligible` BEFORE sampling, so the
    same call reproduces byte-identical output regardless of `eligible`'s own input order.
    """
    ordered = sorted(set(eligible))
    rng = random.Random(seed)
    picks = rng.sample(ordered, k=min(n, len(ordered)))
    rows = []
    for symbol, idx in sorted(picks):
        bars = bars_by_symbol[symbol]
        pattern_id = f"{symbol}:{RANDOM_CONTROL_PATTERN_TYPE}:{_iso(bars, idx)}"
        rows.append(_build_baseline_row(
            bars, symbol, idx, pattern_type=RANDOM_CONTROL_PATTERN_TYPE, pattern_id=pattern_id,
            cfg=cfg, cost_cfg=cost_cfg,
        ))
    return rows


def buy_next_open_baseline_rows(
    bars_by_symbol: dict, events: Sequence[dict], *, cfg: dict = CONFIG,
    cost_cfg: Optional[costs_bridge.CostConfig] = None,
) -> list[dict]:
    """One baseline row per pattern EVENT (`extraction.extract_events`'s own output rows), at
    the identical (symbol, confirmation_bar_index) -- "if you had simply bought the next open on
    every date a pattern confirmed, regardless of the pattern's own BULLISH/BEARISH call"."""
    rows = []
    for ev in events:
        symbol = ev["symbol"]
        idx = ev["confirmation_bar_index"]
        bars = bars_by_symbol[symbol]
        pattern_id = f"{ev['pattern_id']}:BASELINE"
        rows.append(_build_baseline_row(
            bars, symbol, idx, pattern_type=BUY_NEXT_OPEN_BASELINE_PATTERN_TYPE, pattern_id=pattern_id,
            cfg=cfg, cost_cfg=cost_cfg, source_event_id=ev["event_id"],
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
    cost_cfg: Optional[costs_bridge.CostConfig] = None,
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
    """
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
            v = _atr_pct_at(bars_by_symbol[s], i, cfg)
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
                cfg=cfg, cost_cfg=cost_cfg, source_event_id=ev["event_id"],
            ))
    return rows


# ── Random-control 200-seed batch (§7.6.ii) ──────────────────────────────────────────────


def random_control_batch(
    bars_by_symbol: dict, eligible: Sequence[tuple], *, n: int, seeds: Sequence[int] = RANDOM_CONTROL_SEEDS,
    cfg: dict = CONFIG, cost_cfg: Optional[costs_bridge.CostConfig] = None,
) -> dict:
    """§7.6.ii: "a random selection from the same eligible universe and dates, 200 seeds" --
    one independent `random_control_rows` draw per seed (default the pre-registered
    `RANDOM_CONTROL_SEEDS`, 0..199). Returns `{seed: rows}`, never flattened/merged: the
    study report's own requirement ("the pattern rows' percentile within the random ...
    distribution", prereg §7.6) needs the PER-SEED population of outcomes (200 independent
    draws), not one pooled 200x-n sample."""
    return {seed: random_control_rows(bars_by_symbol, eligible, n=n, seed=seed, cfg=cfg, cost_cfg=cost_cfg)
            for seed in seeds}
