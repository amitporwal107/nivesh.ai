"""P0 pattern detectors — docs/charting.md §13.1 (HH/HL), §13.2 (S/R), §13.3 (rectangle),
§13.9 (breakout/retest), §17 (false breakout), wired to the §11 lifecycle in `lifecycle.py`
and the §30.1 geometry predicates in `geometry.py`.

Single entry point: `detect_as_of(bars, t, cfg=CONFIG, symbol="UNKNOWN", incomplete_bar=None)`.
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
`status` to `CONTEXT_VALIDATED` or `RESEARCH_ELIGIBLE`: `CONTEXT_VALIDATED` needs market/sector
context (Phase 3, not built here), and `RESEARCH_ELIGIBLE` is E-5's explicit job (plan.md S22,
"Lifecycle wired to detectors") via `lifecycle.research_eligible()`, which a downstream caller
can call directly on the `components` this module returns. A pattern is therefore never
reported as `RESEARCH_ELIGIBLE` by this module, by construction, regardless of config flags.

Mutual exclusivity (task requirement: "a bar can never be both a valid breakout and a valid
failure"): a failure classification only ever fires against an ALREADY-confirmed breakout in
one direction (see `_walk_rectangle_lifecycle`). A bar with no prior confirmed direction is
always evaluated fresh as a candidate breakout/breakdown, never as a failure — see fixture 5b
(`test_patterns.py`), which is exactly this control.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Sequence

import numpy as np
import pandas as pd

from research.charting import geometry
from research.charting.config import CONFIG
from research.charting.lifecycle import ComponentStatus, DataQualityStatus, FailureReason, LifecycleState, PatternComponents
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


def _lookback_start(t: int, cfg: dict) -> int:
    """v1 performance/relevance bound: only cluster pivots within
    `maximum_pattern_length * _LOOKBACK_MULTIPLIER` bars of `t`. A rectangle or structure
    that fully formed and never resolved further back than this is not reconstructed —
    documented scope choice (not a PIT concern: it only ever narrows the window toward `t`,
    never reads past it)."""
    return max(0, t - cfg["maximum_pattern_length"] * _LOOKBACK_MULTIPLIER)


# ── Rectangle consolidation (§13.3) — candidate search ───────────────────────────────────


def _rectangle_candidates(view: pd.DataFrame, t: int, pivots: Sequence[Pivot], atr_ser: pd.Series, cfg: dict) -> list[dict]:
    """Every (resistance_level, support_level) pair with a valid rectangle formation inside
    [lookback_start, t]. The EARLIEST valid `formation_end` is kept per level pair — the
    pattern locks in the moment its geometry first qualifies; later bars are breakout
    evaluation, not re-validated formation. "No unresolved data gaps" (§13.3) is NOT checked
    here — deferred, see module docstring / final report."""
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
    lo, hi = cfg["followthrough_min_rel_volume"], cfg["followthrough_max_rel_volume"]
    if not np.isfinite(rel_vol):
        return RuleRow("FOLLOWTHROUGH_VOLUME_UNAVAILABLE", "FAIL", rel_vol, (lo, hi))
    if rel_vol < lo:
        return RuleRow("FOLLOWTHROUGH_VOLUME_BELOW_MIN", "FAIL", rel_vol, lo)
    if rel_vol > hi:
        return RuleRow("FOLLOWTHROUGH_VOLUME_ABOVE_MAX", "FAIL", rel_vol, hi)
    return RuleRow("FOLLOWTHROUGH_VOLUME_BAND", "PASS", rel_vol, (lo, hi))


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
    fail_buf = cfg["failure_buffer_atr"]
    fail_window = cfg["failure_window_bars"]
    cluster_width = cfg["level_cluster_width_atr"]

    atr_baseline = atr_ser.iloc[formation_end]
    state = LifecycleState.GEOMETRY_VALID
    breakout_direction: str | None = None
    confirm_index: int | None = None
    retest_pending = False
    events: list[dict] = []
    rules: list[RuleRow] = []
    price_c = ComponentStatus.PENDING
    volume_c = ComponentStatus.PENDING
    volatility_c = ComponentStatus.PENDING
    confirm_breakout_level: float | None = None
    confirm_breakdown_level: float | None = None

    def add_event(idx: int, event_type: str, rule_id: str, observed: dict) -> None:
        events.append({"date": _iso(dates.iloc[idx]), "event_type": event_type, "rule_id": rule_id, "observed_values": observed})

    terminal = False
    for i in range(formation_end + 1, t + 1):
        if terminal:
            break
        a = atr_ser.iloc[i]
        if not geometry._atr_valid(a):
            continue
        bo_level = resistance + buf * a
        bd_level = support - buf * a

        if breakout_direction is None:
            if closes[i] > bo_level:
                breakout_direction = "BULLISH"
                confirm_index = i
                confirm_breakout_level = bo_level
                confirm_breakdown_level = bd_level
                state = LifecycleState.PRICE_CONFIRMED
                price_c = ComponentStatus.CONFIRMED
                add_event(i, "PRICE_CONFIRMED", "CLOSE_ABOVE_BREAKOUT", {"close": float(closes[i]), "breakout_level": bo_level})
                rules.append(RuleRow("CLOSE_ABOVE_BREAKOUT", "PASS", float(closes[i]), bo_level))
                rv = relvol_ser.iloc[i]
                vr = (a / atr_baseline) if geometry._atr_valid(atr_baseline) else float("nan")
                vol_rule = _followthrough_volume_rule(rv, cfg)
                rules.append(vol_rule)
                volume_c = ComponentStatus.CONFIRMED if vol_rule.result == "PASS" else ComponentStatus.FAILED
                atr_ok = np.isfinite(vr) and vr <= cfg["followthrough_max_atr_expansion"]
                rules.append(RuleRow("FOLLOWTHROUGH_ATR_EXPANSION", "PASS" if atr_ok else "FAIL", vr, cfg["followthrough_max_atr_expansion"]))
                volatility_c = ComponentStatus.CONFIRMED if atr_ok else ComponentStatus.FAILED
                continue
            if closes[i] < bd_level:
                breakout_direction = "BEARISH"
                confirm_index = i
                confirm_breakout_level = bd_level
                confirm_breakdown_level = bo_level  # opposite-side threshold (for invalidation display)
                state = LifecycleState.PRICE_CONFIRMED
                price_c = ComponentStatus.CONFIRMED
                add_event(i, "PRICE_CONFIRMED", "CLOSE_BELOW_BREAKDOWN", {"close": float(closes[i]), "breakdown_level": bd_level})
                rules.append(RuleRow("CLOSE_BELOW_BREAKDOWN", "PASS", float(closes[i]), bd_level))
                rv = relvol_ser.iloc[i]
                vr = (a / atr_baseline) if geometry._atr_valid(atr_baseline) else float("nan")
                vol_rule = _followthrough_volume_rule(rv, cfg)
                rules.append(vol_rule)
                volume_c = ComponentStatus.CONFIRMED if vol_rule.result == "PASS" else ComponentStatus.FAILED
                atr_ok = np.isfinite(vr) and vr <= cfg["followthrough_max_atr_expansion"]
                rules.append(RuleRow("FOLLOWTHROUGH_ATR_EXPANSION", "PASS" if atr_ok else "FAIL", vr, cfg["followthrough_max_atr_expansion"]))
                volatility_c = ComponentStatus.CONFIRMED if atr_ok else ComponentStatus.FAILED
                continue
            if highs[i] >= bo_level or lows[i] <= bd_level:
                state = LifecycleState.BREAKOUT_ATTEMPT
                side = "UPPER" if highs[i] >= bo_level else "LOWER"
                add_event(i, "BREAKOUT_ATTEMPT", f"WICK_BREACH_{side}", {"high": float(highs[i]), "low": float(lows[i]), "breakout_level": bo_level, "breakdown_level": bd_level})
                rules.append(RuleRow(f"WICK_BREACH_{side}", "PASS", float(highs[i]) if side == "UPPER" else float(lows[i]), bo_level if side == "UPPER" else bd_level))
            continue

        # A breakout is already confirmed in `breakout_direction`. Evaluate retest / failure.
        within_window = (i - confirm_index) <= fail_window
        if breakout_direction == "BULLISH":
            failure_level = resistance - fail_buf * a
            gapped_through = highs[i] < support
            # NI-2 §5 gives ONE exact formula for the failure buffer (Close < prior_resistance
            # - failure_buffer_atr*ATR) — implemented verbatim, deliberately WITHOUT a looser
            # "close anywhere inside the pattern" trigger. §17.1's prose also lists "price
            # returns inside the pattern", but a shallow, still-above-the-failure-buffer close
            # (e.g. a legitimate §13.9 retest dip just under resistance) is inside the pattern
            # by that reading too — treating it as an immediate failure would misclassify every
            # ordinary retest as FALSE_BREAKOUT before it gets a chance to resolve. NI-2's own
            # framing ("Keeping failure_buffer_atr == breakout_buffer_atr means a bar cannot be
            # simultaneously a valid breakout and a valid failure") is written entirely in terms
            # of the buffer formula, so that is what this module treats as authoritative.
            hard_failure = closes[i] < failure_level
            if within_window and (gapped_through or hard_failure):
                reason = FailureReason.GAP_FAILURE if gapped_through else (FailureReason.FAILED_RETEST if retest_pending else FailureReason.FALSE_BREAKOUT)
                state = LifecycleState.FAILED
                add_event(i, "FAILED", reason.value, {"close": float(closes[i]), "failure_level": failure_level})
                rules.append(RuleRow("FAILURE_BUFFER_BREACH", "FAIL", float(closes[i]), failure_level))
                terminal = True
                continue
            if not retest_pending and closes[i] <= resistance:
                retest_pending = True
                add_event(i, "RETEST_PENDING", "RETEST_ZONE_ENTERED", {"close": float(closes[i]), "resistance": resistance})
            elif retest_pending and closes[i] > resistance + cluster_width * a:
                add_event(i, "RETEST_SUCCESSFUL", "CLOSE_ABOVE_RETEST_LEVEL", {"close": float(closes[i])})
                rules.append(RuleRow("RETEST_CONFIRMATION", "PASS", float(closes[i]), resistance + cluster_width * a))
                terminal = True
        else:  # BEARISH — mirror of the bullish branch; see its comment for the NI-2 §5 rationale.
            failure_level = support + fail_buf * a
            gapped_through = lows[i] > resistance
            hard_failure = closes[i] > failure_level
            if within_window and (gapped_through or hard_failure):
                reason = FailureReason.GAP_FAILURE if gapped_through else (FailureReason.FAILED_RETEST if retest_pending else FailureReason.FALSE_BREAKOUT)
                state = LifecycleState.FAILED
                add_event(i, "FAILED", reason.value, {"close": float(closes[i]), "failure_level": failure_level})
                rules.append(RuleRow("FAILURE_BUFFER_BREACH", "FAIL", float(closes[i]), failure_level))
                terminal = True
                continue
            if not retest_pending and closes[i] >= support:
                retest_pending = True
                add_event(i, "RETEST_PENDING", "RETEST_ZONE_ENTERED", {"close": float(closes[i]), "support": support})
            elif retest_pending and closes[i] < support - cluster_width * a:
                add_event(i, "RETEST_SUCCESSFUL", "CLOSE_BELOW_RETEST_LEVEL", {"close": float(closes[i])})
                rules.append(RuleRow("RETEST_CONFIRMATION", "PASS", float(closes[i]), support - cluster_width * a))
                terminal = True

    if breakout_direction is None and (t - formation_end) > cfg["maximum_pattern_length"]:
        state = LifecycleState.EXPIRED

    return {
        "state": state, "direction": breakout_direction or "NEUTRAL",
        "price_component": price_c, "volume_component": volume_c, "volatility_component": volatility_c,
        "events": events, "rules": rules,
        "breakout_level": confirm_breakout_level, "invalidation_level": confirm_breakdown_level,
        "atr_baseline": atr_baseline,
    }


def _build_rectangle_snapshot(view: pd.DataFrame, t: int, cand: dict, atr_ser: pd.Series, relvol_ser: pd.Series, cfg: dict, symbol: str) -> PatternSnapshot:
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

    pivot_dicts = [_pivot_dict(x) for x in (*cand["res_touches"], *cand["sup_touches"])]
    pivot_dicts.sort(key=lambda d: d["date"])

    rules = [r.to_dict() for r in (*geometry_rules, *walk["rules"])]

    pattern_id = f"{symbol}:RECTANGLE:{_iso(view['date'].iloc[formation_start])}:{round(resistance, 2)}-{round(support, 2)}"

    return PatternSnapshot(
        pattern_id=pattern_id,
        pattern_type="RECTANGLE",
        direction=walk["direction"],
        population="CONFIRMED",
        status=walk["state"].value,
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


def _sr_level_patterns(view: pd.DataFrame, t: int, pivots: Sequence[Pivot], atr_ser: pd.Series, relvol_ser: pd.Series, cfg: dict, symbol: str) -> list[PatternSnapshot]:
    """Standalone S/R levels: geometry (clustering + >=level_min_touches) and a same-bar
    price-confirmation check at `t` only — this package's simpler scope for E-1 (plan.md:
    "deterministic; breach types distinguished"). Full multi-bar retest/failure tracking is
    implemented for RECTANGLE only (E-4's explicit scope); a standalone level's `status`
    never advances past BREAKOUT_ATTEMPT/PRICE_CONFIRMED as observed at `t`.
    """
    lookback_start = _lookback_start(t, cfg)
    recent = [p for p in pivots if p.pivot_index >= lookback_start]
    atr_t = atr_ser.iloc[t] if t < len(atr_ser) else float("nan")
    if not recent or not geometry._atr_valid(atr_t):
        return []

    out: list[PatternSnapshot] = []
    close_t = float(view["close"].iloc[t])
    high_t = float(view["high"].iloc[t])
    low_t = float(view["low"].iloc[t])
    date_t = _iso(view["date"].iloc[t])
    rv_t = relvol_ser.iloc[t]

    for kind, level_kind, direction, buf_sign in (("HIGH", "RESISTANCE", "BULLISH", +1), ("LOW", "SUPPORT", "BEARISH", -1)):
        levels = [
            lvl for lvl in geometry.cluster_pivots_into_levels(recent, view, atr_t, cfg, kind=kind)
            if len(lvl.touches) >= cfg["level_min_touches"]
        ]
        for lvl in levels:
            level_price = lvl.price
            buffer = cfg["breakout_buffer_atr"] * atr_t
            trigger = level_price + buf_sign * buffer
            rules = [RuleRow("SR_MIN_TOUCHES", "PASS", len(lvl.touches), cfg["level_min_touches"])]
            events: list[dict] = []
            price_c = ComponentStatus.PENDING
            status = LifecycleState.GEOMETRY_VALID
            wick_touch = (high_t >= trigger) if buf_sign > 0 else (low_t <= trigger)
            confirmed = (close_t > trigger) if buf_sign > 0 else (close_t < trigger)
            rule_id = "CLOSE_ABOVE_RESISTANCE" if buf_sign > 0 else "CLOSE_BELOW_SUPPORT"
            if confirmed:
                status = LifecycleState.PRICE_CONFIRMED
                price_c = ComponentStatus.CONFIRMED
                events.append({"date": date_t, "event_type": "PRICE_CONFIRMED", "rule_id": rule_id, "observed_values": {"close": close_t, "level": trigger}})
                rules.append(RuleRow(rule_id, "PASS", close_t, trigger))
            elif wick_touch:
                status = LifecycleState.BREAKOUT_ATTEMPT
                events.append({"date": date_t, "event_type": "BREAKOUT_ATTEMPT", "rule_id": "WICK_BREACH", "observed_values": {"high": high_t, "low": low_t, "level": trigger}})
                rules.append(RuleRow("WICK_BREACH", "PASS", high_t if buf_sign > 0 else low_t, trigger))

            strength = geometry.level_strength(
                lvl, as_of_index=t, window_start=lookback_start, window_end=t,
                bars=view, relative_volume=relvol_ser, atr=atr_t, cfg=cfg,
            )
            rules.append(RuleRow("SR_LEVEL_STRENGTH", "PASS", round(strength.level_strength, 6), None))

            components = PatternComponents(
                geometry=ComponentStatus.CONFIRMED, price=price_c, data_quality=DataQualityStatus.VALID,
            )
            earliest = min(x.pivot_index for x in lvl.touches)
            pattern_id = f"{symbol}:SUPPORT_RESISTANCE:{_iso(view['date'].iloc[earliest])}:{round(level_price, 2)}"
            out.append(PatternSnapshot(
                pattern_id=pattern_id, pattern_type="SUPPORT_RESISTANCE", direction=direction,
                population="CONFIRMED", status=status.value, stage=None,
                formation_start=_iso(view["date"].iloc[earliest]), formation_end=date_t,
                levels={"level": level_price, "kind": level_kind, "breakout_level" if buf_sign > 0 else "breakdown_level": trigger},
                pivots=[_pivot_dict(x) for x in lvl.touches],
                components=_components_dict(components),
                rules=[r.to_dict() for r in rules],
                events=events,
            ))
    return out


# ── Higher-high / higher-low structure (§13.1) ───────────────────────────────────────────


def _hh_hl_patterns(view: pd.DataFrame, t: int, pivots: Sequence[Pivot], cfg: dict, symbol: str) -> list[PatternSnapshot]:
    """§13.1. Interpretation (PRD gives the rule, not the exact bar-count): "at least two
    confirmed higher highs" / "higher lows" is read as the last two consecutive transitions
    between confirmed same-kind pivots both being higher (needs >=3 pivots of that kind).
    Continuation confirmation ("latest meaningful high breaks the previous meaningful high")
    is read as `close[t] > most_recent_confirmed_HIGH.price` for the bullish case (mirrored
    for bearish) — directly checkable from bar t's own close, no future data needed.
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
    close_t = float(view["close"].iloc[t])
    date_t = _iso(view["date"].iloc[t])

    rules = [
        RuleRow("HH_HL_TREND_CONSISTENT", "PASS", high_dir, "UP/DOWN matches across highs and lows"),
        RuleRow("HH_HL_PATTERN_LENGTH", "PASS", length, (cfg["minimum_pattern_length"], cfg["maximum_pattern_length"])),
    ]
    events: list[dict] = []
    price_c = ComponentStatus.PENDING
    status = LifecycleState.GEOMETRY_VALID

    if direction == "BULLISH":
        if close_t > last_high.price:
            status, price_c = LifecycleState.PRICE_CONFIRMED, ComponentStatus.CONFIRMED
            events.append({"date": date_t, "event_type": "PRICE_CONFIRMED", "rule_id": "CLOSE_ABOVE_PRIOR_HIGH", "observed_values": {"close": close_t, "prior_high": last_high.price}})
            rules.append(RuleRow("CLOSE_ABOVE_PRIOR_HIGH", "PASS", close_t, last_high.price))
        elif close_t < last_low.price:
            status = LifecycleState.INVALIDATED
            events.append({"date": date_t, "event_type": "INVALIDATED", "rule_id": "CLOSE_BELOW_INVALIDATION_SWING", "observed_values": {"close": close_t, "invalidation_swing": last_low.price}})
            rules.append(RuleRow("CLOSE_BELOW_INVALIDATION_SWING", "FAIL", close_t, last_low.price))
    else:
        if close_t < last_low.price:
            status, price_c = LifecycleState.PRICE_CONFIRMED, ComponentStatus.CONFIRMED
            events.append({"date": date_t, "event_type": "PRICE_CONFIRMED", "rule_id": "CLOSE_BELOW_PRIOR_LOW", "observed_values": {"close": close_t, "prior_low": last_low.price}})
            rules.append(RuleRow("CLOSE_BELOW_PRIOR_LOW", "PASS", close_t, last_low.price))
        elif close_t > last_high.price:
            status = LifecycleState.INVALIDATED
            events.append({"date": date_t, "event_type": "INVALIDATED", "rule_id": "CLOSE_ABOVE_INVALIDATION_SWING", "observed_values": {"close": close_t, "invalidation_swing": last_high.price}})
            rules.append(RuleRow("CLOSE_ABOVE_INVALIDATION_SWING", "FAIL", close_t, last_high.price))

    components = PatternComponents(geometry=ComponentStatus.CONFIRMED, price=price_c, data_quality=DataQualityStatus.VALID)
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
    )]


