"""NI-3 §3 — P-2 flags and pennants: a pole, then a P-1 shape.

The body IS a P-1 shape, so this module calls `patterns_p1.evaluate_candidate` and never
re-implements line fitting, the fit tolerance, containment, crossing or classification. Duplicating
that geometry is the one thing this family must not do: two copies of the seven-step engine would
drift, and only one of them is covered by the frozen fixtures.

One deliberate asymmetry. P-1 rejects FLAT/FLAT/PARALLEL with `SHAPE_FLAT_PARALLEL_IS_RECTANGLE`,
because as a standalone structure the live RECTANGLE family owns it. As a flag BODY it is valid —
NI-3 §3 lists "flat parallel (sideways)" for both bull and bear flags (§13.8 "countertrend or
sideways consolidation"). So this module reads that specific rejection as a legitimate body shape.
The rejection reason carries the information; nothing is recomputed.

Registry: the four P-2 families stay DISABLED. This is an implementation artifact until its fixtures
certify.
"""
from __future__ import annotations

from typing import Optional, Sequence

import numpy as np
import pandas as pd

from research.charting import geometry, ni3_config
from research.charting.lifecycle import LifecycleState
from research.charting.patterns import PatternSnapshot, RuleRow, _iso
from research.charting.patterns_p1 import (
    SHAPE_FLAT_PARALLEL_IS_RECTANGLE, _alternating_suffix, evaluate_candidate,
)
from research.charting.series import atr as atr_series_fn
from research.charting.series import relative_volume as relvol_series_fn
from research.charting.swings import Pivot, find_swings

# NI-3 §3 reason codes.
POLE_TOO_WEAK = "POLE_TOO_WEAK"
POLE_TOO_SLOW = "POLE_TOO_SLOW"
BODY_INSUFFICIENT_PIVOTS = "BODY_INSUFFICIENT_PIVOTS"
BODY_OVER_RETRACEMENT = "BODY_OVER_RETRACEMENT"
BODY_DURATION_EXCEEDS_POLE = "BODY_DURATION_EXCEEDS_POLE"
BODY_TOO_LONG = "BODY_TOO_LONG"
BODY_SHAPE_NOT_FLAG = "BODY_SHAPE_NOT_FLAG"

#: A body shape that is flat-parallel is reported under this pseudo-shape, because P-1 does not emit
#: it as a standalone pattern but §3 accepts it as a body.
FLAT_PARALLEL_BODY = "FLAT_PARALLEL"

def _p2_table(f: dict) -> dict[tuple[str, str], str]:
    """NI-3 §3 classification, built FROM the frozen config rather than transcribed.

    `bull_flag_bodies`, `bear_flag_bodies` and `pennant_bodies` are part of the hashed table, so
    reading them here means the classification cannot drift from the fingerprint. A body shape not
    in any list is "not a flag": it stays its own P-1 shape (`other_body_after_pole`), which the P-1
    engine already emits, so nothing is emitted here.
    """
    table: dict[tuple[str, str], str] = {}
    for body in f["bull_flag_bodies"]:
        table[("UP", body.upper())] = "BULL_FLAG"
    for body in f["bear_flag_bodies"]:
        table[("DOWN", body.upper())] = "BEAR_FLAG"
    for body in f["pennant_bodies"]:
        table[("UP", body.upper())] = "BULL_PENNANT"
        table[("DOWN", body.upper())] = "BEAR_PENNANT"
    return table


class Pole:
    """A confirmed LOW->HIGH (up) or HIGH->LOW (down) move that is steep enough and quick enough."""

    __slots__ = ("start", "end", "direction", "move_atr", "bars", "reason")

    def __init__(self, start: Pivot, end: Pivot, direction: str, move_atr: float, bars: int,
                 reason: Optional[str] = None):
        self.start, self.end = start, end
        self.direction, self.move_atr, self.bars, self.reason = direction, move_atr, bars, reason

    @property
    def height(self) -> float:
        return abs(self.end.price - self.start.price)


