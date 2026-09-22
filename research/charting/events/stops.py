"""Initial stop, targets and the target/stop outcome walk for one BULLISH event -- docs/
charting.md §37.2 (Outcome definitions), §37.3 (Stop policy), §30.1 (frozen `failure_buffer_atr`).
Owner decisions given in chat on 2026-09-22 ("final baseline I would freeze" -- see §37's own
header); this module is the first code to apply them.

This package only ever prices a LONG round trip (§36.1's "two return series, never mixed" is
about net-trading-return vs after-tax-return, not about direction -- the direction restriction
is §37.4's own: "No fictitious overnight short trade is priced"). A pattern family's own
`direction` is BULLISH or BEARISH by construction once PRICE_CONFIRMED (RECTANGLE/
SUPPORT_RESISTANCE/HH_HL's own confirmation trigger always resolves one or the other --
verified against `patterns.py` 2026-09-22, see `structural_stop`'s own per-family branch below);
NEUTRAL is never a `direction` this package's callers see on a PRICE_CONFIRMED row, so every
function below that is direction-symmetric (`structural_stop`) still only DOCUMENTS BEARISH
behaviour for completeness/testability, while the ones that build an actual trade
(`build_stop_and_targets_block` and everything it calls) are BULLISH-only and must not be called
for a BEARISH row -- see extraction.py's own direction gate (§37.4).

-- Layer 1 / Layer 2 (§37.3) -----------------------------------------------------------------
Layer 1 (structural, pattern-invalidation) stop, per P0 family:
  RECTANGLE / SUPPORT_RESISTANCE (breakout families) -- `broken level - failure_buffer_atr *
    ATR(t)` (§30.1's frozen `failure_buffer_atr` = 0.25, the SAME buffer the confirmation
    trigger itself used, "so states cannot overlap" -- §30.1's own words). "broken level" is
    this package's own `schema.level_broken()` value (RECTANGLE's `breakout_level` /
    SUPPORT_RESISTANCE's `breakout_level`/`breakdown_level`), NOT `patterns.py`'s
    `invalidation_level` field (that is the pattern's OPPOSITE boundary breakout threshold --
    a much wider level meant for the pattern's own lifecycle, not a tight failure-buffer stop).
  HH_HL -- "the invalidation swing": verified directly against `patterns.py::_hh_hl_patterns`
    (2026-09-22) -- the INVALIDATED transition compares `close` to `last_low.price` (BULLISH)
    / `last_high.price` (BEARISH), and those are exactly `snap.levels["prior_low"]` /
    `snap.levels["prior_high"]` (the same `last_low`/`last_high` objects feed both). No ATR
    buffer is subtracted for this family -- §37.3 says "at the invalidation swing", not
    "swing minus a buffer", unlike the breakout families' own explicit formula.

Layer 2 (minimum distance): "the stop is at least 0.75 x ATR(14) below entry (widened, never
tightened)". Implemented as `final_distance = max(structural_distance, layer2_distance)` --
this single `max()` both (a) widens a too-tight structural stop up to the 0.75-ATR floor and
(b) self-corrects the pathological case of a structural stop sitting AT OR ABOVE entry (e.g. a
large gap-down entry vs. a structural stop computed from the confirmation bar's own close) --
since `layer2_distance` is always > 0 whenever ATR(t) is valid, `final_distance` is always
positive in that case too, so `final_stop` is always strictly below `entry_price` whenever
Layer 2 itself is available. This is a documented consequence of the "widen, never tighten"
formula, not a separate special case.

`atr_at_t` throughout this module is the SAME `ATR(cfg["atr_period"])` reading extraction.py
already computes once per row (not a second, independent ATR(14) query) -- under the frozen
`PATTERN_CONFIRMATION_V1_RESEARCH` profile (§30) `cfg["atr_period"] == 14`, so this is exactly
the "ATR(14)" §37.3 asks for.

-- Targets (§37.2) -----------------------------------------------------------------------------
+2%/+3%/+5%/+10% from entry, plus 1R/1.5R/2R/3R where `R = entry_price - final_stop` (§37.2's
own "R = entry - initial stop"; "initial stop" is read as the fully-resolved Layer1+Layer2 stop
that is actually placed on the trade, since that is the stop whose distance defines the trade's
real risk -- the Layer 1 structural stop ALONE, before Layer 2 possibly widens it, is never the
stop actually used).

-- The target/stop walk, AMBIGUOUS and the gap rule (§37.3) ------------------------------------
One bar-by-bar walk per (target, stop) pair, starting at the ENTRY bar itself (offset 0 -- "the
entry bar itself, use only the part of the bar after the open: treat the entry bar like any
other bar (the entry is at its open)" -- the entry bar's own high/low, taken as a whole, ARE
"the part of the bar after the open" since the position is opened AT that same bar's open, so
there is nothing before entry within that bar to exclude). For every LATER bar (offset > 0),
the §37.3 gap rule is checked first, before the bar's own high/low: an OPEN at/below the stop
fills at the open (STOP, gap); an OPEN at/above the target fills at the open (TARGET, gap) --
these two conditions cannot BOTH fire on the same bar (stop_price < entry_price < target_price
by construction, so a single open cannot be both <= stop and >= target). Only once neither gap
condition fires does the bar's own high/low get checked: high >= target AND low <= stop on the
SAME bar (that did not gap through either) is AMBIGUOUS -- "never assume an order" -- and
carries no single exit price (both bounds are reported separately, see
`_horizon_result_ambiguous`). A bar that touches only one side resolves normally.

This is a single STATEFUL walk (not an independent "was X touched anywhere in the window" pair
of flags): once a bar resolves TARGET/STOP/AMBIGUOUS, the walk stops there -- a later bar's
own high/low is never inspected for that (target, stop, horizon) triple, exactly like a real
trade that has already exited. `target_hit`/`stop_hit`/`both_hit`/`neither_hit` are DERIVED from
that single resolution (`both_hit` is true only for the AMBIGUOUS case -- both were touched on
the exact bar that ended the walk, not "at some point during the window" more broadly), not
computed independently. Per horizon `h`: if the walk's own resolution offset is <= h, that
horizon reports the resolved outcome (regardless of `h`'s own data availability beyond the
resolution -- once resolved, more bars cannot change the answer); otherwise, if bars
[entry .. entry+h] were ALL actually available and none of them resolved the walk,
`neither_hit`/`NONE` is reported (a genuine, informative fact); if the walk ran out of bars
before both resolving AND covering `h`, that horizon is `available: False` (never truncated
silently, mirroring `outcomes.bars_to_targets`' identical `insufficient_forward_bars` reason).
"""
from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd

