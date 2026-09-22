"""P0 pattern detectors — docs/charting.md §13.1 (HH/HL), §13.2 (S/R), §13.3 (rectangle),
§13.9 (breakout/retest), §17 (false breakout), wired to the §11 lifecycle in `lifecycle.py`
and the §30.1 geometry predicates in `geometry.py`.

Single entry point: `detect_as_of(bars, t, cfg=CONFIG, symbol="UNKNOWN", incomplete_bar=None,
unresolved_gap_dates=None, evaluate_research_eligibility=False)`.
Point-in-time contract (PRD §2.2, restated here because it governs every line below): `bars`
is sliced to `view = bars.iloc[:t+1]` FIRST, before any pivot/indicator/candidate work, and
every function in this module only ever reads `view` (or things derived from it) — never
the original `bars` again. This is what makes `test_patterns_lookahead.py`'s poisoned-future
probe meaningful: nothing after `t` can be in scope by construction, not by a later filter.

Scope boundary — `status` vs `RESEARCH_ELIGIBLE` (read before changing the lifecycle wiring):
this package (plan.md E-1..E-4) computes and stores the seven `PatternComponents` faithfully,
and advances `status` through the primary §11 chain only as far as this package can honestly
confirm on price/volume/volatility evidence alone: ``CANDIDATE -> FORMING -> GEOMETRY_VALID ->
BREAKOUT_ATTEMPT -> PRICE_CONFIRMED -> VOLUME_CONFIRMED`` (or a terminal state). It never sets
`status` to `CONTEXT_VALIDATED`: that needs market/sector context (Phase 3, not built here).

E-5 update (2026-09-22, "wire lifecycle.research_eligible()"): this module CAN now advance a
qualifying `PRICE_CONFIRMED` snapshot straight to `RESEARCH_ELIGIBLE` (the exact G-2 chain-skip
edge `lifecycle.ALLOWED_TRANSITIONS` already allows), via `lifecycle.research_eligible()` —
but ONLY when the caller opts in with `evaluate_research_eligibility=True`. Default is `False`,
matching every pre-existing call site (`replay.py`, `export.py`) and every pre-E-5 test: those
were written against "this module never emits RESEARCH_ELIGIBLE" and their assertions (e.g.
`test_replay.py`'s `"PRICE_CONFIRMED" in statuses_seen` — replay walks bar-by-bar and would
otherwise never observe a bare `PRICE_CONFIRMED` status once a pattern instantly qualifies)
depend on that. A downstream caller that wants the old always-silent behavior, or one that
wants E-5 wired live, both get an honest, explicit choice — nothing changes by surprise for a
caller that does not ask for it. See `_maybe_research_eligible`.

Mutual exclusivity (task requirement: "a bar can never be both a valid breakout and a valid
failure"): a failure classification only ever fires against an ALREADY-confirmed breakout in
one direction (see `_walk_rectangle_lifecycle`). A bar with no prior confirmed direction is
always evaluated fresh as a candidate breakout/breakdown, never as a failure — see fixture 5b
(`test_patterns.py`), which is exactly this control.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Collection, Sequence

import numpy as np
import pandas as pd

from research.charting import geometry
from research.charting.config import CONFIG, relative_volume_band
from research.charting.lifecycle import (
    ComponentStatus,
    DataQualityStatus,
    FailureReason,
    LifecycleState,
    PatternComponents,
    research_eligible,
)
from research.charting.series import atr as atr_series_fn
from research.charting.series import relative_volume as relvol_series_fn
from research.charting.swings import Pivot, find_swings

_LOOKBACK_MULTIPLIER = 3  # v1 performance/relevance bound — see module docstring in _lookback_start


# ── Serialisable output — must match research/charting/SNAPSHOT_SCHEMA.md exactly ───────────

_COMPONENT_TO_SNAPSHOT = {
    ComponentStatus.CONFIRMED: "PASS",
    ComponentStatus.FAILED: "FAIL",
    ComponentStatus.PENDING: "PENDING",
}


@dataclass(frozen=True)
class RuleRow:
    rule_id: str
    result: str  # "PASS" | "FAIL"
    observed: Any
    threshold: Any

    def to_dict(self) -> dict:
        return {"rule_id": self.rule_id, "result": self.result, "observed": self.observed, "threshold": self.threshold}


@dataclass
class PatternSnapshot:
    """Exactly the shape documented in SNAPSHOT_SCHEMA.md's "Pattern objects" section."""

    pattern_id: str
    pattern_type: str
    direction: str  # BULLISH | BEARISH | NEUTRAL
    population: str  # always "CONFIRMED" here — see module docstring
    status: str
    stage: str | None  # always None here (§34 early-stage scoring is a separate package)
    formation_start: str
    formation_end: str
    levels: dict
    pivots: list[dict]
    components: dict
    rules: list[dict]
    events: list[dict]
    scores: None = None
    # §35.2 amendment additions (N§13, "Retest quality: penetration depth, number of
    # attempts, retest volume, time to retest, time to continuation" -- descriptive only,
    # never a confirmation gate). One consolidated block rather than per-event fields: these
    # are properties of the retest EPISODE as a whole (deepest penetration reached, total
    # attempts, bar counts to/from it), not of any single RETEST_* bar. `None` when the
    # pattern never reached PRICE_CONFIRMED (retest is not yet applicable); once confirmed,
    # always a dict -- see `_walk_retest_and_failure`'s `_quality` closure for the
    # "confirmed but no pullback ever observed" case (attempts=0, fields None, `note` set).
    retest_quality: dict | None = None

    def to_dict(self) -> dict:
        return {
            "pattern_id": self.pattern_id,
            "pattern_type": self.pattern_type,
            "direction": self.direction,
            "population": self.population,
            "status": self.status,
            "stage": self.stage,
            "formation_start": self.formation_start,
            "formation_end": self.formation_end,
            "levels": self.levels,
            "pivots": self.pivots,
            "components": self.components,
            "rules": self.rules,
            "events": self.events,
            "scores": self.scores,
            "retest_quality": self.retest_quality,
        }


def _components_dict(pc: PatternComponents) -> dict:
    return {
        "geometry": _COMPONENT_TO_SNAPSHOT[pc.geometry],
        "price": _COMPONENT_TO_SNAPSHOT[pc.price],
        "volume": _COMPONENT_TO_SNAPSHOT[pc.volume],
        "volatility": _COMPONENT_TO_SNAPSHOT[pc.volatility],
        # market/sector context is Phase 3 (not built by this package) — always UNAVAILABLE.
        "market": "UNAVAILABLE",
        "sector": "UNAVAILABLE",
        "data_quality": pc.data_quality.value,
    }


def _iso(d: Any) -> str:
    return pd.Timestamp(d).date().isoformat()


def _pivot_dict(t: geometry.Touch) -> dict:
    return {"date": _iso(t.pivot_date), "price": t.price, "kind": t.kind, "confirmed_date": _iso(t.confirmed_date)}


def _candle_quality(view: pd.DataFrame, idx: int) -> dict:
    """N§8 breakout candle quality (docs/charting.md §35.2 -- "body % and close location
    stored as descriptive fields, not confirmation gates until validated"), computed from the
    CONFIRMING bar's own OHLC only (bar `idx`, always the same bar that records the
    PRICE_CONFIRMED event it is attached to -- point-in-time by construction, nothing later
    is ever read):

        body_pct        = |close - open| / (high - low)
        close_location  = (close - low) / (high - low)   # 0 = at the bar's low, 1 = at its high

    A zero-range bar (`high == low` -- e.g. a circuit-frozen session) makes both
    geometrically undefined: returns `None` for each, never NaN or a ZeroDivisionError (the
    backend serves strict JSON -- §35 JSON-safety)."""
    o = float(view["open"].iloc[idx])
    h = float(view["high"].iloc[idx])
    l = float(view["low"].iloc[idx])
    c = float(view["close"].iloc[idx])
    rng = h - l
    if not (np.isfinite(o) and np.isfinite(h) and np.isfinite(l) and np.isfinite(c)) or rng <= 0:
        return {"body_pct": None, "close_location": None}
    return {"body_pct": abs(c - o) / rng, "close_location": (c - l) / rng}


