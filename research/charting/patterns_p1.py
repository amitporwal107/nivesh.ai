"""NI-3 §2 — the P-1 geometry engine: triangles, wedges and channels.

One engine, seven shapes. The seven-step method is reproduced exactly as frozen; this module adds no
rule of its own and resolves no open question (C-13 in particular is untouched — it concerns the
double-extreme families and has no bearing here).

    1. most recent confirmed ALTERNATING pivots; try k = 6, then 5, then 4
    2. fit an upper line through the highs, a lower line through the lows
    3. fit check      -- every pivot within G3 (0.25 ATR) of its own line
    4. containment    -- between the first and last pivot, no CLOSE beyond either line by more
                         than S5; wicks are allowed
    5. no crossing    -- the two lines do not intersect between the first and last pivot
    6. length         -- within S4
    7. classify       -- each line's direction (G4 percentage), the pair (width ratio), shape table

THE ORDERING IS PART OF THE SPECIFICATION. "Try k = 6, then 5, then 4, and keep the largest k that
passes every check" means the FIRST k that passes wins, scanning downwards. It must never become
"whichever k gives the best-looking pattern" — that would make two conforming implementations
produce different structures from identical OHLCV, which is exactly what the frozen fingerprint
exists to prevent.

This module is an implementation artifact. It enables nothing: the seven families stay DISABLED in
`pattern_registry.py` until their fixtures certify.
"""
from __future__ import annotations

from typing import Optional, Sequence

import numpy as np
import pandas as pd

from research.charting import geometry, ni3_config
from research.charting.lifecycle import LifecycleState
from research.charting.patterns import PatternSnapshot, RuleRow, _iso
from research.charting.series import atr as atr_series_fn
from research.charting.swings import Pivot, find_swings

# NI-3 §2 reason codes.
SHAPE_INSUFFICIENT_PIVOTS = "SHAPE_INSUFFICIENT_PIVOTS"
SHAPE_PIVOT_OFF_LINE = "SHAPE_PIVOT_OFF_LINE"
SHAPE_LINES_CROSS = "SHAPE_LINES_CROSS"
SHAPE_UNCLASSIFIED = "SHAPE_UNCLASSIFIED"
SHAPE_EXPANDING_OUT_OF_SCOPE = "SHAPE_EXPANDING_OUT_OF_SCOPE"
SHAPE_NOT_CONTAINED = "SHAPE_NOT_CONTAINED"
SHAPE_LENGTH_OUT_OF_BOUNDS = "SHAPE_LENGTH_OUT_OF_BOUNDS"
SHAPE_FLAT_PARALLEL_IS_RECTANGLE = "SHAPE_FLAT_PARALLEL_IS_RECTANGLE"
APEX_REACHED = "APEX_REACHED"
COUNTERTREND_BREAKOUT = "COUNTERTREND_BREAKOUT"

#: NI-3 §2 shape table: (upper direction, lower direction, pair) -> (pattern_type, direction).
#: A missing key is not a shape. FLAT/FLAT/PARALLEL and every EXPANDING pair are deliberately absent
#: -- the live RECTANGLE family owns the first and the second is out of scope in v2.
SHAPE_TABLE: dict[tuple[str, str, str], tuple[str, str]] = {
    (geometry.FLAT, geometry.RISING, geometry.CONVERGING): ("ASCENDING_TRIANGLE", "BULLISH"),
    (geometry.FALLING, geometry.FLAT, geometry.CONVERGING): ("DESCENDING_TRIANGLE", "BEARISH"),
    (geometry.FALLING, geometry.RISING, geometry.CONVERGING): ("SYMMETRICAL_TRIANGLE", "NEUTRAL"),
    (geometry.RISING, geometry.RISING, geometry.CONVERGING): ("RISING_WEDGE", "BEARISH"),
    (geometry.FALLING, geometry.FALLING, geometry.CONVERGING): ("FALLING_WEDGE", "BULLISH"),
    (geometry.RISING, geometry.RISING, geometry.PARALLEL): ("ASCENDING_CHANNEL", "NEUTRAL"),
    (geometry.FALLING, geometry.FALLING, geometry.PARALLEL): ("DESCENDING_CHANNEL", "NEUTRAL"),
}

