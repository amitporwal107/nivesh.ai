"""Research enrichment layer -- docs/charting.md section 37.6, built as a SEPARATE package
per the owner's mid-task course correction (2026-09-22, relayed to this agent):

    "Don't let the research-state calculation mutate the production pattern result."
    Production detector -> production pattern -> lifecycle/API/UI stays untouched; research
    enrichment is a separate layer on top.

This module therefore NEVER writes into a `research.charting.patterns.PatternSnapshot` (or
its `.to_dict()` output) -- `enrich_pattern()` only ever READS `pattern_dict` and returns a
brand-new dict. `research/charting/patterns.py` is not imported here at all (importing it
would invite a future edit to reach into its return value by mistake); the only contract
this module depends on is the SHAPE of `PatternSnapshot.to_dict()`, documented in
`research/charting/patterns.py` and `SNAPSHOT_SCHEMA.md`.

Scope (deliberate, see the "keyed by pattern_id" phrase in the task brief): this module
enriches CONFIRMED-population pattern dicts only (`research.charting.patterns.PatternSnapshot
.to_dict()` output -- has `pattern_id`/`status`/`events`). `research.charting.early`'s EARLY
population (`EarlyFormationRecord.to_dict()`) has no `pattern_id` field to key an enrichment
record by, and none of the breakout-distance/volume fields below apply to a pre-breakout
record by definition (section 34.2: "Stage 1-3 detections ... must never be reported as
confirmed patterns"). `states.derive_research_state()` itself IS population-agnostic (it
takes an early_stage branch too) and is available for a future EARLY-population enrichment
function if one is wanted -- NEEDS-INPUT, flagged rather than silently built or silently
skipped; see this package's final report.

What `enrich_pattern()` adds, all computed fresh from `bars`/`benchmark_df` (never from
`pattern_dict`, which patterns.py already computed point-in-time-correctly on its own):

  - `research_state` (section 37.6): `states.derive_research_state(pattern_dict["status"],
    None, pattern_dict["direction"])` -- a pure re-labelling of what `pattern_dict` already
    asserts about itself; no bars are read for this one field.
  - `stock_trend_class_*` / `market_trend_class_*` (section 37.1, `regime.trend_classification`):
    the stock's own trend class and NIFTY 500's, both evaluated AT `t` (see below).
  - `breakout_level` / `breakout_threshold_pct` / `breakout_threshold_atr` /
    `breakout_volume_ratio` -- "where applicable": only when `pattern_dict["events"]`
    contains a `PRICE_CONFIRMED` event whose OWN date is `<= t` (a pattern not yet confirmed
    as of `t`, or confirmed only after `t`, must not reveal a future breakout's metrics --
    this is the one place in this module where "as of t" is a real constraint, not just a
    pass-through of patterns.py's own PIT guarantee). `None` when not applicable.

Point-in-time: `bars` is truncated to `bars[bars["date"] <= t]` FIRST, before anything else
in this module reads it -- the same "truncate first" discipline `patterns.py`'s own module
docstring describes for its `view = bars.iloc[:t+1]`. `t` must be an actual bar date present
in `bars` (the same requirement `regime.py`'s own `_window_check` already imposes -- this
module does not relax it).

Non-mutation contract (the owner's course-correction, restated as code): `enrich_pattern`
never assigns into `pattern_dict` (or any nested value inside it) -- see
`test_enrich_non_mutation.py`, which proves this with a byte-identical
`json.dumps(sort_keys=True)` before/after, not merely "no exception was raised".
"""
from __future__ import annotations

from typing import Any

import pandas as pd

from research.charting import regime, states
from research.charting.config import CONFIG
from research.charting.context import load_index_history
from research.charting.series import atr as atr_series_fn
from research.charting.series import relative_volume as relvol_series_fn

# Priority-ordered key names patterns.py's three detectors use for "the level a PRICE_CONFIRMED
# bar broke" inside a PRICE_CONFIRMED event's `observed_values` (RECTANGLE: breakout_level /
# breakdown_level; SUPPORT_RESISTANCE: level; HH_HL: confirm_level -- see patterns.py's
# `_walk_rectangle_lifecycle` / `_sr_patterns` / `_hh_hl_patterns`, read but not imported here).
# NOTE: for RECTANGLE/SUPPORT_RESISTANCE this is already the ATR-buffered TRIGGER (e.g.
# `resistance + breakout_buffer_atr * ATR[i]`, section 30.1), not the raw resistance/support
# price -- patterns.py itself calls this value "breakout_level"/"level", so `breakout_level`
# below and `breakout_threshold_pct`/`breakout_threshold_atr` (the confirming close's distance
# beyond it) are measured against THAT number, matching the event's own naming. The
# confirmation rule guarantees `close` is strictly beyond it, not any particular ATR multiple
# beyond it (see test_enrich.py's own note on this).
_LEVEL_KEYS = ("breakout_level", "breakdown_level", "level", "confirm_level")


def _find_price_confirmed_event(pattern_dict: dict) -> dict | None:
    for event in pattern_dict.get("events", ()):
        if event.get("event_type") == "PRICE_CONFIRMED":
            return event
    return None