def _lookback_start(t: int, cfg: dict) -> int:
    """v1 performance/relevance bound: only cluster pivots within
    `maximum_pattern_length * _LOOKBACK_MULTIPLIER` bars of `t`. A rectangle or structure
    that fully formed and never resolved further back than this is not reconstructed —
    documented scope choice (not a PIT concern: it only ever narrows the window toward `t`,
    never reads past it)."""
    return max(0, t - cfg["maximum_pattern_length"] * _LOOKBACK_MULTIPLIER)


# ── Rectangle consolidation (§13.3) — candidate search ───────────────────────────────────


def _rectangle_candidates(
    view: pd.DataFrame, t: int, pivots: Sequence[Pivot], atr_ser: pd.Series, cfg: dict,
    unresolved_gap_dates: Collection[Any] | None = None,
) -> list[dict]:
    """Every (resistance_level, support_level) pair with a valid rectangle formation inside
    [lookback_start, t]. The EARLIEST valid `formation_end` is kept per level pair — the
    pattern locks in the moment its geometry first qualifies; later bars are breakout
    evaluation, not re-validated formation.

    "No unresolved data gaps" (§13.3 Formation) — `unresolved_gap_dates` (optional; a
    caller-supplied collection of dates known to be interior data gaps for THIS symbol, e.g.
    `{f.date for f in validate.validate_symbol(df, calendar=universe_calendar) if
    f.rule_id == "MISSING_CANDLE"}`): §13.3 lists this alongside "Minimum 15 candles", "At
    least two resistance touches", etc. — every one of those siblings is already a hard
    formation gate below (a candidate `formation_end` that fails it is skipped, never scored
    "a bit less cleanly"), so this is implemented the same way for consistency with the rest
    of this function: a `formation_end` whose [formation_start, formation_end] DATE range
    contains any of `unresolved_gap_dates` is rejected outright, exactly like a candidate that
    fails the flat-boundary or 70%-inside-zone checks.

    `unresolved_gap_dates=None` (the default) means "not checked" — this module has no
    whole-universe trading calendar of its own (validate.py's MISSING_CANDLE explicitly needs
    one; see validate.build_trading_calendar's own docstring), so with no calendar supplied
    the gap gate is simply skipped, not silently assumed clean. Every pre-existing call site
    and fixture (which never pass this parameter) is therefore byte-for-byte unaffected.
    """
    lookback_start = _lookback_start(t, cfg)
    recent = [p for p in pivots if p.pivot_index >= lookback_start]
    if not recent:
        return []

    atr_t = atr_ser.iloc[t] if t < len(atr_ser) else float("nan")
    resistance_levels = [
        lvl for lvl in geometry.cluster_pivots_into_levels(recent, view, atr_t, cfg, kind="HIGH")
        if len(lvl.touches) >= cfg["pattern_boundary_min_touches"]
    ]
    support_levels = [
        lvl for lvl in geometry.cluster_pivots_into_levels(recent, view, atr_t, cfg, kind="LOW")
        if len(lvl.touches) >= cfg["pattern_boundary_min_touches"]
    ]
    if not resistance_levels or not support_levels:
        return []

    closes = view["close"].to_numpy(dtype=float)
    min_touch = cfg["pattern_boundary_min_touches"]
    candidates: list[dict] = []
    seen: set[tuple] = set()

    for res in resistance_levels:
        for sup in support_levels:
            if res.price <= sup.price:
                continue
            first_touch = min(tt.pivot_index for tt in (*res.touches, *sup.touches))
            # Allow up to `minimum_pattern_length - 1` bars of "approach" before the first
            # confirmed touch (a rectangle's own two touches, by definition, cannot appear
            # until partway into its formation — RECT-1's earliest touch is fixture bar 3,
            # two bars after the true formation start at fixture bar 1). Anchoring
            # formation_start strictly to the first touch would make a minimum_pattern_length
            # window structurally unreachable whenever the touches themselves are clustered
            # late in the window, as RECT-1 is by construction.
            formation_start = max(lookback_start, first_touch - cfg["minimum_pattern_length"] + 1)
            res_idx_sorted = sorted(tt.pivot_index for tt in res.touches)
            sup_idx_sorted = sorted(tt.pivot_index for tt in sup.touches)
            earliest_qualifying = max(res_idx_sorted[min_touch - 1], sup_idx_sorted[min_touch - 1])
            end_lo = max(formation_start + cfg["minimum_pattern_length"] - 1, earliest_qualifying)
            end_hi = min(t, formation_start + cfg["maximum_pattern_length"] - 1)
            if end_lo > end_hi:
                continue

            found = None
            for formation_end in range(end_lo, end_hi + 1):
                res_in = [tt for tt in res.touches if tt.pivot_index <= formation_end]
                sup_in = [tt for tt in sup.touches if tt.pivot_index <= formation_end]
                if len(res_in) < min_touch or len(sup_in) < min_touch:
                    continue
                a = atr_ser.iloc[formation_end]
                if not geometry._atr_valid(a):
                    continue
                length = formation_end - formation_start + 1
                res_drift = geometry.boundary_drift(
                    geometry.ols_slope([x.pivot_index for x in res_in], [x.price for x in res_in]), length, a, cfg
                )
                sup_drift = geometry.boundary_drift(
                    geometry.ols_slope([x.pivot_index for x in sup_in], [x.price for x in sup_in]), length, a, cfg
                )
                if res_drift.direction != "FLAT" or sup_drift.direction != "FLAT":
                    continue
                window = closes[formation_start : formation_end + 1]
                inside_frac = float(np.mean((window > sup.price) & (window < res.price)))
                if inside_frac < 0.70:
                    continue
                range_ok = geometry.rectangle_range_ok(res.price, sup.price, a, cfg)
                if not range_ok.valid:
                    continue
                if unresolved_gap_dates:
                    start_date = view["date"].iloc[formation_start]
                    end_date = view["date"].iloc[formation_end]
                    if any(start_date <= pd.Timestamp(d) <= end_date for d in unresolved_gap_dates):
                        continue
                found = {
                    "resistance": res, "support": sup,
                    "formation_start": formation_start, "formation_end": formation_end,
                    "res_touches": tuple(res_in), "sup_touches": tuple(sup_in),
                    "inside_frac": inside_frac, "range_atr": range_ok.range_atr,
                    "res_drift": res_drift, "sup_drift": sup_drift, "length": length,
                }
                break
            if found is None:
                continue
            key = (round(found["resistance"].price, 4), round(found["support"].price, 4), found["formation_start"])
            if key in seen:
                continue
            seen.add(key)
            candidates.append(found)
    return candidates