#: Shapes whose direction is decided by the side actually broken, not by the geometry (NI-3 §2).
DIRECTION_BY_BREAK = {"SYMMETRICAL_TRIANGLE", "ASCENDING_CHANNEL", "DESCENDING_CHANNEL"}


class Candidate:
    """One evaluated (k, pivot-window) attempt. Carries its rejection reason when it failed, so a
    caller can report WHY a structure was not emitted instead of it vanishing."""

    __slots__ = ("k", "pivots", "upper", "lower", "reason", "shape", "direction", "pair", "u_dir", "l_dir", "w")

    def __init__(self, k: int, pivots: list[Pivot]):
        self.k = k
        self.pivots = pivots
        self.upper: Optional[geometry.Line] = None
        self.lower: Optional[geometry.Line] = None
        self.reason: Optional[str] = None
        self.shape: Optional[str] = None
        self.direction: Optional[str] = None
        self.pair: Optional[str] = None
        self.u_dir: Optional[str] = None
        self.l_dir: Optional[str] = None
        self.w: float = float("nan")


def _alternating_suffix(pivots: Sequence[Pivot]) -> list[Pivot]:
    """The longest run of strictly alternating HIGH/LOW pivots ending at the most recent one."""
    out: list[Pivot] = []
    for p in reversed(pivots):
        if out and p.kind == out[-1].kind:
            break
        out.append(p)
    return list(reversed(out))


def evaluate_candidate(
    view: pd.DataFrame, t: int, window: list[Pivot], atr_arr: np.ndarray, p1: dict, shared: dict,
) -> Candidate:
    """Steps 2–7 for one fixed pivot window. Pure: it reads bars and returns a verdict."""
    cand = Candidate(len(window), window)
    highs = [p for p in window if p.kind == "HIGH"]
    lows = [p for p in window if p.kind == "LOW"]

    # G1: at least 2 per line.
    if len(highs) < 2 or len(lows) < 2:
        cand.reason = SHAPE_INSUFFICIENT_PIVOTS
        return cand

    upper = geometry.fit_line([p.pivot_index for p in highs], [p.price for p in highs])
    lower = geometry.fit_line([p.pivot_index for p in lows], [p.price for p in lows])
    cand.upper, cand.lower = upper, lower

    first_x = window[0].pivot_index
    last_x = window[-1].pivot_index

    # Step 3 — fit check: every pivot within G3 x ATR of its own line.
    atr_t = float(atr_arr[t]) if t < len(atr_arr) and np.isfinite(atr_arr[t]) else float("nan")
    if not np.isfinite(atr_t) or atr_t <= 0:
        cand.reason = SHAPE_PIVOT_OFF_LINE
        return cand
    tol = p1["pivot_line_residual_max_atr"] * atr_t
    for p, line in [(p, upper) for p in highs] + [(p, lower) for p in lows]:
        if abs(p.price - geometry.trendline_value_at(line, p.pivot_index)) > tol:
            cand.reason = SHAPE_PIVOT_OFF_LINE
            return cand

    # Step 5 — no crossing between the first and last pivot (checked before containment so a
    # crossed pair reports the more specific reason).
    band = shared["breakout_threshold_pct"] / 100.0
    for x in range(first_x, last_x + 1):
        if geometry.trendline_value_at(upper, x) <= geometry.trendline_value_at(lower, x):
            cand.reason = SHAPE_LINES_CROSS
            return cand

    # Step 4 — containment: no CLOSE beyond either line by more than S5. Wicks are allowed.
    closes = view["close"].to_numpy()
    for x in range(first_x, last_x + 1):
        u = geometry.trendline_value_at(upper, x)
        l = geometry.trendline_value_at(lower, x)
        c = float(closes[x])
        if c > u * (1 + band) or c < l * (1 - band):
            cand.reason = SHAPE_NOT_CONTAINED
            return cand

    # Step 6 — length.
    length = t - first_x + 1
    if not (shared["min_formation_bars"] <= length <= shared["max_formation_bars"]):
        cand.reason = SHAPE_LENGTH_OUT_OF_BOUNDS
        return cand

    # Step 7 — classify.
    cand.u_dir = geometry.line_direction(upper, first_x, last_x, cfg=p1)
    cand.l_dir = geometry.line_direction(lower, first_x, last_x, cfg=p1)
    cand.w = geometry.width_ratio(upper, lower, first_x, last_x)
    cand.pair = geometry.classify_pair(cand.w, cfg=p1)

    if cand.pair == geometry.EXPANDING:
        cand.reason = SHAPE_EXPANDING_OUT_OF_SCOPE
        return cand
    if cand.pair == geometry.SHAPE_UNCLASSIFIED:
        cand.reason = SHAPE_UNCLASSIFIED
        return cand

    key = (cand.u_dir, cand.l_dir, cand.pair)
    if key == (geometry.FLAT, geometry.FLAT, geometry.PARALLEL):
        cand.reason = SHAPE_FLAT_PARALLEL_IS_RECTANGLE
        return cand
    if key not in SHAPE_TABLE:
        cand.reason = SHAPE_UNCLASSIFIED
        return cand

    cand.shape, cand.direction = SHAPE_TABLE[key]
    return cand