def find_poles(pivots: Sequence[Pivot], atr_arr: np.ndarray, f: dict) -> tuple[list[Pole], list[Pole]]:
    """Every adjacent pivot pair evaluated as a pole. Returns (valid, rejected-with-reason)."""
    ordered = sorted(pivots, key=lambda p: p.pivot_index)
    ok: list[Pole] = []
    bad: list[Pole] = []
    for a, b in zip(ordered, ordered[1:]):
        if a.kind == b.kind:
            continue
        direction = "UP" if (a.kind == "LOW" and b.kind == "HIGH") else "DOWN"
        bars = b.pivot_index - a.pivot_index
        atr_at = atr_arr[b.pivot_index] if b.pivot_index < len(atr_arr) else float("nan")
        if not np.isfinite(atr_at) or atr_at <= 0:
            continue
        move_atr = abs(b.price - a.price) / float(atr_at)
        pole = Pole(a, b, direction, move_atr, bars)
        if move_atr < f["pole_min_move_atr"]:
            pole.reason = POLE_TOO_WEAK
            bad.append(pole)
        elif bars > f["pole_max_bars"]:
            pole.reason = POLE_TOO_SLOW
            bad.append(pole)
        else:
            ok.append(pole)
    return ok, bad


def _body_shape(view: pd.DataFrame, t: int, window: list[Pivot], atr_arr: np.ndarray,
                p1: dict, shared: dict) -> tuple[Optional[str], Optional[object], Optional[str]]:
    """Classify a body window using the P-1 engine. Returns (shape, candidate, rejection_reason).

    A FLAT/FLAT/PARALLEL body is valid here even though P-1 will not emit it standalone.
    """
    cand = evaluate_candidate(view, t, window, atr_arr, p1, shared)
    if cand.shape is not None:
        return cand.shape, cand, None
    if cand.reason == SHAPE_FLAT_PARALLEL_IS_RECTANGLE:
        return FLAT_PARALLEL_BODY, cand, None
    return None, cand, cand.reason