def _followthrough_volume_rule(rel_vol: float, cfg: dict) -> RuleRow:
    """§12.3 follow-through volume confirmation band.

    Review 2026-09-22 (defect #5, "config.relative_volume_band has no production caller"):
    `observed` now records BOTH the raw relative-volume reading and its descriptive
    WEAK/NORMAL/SUPPORTING/STRONG band label (`config.relative_volume_band`) as a dict, purely
    for descriptive/reporting output -- the band label never drives PASS/FAIL/UNAVAILABLE
    here, which is (and was already) decided by the followthrough_min/max_rel_volume
    thresholds alone.
    """
    lo, hi = cfg["followthrough_min_rel_volume"], cfg["followthrough_max_rel_volume"]
    if not np.isfinite(rel_vol):
        observed = {"relative_volume": rel_vol, "band": None}  # never fabricate a band for a NaN reading
        return RuleRow("FOLLOWTHROUGH_VOLUME_UNAVAILABLE", "FAIL", observed, (lo, hi))
    observed = {"relative_volume": rel_vol, "band": relative_volume_band(rel_vol)}
    if rel_vol < lo:
        return RuleRow("FOLLOWTHROUGH_VOLUME_BELOW_MIN", "FAIL", observed, lo)
    if rel_vol > hi:
        return RuleRow("FOLLOWTHROUGH_VOLUME_ABOVE_MAX", "FAIL", observed, hi)
    return RuleRow("FOLLOWTHROUGH_VOLUME_BAND", "PASS", observed, (lo, hi))


def _maybe_research_eligible(
    state: LifecycleState, components: PatternComponents, cfg: dict, *, evaluate: bool,
) -> LifecycleState:
    """E-5 (spec.md S22, "Lifecycle wired to detectors"): PRICE_CONFIRMED may advance
    straight to RESEARCH_ELIGIBLE — exactly the G-2 chain-skip edge
    `lifecycle.ALLOWED_TRANSITIONS[LifecycleState.PRICE_CONFIRMED]` already allows — iff
    `lifecycle.research_eligible()` confirms every component the given `cfg` requires.

    Deliberately narrow in two ways:
    - Only when `evaluate=True` (the caller's explicit opt-in; see module docstring's E-5
      note for why this is not the default).
    - Only from `state == PRICE_CONFIRMED`, never from any other state. `research_eligible()`
      only inspects `components`, not a pattern's own failure/expiry history — e.g. in
      `_walk_rectangle_lifecycle`, `price` is set CONFIRMED at the moment of breakout and is
      NEVER reset even if the pattern later transitions to FAILED (fixture #3/#4/#5). Gating
      on the CURRENT state, not just the components, is what stops a FAILED/EXPIRED/
      INVALIDATED/GEOMETRY_VALID/BREAKOUT_ATTEMPT pattern from ever being misreported as
      RESEARCH_ELIGIBLE.
    """
    if not evaluate or state != LifecycleState.PRICE_CONFIRMED:
        return state
    return LifecycleState.RESEARCH_ELIGIBLE if research_eligible(components, cfg) else state


def _walk_retest_and_failure(
    view: pd.DataFrame, confirm_index: int, direction: str, broken_level: float, opposite_level: float | None,
    atr_ser: pd.Series, relvol_ser: pd.Series, t: int, cfg: dict, add_event, rules: list[RuleRow],
) -> tuple[LifecycleState, dict]:
    """§13.9 retest / §17 failure, bar-by-bar from `confirm_index + 1` through `t`.

    Factored out of `_walk_rectangle_lifecycle` (sub-task d) so SUPPORT_RESISTANCE and HH_HL
    reuse the identical, already-proven state machine instead of a second hand-copied
    implementation — RECTANGLE's own call site is a pure refactor (see that function's
    comments); its behaviour is unchanged.

    `broken_level` is the boundary just closed beyond: RECTANGLE's resistance/support,
    a standalone SUPPORT_RESISTANCE level's own price, or HH_HL's broken prior swing
    high/low. `opposite_level` is the far reference used for the §17 gap-through check
    (RECTANGLE's other boundary); pass `None` when the pattern has no natural opposite
    boundary (a standalone S/R level, or HH_HL) — the gap-through clause then simply never
    fires, and failure is decided by the failure-buffer close test alone, same as every
    other bar.

    Mutates the caller's `rules` list and calls the caller's `add_event` closure in place
    (matching how `_walk_rectangle_lifecycle` already accumulates both), rather than
    returning a fresh list, so every call site's existing accumulation/pattern_id/date
    plumbing is untouched. Returns the pattern's resulting `LifecycleState`: `FAILED` if a
    §17 failure fires within `failure_window_bars`, `PRICE_CONFIRMED` otherwise (whether or
    not a retest ever resolved) — mirroring `_walk_rectangle_lifecycle`'s "freeze after
    RETEST_SUCCESSFUL, freeze after the failure window closes with no failure" behaviour: once
    this returns, the caller stops evaluating further bars for this pattern instance.

    `retest_window_bars` semantics (review 2026-09-22, defect #2 — this CONFIG value was
    hashed but read by no code): a retest only counts as a retest if the pullback FIRST
    re-enters the broken level (`closes[i] <= broken_level` bullish / `>= broken_level`
    bearish — the same condition as before) within `retest_window_bars` bars of confirmation,
    i.e. at some `i` with `(i - confirm_index) <= retest_window_bars`. Once that window has
    closed with no pullback ever having entered the zone, this function stops opening a new
    `RETEST_PENDING` — the breakout is treated as holding, quietly, with no retest at all — but
    a pullback that already opened `RETEST_PENDING` while inside the window keeps resolving
    normally (RETEST_SUCCESSFUL or a failure) however many bars later that takes. This gate
    applies ONLY to opening a retest; the separate §17 failure rule (`failure_buffer_atr`,
    `failure_window_bars` — NI-2 frozen, unchanged by this fix) keeps evaluating every bar
    exactly as it did before, on its own independent window anchored at the same
    `confirm_index`.

    Retest quality (N§13, docs/charting.md §35.2, added 2026-09-22): now also returns a
    second value, the `retest_quality` dict described on `PatternSnapshot.retest_quality`.
    This is PURE bookkeeping laid on top of the state machine above without altering a single
    existing branch: `attempts`/`deepest_pen*` update only where the ALREADY-EXISTING
    `retest_pending` flag says a retest is genuinely open (piggybacked on its own transitions,
    never re-derived independently), plus one new `elif retest_pending:` branch for bars the
    original code silently did nothing on (retest pending, neither the success trigger nor a
    §17 failure fires that bar) -- a strict no-op in the original code, so adding bookkeeping
    there cannot change `state`/`events`/`rules`. Every `return` site is extended to also
    return this dict; no return VALUE (LifecycleState) or event/rule emission changes.
    """
    closes = view["close"].to_numpy(dtype=float)
    highs = view["high"].to_numpy(dtype=float)
    lows = view["low"].to_numpy(dtype=float)

    fail_buf = cfg["failure_buffer_atr"]
    fail_window = cfg["failure_window_bars"]
    retest_window = cfg["retest_window_bars"]
    cluster_width = cfg["level_cluster_width_atr"]
    retest_pending = False

    # N§13 retest-quality bookkeeping state -- read by `_quality()` below, never by the
    # state machine above.
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
        rvol = float(relvol_ser.iloc[deepest_pen_idx]) if deepest_pen_idx is not None else float("nan")
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
        a = atr_ser.iloc[i]
        if not geometry._atr_valid(a):
            continue
        within_window = (i - confirm_index) <= fail_window
        within_retest_window = (i - confirm_index) <= retest_window
        if direction == "BULLISH":
            failure_level = broken_level - fail_buf * a
            gapped_through = (highs[i] < opposite_level) if opposite_level is not None else False
            # NI-2 §5 gives ONE exact formula for the failure buffer (Close < prior_resistance
            # - failure_buffer_atr*ATR) — implemented verbatim, deliberately WITHOUT a looser
            # "close anywhere inside the pattern" trigger. See _walk_rectangle_lifecycle's
            # original comment (preserved in git history) for the full NI-2 §5 rationale.
            hard_failure = closes[i] < failure_level
            if within_window and (gapped_through or hard_failure):
                if retest_pending:  # a failure while a retest is already open still deepens it
                    pen = max(0.0, broken_level - lows[i])
                    if deepest_pen is None or pen > deepest_pen:
                        deepest_pen, deepest_pen_idx, deepest_pen_atr = pen, i, float(a)
                reason = FailureReason.GAP_FAILURE if gapped_through else (FailureReason.FAILED_RETEST if retest_pending else FailureReason.FALSE_BREAKOUT)
                add_event(i, "FAILED", reason.value, {"close": float(closes[i]), "failure_level": failure_level})
                rules.append(RuleRow("FAILURE_BUFFER_BREACH", "FAIL", float(closes[i]), failure_level))
                return LifecycleState.FAILED, _quality(i, False)
            if not retest_pending and within_retest_window and closes[i] <= broken_level:
                retest_pending = True
                attempts, first_entry_idx, last_bar_in_zone = 1, i, True
                deepest_pen, deepest_pen_idx, deepest_pen_atr = max(0.0, broken_level - lows[i]), i, float(a)
                add_event(i, "RETEST_PENDING", "RETEST_ZONE_ENTERED", {"close": float(closes[i]), "level": broken_level})
            elif retest_pending and closes[i] > broken_level + cluster_width * a:
                add_event(i, "RETEST_SUCCESSFUL", "CLOSE_ABOVE_RETEST_LEVEL", {"close": float(closes[i])})
                rules.append(RuleRow("RETEST_CONFIRMATION", "PASS", float(closes[i]), broken_level + cluster_width * a))
                return LifecycleState.PRICE_CONFIRMED, _quality(i, True)
            elif retest_pending:
                # Original code: a strict no-op (falls through to the next bar). New: track
                # re-entries into the zone (a fresh "attempt") and the deepest wick penetration
                # seen so far -- read-only bookkeeping, no event/rule/state ever emitted here.
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
                reason = FailureReason.GAP_FAILURE if gapped_through else (FailureReason.FAILED_RETEST if retest_pending else FailureReason.FALSE_BREAKOUT)
                add_event(i, "FAILED", reason.value, {"close": float(closes[i]), "failure_level": failure_level})
                rules.append(RuleRow("FAILURE_BUFFER_BREACH", "FAIL", float(closes[i]), failure_level))
                return LifecycleState.FAILED, _quality(i, False)
            if not retest_pending and within_retest_window and closes[i] >= broken_level:
                retest_pending = True
                attempts, first_entry_idx, last_bar_in_zone = 1, i, True
                deepest_pen, deepest_pen_idx, deepest_pen_atr = max(0.0, highs[i] - broken_level), i, float(a)
                add_event(i, "RETEST_PENDING", "RETEST_ZONE_ENTERED", {"close": float(closes[i]), "level": broken_level})
            elif retest_pending and closes[i] < broken_level - cluster_width * a:
                add_event(i, "RETEST_SUCCESSFUL", "CLOSE_BELOW_RETEST_LEVEL", {"close": float(closes[i])})
                rules.append(RuleRow("RETEST_CONFIRMATION", "PASS", float(closes[i]), broken_level - cluster_width * a))
                return LifecycleState.PRICE_CONFIRMED, _quality(i, True)
            elif retest_pending:
                bar_in_zone = closes[i] >= broken_level
                if bar_in_zone:
                    pen = max(0.0, highs[i] - broken_level)
                    if deepest_pen is None or pen > deepest_pen:
                        deepest_pen, deepest_pen_idx, deepest_pen_atr = pen, i, float(a)
                    if not last_bar_in_zone:
                        attempts += 1
                last_bar_in_zone = bar_in_zone

    return LifecycleState.PRICE_CONFIRMED, _quality(None, False)  # walk exhausted, no failure/retest resolution