from research.charting.config import CONFIG
from research.charting.events import costs_bridge, schema
from research.charting.events.schema import HORIZONS, R_MULTIPLES, TARGET_PCTS, iso_date

# -- §37.2 target name -> spec ---------------------------------------------------------------
_PCT_TARGET_NAMES = tuple(f"pct_{round(p * 100)}" for p in TARGET_PCTS)  # pct_2, pct_3, pct_5, pct_10
_R_TARGET_NAMES = tuple(f"r_{str(m).replace('.', '_')}" for m in R_MULTIPLES)  # r_1_0, r_1_5, r_2_0, r_3_0

# -- §37.3 HH_HL invalidation-swing field, per direction (verified against patterns.py, see
# module docstring) -- the one place this mapping is encoded, mirroring schema.level_broken()'s
# own per-family mapping for the (different) "broken level" concept.
_HH_HL_INVALIDATION_SWING_FIELD = {"BULLISH": "prior_low", "BEARISH": "prior_high"}


def structural_stop(
    pattern_type: Optional[str], direction: str, levels: Optional[dict],
    level_broken_value: Optional[float], atr_at_t: Optional[float], cfg: dict = CONFIG,
) -> tuple[Optional[float], Optional[str]]:
    """(stop_price, method) for the §37.3 Layer 1 structural stop, or `(None, None)` for an
    unrecognised family or missing inputs -- never a guessed number (mirrors
    `schema.level_broken()`'s own contract). `pattern_type=None` (a control row -- no pattern at
    all) always returns `(None, None)`, which is the documented, correct way for a control to
    fall through to Layer 2 only (§37 task item 7)."""
    if pattern_type in ("RECTANGLE", "SUPPORT_RESISTANCE"):
        if level_broken_value is None or atr_at_t is None or not np.isfinite(atr_at_t):
            return None, None
        buf = cfg["failure_buffer_atr"] * atr_at_t
        stop = (level_broken_value - buf) if direction == "BULLISH" else (level_broken_value + buf)
        return float(stop), "broken_level_minus_failure_buffer_atr"
    if pattern_type == "HH_HL":
        field = _HH_HL_INVALIDATION_SWING_FIELD.get(direction)
        if field is None or not levels or levels.get(field) is None:
            return None, None
        return float(levels[field]), "hh_hl_invalidation_swing"
    return None, None


