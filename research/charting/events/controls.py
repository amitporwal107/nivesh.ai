"""Comparison-group hooks -- docs/charting.md S18.3 "Required comparison groups": a fixed-seed
random-selection control from the same eligible universe/dates, and a buy-at-next-open baseline.

Both produce rows in the SAME nested shape `extraction.py` produces (`entry` / `outcomes` /
`outcomes_alt_close_entry` / `liquidity` / `costs`, via the identical
`extraction.build_outcome_cost_block` helper), so a downstream comparison never has to
reconcile two different row shapes -- only `pattern_type`/`pattern_id`/`direction` differ.

Per the task brief, this module is INFRASTRUCTURE ONLY -- "Build and test them; do not run
them for results." Nothing here is ever invoked over real bars in this session; see
`research/charting/tests/test_events_controls.py` (synthetic fixtures only) and
`pipeline.py`, which never calls these two functions.
"""
from __future__ import annotations

import random
from typing import Optional, Sequence

import pandas as pd

from research.charting.config import CONFIG, ENGINE_VERSION, PROFILE_NAME, config_hash
from research.charting.events import costs_bridge, schema
from research.charting.events.extraction import build_outcome_cost_block
from research.charting.series import atr as atr_series_fn

RANDOM_CONTROL_PATTERN_TYPE = "RANDOM_CONTROL"
BUY_NEXT_OPEN_BASELINE_PATTERN_TYPE = "BUY_NEXT_OPEN_BASELINE"
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