def _walk_rectangle_lifecycle(
    view: pd.DataFrame, formation_start: int, formation_end: int, resistance: float, support: float,
    atr_ser: pd.Series, relvol_ser: pd.Series, t: int, cfg: dict,
) -> dict:
    """Bar-by-bar replay from `formation_end + 1` through `t`, evaluating §12.3 confirmation,
    §13.9 retest and §17 failure. Returns a dict of everything `_build_rectangle_snapshot`
    needs. See module docstring for the mutual-exclusivity guarantee.
    """
    closes = view["close"].to_numpy(dtype=float)
    highs = view["high"].to_numpy(dtype=float)
    lows = view["low"].to_numpy(dtype=float)
    dates = view["date"]

    buf = cfg["breakout_buffer_atr"]

    atr_baseline = atr_ser.iloc[formation_end]
    state = LifecycleState.GEOMETRY_VALID
    breakout_direction: str | None = None
    confirm_index: int | None = None
    attempt_index: int | None = None  # bar of the FIRST pending wick-only BREAKOUT_ATTEMPT
    events: list[dict] = []
    rules: list[RuleRow] = []
    price_c = ComponentStatus.PENDING
    volume_c = ComponentStatus.PENDING
    volatility_c = ComponentStatus.PENDING
    confirm_breakout_level: float | None = None
    confirm_breakdown_level: float | None = None

    def add_event(idx: int, event_type: str, rule_id: str, observed: dict) -> None:
        events.append({"date": _iso(dates.iloc[idx]), "event_type": event_type, "rule_id": rule_id, "observed_values": observed})

    # Phase 1: scan for the initial breakout/breakdown (§12.3), tracking BREAKOUT_ATTEMPT
    # (wick-only touches) and their confirmation_window_bars expiry along the way. Stops the
    # moment a close-confirmation fires (`break`) — phase 2 (retest/failure) takes over from
    # there via the shared `_walk_retest_and_failure` helper, exactly replicating what this
    # loop used to do inline for RECTANGLE (see git history for the pre-refactor version).
    for i in range(formation_end + 1, t + 1):
        a = atr_ser.iloc[i]
        if not geometry._atr_valid(a):
            continue
        bo_level = resistance + buf * a
        bd_level = support - buf * a

        # confirmation_window_bars expiry: a pending wick-only BREAKOUT_ATTEMPT (§12.3 "a
        # wick-only breach is BREAKOUT_ATTEMPT, not confirmation") that never closes beyond
        # the level within `confirmation_window_bars` bars of its FIRST touch must not sit
        # pending forever. Bars attempt_index+1 .. attempt_index+confirmation_window_bars are
        # still inside the window; strictly more than that many bars later, still unconfirmed,
        # the ATTEMPT expires — not the rectangle. The rectangle stays live (§13.3 invalidates
        # only on an opposite-boundary close, maximum age, or a reclaimed break), so the attempt
        # clock resets and scanning continues: a genuine close beyond the level on this same bar
        # or any later bar still confirms normally, and a later wick starts a fresh attempt.
        # (Ending the pattern here turned real breakouts into EXPIRED — ADANIPOWER 2026-04-02.)
        if attempt_index is not None and (i - attempt_index) > cfg["confirmation_window_bars"]:
            add_event(i, "BREAKOUT_ATTEMPT_EXPIRED", "BREAKOUT_ATTEMPT_WINDOW_EXPIRED", {
                "attempt_date": _iso(dates.iloc[attempt_index]),
                "bars_since_attempt": i - attempt_index,
                "confirmation_window_bars": cfg["confirmation_window_bars"],
            })
            rules.append(RuleRow("BREAKOUT_ATTEMPT_CONFIRMATION_WINDOW", "FAIL", i - attempt_index, cfg["confirmation_window_bars"]))
            attempt_index = None
            state = LifecycleState.GEOMETRY_VALID
        if closes[i] > bo_level:
            breakout_direction = "BULLISH"
            confirm_index = i
            confirm_breakout_level = bo_level
            confirm_breakdown_level = bd_level
            state = LifecycleState.PRICE_CONFIRMED
            price_c = ComponentStatus.CONFIRMED
            add_event(i, "PRICE_CONFIRMED", "CLOSE_ABOVE_BREAKOUT", {"close": float(closes[i]), "breakout_level": bo_level, **_candle_quality(view, i)})
            rules.append(RuleRow("CLOSE_ABOVE_BREAKOUT", "PASS", float(closes[i]), bo_level))
            rv = relvol_ser.iloc[i]
            vr = (a / atr_baseline) if geometry._atr_valid(atr_baseline) else float("nan")
            vol_rule = _followthrough_volume_rule(rv, cfg)
            rules.append(vol_rule)
            volume_c = ComponentStatus.CONFIRMED if vol_rule.result == "PASS" else ComponentStatus.FAILED
            atr_ok = np.isfinite(vr) and vr <= cfg["followthrough_max_atr_expansion"]
            rules.append(RuleRow("FOLLOWTHROUGH_ATR_EXPANSION", "PASS" if atr_ok else "FAIL", vr, cfg["followthrough_max_atr_expansion"]))
            volatility_c = ComponentStatus.CONFIRMED if atr_ok else ComponentStatus.FAILED
            break
        if closes[i] < bd_level:
            breakout_direction = "BEARISH"
            confirm_index = i
            confirm_breakout_level = bd_level
            confirm_breakdown_level = bo_level  # opposite-side threshold (for invalidation display)
            state = LifecycleState.PRICE_CONFIRMED
            price_c = ComponentStatus.CONFIRMED
            add_event(i, "PRICE_CONFIRMED", "CLOSE_BELOW_BREAKDOWN", {"close": float(closes[i]), "breakdown_level": bd_level, **_candle_quality(view, i)})
            rules.append(RuleRow("CLOSE_BELOW_BREAKDOWN", "PASS", float(closes[i]), bd_level))
            rv = relvol_ser.iloc[i]
            vr = (a / atr_baseline) if geometry._atr_valid(atr_baseline) else float("nan")
            vol_rule = _followthrough_volume_rule(rv, cfg)
            rules.append(vol_rule)
            volume_c = ComponentStatus.CONFIRMED if vol_rule.result == "PASS" else ComponentStatus.FAILED
            atr_ok = np.isfinite(vr) and vr <= cfg["followthrough_max_atr_expansion"]
            rules.append(RuleRow("FOLLOWTHROUGH_ATR_EXPANSION", "PASS" if atr_ok else "FAIL", vr, cfg["followthrough_max_atr_expansion"]))
            volatility_c = ComponentStatus.CONFIRMED if atr_ok else ComponentStatus.FAILED
            break
        if highs[i] >= bo_level or lows[i] <= bd_level:
            state = LifecycleState.BREAKOUT_ATTEMPT
            if attempt_index is None:
                attempt_index = i  # clock starts at the FIRST wick touch, never resets
            side = "UPPER" if highs[i] >= bo_level else "LOWER"
            add_event(i, "BREAKOUT_ATTEMPT", f"WICK_BREACH_{side}", {"high": float(highs[i]), "low": float(lows[i]), "breakout_level": bo_level, "breakdown_level": bd_level})
            rules.append(RuleRow(f"WICK_BREACH_{side}", "PASS", float(highs[i]) if side == "UPPER" else float(lows[i]), bo_level if side == "UPPER" else bd_level))

    # Phase 2: a breakout confirmed in phase 1 — evaluate retest / failure via the shared
    # helper (also used by SUPPORT_RESISTANCE / HH_HL — sub-task d).
    retest_quality: dict | None = None
    if breakout_direction is not None:
        opposite_level = support if breakout_direction == "BULLISH" else resistance
        broken_level = resistance if breakout_direction == "BULLISH" else support
        state, retest_quality = _walk_retest_and_failure(
            view, confirm_index, breakout_direction, broken_level, opposite_level, atr_ser, relvol_ser, t, cfg, add_event, rules,
        )

    if breakout_direction is None and (t - formation_end) > cfg["maximum_pattern_length"]:
        state = LifecycleState.EXPIRED

    return {
        "state": state, "direction": breakout_direction or "NEUTRAL",
        "price_component": price_c, "volume_component": volume_c, "volatility_component": volatility_c,
        "events": events, "rules": rules,
        "breakout_level": confirm_breakout_level, "invalidation_level": confirm_breakdown_level,
        "atr_baseline": atr_baseline,
        "retest_quality": retest_quality,
    }


