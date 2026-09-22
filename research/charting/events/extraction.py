"""Historical pattern event extraction -- docs/charting.md S35.2 ("Historical event dataset"),
S18 (Historical Validation Framework), S19 (Historical Replay), S23.2/S23.3 (event/outcome
records). One row per pattern instance, at the bar `t` its `status` first becomes
PRICE_CONFIRMED (`research.charting.lifecycle.LifecycleState.PRICE_CONFIRMED`), read via
`research.charting.replay.replay()`'s own transition log (replay.py's own docstring: "record
every pattern lifecycle-status transition as an append-only event") -- this module inherits
replay()'s already-proven point-in-time walk rather than re-implementing it, and never edits
replay.py/patterns.py/context.py/config.py (other agents own those).

`TransitionEvent` (replay.py) does not itself carry `direction`/`levels` (only pattern_id /
pattern_type / status / event metadata -- see its dataclass). This module recovers them by
calling `patterns.detect_as_of` ONE MORE TIME, at the exact same bar `t` and the exact same
point-in-time view (`bars.iloc[:t+1]`) replay()'s own loop already used internally to produce
that transition -- a second, PURE, deterministic call given the same (bars, t, cfg, symbol), not
a new source of look-ahead: patterns.py's own contract is "`view = bars.iloc[:t+1]` FIRST...
every function in this module only ever reads `view`". This mirrors replay.py's own "second,
independent PIT boundary" design note, and avoids editing replay.py just to have it also return
direction/levels.
"""
from __future__ import annotations

from typing import Optional

import pandas as pd

from research.charting import patterns, replay
from research.charting.config import CONFIG, ENGINE_VERSION, PROFILE_NAME, config_hash
from research.charting.events import costs_bridge, outcomes, schema
from research.charting.research_window import assert_no_sealed_rows
from research.charting.series import atr as atr_series_fn
from research.charting.series import relative_volume as relvol_series_fn

_CONFIRMED_STATUS = "PRICE_CONFIRMED"


def build_outcome_cost_block(
    bars: pd.DataFrame, t_idx: int, direction: str, *, cfg: dict = CONFIG,
    cost_cfg: Optional[costs_bridge.CostConfig] = None,
) -> dict:
    """Everything downstream of "a signal exists at bar t, in direction `direction`": the
    primary/alternative entry, both entries' forward-outcome blocks, the ADV/liquidity figures,
    and the primary entry's cost blocks for every horizon. Shared by `extract_events` (real
    pattern events) and `controls.py` (the S18.3 comparison groups), so a pattern row and a
    control row are never built from two different code paths.
    """
    cost_cfg = cost_cfg or costs_bridge.CostConfig()

    primary = outcomes.primary_entry(bars, t_idx)
    alt = outcomes.alternative_entry(bars, t_idx)
    adv = outcomes.adv_inr_at(bars, t_idx, n=cfg["volume_baseline_bars"])

    block: dict = {
        "entry": {"primary": primary, "alternative_close_t": alt},
        "outcomes": None,
        "outcomes_alt_close_entry": None,
        "liquidity": {"adv_inr_at_t": adv, "notional_inr": float(cost_cfg.notional_inr)},
        "costs": None,
        "unavailable_reason": None,
    }

    if primary is None:
        block["unavailable_reason"] = "no_bar_after_confirmation"
        return block

    ei, ep = primary["index"], primary["price"]
    fwd = outcomes.forward_outcome_block(bars, ei, ep, direction)
    bt = outcomes.bars_to_targets(bars, ei, ep)
    hit = outcomes.hit_flags(fwd["raw"], bt)
    block["outcomes"] = {
        "entry_method": primary["method"],
        "forward_returns": fwd["raw"],
        "forward_returns_directional": fwd["directional"],
        "bars_to_target": {f"plus_{round(pct * 100)}pct": v for pct, v in bt.items()},
        **hit,
    }

    alt_ei, alt_ep = alt["index"], alt["price"]
    fwd_alt = outcomes.forward_outcome_block(bars, alt_ei, alt_ep, direction)
    block["outcomes_alt_close_entry"] = {
        "entry_method": alt["method"],
        "forward_returns": fwd_alt["raw"],
        "forward_returns_directional": fwd_alt["directional"],
    }

    qty = costs_bridge.qty_for_notional(ep, cost_cfg.notional_inr)
    position_value = costs_bridge.position_value_inr(ep, qty)
    participation = costs_bridge.participation_ratio_for(position_value, adv)
    block["liquidity"].update(qty=qty, position_value_inr=position_value, participation_ratio=participation)

    costs_by_horizon: dict = {}
    for h, raw_h in fwd["raw"].items():
        if not raw_h.get("available"):
            costs_by_horizon[h] = {"available": False, "reason": raw_h.get("reason")}
            continue
        entry_date = pd.Timestamp(primary["date"]).date()
        exit_date = pd.Timestamp(raw_h["exit_date"]).date()
        costs_by_horizon[h] = costs_bridge.compute_cost_block(
            entry_date=entry_date, entry_price=ep, exit_date=exit_date, exit_price=raw_h["exit_close"],
            qty=qty, adv_inr=adv, cfg=cost_cfg,
        )
    # Every cost block is a LONG round trip (buy at entry, sell at exit). A BEARISH signal's
    # directional return is short-side, but an overnight short is not possible in the cash
    # delivery segment, so its short-side costs are not modelled -- say so on the row rather
    # than let the long net figure be read as the short outcome.
    block["costs"] = {
        "trade_side": "LONG",
        "short_side_costs": "NOT_MODELLED" if direction == "BEARISH" else None,
        "by_horizon": costs_by_horizon,
    }
    return block


def _iso(bars: pd.DataFrame, idx: int) -> str:
    return schema.iso_date(bars["date"].iloc[idx])