def resolve_stop(entry_price: float, structural_stop_value: Optional[float], atr_at_t: Optional[float], cfg: dict = CONFIG) -> dict:
    """Layer 1 + Layer 2 (§37.3) -> `{"structural_stop", "layer2_min_distance", "final_stop",
    "stop_layer", "r_value"}`. `stop_layer` is one of `"structural"` (Layer 1 already met the
    Layer 2 floor), `"layer2_widened"` (Layer 1 existed but was tighter than the floor),
    `"layer2_only"` (no Layer 1 at all -- a control row, or an unrecognised family), or `None`
    (neither layer could be computed -- ATR(t) itself was unavailable AND there was no
    structural stop either; this cannot happen for a real PRICE_CONFIRMED P0 event, since a
    valid ATR reading is already required for the pattern to have confirmed at all, but is
    handled here rather than assumed impossible)."""
    layer2_distance = None
    if atr_at_t is not None and np.isfinite(atr_at_t):
        layer2_distance = schema.LAYER2_MIN_STOP_DISTANCE_ATR * atr_at_t

    if structural_stop_value is None and layer2_distance is None:
        return {"structural_stop": None, "layer2_min_distance": None, "final_stop": None, "stop_layer": None, "r_value": None,
                "entry_beyond_structural_stop": None}

    if structural_stop_value is None:
        final_stop = entry_price - layer2_distance
        return {
            "structural_stop": None, "layer2_min_distance": layer2_distance, "final_stop": final_stop,
            "stop_layer": "layer2_only", "r_value": entry_price - final_stop, "entry_beyond_structural_stop": None,
        }

    structural_distance = entry_price - structural_stop_value
    # The entry bar opened at or below the structural stop (a gap through the invalidation level): the pattern
    # was already invalid at entry. The Layer 2 floor still sets the stop (widen, never tighten) and this flag
    # says so, so the study can count or segment these rows instead of reading them as ordinary widened stops.
    beyond = bool(structural_distance <= 0)
    if layer2_distance is None:
        if beyond:
            return {"structural_stop": structural_stop_value, "layer2_min_distance": None, "final_stop": None,
                    "stop_layer": None, "r_value": None, "entry_beyond_structural_stop": True}
        return {
            "structural_stop": structural_stop_value, "layer2_min_distance": None, "final_stop": structural_stop_value,
            "stop_layer": "structural", "r_value": structural_distance, "entry_beyond_structural_stop": False,
        }

    if structural_distance >= layer2_distance:
        return {
            "structural_stop": structural_stop_value, "layer2_min_distance": layer2_distance,
            "final_stop": structural_stop_value, "stop_layer": "structural", "r_value": structural_distance,
            "entry_beyond_structural_stop": False,
        }
    final_stop = entry_price - layer2_distance  # widen, never tighten -- see module docstring
    return {
        "structural_stop": structural_stop_value, "layer2_min_distance": layer2_distance, "final_stop": final_stop,
        "stop_layer": "layer2_widened", "r_value": entry_price - final_stop, "entry_beyond_structural_stop": beyond,
    }


def target_prices(entry_price: float, r_value: Optional[float]) -> dict:
    """The 8 §37.2 target prices, keyed `pct_2`/`pct_3`/`pct_5`/`pct_10` (from `entry_price`
    alone) and `r_1_0`/`r_1_5`/`r_2_0`/`r_3_0` (from `entry_price + multiple * r_value`, `None`
    for every R-multiple key when `r_value` itself is `None` -- never a guessed price)."""
    out = {name: entry_price * (1 + pct) for name, pct in zip(_PCT_TARGET_NAMES, TARGET_PCTS)}
    for name, mult in zip(_R_TARGET_NAMES, R_MULTIPLES):
        out[name] = (entry_price + mult * r_value) if r_value is not None else None
    return out