def _build_rectangle_snapshot(
    view: pd.DataFrame, t: int, cand: dict, atr_ser: pd.Series, relvol_ser: pd.Series, cfg: dict, symbol: str,
    unresolved_gap_dates: Collection[Any] | None = None, evaluate_research_eligibility: bool = False,
) -> PatternSnapshot:
    resistance = cand["resistance"].price
    support = cand["support"].price
    formation_start, formation_end = cand["formation_start"], cand["formation_end"]
    a_end = atr_ser.iloc[formation_end]

    geometry_rules = [
        RuleRow("RECT_MIN_TOUCHES_RESISTANCE", "PASS", len(cand["res_touches"]), cfg["pattern_boundary_min_touches"]),
        RuleRow("RECT_MIN_TOUCHES_SUPPORT", "PASS", len(cand["sup_touches"]), cfg["pattern_boundary_min_touches"]),
        RuleRow("RECT_FLAT_RESISTANCE", "PASS", cand["res_drift"].drift_atr, cfg["flat_boundary_max_drift_atr"]),
        RuleRow("RECT_FLAT_SUPPORT", "PASS", cand["sup_drift"].drift_atr, cfg["flat_boundary_max_drift_atr"]),
        RuleRow("RECT_CLOSES_INSIDE_ZONE", "PASS", cand["inside_frac"], 0.70),
        RuleRow("RECT_RANGE_ATR", "PASS", cand["range_atr"], (cfg["rectangle_min_range_atr"], cfg["rectangle_max_range_atr"])),
        RuleRow("RECT_PATTERN_LENGTH", "PASS", cand["length"], (cfg["minimum_pattern_length"], cfg["maximum_pattern_length"])),
    ]
    # §13.3 "No unresolved data gaps": only a rule row when the caller actually supplied
    # gap data to check — a candidate that reaches this point already passed the
    # `_rectangle_candidates` gate (or the gate was never checked), so this is always PASS
    # when present; adding a FAIL-capable row here would be dead code (a gapped formation
    # window never produces a candidate at all — see _rectangle_candidates docstring).
    if unresolved_gap_dates is not None:
        geometry_rules.append(RuleRow("RECT_NO_UNRESOLVED_DATA_GAPS", "PASS", 0, 0))

    walk = _walk_rectangle_lifecycle(view, formation_start, formation_end, resistance, support, atr_ser, relvol_ser, t, cfg)

    default_breakout = resistance + cfg["breakout_buffer_atr"] * a_end if geometry._atr_valid(a_end) else None
    default_breakdown = support - cfg["breakout_buffer_atr"] * a_end if geometry._atr_valid(a_end) else None
    breakout_level = walk["breakout_level"] if walk["breakout_level"] is not None else default_breakout
    invalidation_level = walk["invalidation_level"] if walk["invalidation_level"] is not None else default_breakdown

    components = PatternComponents(
        geometry=ComponentStatus.CONFIRMED,
        price=walk["price_component"],
        volume=walk["volume_component"],
        volatility=walk["volatility_component"],
        data_quality=DataQualityStatus.VALID,
    )
    final_state = _maybe_research_eligible(walk["state"], components, cfg, evaluate=evaluate_research_eligibility)

    pivot_dicts = [_pivot_dict(x) for x in (*cand["res_touches"], *cand["sup_touches"])]
    pivot_dicts.sort(key=lambda d: d["date"])

    rules = [r.to_dict() for r in (*geometry_rules, *walk["rules"])]

    pattern_id = f"{symbol}:RECTANGLE:{_iso(view['date'].iloc[formation_start])}:{round(resistance, 2)}-{round(support, 2)}"

    return PatternSnapshot(
        pattern_id=pattern_id,
        pattern_type="RECTANGLE",
        direction=walk["direction"],
        population="CONFIRMED",
        status=final_state.value,
        stage=None,
        formation_start=_iso(view["date"].iloc[formation_start]),
        formation_end=_iso(view["date"].iloc[formation_end]),
        levels={
            "support": support, "resistance": resistance,
            "breakout_level": breakout_level, "invalidation_level": invalidation_level,
        },
        pivots=pivot_dicts,
        components=_components_dict(components),
        rules=rules,
        events=walk["events"],
        retest_quality=walk["retest_quality"],
    )