def select_candidate(
    view: pd.DataFrame, t: int, pivots: Sequence[Pivot], atr_arr: np.ndarray, p1: dict, shared: dict,
) -> tuple[Optional[Candidate], list[Candidate]]:
    """Step 1 — the frozen selection order: k = 6, then 5, then 4; the FIRST that passes wins.

    Returns the winner (or None) and every attempt, so a caller can report the rejection reasons of
    the k values that failed. The order is never re-ranked by how good a shape looks.
    """
    run = _alternating_suffix(sorted(pivots, key=lambda p: p.pivot_index))
    attempts: list[Candidate] = []
    for k in range(int(p1["max_pivots_considered"]), int(p1["min_pivots"]) - 1, -1):
        if len(run) < k:
            continue
        cand = evaluate_candidate(view, t, run[-k:], atr_arr, p1, shared)
        attempts.append(cand)
        if cand.shape is not None:
            return cand, attempts          # largest valid k wins; stop scanning
    return None, attempts


def _apex_x(upper: geometry.Line, lower: geometry.Line) -> Optional[float]:
    """Where the two fitted lines meet. None when they are parallel."""
    denom = upper.slope - lower.slope
    if denom == 0 or not np.isfinite(denom):
        return None
    return (lower.intercept - upper.intercept) / denom