def _walk_target_stop(bars: pd.DataFrame, entry_index: int, target_price: float, stop_price: float, max_offset: int) -> dict:
    """The single stateful walk described in the module docstring. Returns
    `{"exit_offset", "exit_event", "exit_price", "exhausted_at_offset"}`:
      - resolved (`exit_event` in TARGET/STOP/AMBIGUOUS): `exit_offset` is the bar (sessions
        from entry, entry bar = 0) that resolved it; `exit_price` is `None` for AMBIGUOUS.
      - fully scanned with no resolution (`exit_event == "NONE"`): every bar
        [entry_index .. entry_index+max_offset] existed and none of them resolved the walk.
      - ran out of bars before resolving (`exit_event is None`): `exhausted_at_offset` is the
        first offset whose bar does not exist -- every horizon `h >= exhausted_at_offset` is
        `insufficient_forward_bars`; every `h < exhausted_at_offset` is a genuine `neither_hit`
        (those bars were all actually scanned).
    """
    n = len(bars)
    opens = bars["open"].to_numpy(dtype=float)
    highs = bars["high"].to_numpy(dtype=float)
    lows = bars["low"].to_numpy(dtype=float)
    for offset in range(0, max_offset + 1):
        i = entry_index + offset
        if i >= n:
            return {"exit_offset": None, "exit_event": None, "exit_price": None, "exhausted_at_offset": offset}
        o, hi, lo = opens[i], highs[i], lows[i]
        if offset > 0 and o <= stop_price:  # gap rule: open at/below the stop fills at the open
            return {"exit_offset": offset, "exit_event": "STOP", "exit_price": o, "exhausted_at_offset": None}
        if offset > 0 and o >= target_price:  # gap rule: open at/above the target fills at the open
            return {"exit_offset": offset, "exit_event": "TARGET", "exit_price": o, "exhausted_at_offset": None}
        target_touched = hi >= target_price
        stop_touched = lo <= stop_price
        if target_touched and stop_touched:
            return {"exit_offset": offset, "exit_event": "AMBIGUOUS", "exit_price": None, "exhausted_at_offset": None}
        if target_touched:
            return {"exit_offset": offset, "exit_event": "TARGET", "exit_price": target_price, "exhausted_at_offset": None}
        if stop_touched:
            return {"exit_offset": offset, "exit_event": "STOP", "exit_price": stop_price, "exhausted_at_offset": None}
    return {"exit_offset": None, "exit_event": "NONE", "exit_price": None, "exhausted_at_offset": None}


def _exit_leg(
    bars: pd.DataFrame, entry_index: int, entry_price: float, exit_offset: int, exit_price: float, *,
    qty: int, adv_inr: Optional[float], cfg: dict, cost_cfg: Optional[costs_bridge.CostConfig],
) -> dict:
    """One priced exit leg (item 4): exit price/date, holding period, gross return, and the
    full §36 net-cost block (base scenario plus the other three, long round trip) via the same
    `costs_bridge.compute_cost_block` every horizon's own cost block already uses. `qty<=0`
    (non-positive entry price) is handled by `compute_cost_block` itself
    (`{"available": False, "reason": "non_positive_qty"}`) -- not special-cased here."""
    entry_date = pd.Timestamp(bars["date"].iloc[entry_index]).date()
    exit_date = pd.Timestamp(bars["date"].iloc[entry_index + exit_offset]).date()
    cost_cfg = cost_cfg or costs_bridge.CostConfig()
    return {
        "exit_price": exit_price,
        "exit_date": iso_date(exit_date),
        "holding_period_sessions": exit_offset,
        "gross_return": (exit_price - entry_price) / entry_price,
        "costs": costs_bridge.compute_cost_block(
            entry_date=entry_date, entry_price=entry_price, exit_date=exit_date, exit_price=exit_price,
            qty=qty, adv_inr=adv_inr, cfg=cost_cfg,
        ),
    }


def _horizon_result(
    bars: pd.DataFrame, entry_index: int, entry_price: float, target_price: float, stop_price: float,
    walk: dict, *, qty: int, adv_inr: Optional[float], cfg: dict, cost_cfg: Optional[costs_bridge.CostConfig],
) -> dict:
    exit_offset, exit_event = walk["exit_offset"], walk["exit_event"]
    if exit_event == "AMBIGUOUS":
        return {
            "available": True, "reason": None,
            "target_hit": True, "stop_hit": True, "both_hit": True, "neither_hit": False,
            "target_hit_session": exit_offset, "stop_hit_session": exit_offset, "first_exit_event": "AMBIGUOUS",
            "exit": None,
            "as_if_target": _exit_leg(bars, entry_index, entry_price, exit_offset, target_price, qty=qty, adv_inr=adv_inr, cfg=cfg, cost_cfg=cost_cfg),
            "as_if_stop": _exit_leg(bars, entry_index, entry_price, exit_offset, stop_price, qty=qty, adv_inr=adv_inr, cfg=cfg, cost_cfg=cost_cfg),
        }
    if exit_event == "NONE":
        return {
            "available": True, "reason": None,
            "target_hit": False, "stop_hit": False, "both_hit": False, "neither_hit": True,
            "target_hit_session": None, "stop_hit_session": None, "first_exit_event": "NONE",
            "exit": None, "as_if_target": None, "as_if_stop": None,
        }
    # TARGET or STOP
    is_target = exit_event == "TARGET"
    return {
        "available": True, "reason": None,
        "target_hit": is_target, "stop_hit": not is_target, "both_hit": False, "neither_hit": False,
        "target_hit_session": exit_offset if is_target else None,
        "stop_hit_session": exit_offset if not is_target else None,
        "first_exit_event": exit_event,
        "exit": _exit_leg(bars, entry_index, entry_price, exit_offset, walk["exit_price"], qty=qty, adv_inr=adv_inr, cfg=cfg, cost_cfg=cost_cfg),
        "as_if_target": None, "as_if_stop": None,
    }