def _apply_incomplete_bar(snap: PatternSnapshot, incomplete_bar: dict, atr_at_t: float, cfg: dict) -> PatternSnapshot:
    """§7.2 / task requirement: "Incomplete candle never confirms
    (allow_intrabar_confirmation False)". Only meaningful for a RECTANGLE pattern still
    awaiting its first confirmation (GEOMETRY_VALID / BREAKOUT_ATTEMPT); a wick breach from
    the running candle is recorded as BREAKOUT_ATTEMPT, but PRICE_CONFIRMED is explicitly
    blocked and recorded as a FAILed rule row even when the running close is past the level —
    never silently ignored.
    """
    if snap.pattern_type != "RECTANGLE" or snap.status not in (LifecycleState.GEOMETRY_VALID.value, LifecycleState.BREAKOUT_ATTEMPT.value):
        return snap
    if not geometry._atr_valid(atr_at_t) or incomplete_bar.get("is_complete", False):
        return snap

    resistance = snap.levels["resistance"]
    support = snap.levels["support"]
    bo_level = resistance + cfg["breakout_buffer_atr"] * atr_at_t
    bd_level = support - cfg["breakout_buffer_atr"] * atr_at_t
    close = float(incomplete_bar["close"])
    high = float(incomplete_bar["high"])
    low = float(incomplete_bar["low"])
    date = _iso(incomplete_bar["date"])

    events = list(snap.events)
    rules = list(snap.rules)
    status = snap.status

    would_confirm_up = close > bo_level
    would_confirm_down = close < bd_level
    if would_confirm_up or would_confirm_down:
        rule_id = "CLOSE_ABOVE_BREAKOUT" if would_confirm_up else "CLOSE_BELOW_BREAKDOWN"
        level = bo_level if would_confirm_up else bd_level
        rules.append(RuleRow("INCOMPLETE_CANDLE_CONFIRMATION_BLOCKED", "FAIL", close, level).to_dict())
        events.append({
            "date": date, "event_type": "BREAKOUT_ATTEMPT", "rule_id": f"INCOMPLETE_CANDLE_{rule_id}_NOT_CONFIRMED",
            "observed_values": {"close": close, "level": level, "is_complete": False, "allow_intrabar_confirmation": cfg["allow_intrabar_confirmation"]},
        })
        status = LifecycleState.BREAKOUT_ATTEMPT.value
    elif high >= bo_level or low <= bd_level:
        side = "UPPER" if high >= bo_level else "LOWER"
        events.append({
            "date": date, "event_type": "BREAKOUT_ATTEMPT", "rule_id": f"WICK_BREACH_{side}_RUNNING",
            "observed_values": {"high": high, "low": low, "breakout_level": bo_level, "breakdown_level": bd_level, "is_complete": False},
        })
        rules.append(RuleRow(f"WICK_BREACH_{side}_RUNNING", "PASS", high if side == "UPPER" else low, bo_level if side == "UPPER" else bd_level).to_dict())
        status = LifecycleState.BREAKOUT_ATTEMPT.value

    snap.events = events
    snap.rules = rules
    snap.status = status
    return snap


# ── Standalone support/resistance levels (§13.2) ─────────────────────────────────────────