def detect_p1_as_of(bars: pd.DataFrame, t: int, *, symbol: str = "UNKNOWN") -> list[PatternSnapshot]:
    """The P-1 shape known at bar `t`, or nothing. At most one: the engine selects a single pivot
    window, so a bar carries one P-1 structure."""
    view = bars.iloc[: t + 1].reset_index(drop=True)
    if len(view) == 0:
        return []
    ni3 = ni3_config.load()
    p1, shared = ni3["p1_geometry"], ni3["shared"]
    pivots = find_swings(view, left_bars=shared["swing_left_bars"], right_bars=shared["swing_right_bars"])
    atr_arr = atr_series_fn(view, period=shared["atr_period"]).to_numpy()

    cand, attempts = select_candidate(view, t, pivots, atr_arr, p1, shared)
    if cand is None or cand.shape is None:
        return []

    closes = view["close"].to_numpy()
    dates = view["date"].to_numpy()
    first_x, last_x = cand.pivots[0].pivot_index, cand.pivots[-1].pivot_index
    band = shared["breakout_threshold_pct"] / 100.0

    rules = [
        RuleRow("P1_PIVOT_COUNT", "PASS", cand.k, (p1["min_pivots"], p1["max_pivots_considered"])),
        RuleRow("P1_FIT_RESIDUAL_ATR", "PASS", p1["pivot_line_residual_max_atr"], p1["pivot_line_residual_max_atr"]),
        RuleRow("P1_UPPER_DIRECTION", "PASS", cand.u_dir, p1["flat_max_drift_pct"]),
        RuleRow("P1_LOWER_DIRECTION", "PASS", cand.l_dir, p1["flat_max_drift_pct"]),
        RuleRow("P1_WIDTH_RATIO", "PASS", round(cand.w, 6), cand.pair),
        RuleRow("P1_SHAPE", "PASS", cand.shape, None),
    ]

    # Lifecycle: the walk starts only once every pivot in the window was knowable.
    ready = max(p.confirmed_index for p in cand.pivots)
    status = LifecycleState.GEOMETRY_VALID
    events: list[dict] = []
    direction = cand.direction
    for b in range(max(ready, last_x), t + 1):
        u = geometry.trendline_value_at(cand.upper, b)
        l = geometry.trendline_value_at(cand.lower, b)
        c = float(closes[b])
        up_break = c > u * (1 + band)
        down_break = c < l * (1 - band)
        if up_break or down_break:
            broke_up = bool(up_break)
            # A wedge breaking against its own bias is INVALIDATED, not confirmed (NI-3 §2).
            countertrend = (
                (cand.shape == "RISING_WEDGE" and broke_up) or (cand.shape == "FALLING_WEDGE" and not broke_up)
            )
            if countertrend:
                status = LifecycleState.INVALIDATED
                rules.append(RuleRow("P1_COUNTERTREND_BREAKOUT", "FAIL", c, round(u if broke_up else l, 6)))
                events.append({"date": _iso(dates[b]), "event_type": "INVALIDATED",
                               "rule_id": COUNTERTREND_BREAKOUT,
                               "observed_values": {"close": c, "line": round(u if broke_up else l, 6)}})
            else:
                status = LifecycleState.PRICE_CONFIRMED
                if cand.shape in DIRECTION_BY_BREAK:
                    direction = "BULLISH" if broke_up else "BEARISH"
                rules.append(RuleRow("P1_CLOSE_BEYOND_LINE", "PASS", c, round(u if broke_up else l, 6)))
                events.append({"date": _iso(dates[b]), "event_type": "PRICE_CONFIRMED",
                               "rule_id": "P1_CLOSE_BEYOND_LINE",
                               "observed_values": {"close": c, "line": round(u if broke_up else l, 6),
                                                   "side": "UPPER" if broke_up else "LOWER"}})
            break

    # Expiry (NI-3 §2), only while no breakout has happened.
    if status == LifecycleState.GEOMETRY_VALID:
        if cand.pair == geometry.CONVERGING:
            apex = _apex_x(cand.upper, cand.lower)
            if apex is not None and apex > first_x:
                deadline = first_x + p1["apex_breakout_deadline_frac"] * (apex - first_x)
                if t > deadline:
                    status = LifecycleState.EXPIRED
                    rules.append(RuleRow("P1_APEX_DEADLINE", "FAIL", int(t), round(deadline, 4)))
                    events.append({"date": _iso(dates[t]), "event_type": "EXPIRED", "rule_id": APEX_REACHED,
                                   "observed_values": {"apex_x": round(apex, 4), "deadline_x": round(deadline, 4)}})
        elif cand.pair == geometry.PARALLEL:
            if (t - first_x + 1) >= shared["max_formation_bars"]:
                status = LifecycleState.EXPIRED
                rules.append(RuleRow("P1_MAX_FORMATION_BARS", "FAIL", int(t - first_x + 1), shared["max_formation_bars"]))
                events.append({"date": _iso(dates[t]), "event_type": "EXPIRED", "rule_id": "MAX_FORMATION_BARS",
                               "observed_values": {"length": int(t - first_x + 1)}})

    return [PatternSnapshot(
        pattern_id=f"{symbol}:{cand.shape}:{_iso(dates[first_x])}:k{cand.k}",
        pattern_type=cand.shape, direction=direction, population="CONFIRMED",
        status=status.value, stage=None,
        formation_start=_iso(dates[first_x]), formation_end=_iso(dates[t]),
        levels={
            "upper_slope": cand.upper.slope, "upper_intercept": cand.upper.intercept,
            "lower_slope": cand.lower.slope, "lower_intercept": cand.lower.intercept,
            "upper_value_at_t": round(geometry.trendline_value_at(cand.upper, t), 6),
            "lower_value_at_t": round(geometry.trendline_value_at(cand.lower, t), 6),
            "width_ratio": round(cand.w, 6), "pair": cand.pair,
        },
        pivots=[{"date": _iso(p.pivot_date), "price": p.price, "kind": p.kind,
                 "confirmed_date": _iso(p.confirmed_date)} for p in cand.pivots],
        components={"geometry": "PASS", "price": "PASS" if status == LifecycleState.PRICE_CONFIRMED else "PENDING",
                    "volume": "PENDING", "market": "UNAVAILABLE", "sector": "UNAVAILABLE",
                    "volatility": "PENDING", "data_quality": "VALID"},
        rules=[r.to_dict() for r in rules],
        events=events,
    )]
