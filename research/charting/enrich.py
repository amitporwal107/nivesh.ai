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
  - `candle_quality` / `retest_quality` (CANDLE-MOVE, 2026-09-22, docs/charting.md §38.18
    decisions-log #93/#110, "Candle/retest metrics -- ACCEPT. They move from the production
    pattern record into the research record."): these used to be computed BY `patterns.py`
    itself (`body_pct`/`close_location` spliced into the PRICE_CONFIRMED event's
    `observed_values`, and a pattern-level `retest_quality` block) -- see git history for the
    pre-move shape, still documented as the historical schema in
    `research/charting/tests/test_patterns_lookahead.py`'s own comments. They are now computed
    HERE instead, by `_candle_quality`/`_compute_retest_quality` below (the same formulas,
    literally relocated, not reduced or approximated), same "where applicable" PIT gate as the
    breakout metrics above (only once a PRICE_CONFIRMED event exists with date `<= t`). Both
    read `pattern_dict["levels"]`/`["direction"]`/`["pattern_type"]` (the RAW resistance/
    support/prior-high/prior-low a breakout broke through -- a different number from the
    ATR-buffered `breakout_level` trigger above, see `_broken_and_opposite_level`'s own note)
    plus the truncated `bars`, never `patterns.py` (still never imported here).

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

import numpy as np
import pandas as pd

from research.charting import geometry, regime, states
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


def _candle_quality(view: pd.DataFrame, idx: int) -> dict:
    """N§8 breakout candle quality (docs/charting.md §35.2 -- "body % and close location
    stored as descriptive fields, not confirmation gates until validated"), computed from the
    CONFIRMING bar's own OHLC only (bar `idx`):

        body_pct        = |close - open| / (high - low)
        close_location  = (close - low) / (high - low)   # 0 = at the bar's low, 1 = at its high

    A zero-range bar (`high == low` -- e.g. a circuit-frozen session) makes both
    geometrically undefined: returns `None` for each, never NaN or a ZeroDivisionError.

    CANDLE-MOVE (2026-09-22): moved here verbatim from `research.charting.patterns`
    (docs/charting.md §38.18 decisions-log #93/#110) -- same formula, same edge-case
    handling, only the caller changed (this module's `enrich_pattern`, not
    `_walk_rectangle_lifecycle` / `_sr_level_patterns` / `_hh_hl_patterns`)."""
    o = float(view["open"].iloc[idx])
    h = float(view["high"].iloc[idx])
    l = float(view["low"].iloc[idx])
    c = float(view["close"].iloc[idx])
    rng = h - l
    if not (np.isfinite(o) and np.isfinite(h) and np.isfinite(l) and np.isfinite(c)) or rng <= 0:
        return {"body_pct": None, "close_location": None}
    return {"body_pct": abs(c - o) / rng, "close_location": (c - l) / rng}


# Which `pattern_dict["levels"]` keys hold the RAW level a confirmed breakout broke through
# (never the ATR-buffered trigger `_LEVEL_KEYS` reads -- see that constant's own note), and
# the opposite boundary (§17 gap-through reference; `None` when the pattern type has none) --
# keyed by direction, mirroring exactly what patterns.py's own three call sites passed into
# `_walk_retest_and_failure` before CANDLE-MOVE (read but not imported here; see
# `_walk_rectangle_lifecycle` / `_sr_level_patterns` / `_hh_hl_patterns` in patterns.py, kept
# in sync by their shared test coverage in test_enrich.py).
_RECTANGLE_LEVEL_KEYS = {"BULLISH": ("resistance", "support"), "BEARISH": ("support", "resistance")}
_HH_HL_LEVEL_KEYS = {"BULLISH": ("prior_high", "prior_low"), "BEARISH": ("prior_low", "prior_high")}


def _broken_and_opposite_level(pattern_dict: dict) -> tuple[float | None, float | None]:
    """(broken_level, opposite_level) for `_compute_retest_quality`, read from
    `pattern_dict["levels"]`/`["pattern_type"]`/`["direction"]` -- `(None, None)` for a
    pattern type/direction this module does not recognise (never fabricated)."""
    levels = pattern_dict.get("levels") or {}
    pattern_type = pattern_dict.get("pattern_type")
    direction = pattern_dict.get("direction")
    if pattern_type == "RECTANGLE":
        pair = _RECTANGLE_LEVEL_KEYS.get(direction)
    elif pattern_type == "SUPPORT_RESISTANCE":
        return levels.get("level"), None
    elif pattern_type == "HH_HL":
        pair = _HH_HL_LEVEL_KEYS.get(direction)
    else:
        return None, None
    if pair is None:
        return None, None
    broken_key, opposite_key = pair
    return levels.get(broken_key), levels.get(opposite_key)


def _compute_retest_quality(
    view: pd.DataFrame, confirm_index: int, direction: str, broken_level: float, opposite_level: float | None,
    atr_arr: np.ndarray, relvol_arr: np.ndarray, t: int, cfg: dict,
) -> dict:
    """N§13 retest quality (docs/charting.md §35.2), computed point-in-time from bars <= `t`
    only, for one already-confirmed pattern:

        attempts                     = count of distinct dips into the broken level's zone
        penetration_atr / _pct       = the DEEPEST intrabar penetration beyond the broken
                                        level seen during the retest episode, in ATR units
                                        and as a % of the broken level
        retest_relative_volume       = relative volume at the bar of that deepest penetration
        bars_confirmation_to_retest  = first zone-entry bar index - confirmation bar index
        bars_retest_to_continuation  = resolution bar index - first zone-entry bar index,
                                        ONLY when the retest resolved successfully
        note                         = set (fields None, attempts 0) when no pullback into
                                        the broken level was ever observed

    CANDLE-MOVE (2026-09-22): moved here from `research.charting.patterns`'s
    `_walk_retest_and_failure` (docs/charting.md §38.18 decisions-log #93/#110) -- the SAME
    bar-by-bar walk and the SAME failure-buffer / retest-window / cluster-width formulas
    (`cfg["failure_buffer_atr"]`, `cfg["failure_window_bars"]`, `cfg["retest_window_bars"]`,
    `cfg["level_cluster_width_atr"]`), so this reaches the identical resolution bar/outcome
    `patterns.py`'s own state machine does for the same inputs -- see
    `test_patterns_retest_quality.py`'s hand-computed cases, now asserted against THIS
    function's output via `enrich_pattern`. Deliberately duplicated rather than imported
    (patterns.py is never imported here, per this module's own non-mutation/separation
    contract -- module docstring) and deliberately narrower than the original: it emits no
    events, no rules, and decides no `LifecycleState` -- `patterns.py` alone still owns those,
    unchanged by this move. `view`/`t` here are the caller's OWN `bars <= t` truncation
    (`enrich_pattern`'s `truncated`, `t` = `len(truncated) - 1`), not `patterns.py`'s.
    """
    closes = view["close"].to_numpy(dtype=float)
    highs = view["high"].to_numpy(dtype=float)
    lows = view["low"].to_numpy(dtype=float)

    fail_buf = cfg["failure_buffer_atr"]
    fail_window = cfg["failure_window_bars"]
    retest_window = cfg["retest_window_bars"]
    cluster_width = cfg["level_cluster_width_atr"]
    retest_pending = False

    attempts = 0
    first_entry_idx: int | None = None
    deepest_pen: float | None = None       # price units; worst intrabar penetration beyond broken_level
    deepest_pen_idx: int | None = None
    deepest_pen_atr: float | None = None   # ATR at deepest_pen_idx (already validated by the loop's own skip)
    last_bar_in_zone = False

    def _quality(resolution_idx: int | None, resolved_success: bool) -> dict:
        if first_entry_idx is None:
            return {
                "attempts": 0, "penetration_atr": None, "penetration_pct": None,
                "retest_relative_volume": None, "bars_confirmation_to_retest": None,
                "bars_retest_to_continuation": None,
                "note": "no pullback into the broken level observed within retest_window_bars",
            }
        pen_atr = (deepest_pen / deepest_pen_atr) if deepest_pen_atr else None
        pen_pct = (deepest_pen / broken_level * 100.0) if broken_level else None
        rvol = float(relvol_arr[deepest_pen_idx]) if deepest_pen_idx is not None else float("nan")
        return {
            "attempts": attempts,
            "penetration_atr": pen_atr if (pen_atr is not None and np.isfinite(pen_atr)) else None,
            "penetration_pct": pen_pct if (pen_pct is not None and np.isfinite(pen_pct)) else None,
            "retest_relative_volume": rvol if np.isfinite(rvol) else None,
            "bars_confirmation_to_retest": first_entry_idx - confirm_index,
            "bars_retest_to_continuation": (resolution_idx - first_entry_idx) if (resolved_success and resolution_idx is not None) else None,
            "note": None,
        }

    for i in range(confirm_index + 1, t + 1):
        a = atr_arr[i]
        if not geometry._atr_valid(a):
            continue
        within_window = (i - confirm_index) <= fail_window
        within_retest_window = (i - confirm_index) <= retest_window
        if direction == "BULLISH":
            failure_level = broken_level - fail_buf * a
            gapped_through = (highs[i] < opposite_level) if opposite_level is not None else False
            hard_failure = closes[i] < failure_level
            if within_window and (gapped_through or hard_failure):
                if retest_pending:  # a failure while a retest is already open still deepens it
                    pen = max(0.0, broken_level - lows[i])
                    if deepest_pen is None or pen > deepest_pen:
                        deepest_pen, deepest_pen_idx, deepest_pen_atr = pen, i, float(a)
                return _quality(i, False)
            if not retest_pending and within_retest_window and closes[i] <= broken_level:
                retest_pending = True
                attempts, first_entry_idx, last_bar_in_zone = 1, i, True
                deepest_pen, deepest_pen_idx, deepest_pen_atr = max(0.0, broken_level - lows[i]), i, float(a)
            elif retest_pending and closes[i] > broken_level + cluster_width * a:
                return _quality(i, True)
            elif retest_pending:
                bar_in_zone = closes[i] <= broken_level
                if bar_in_zone:
                    pen = max(0.0, broken_level - lows[i])
                    if deepest_pen is None or pen > deepest_pen:
                        deepest_pen, deepest_pen_idx, deepest_pen_atr = pen, i, float(a)
                    if not last_bar_in_zone:
                        attempts += 1
                last_bar_in_zone = bar_in_zone
        else:  # BEARISH — mirror of the bullish branch above.
            failure_level = broken_level + fail_buf * a
            gapped_through = (lows[i] > opposite_level) if opposite_level is not None else False
            hard_failure = closes[i] > failure_level
            if within_window and (gapped_through or hard_failure):
                if retest_pending:
                    pen = max(0.0, highs[i] - broken_level)
                    if deepest_pen is None or pen > deepest_pen:
                        deepest_pen, deepest_pen_idx, deepest_pen_atr = pen, i, float(a)
                return _quality(i, False)
            if not retest_pending and within_retest_window and closes[i] >= broken_level:
                retest_pending = True
                attempts, first_entry_idx, last_bar_in_zone = 1, i, True
                deepest_pen, deepest_pen_idx, deepest_pen_atr = max(0.0, highs[i] - broken_level), i, float(a)
            elif retest_pending and closes[i] < broken_level - cluster_width * a:
                return _quality(i, True)
            elif retest_pending:
                bar_in_zone = closes[i] >= broken_level
                if bar_in_zone:
                    pen = max(0.0, highs[i] - broken_level)
                    if deepest_pen is None or pen > deepest_pen:
                        deepest_pen, deepest_pen_idx, deepest_pen_atr = pen, i, float(a)
                    if not last_bar_in_zone:
                        attempts += 1
                last_bar_in_zone = bar_in_zone

    return _quality(None, False)  # walk exhausted, no failure/retest resolution


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
    # #110 needs to know whether this instance ever reached BREAKOUT_CANDIDATE. The pure mapping
    # cannot see that from a terminal status alone, but this record can: the event log is right
    # here, and `_find_price_confirmed_event` already reads it for the confirmation date.
    ever_price_confirmed = _find_price_confirmed_event(pattern_dict) is not None
    research_state = states.derive_research_state(
        pattern_dict["status"], None, pattern_dict["direction"], volume_status=volume_status,
        ever_price_confirmed=ever_price_confirmed,
    )

    out: dict[str, Any] = {
        "pattern_id": pattern_dict["pattern_id"],
        "as_of_date": ts.date().isoformat(),
        "research_state": research_state,
        # the inputs research_state was derived from, so an unmapped (None) state is never a dead end
        "research_state_basis": {"lifecycle_state": pattern_dict["status"], "volume_component": volume_status,
                                 "ever_price_confirmed": ever_price_confirmed},
    }

    for key, fv in regime.trend_classification(truncated, ts).items():
        out.update(fv.flatten(f"stock_trend_class_{key}"))
    for key, fv in regime.trend_classification(benchmark_df, ts).items():
        out.update(fv.flatten(f"market_trend_class_{key}"))

    breakout_level = breakout_threshold_pct = breakout_threshold_atr = breakout_volume_ratio = None
    candle_quality = None
    retest_quality = None
    if confirm_event is not None and pd.Timestamp(confirm_event["date"]).normalize() <= ts:
        confirm_idx = _bar_index_for_date(truncated, confirm_event["date"])
        if confirm_idx is not None:
            atr_series = atr_series_fn(truncated, period=CONFIG["atr_period"])
            relvol_series = relvol_series_fn(truncated, n=CONFIG["volume_baseline_bars"])

            level = _level_from_event(confirm_event)
            confirming_close = confirm_event.get("observed_values", {}).get("close")
            if level is not None and confirming_close is not None and level != 0.0:
                confirming_close = float(confirming_close)
                breakout_level = level
                breakout_threshold_pct = abs(confirming_close - level) / level * 100.0

                atr_at_confirm = atr_series.iloc[confirm_idx]
                if pd.notna(atr_at_confirm) and atr_at_confirm > 0:
                    breakout_threshold_atr = abs(confirming_close - level) / float(atr_at_confirm)

                relvol_at_confirm = relvol_series.iloc[confirm_idx]
                if pd.notna(relvol_at_confirm):
                    breakout_volume_ratio = float(relvol_at_confirm)

            # CANDLE-MOVE: candle/retest quality, computed HERE from `pattern_dict`'s own
            # levels/direction + the truncated bars -- see module docstring and
            # `_compute_retest_quality`'s own docstring for why this duplicates (rather than
            # imports) patterns.py's original formulas.
            candle_quality = _candle_quality(truncated, confirm_idx)

            broken_level, opposite_level = _broken_and_opposite_level(pattern_dict)
            if broken_level is not None:
                retest_quality = _compute_retest_quality(
                    truncated, confirm_idx, pattern_dict["direction"], broken_level, opposite_level,
                    atr_series.to_numpy(), relvol_series.to_numpy(), len(truncated) - 1, CONFIG,
                )

    out["breakout_level"] = breakout_level
    out["breakout_threshold_pct"] = breakout_threshold_pct
    out["breakout_threshold_atr"] = breakout_threshold_atr
    out["breakout_volume_ratio"] = breakout_volume_ratio
    out["candle_quality"] = candle_quality
    out["retest_quality"] = retest_quality

    return out