def _sr_level_patterns(
    view: pd.DataFrame, t: int, pivots: Sequence[Pivot], atr_ser: pd.Series, relvol_ser: pd.Series, cfg: dict, symbol: str,
    evaluate_research_eligibility: bool = False,
) -> list[PatternSnapshot]:
    """Standalone S/R levels: geometry (clustering + >=level_min_touches), then a bar-by-bar
    walk from the moment the level's own touches are all confirmed through `t` — the same
    §12.3 confirmation scan `_walk_rectangle_lifecycle` runs, generalized here (sub-task d)
    so a standalone level gets the identical §13.9 retest / §17 failure tracking once it
    confirms, via the shared `_walk_retest_and_failure` helper (RECTANGLE-only was E-4's
    original, explicitly narrower scope; this lifts that restriction).

    A level with NO close-confirmation anywhere in its own window still reports only its
    CURRENT (bar `t`) wick-touch state — there is nothing "pending" to retest yet, so this
    part of the original E-1 "as observed at t" scope is unchanged.
    """
    lookback_start = _lookback_start(t, cfg)
    recent = [p for p in pivots if p.pivot_index >= lookback_start]
    atr_t = atr_ser.iloc[t] if t < len(atr_ser) else float("nan")
    if not recent or not geometry._atr_valid(atr_t):
        return []

    out: list[PatternSnapshot] = []
    dates = view["date"]
    closes = view["close"].to_numpy(dtype=float)
    highs = view["high"].to_numpy(dtype=float)
    lows = view["low"].to_numpy(dtype=float)
    date_t = _iso(view["date"].iloc[t])

    for kind, level_kind, direction, buf_sign in (("HIGH", "RESISTANCE", "BULLISH", +1), ("LOW", "SUPPORT", "BEARISH", -1)):
        levels = [
            lvl for lvl in geometry.cluster_pivots_into_levels(recent, view, atr_t, cfg, kind=kind)
            if len(lvl.touches) >= cfg["level_min_touches"]
        ]
        for lvl in levels:
            level_price = lvl.price
            # PIT: the level is only "known" once every touch is confirmed — walk from
            # there, INCLUSIVE (see _hh_hl_patterns' identical comment on `confirmed_index`
            # for why this is not the rectangle-style formation_end+1 exclusive start).
            level_ready_index = max(x.confirmed_index for x in lvl.touches)
            rules: list[RuleRow] = [RuleRow("SR_MIN_TOUCHES", "PASS", len(lvl.touches), cfg["level_min_touches"])]
            events: list[dict] = []

            def add_event(idx: int, event_type: str, rule_id: str, observed: dict) -> None:
                events.append({"date": _iso(dates.iloc[idx]), "event_type": event_type, "rule_id": rule_id, "observed_values": observed})

            status = LifecycleState.GEOMETRY_VALID
            price_c = ComponentStatus.PENDING
            confirm_idx: int | None = None
            confirm_trigger: float | None = None
            confirm_rule_id = "CLOSE_ABOVE_RESISTANCE" if buf_sign > 0 else "CLOSE_BELOW_SUPPORT"

            for i in range(level_ready_index, t + 1):
                a = atr_ser.iloc[i]
                if not geometry._atr_valid(a):
                    continue
                trigger_i = level_price + buf_sign * cfg["breakout_buffer_atr"] * a
                confirmed_i = (closes[i] > trigger_i) if buf_sign > 0 else (closes[i] < trigger_i)
                if confirmed_i:
                    confirm_idx, confirm_trigger = i, trigger_i
                    status, price_c = LifecycleState.PRICE_CONFIRMED, ComponentStatus.CONFIRMED
                    add_event(i, "PRICE_CONFIRMED", confirm_rule_id, {"close": float(closes[i]), "level": trigger_i, **_candle_quality(view, i)})
                    rules.append(RuleRow(confirm_rule_id, "PASS", float(closes[i]), trigger_i))
                    break

            retest_quality: dict | None = None
            if confirm_idx is not None:
                status, retest_quality = _walk_retest_and_failure(
                    view, confirm_idx, direction, level_price, None, atr_ser, relvol_ser, t, cfg, add_event, rules,
                )
            else:
                trigger_t = level_price + buf_sign * cfg["breakout_buffer_atr"] * atr_t
                wick_touch = (highs[t] >= trigger_t) if buf_sign > 0 else (lows[t] <= trigger_t)
                if wick_touch:
                    status = LifecycleState.BREAKOUT_ATTEMPT
                    add_event(t, "BREAKOUT_ATTEMPT", "WICK_BREACH", {"high": float(highs[t]), "low": float(lows[t]), "level": trigger_t})
                    rules.append(RuleRow("WICK_BREACH", "PASS", float(highs[t]) if buf_sign > 0 else float(lows[t]), trigger_t))

            strength = geometry.level_strength(
                lvl, as_of_index=t, window_start=lookback_start, window_end=t,
                bars=view, relative_volume=relvol_ser, atr=atr_t, cfg=cfg,
            )
            rules.append(RuleRow("SR_LEVEL_STRENGTH", "PASS", round(strength.level_strength, 6), None))

            components = PatternComponents(
                geometry=ComponentStatus.CONFIRMED, price=price_c, data_quality=DataQualityStatus.VALID,
            )
            status = _maybe_research_eligible(status, components, cfg, evaluate=evaluate_research_eligibility)
            earliest = min(x.pivot_index for x in lvl.touches)
            pattern_id = f"{symbol}:SUPPORT_RESISTANCE:{_iso(view['date'].iloc[earliest])}:{round(level_price, 2)}"
            reported_trigger = confirm_trigger if confirm_trigger is not None else level_price + buf_sign * cfg["breakout_buffer_atr"] * atr_t
            out.append(PatternSnapshot(
                pattern_id=pattern_id, pattern_type="SUPPORT_RESISTANCE", direction=direction,
                population="CONFIRMED", status=status.value, stage=None,
                formation_start=_iso(view["date"].iloc[earliest]), formation_end=date_t,
                levels={"level": level_price, "kind": level_kind, "breakout_level" if buf_sign > 0 else "breakdown_level": reported_trigger},
                pivots=[_pivot_dict(x) for x in lvl.touches],
                components=_components_dict(components),
                rules=[r.to_dict() for r in rules],
                events=events,
                retest_quality=retest_quality,
            ))
    return out


# ── Higher-high / higher-low structure (§13.1) ───────────────────────────────────────────