# ── Entry point ───────────────────────────────────────────────────────────────────────────


def detect_as_of(
    bars: pd.DataFrame, t: int, cfg: dict = CONFIG, *, symbol: str = "UNKNOWN", incomplete_bar: dict | None = None,
) -> list[PatternSnapshot]:
    """Every P0 pattern known at bar `t`, using `bars[0..t]` ONLY.

    `incomplete_bar` (optional): a running/not-yet-completed candle dated after `t` (the
    `synth.fixture_12_incomplete_candle` shape: BARS_COLUMNS fields + `is_complete`). It is
    never added as a row to the frame patterns are detected from — it is evaluated only for
    RECTANGLE patterns still awaiting confirmation, and only for BREAKOUT_ATTEMPT (wick)
    purposes; it can never produce a PRICE_CONFIRMED event (§7.2, `allow_intrabar_confirmation`).
    """
    view = bars.iloc[: t + 1].reset_index(drop=True)
    if len(view) == 0:
        return []

    pivots = find_swings(view, left_bars=cfg["swing_left_bars"], right_bars=cfg["swing_right_bars"])
    atr_ser = atr_series_fn(view, period=cfg["atr_period"])
    relvol_ser = relvol_series_fn(view, n=cfg["volume_baseline_bars"])

    patterns: list[PatternSnapshot] = []

    for cand in _rectangle_candidates(view, t, pivots, atr_ser, cfg):
        snap = _build_rectangle_snapshot(view, t, cand, atr_ser, relvol_ser, cfg, symbol)
        if incomplete_bar is not None:
            atr_t = atr_ser.iloc[t] if t < len(atr_ser) else float("nan")
            snap = _apply_incomplete_bar(snap, incomplete_bar, atr_t, cfg)
        patterns.append(snap)

    patterns.extend(_sr_level_patterns(view, t, pivots, atr_ser, relvol_ser, cfg, symbol))
    patterns.extend(_hh_hl_patterns(view, t, pivots, cfg, symbol))

    return patterns