def _build_event_row(
    bars: pd.DataFrame, symbol: str, t_idx: int, snap, cfg: dict, cost_cfg: Optional[costs_bridge.CostConfig]
) -> dict:
    view = bars.iloc[: t_idx + 1].reset_index(drop=True)
    atr_ser = atr_series_fn(view, period=cfg["atr_period"])
    relvol_ser = relvol_series_fn(view, n=cfg["volume_baseline_bars"])
    atr_val = atr_ser.iloc[t_idx]
    relvol_val = relvol_ser.iloc[t_idx]
    level_value, level_field = schema.level_broken(snap.pattern_type, snap.direction, snap.levels)

    row: dict = {
        # `snap.pattern_id` already carries the "{symbol}:{pattern_type}:..." prefix
        # (patterns.py's own convention) -- do not prepend `symbol` again.
        "event_id": f"{snap.pattern_id}:{_iso(bars, t_idx)}",
        "symbol": symbol,
        "pattern_id": snap.pattern_id,
        "pattern_type": snap.pattern_type,
        "direction": snap.direction,
        "signal_date": _iso(bars, t_idx),
        "confirmation_bar_index": t_idx,
        "level_broken": level_value,
        "level_broken_field": level_field,
        "atr_at_t": float(atr_val) if pd.notna(atr_val) else None,
        "relative_volume_at_t": float(relvol_val) if pd.notna(relvol_val) else None,
        "config_hash": config_hash(cfg),
        "engine_version": ENGINE_VERSION,
        "profile": PROFILE_NAME,
        "dataset_version": schema.EVENTS_SCHEMA_VERSION,
        "versioning": {
            "signal_timestamp": _iso(bars, t_idx),
            "data_cutoff_timestamp": _iso(bars, t_idx),
            "config_hash": config_hash(cfg),
            "engine_version": ENGINE_VERSION,
            "cost_rule_version": None,  # filled below once the cost block resolves a rule id
            "tax_rule_version": None,
            "slippage_model_version": None,  # per-scenario; see costs.by_horizon.*.scenarios.*
            "dataset_version": schema.EVENTS_SCHEMA_VERSION,
        },
    }
    row.update(build_outcome_cost_block(bars, t_idx, snap.direction, cfg=cfg, cost_cfg=cost_cfg))

    # Surface the resolved cost/tax rule versions at the top-level versioning block too, once
    # known (from the first horizon that actually resolved a cost block) -- PRD S30.
    costs_by_horizon = (row.get("costs") or {}).get("by_horizon") or {}
    resolved = next((b for b in costs_by_horizon.values() if b.get("available")), None)
    if resolved is not None:
        row["versioning"]["cost_rule_version"] = resolved.get("cost_rule_version")
        row["versioning"]["tax_rule_version"] = resolved.get("tax_rule_version")
    return row


def extract_events(
    bars: pd.DataFrame, symbol: str, *, cfg: dict = CONFIG,
    cost_cfg: Optional[costs_bridge.CostConfig] = None,
    start_index: int = 0, end_index: Optional[int] = None,
) -> list[dict]:
    """One row per pattern instance, at its (first) PRICE_CONFIRMED bar -- task item 1. Runs
    `replay.replay()` (which already enforces the sealed-window guard on the whole
    `bars[0..end_index]` span before anything else happens -- S35.4 fix #1), then independently
    re-asserts no sealed date reached this module's own OUTPUT rows (defense in depth, mirroring
    `replay.write_run`'s identical second check).
    """
    result = replay.replay(bars, cfg=cfg, symbol=symbol, start_index=start_index, end_index=end_index)
    confirmed = [t for t in result.transitions if t.new_status == _CONFIRMED_STATUS]
    assert_no_sealed_rows(t.event_date for t in confirmed)

    seen_pattern_ids: set = set()
    rows: list[dict] = []
    for tr in confirmed:
        if tr.pattern_id in seen_pattern_ids:
            # Defensive only: every family's lifecycle (lifecycle.py's ALLOWED_TRANSITIONS)
            # reaches PRICE_CONFIRMED at most once per pattern instance in current code, but a
            # dataset builder must not silently duplicate a row if that ever changed -- keep
            # only the first (earliest) PRICE_CONFIRMED transition for a given pattern_id.
            continue
        seen_pattern_ids.add(tr.pattern_id)
        t_idx = tr.event_index
        view = bars.iloc[: t_idx + 1].reset_index(drop=True)
        snaps = patterns.detect_as_of(view, t_idx, cfg=cfg, symbol=symbol)
        snap = next((s for s in snaps if s.pattern_id == tr.pattern_id), None)
        if snap is None:
            # Should not happen: replay() and detect_as_of() are both pure functions of the
            # same (bars, t, cfg, symbol) and replay() itself calls detect_as_of internally to
            # produce this exact transition. Skip rather than crash the whole extraction run if
            # it ever does -- the row is simply absent, never fabricated.
            continue
        rows.append(_build_event_row(bars, symbol, t_idx, snap, cfg, cost_cfg))
    return rows


def extract_events_multi(
    bars_by_symbol: dict, *, cfg: dict = CONFIG, cost_cfg: Optional[costs_bridge.CostConfig] = None,
) -> list[dict]:
    """`extract_events` over every symbol in `bars_by_symbol`, symbols visited in sorted order
    (deterministic output, matching `bars.py.load_all`'s own convention) -- no cross-symbol
    leakage by construction, each symbol's own frame is the only thing it is extracted from."""
    rows: list[dict] = []
    for symbol in sorted(bars_by_symbol):
        rows.extend(extract_events(bars_by_symbol[symbol], symbol, cfg=cfg, cost_cfg=cost_cfg))
    return rows