def _level_from_event(event: dict) -> float | None:
    observed = event.get("observed_values", {})
    for key in _LEVEL_KEYS:
        if key in observed and observed[key] is not None:
            return float(observed[key])
    return None


def _bar_index_for_date(bars: pd.DataFrame, date: Any) -> int | None:
    ts = pd.Timestamp(date).normalize()
    matches = bars.index[bars["date"] == ts]
    if len(matches) == 0:
        return None
    return int(matches[0])


def enrich_pattern(
    pattern_dict: dict,
    bars: pd.DataFrame,
    t: Any = None,
    *,
    benchmark_df: pd.DataFrame | None = None,
) -> dict:
    """Build a NEW research-enrichment record for one CONFIRMED-population pattern dict
    (`research.charting.patterns.PatternSnapshot.to_dict()` output). `pattern_dict` is only
    ever read, never mutated (see module docstring's non-mutation contract) -- the return
    value is an independent dict, keyed by `pattern_id`.

    `bars`: the symbol's OWN OHLCV frame (same shape `regime.py`/`patterns.py` already use).
    `t`: the date to evaluate `stock_trend_class_*`/`market_trend_class_*` at -- must be an
    actual bar date present in `bars` (see module docstring). Defaults to the pattern's own
    "signal date": the `PRICE_CONFIRMED` event's date when one exists, else
    `pattern_dict["formation_end"]` (always present) -- i.e. the last date the detector that
    produced `pattern_dict` actually knew about.
    `benchmark_df`: NIFTY 500 history; defaults to loading fresh
    (`load_index_history(regime.FEATURE_CONFIG["market_benchmark"])`), matching `regime.py`'s
    own convention -- a caller enriching many patterns should load once and pass it in.
    """
    if "status" not in pattern_dict or "pattern_id" not in pattern_dict:
        raise ValueError(
            "enrich_pattern expects a CONFIRMED-population pattern dict "
            "(research.charting.patterns.PatternSnapshot.to_dict()) -- missing 'status'/'pattern_id'. "
            "See module docstring for why the EARLY population (research.charting.early) is out of scope."
        )

    confirm_event = _find_price_confirmed_event(pattern_dict)
    if t is None:
        t = confirm_event["date"] if confirm_event is not None else pattern_dict["formation_end"]
    ts = pd.Timestamp(t).normalize()

    # Truncate FIRST -- nothing below this line reads a row dated after `ts` (module docstring).
    truncated = bars[pd.to_datetime(bars["date"]).dt.normalize() <= ts].reset_index(drop=True)

    if benchmark_df is None:
        benchmark_df = load_index_history(regime.FEATURE_CONFIG["market_benchmark"])

    volume_status = (pattern_dict.get("components") or {}).get("volume")
    research_state = states.derive_research_state(
        pattern_dict["status"], None, pattern_dict["direction"], volume_status=volume_status
    )

    out: dict[str, Any] = {
        "pattern_id": pattern_dict["pattern_id"],
        "as_of_date": ts.date().isoformat(),
        "research_state": research_state,
        # the inputs research_state was derived from, so an unmapped (None) state is never a dead end
        "research_state_basis": {"lifecycle_state": pattern_dict["status"], "volume_component": volume_status},
    }

    for key, fv in regime.trend_classification(truncated, ts).items():
        out.update(fv.flatten(f"stock_trend_class_{key}"))
    for key, fv in regime.trend_classification(benchmark_df, ts).items():
        out.update(fv.flatten(f"market_trend_class_{key}"))

    breakout_level = breakout_threshold_pct = breakout_threshold_atr = breakout_volume_ratio = None
    if confirm_event is not None and pd.Timestamp(confirm_event["date"]).normalize() <= ts:
        confirm_idx = _bar_index_for_date(truncated, confirm_event["date"])
        level = _level_from_event(confirm_event)
        confirming_close = confirm_event.get("observed_values", {}).get("close")
        if confirm_idx is not None and level is not None and confirming_close is not None and level != 0.0:
            confirming_close = float(confirming_close)
            breakout_level = level
            breakout_threshold_pct = abs(confirming_close - level) / level * 100.0

            atr_series = atr_series_fn(truncated, period=CONFIG["atr_period"])
            atr_at_confirm = atr_series.iloc[confirm_idx]
            if pd.notna(atr_at_confirm) and atr_at_confirm > 0:
                breakout_threshold_atr = abs(confirming_close - level) / float(atr_at_confirm)

            relvol_series = relvol_series_fn(truncated, n=CONFIG["volume_baseline_bars"])
            relvol_at_confirm = relvol_series.iloc[confirm_idx]
            if pd.notna(relvol_at_confirm):
                breakout_volume_ratio = float(relvol_at_confirm)

    out["breakout_level"] = breakout_level
    out["breakout_threshold_pct"] = breakout_threshold_pct
    out["breakout_threshold_atr"] = breakout_threshold_atr
    out["breakout_volume_ratio"] = breakout_volume_ratio

    return out