def target_outcome_by_horizon(
    bars: pd.DataFrame, entry_index: int, entry_price: float, target_price: float, stop_price: float, *,
    qty: int, adv_inr: Optional[float], cfg: dict = CONFIG, cost_cfg: Optional[costs_bridge.CostConfig] = None,
    horizons=HORIZONS,
) -> dict:
    """`{h: {...}}` for one (target, stop) pair across every horizon -- item 3 + item 4's
    combined per-horizon block. A single walk resolves the whole thing (see module docstring on
    why this is equivalent to, but far cheaper than, one independent bounded walk per horizon)."""
    max_h = max(horizons)
    walk = _walk_target_stop(bars, entry_index, target_price, stop_price, max_h)
    out: dict = {}
    for h in horizons:
        exit_offset = walk["exit_offset"]
        if exit_offset is not None and exit_offset <= h:
            out[h] = _horizon_result(bars, entry_index, entry_price, target_price, stop_price, walk, qty=qty, adv_inr=adv_inr, cfg=cfg, cost_cfg=cost_cfg)
            continue
        exhausted_at = walk["exhausted_at_offset"]
        if exhausted_at is not None and exhausted_at <= h:
            out[h] = {"available": False, "reason": "insufficient_forward_bars"}
            continue
        # Either the walk fully resolved to "NONE" over [0, max_h] (h <= max_h, so every bar
        # through h was actually scanned), or it was exhausted strictly AFTER h -- either way,
        # bars [entry_index .. entry_index+h] were all real and none of them resolved the walk.
        out[h] = _horizon_result(bars, entry_index, entry_price, target_price, stop_price, {"exit_offset": None, "exit_event": "NONE"}, qty=qty, adv_inr=adv_inr, cfg=cfg, cost_cfg=cost_cfg)
    return out


def build_stop_and_targets_block(
    bars: pd.DataFrame, entry_index: int, entry_price: float, *, direction: str,
    pattern_type: Optional[str] = None, levels: Optional[dict] = None, level_broken_value: Optional[float] = None,
    atr_at_t: Optional[float] = None, qty: int, adv_inr: Optional[float], cfg: dict = CONFIG,
    cost_cfg: Optional[costs_bridge.CostConfig] = None, horizons=HORIZONS,
) -> dict:
    """Top-level combinator (§37.2/§37.3): resolves the stop, derives the 8 targets, and walks
    every target against the resolved stop over every horizon. `{"stop": {...}, "targets": None
    | {name: {"target_price", "by_horizon": {h: {...}}}}}`.

    BULLISH/long only -- the caller (extraction.py / controls.py) must never call this for a
    BEARISH row (§37.4: no stop/target trade is priced for a bearish "avoid" signal); this
    function does not itself branch on `direction` beyond passing it through to
    `structural_stop` (kept direction-symmetric there purely for its own independent
    testability -- see that function's docstring), so calling it for BEARISH would silently
    produce a nonsensical "long" trade rather than refusing -- the gate belongs at the caller,
    exactly where §37.4 lives (extraction.py's own direction check), not duplicated here.
    """
    structural = method = None
    if pattern_type is not None:
        structural, method = structural_stop(pattern_type, direction, levels, level_broken_value, atr_at_t, cfg)
    stop_block = resolve_stop(entry_price, structural, atr_at_t, cfg)
    stop_block = {**stop_block, "structural_stop_method": method}

    if stop_block["final_stop"] is None:
        return {"stop": stop_block, "targets": None}

    prices = target_prices(entry_price, stop_block["r_value"])
    targets = {
        name: {
            "target_price": price,
            "by_horizon": target_outcome_by_horizon(
                bars, entry_index, entry_price, price, stop_block["final_stop"],
                qty=qty, adv_inr=adv_inr, cfg=cfg, cost_cfg=cost_cfg, horizons=horizons,
            ),
        }
        for name, price in prices.items()
        if price is not None
    }
    # An R-multiple target is legitimately absent (price is None) only when r_value was None --
    # which cannot happen once `stop_block["final_stop"]` is not None (r_value is always set
    # alongside it in every `resolve_stop` branch), so in practice every one of the 8 names is
    # always present here; the `if price is not None` guard above is defensive, not load-bearing.
    return {"stop": stop_block, "targets": targets}