def _hh_hl_patterns(
    view: pd.DataFrame, t: int, pivots: Sequence[Pivot], atr_ser: pd.Series, relvol_ser: pd.Series, cfg: dict, symbol: str,
    evaluate_research_eligibility: bool = False,
) -> list[PatternSnapshot]:
    """§13.1. Interpretation (PRD gives the rule, not the exact bar-count): "at least two
    confirmed higher highs" / "higher lows" is read as the last two consecutive transitions
    between confirmed same-kind pivots both being higher (needs >=3 pivots of that kind).
    Continuation confirmation ("latest meaningful high breaks the previous meaningful high")
    is read as `close[i] > most_recent_confirmed_HIGH.price + breakout_buffer_atr * ATR[i]`
    (review 2026-09-22, defect #3: this used to confirm on a bare `close[i] >
    most_recent_confirmed_HIGH.price`, with no breakout buffer at all — unlike every other
    P0 family's own confirmation trigger; ATR is read causally at the confirming bar `i`,
    exactly like RECTANGLE/SUPPORT_RESISTANCE's own buffer) — checked bar-by-bar from the
    moment the structure's own pivots are all confirmed through `t` (sub-task d: this used
    to check bar `t` only; now it is a proper walk so that, once confirmed, the broken swing
    gets the same §13.9 retest / §17 failure tracking as RECTANGLE and SUPPORT_RESISTANCE, via
    the shared `_walk_retest_and_failure` helper). `last_high`/`last_low` themselves are still
    the fixed, as-of-`t` structure (unchanged) — only WHEN the crossing is deemed to have
    first happened is now historical instead of "at t only".

    INVALIDATED is unchanged (no buffer — only defect #3's CONFIRMATION trigger gets one): it
    is evaluated in the same walk (first crossing wins, mirroring the original mutual
    exclusivity) and remains its own terminal outcome — a geometry invalidation is not "a
    failed retest of a confirmed breakout" and is never handed to the shared retest/failure
    helper. A bar whose ATR is not yet valid (warmup) is skipped entirely for BOTH checks,
    matching how every other family's own bar-by-bar walk treats an unusable ATR reading.
    """
    lookback_start = _lookback_start(t, cfg)
    highs = sorted((p for p in pivots if p.kind == "HIGH" and p.pivot_index >= lookback_start), key=lambda p: p.pivot_index)
    lows = sorted((p for p in pivots if p.kind == "LOW" and p.pivot_index >= lookback_start), key=lambda p: p.pivot_index)
    if len(highs) < 3 or len(lows) < 3:
        return []

    def _last_two_direction(seq: list[Pivot]) -> str | None:
        last3 = seq[-3:]
        up = last3[1].price > last3[0].price and last3[2].price > last3[1].price
        down = last3[1].price < last3[0].price and last3[2].price < last3[1].price
        if up:
            return "UP"
        if down:
            return "DOWN"
        return None

    high_dir = _last_two_direction(highs)
    low_dir = _last_two_direction(lows)
    if high_dir is None or low_dir is None or high_dir != low_dir:
        return []

    direction = "BULLISH" if high_dir == "UP" else "BEARISH"
    used_highs, used_lows = highs[-3:], lows[-3:]
    formation_start = min(x.pivot_index for x in (*used_highs, *used_lows))
    length = t - formation_start + 1
    if not (cfg["minimum_pattern_length"] <= length <= cfg["maximum_pattern_length"]):
        return []

    last_high, last_low = used_highs[-1], used_lows[-1]
    date_t = _iso(view["date"].iloc[t])
    dates = view["date"]
    closes = view["close"].to_numpy(dtype=float)

    rules: list[RuleRow] = [
        RuleRow("HH_HL_TREND_CONSISTENT", "PASS", high_dir, "UP/DOWN matches across highs and lows"),
        RuleRow("HH_HL_PATTERN_LENGTH", "PASS", length, (cfg["minimum_pattern_length"], cfg["maximum_pattern_length"])),
    ]
    events: list[dict] = []

    def add_event(idx: int, event_type: str, rule_id: str, observed: dict) -> None:
        events.append({"date": _iso(dates.iloc[idx]), "event_type": event_type, "rule_id": rule_id, "observed_values": observed})

    price_c = ComponentStatus.PENDING
    status = LifecycleState.GEOMETRY_VALID
    confirm_idx: int | None = None
    # PIT: the structure is only "known" once BOTH its most recent high and low pivots are
    # confirmed — walk from the later of the two (INCLUSIVE: the bar a pivot's own
    # `confirmed_index` names is the first bar its price is knowable at, so a close AT that
    # very bar is legitimate, already-observed information, not a peek). Unlike a rectangle's
    # `formation_end` (a dedicated last-bar-of-formation index, deliberately excluded from
    # breakout scanning), `confirmed_index` carries no such "this bar belongs to formation,
    # not evaluation" meaning — and the zigzag fixtures below rely on being able to confirm
    # on the very bar the structure becomes knowable.
    geometry_ready_index = max(last_high.confirmed_index, last_low.confirmed_index)

    for i in range(geometry_ready_index, t + 1):
        a = atr_ser.iloc[i]
        if not geometry._atr_valid(a):
            continue
        buf = cfg["breakout_buffer_atr"] * a
        c = closes[i]
        if direction == "BULLISH":
            confirm_level = last_high.price + buf
            if c > confirm_level:
                confirm_idx = i
                status, price_c = LifecycleState.PRICE_CONFIRMED, ComponentStatus.CONFIRMED
                add_event(i, "PRICE_CONFIRMED", "CLOSE_ABOVE_PRIOR_HIGH", {"close": float(c), "prior_high": last_high.price, "confirm_level": confirm_level, **_candle_quality(view, i)})
                rules.append(RuleRow("CLOSE_ABOVE_PRIOR_HIGH", "PASS", float(c), confirm_level))
                break
            if c < last_low.price:
                status = LifecycleState.INVALIDATED
                add_event(i, "INVALIDATED", "CLOSE_BELOW_INVALIDATION_SWING", {"close": float(c), "invalidation_swing": last_low.price})
                rules.append(RuleRow("CLOSE_BELOW_INVALIDATION_SWING", "FAIL", float(c), last_low.price))
                break
        else:
            confirm_level = last_low.price - buf
            if c < confirm_level:
                confirm_idx = i
                status, price_c = LifecycleState.PRICE_CONFIRMED, ComponentStatus.CONFIRMED
                add_event(i, "PRICE_CONFIRMED", "CLOSE_BELOW_PRIOR_LOW", {"close": float(c), "prior_low": last_low.price, "confirm_level": confirm_level, **_candle_quality(view, i)})
                rules.append(RuleRow("CLOSE_BELOW_PRIOR_LOW", "PASS", float(c), confirm_level))
                break
            if c > last_high.price:
                status = LifecycleState.INVALIDATED
                add_event(i, "INVALIDATED", "CLOSE_ABOVE_INVALIDATION_SWING", {"close": float(c), "invalidation_swing": last_high.price})
                rules.append(RuleRow("CLOSE_ABOVE_INVALIDATION_SWING", "FAIL", float(c), last_high.price))
                break

    retest_quality: dict | None = None
    if confirm_idx is not None:
        broken_level = last_high.price if direction == "BULLISH" else last_low.price
        opposite_level = last_low.price if direction == "BULLISH" else last_high.price
        status, retest_quality = _walk_retest_and_failure(
            view, confirm_idx, direction, broken_level, opposite_level, atr_ser, relvol_ser, t, cfg, add_event, rules,
        )

    components = PatternComponents(geometry=ComponentStatus.CONFIRMED, price=price_c, data_quality=DataQualityStatus.VALID)
    status = _maybe_research_eligible(status, components, cfg, evaluate=evaluate_research_eligibility)
    pattern_id = f"{symbol}:HH_HL:{_iso(view['date'].iloc[formation_start])}:{direction}"
    pivot_dicts = [
        {"date": _iso(p.pivot_date), "price": p.price, "kind": p.kind, "confirmed_date": _iso(p.confirmed_date)}
        for p in sorted((*used_highs, *used_lows), key=lambda p: p.pivot_index)
    ]
    return [PatternSnapshot(
        pattern_id=pattern_id, pattern_type="HH_HL", direction=direction, population="CONFIRMED",
        status=status.value, stage=None,
        formation_start=_iso(view["date"].iloc[formation_start]), formation_end=date_t,
        levels={"prior_high": last_high.price, "prior_low": last_low.price},
        pivots=pivot_dicts,
        components=_components_dict(components),
        rules=[r.to_dict() for r in rules],
        events=events,
        retest_quality=retest_quality,
    )]


# ── Entry point ───────────────────────────────────────────────────────────────────────────


def detect_as_of(
    bars: pd.DataFrame, t: int, cfg: dict = CONFIG, *, symbol: str = "UNKNOWN", incomplete_bar: dict | None = None,
    unresolved_gap_dates: Collection[Any] | None = None, evaluate_research_eligibility: bool = False,
) -> list[PatternSnapshot]:
    """Every P0 pattern known at bar `t`, using `bars[0..t]` ONLY.

    `incomplete_bar` (optional): a running/not-yet-completed candle dated after `t` (the
    `synth.fixture_12_incomplete_candle` shape: BARS_COLUMNS fields + `is_complete`). It is
    never added as a row to the frame patterns are detected from — it is evaluated only for
    RECTANGLE patterns still awaiting confirmation, and only for BREAKOUT_ATTEMPT (wick)
    purposes; it can never produce a PRICE_CONFIRMED event (§7.2, `allow_intrabar_confirmation`).

    `unresolved_gap_dates` (optional): dates known to be interior data gaps for THIS symbol
    (§13.3 "No unresolved data gaps" — see `_rectangle_candidates`). This module has no
    whole-universe trading calendar of its own, so it never derives this itself; a caller
    that does have one (validate.py + the full symbol universe) threads it through here.
    `None` (the default) means "not checked" and reproduces every pre-existing call's output
    exactly — this is RECTANGLE-only (§13.3 is a rectangle-formation rule).

    `evaluate_research_eligibility` (default False, E-5 — see module docstring): when True,
    a qualifying PRICE_CONFIRMED snapshot (any pattern type) is advanced to RESEARCH_ELIGIBLE
    via `lifecycle.research_eligible()`. Opt-in so every pre-existing caller/test keeps its
    pre-E-5 meaning unless it explicitly asks for the new behaviour.
    """
    view = bars.iloc[: t + 1].reset_index(drop=True)
    if len(view) == 0:
        return []

    pivots = find_swings(view, left_bars=cfg["swing_left_bars"], right_bars=cfg["swing_right_bars"])
    atr_ser = atr_series_fn(view, period=cfg["atr_period"])
    relvol_ser = relvol_series_fn(view, n=cfg["volume_baseline_bars"])

    patterns: list[PatternSnapshot] = []

    for cand in _rectangle_candidates(view, t, pivots, atr_ser, cfg, unresolved_gap_dates=unresolved_gap_dates):
        snap = _build_rectangle_snapshot(
            view, t, cand, atr_ser, relvol_ser, cfg, symbol,
            unresolved_gap_dates=unresolved_gap_dates, evaluate_research_eligibility=evaluate_research_eligibility,
        )
        if incomplete_bar is not None:
            atr_t = atr_ser.iloc[t] if t < len(atr_ser) else float("nan")
            snap = _apply_incomplete_bar(snap, incomplete_bar, atr_t, cfg)
        patterns.append(snap)

    patterns.extend(_sr_level_patterns(view, t, pivots, atr_ser, relvol_ser, cfg, symbol, evaluate_research_eligibility=evaluate_research_eligibility))
    patterns.extend(_hh_hl_patterns(view, t, pivots, atr_ser, relvol_ser, cfg, symbol, evaluate_research_eligibility=evaluate_research_eligibility))

    return patterns