def detect_p2_as_of(bars: pd.DataFrame, t: int, *, symbol: str = "UNKNOWN") -> list[PatternSnapshot]:
    """Every P-2 flag or pennant known at bar `t`."""
    view = bars.iloc[: t + 1].reset_index(drop=True)
    if len(view) == 0:
        return []
    ni3 = ni3_config.load()
    p1, shared, f = ni3["p1_geometry"], ni3["shared"], ni3["p2_flags"]
    pivots = find_swings(view, left_bars=shared["swing_left_bars"], right_bars=shared["swing_right_bars"])
    atr_arr = atr_series_fn(view, period=shared["atr_period"]).to_numpy()
    relvol_arr = relvol_series_fn(view, n=shared["volume_baseline_bars"]).to_numpy()
    closes = view["close"].to_numpy()
    dates = view["date"].to_numpy()

    poles, _rejected = find_poles(pivots, atr_arr, f)
    out: list[PatternSnapshot] = []

    for pole in poles:
        # The body starts at the pole's end pivot and is built from the pivots after it.
        after = [p for p in pivots if p.pivot_index >= pole.end.pivot_index]
        run = _alternating_suffix(after)
        if len(run) < p1["min_pivots"]:
            continue

        chosen = None
        shape = None
        for k in range(int(p1["max_pivots_considered"]), int(p1["min_pivots"]) - 1, -1):
            if len(run) < k:
                continue
            window = run[-k:]
            body_bars = window[-1].pivot_index - window[0].pivot_index
            if not (f["body_min_bars"] <= body_bars <= f["body_max_bars"]):      # F4/F5
                continue
            if body_bars >= pole.bars:                                           # F3, strict
                continue
            shp, cand, _reason = _body_shape(view, t, window, atr_arr, p1, shared)
            if shp is None:
                continue
            chosen, shape = cand, shp
            break
        if chosen is None:
            continue

        body_window = chosen.pivots
        body_bars = body_window[-1].pivot_index - body_window[0].pivot_index

        # F6: the body must retrace less than 50% of the pole.
        lo = min(p.price for p in body_window)
        hi = max(p.price for p in body_window)
        retrace = (pole.end.price - lo) if pole.direction == "UP" else (hi - pole.end.price)
        retrace_pct = retrace / pole.height * 100.0 if pole.height else 100.0
        if retrace_pct >= f["body_max_retracement_pct_of_pole"]:
            continue

        table = _p2_table(f)
        key = (pole.direction, shape)
        if key not in table:
            # "It stays that P-1 shape, and linked_pattern_id points to the pole" -- the P-1 engine
            # already emits it, so nothing is emitted here. Not a flag is not an error.
            continue
        ptype = table[key]
        direction = "BULLISH" if pole.direction == "UP" else "BEARISH"

        body_rv = float(np.nanmean(relvol_arr[body_window[0].pivot_index: body_window[-1].pivot_index + 1]))
        rules = [
            RuleRow("P2_POLE_MOVE_ATR", "PASS", round(pole.move_atr, 6), f["pole_min_move_atr"]),
            RuleRow("P2_POLE_BARS", "PASS", int(pole.bars), f["pole_max_bars"]),
            RuleRow("P2_BODY_BARS", "PASS", int(body_bars), (f["body_min_bars"], f["body_max_bars"])),
            RuleRow("P2_BODY_SHORTER_THAN_POLE", "PASS", int(body_bars), int(pole.bars)),
            RuleRow("P2_BODY_RETRACEMENT_PCT", "PASS", round(retrace_pct, 6), f["body_max_retracement_pct_of_pole"]),
            RuleRow("P2_BODY_SHAPE", "PASS", shape, sorted({s for _, s in table})),
            # F8 is descriptive (§13.8), never a gate.
            RuleRow("P2_BODY_REL_VOLUME", "PASS", None if not np.isfinite(body_rv) else round(body_rv, 6),
                    f["body_max_rel_volume_descriptive"]),
        ]

        band = shared["breakout_threshold_pct"] / 100.0
        ready = max(p.confirmed_index for p in body_window)
        status = LifecycleState.GEOMETRY_VALID
        events: list[dict] = []
        for b in range(max(ready, body_window[-1].pivot_index), t + 1):
            u = geometry.trendline_value_at(chosen.upper, b)
            l = geometry.trendline_value_at(chosen.lower, b)
            c = float(closes[b])
            with_pole = (c > u * (1 + band)) if pole.direction == "UP" else (c < l * (1 - band))
            against = (c < l * (1 - band)) if pole.direction == "UP" else (c > u * (1 + band))
            if with_pole:
                status = LifecycleState.PRICE_CONFIRMED
                rules.append(RuleRow("P2_CLOSE_BEYOND_WITH_POLE_LINE", "PASS", c,
                                     round(u if pole.direction == "UP" else l, 6)))
                events.append({"date": _iso(dates[b]), "event_type": "PRICE_CONFIRMED",
                               "rule_id": "P2_CLOSE_BEYOND_WITH_POLE_LINE",
                               "observed_values": {"close": c}})
                break
            if against:
                status = LifecycleState.INVALIDATED
                rules.append(RuleRow("P2_OPPOSITE_BREAKOUT", "FAIL", c,
                                     round(l if pole.direction == "UP" else u, 6)))
                events.append({"date": _iso(dates[b]), "event_type": "INVALIDATED",
                               "rule_id": "STRUCTURE_INVALIDATED",
                               "observed_values": {"close": c}})
                break

        out.append(PatternSnapshot(
            pattern_id=f"{symbol}:{ptype}:{_iso(dates[pole.start.pivot_index])}:{shape}",
            pattern_type=ptype, direction=direction, population="CONFIRMED",
            status=status.value, stage=None,
            formation_start=_iso(dates[pole.start.pivot_index]), formation_end=_iso(dates[t]),
            levels={
                "pole_start": pole.start.price, "pole_end": pole.end.price,
                "pole_move_atr": round(pole.move_atr, 6), "pole_bars": int(pole.bars),
                "body_shape": shape, "body_bars": int(body_bars),
                "body_retracement_pct": round(retrace_pct, 6),
                "upper_slope": chosen.upper.slope, "upper_intercept": chosen.upper.intercept,
                "lower_slope": chosen.lower.slope, "lower_intercept": chosen.lower.intercept,
                # Layer-1 stop: the opposite line at the breakout bar (the flag low or high).
                "layer1_stop": round(geometry.trendline_value_at(
                    chosen.lower if pole.direction == "UP" else chosen.upper, t), 6),
            },
            pivots=[{"date": _iso(p.pivot_date), "price": p.price, "kind": p.kind,
                     "confirmed_date": _iso(p.confirmed_date)}
                    for p in [pole.start, pole.end, *body_window]],
            components={"geometry": "PASS",
                        "price": "PASS" if status == LifecycleState.PRICE_CONFIRMED else "PENDING",
                        "volume": "PENDING", "market": "UNAVAILABLE", "sector": "UNAVAILABLE",
                        "volatility": "PENDING", "data_quality": "VALID"},
            rules=[r.to_dict() for r in rules],
            events=events,
        ))
    return out
