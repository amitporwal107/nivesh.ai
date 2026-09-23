"""Detectors for the NI-3 v1.0 families (docs/charting.md §39, NI-3 §4–§7).

DELIBERATELY SEPARATE FROM `patterns.py`. That module is the frozen v1 detector for the three live
families (`config_hash 05167d3a…`) and its behaviour must not move. These families run on the NI-3
table (`de86626c…`) with the owner's PERCENTAGE rules, while the P0 families keep the ATR rules —
§37.7 keeps the two apart on purpose. Sharing a module would make it far too easy for a change to
one convention to reach the other.

Wave B + parallel families (owner directive, 2026-09-23). The five here need no fitted-line engine:
  * double bottom / double top — NI-3 §4/§5, horizontal neckline, nothing new required;
  * head & shoulders / inverse head & shoulders — NI-3 §6/§6b, need only `trendline_value_at`
    for the sloped neckline;
  * cup & handle — NI-3 §7.

Point-in-time: every detector reads `bars[0..t]` only, and uses a pivot only from the bar it became
knowable at (`Pivot.confirmed_index`). The breakout walk starts at the bar every pivot in the
structure was confirmed, never at the bar the geometry happens to look complete in hindsight.

Overlapping detections are all emitted, not pruned to "the best one" (§24: "Multiple patterns can
legitimately coexist… Store all valid detections"). Deciding which matters is the signal
evaluator's job, not the detector's (§39.13).
"""
from __future__ import annotations

from typing import Any, Sequence

import numpy as np
import pandas as pd

from research.charting import geometry, ni3_config
from research.charting.lifecycle import LifecycleState
from research.charting.patterns import PatternSnapshot, RuleRow, _iso
from research.charting import regime
from research.charting.series import atr as atr_series_fn
from research.charting.series import relative_volume as relvol_series_fn
from research.charting.swings import Pivot, find_swings


def _pct_diff(a: float, b: float) -> float:
    """|a - b| as a percentage of their mean — symmetric, so the tolerance does not depend on
    which extreme is named first."""
    mid = (abs(a) + abs(b)) / 2.0
    return float("inf") if mid == 0 else abs(a - b) / mid * 100.0


def _components(price_confirmed: bool) -> dict:
    return {
        "geometry": "PASS",
        "price": "PASS" if price_confirmed else "PENDING",
        "volume": "PENDING",
        "market": "UNAVAILABLE",
        "sector": "UNAVAILABLE",
        "volatility": "PENDING",
        "data_quality": "VALID",
    }


# ── NI-3 §4 / §5 — double bottom and double top ─────────────────────────────────────────────────
def _double_extreme_patterns(
    view: pd.DataFrame, t: int, pivots: Sequence[Pivot], symbol: str, *, bullish: bool, ni3: dict,
) -> list[PatternSnapshot]:
    """Double bottom (bullish) and double top (bearish) — one implementation, mirrored.

    NI-3 §4: "Troughs at least B1 apart and within B2 of each other. The neckline is B3. A recovery
    of at least B5. Breakout: close > neckline x (1 + S5). Invalidation: a close below the second
    trough." §5 is the stated mirror.

    The neckline is a horizontal level (the highest reaction high / lowest reaction low between the
    two extremes), so this family needs no fitted line — which is why it was never actually blocked.
    """
    block = ni3["double_bottom"] if bullish else ni3["double_top"]
    shared = ni3["shared"]
    kind = "LOW" if bullish else "HIGH"
    opposite = "HIGH" if bullish else "LOW"
    min_sep = block["trough_min_separation_bars"] if bullish else block["peak_min_separation_bars"]
    tol_pct = block["trough_tolerance_pct"] if bullish else block["peak_tolerance_pct"]
    move_min_pct = block["recovery_min_pct"] if bullish else block["decline_min_pct"]
    thresh_pct = block["breakout_threshold_pct"] if bullish else block["breakdown_threshold_pct"]
    ptype = "DOUBLE_BOTTOM" if bullish else "DOUBLE_TOP"
    direction = "BULLISH" if bullish else "BEARISH"

    closes = view["close"].to_numpy()
    dates = view["date"].to_numpy()
    date_t = _iso(dates[t])

    extremes = sorted((p for p in pivots if p.kind == kind), key=lambda p: p.pivot_index)
    reactions = sorted((p for p in pivots if p.kind == opposite), key=lambda p: p.pivot_index)
    out: list[PatternSnapshot] = []

    for i, e1 in enumerate(extremes):
        for e2 in extremes[i + 1:]:
            sep = e2.pivot_index - e1.pivot_index
            if sep < min_sep:
                continue
            diff_pct = _pct_diff(e1.price, e2.price)
            if diff_pct > tol_pct:
                continue

            # INTERPRETATION (stated, not buried). NI-3 §4 says "troughs at least B1 apart and
            # within B2 of each other" without saying the two must be ADJACENT extremes. Read
            # literally as any qualifying pair, a window holding six lows emits pairs whose troughs
            # have four other troughs between them, which is not a "double" bottom — measured at 320
            # detections across 12 symbols, against ~10 per symbol for all three frozen families
            # combined. A double bottom is two bottoms, so the pair must be consecutive same-kind
            # pivots. Recorded as an open question for the owner in §39.16; if the looser reading is
            # intended, delete this check and nothing else changes.
            if any(x for x in extremes if e1.pivot_index < x.pivot_index < e2.pivot_index):
                continue

            between = [r for r in reactions if e1.pivot_index < r.pivot_index < e2.pivot_index]
            if not between:
                continue
            neck = max(between, key=lambda r: r.price) if bullish else min(between, key=lambda r: r.price)

            # B5 / P5: the move away from the extremes to the neckline.
            base = min(e1.price, e2.price) if bullish else max(e1.price, e2.price)
            move_pct = abs(neck.price - base) / abs(base) * 100.0 if base else 0.0
            if move_pct < move_min_pct:
                continue

            length = t - e1.pivot_index + 1
            if not (shared["min_formation_bars"] <= length <= shared["max_formation_bars"]):
                continue

            rules = [
                RuleRow("DE_MIN_SEPARATION_BARS", "PASS", int(sep), int(min_sep)),
                RuleRow("DE_EXTREME_TOLERANCE_PCT", "PASS", round(diff_pct, 6), tol_pct),
                RuleRow("DE_NECKLINE_MOVE_PCT", "PASS", round(move_pct, 6), move_min_pct),
                RuleRow("DE_FORMATION_LENGTH", "PASS", int(length),
                        (shared["min_formation_bars"], shared["max_formation_bars"])),
            ]

            trigger = neck.price * (1 + thresh_pct / 100.0) if bullish else neck.price * (1 - thresh_pct / 100.0)
            invalidation = e2.price

            # Nothing is evaluated before every pivot in the structure was knowable.
            ready = max(e1.confirmed_index, e2.confirmed_index, neck.confirmed_index)
            status = LifecycleState.GEOMETRY_VALID
            events: list[dict] = []
            for b in range(ready, t + 1):
                c = float(closes[b])
                broke = c > trigger if bullish else c < trigger
                invalid = c < invalidation if bullish else c > invalidation
                if broke:
                    status = LifecycleState.PRICE_CONFIRMED
                    rules.append(RuleRow("DE_CLOSE_BEYOND_NECKLINE", "PASS", c, round(trigger, 6)))
                    events.append({"date": _iso(dates[b]), "event_type": "PRICE_CONFIRMED",
                                   "rule_id": "DE_CLOSE_BEYOND_NECKLINE",
                                   "observed_values": {"close": c, "trigger": round(trigger, 6)}})
                    break
                if invalid:
                    status = LifecycleState.INVALIDATED
                    rules.append(RuleRow("DE_CLOSE_BEYOND_SECOND_EXTREME", "FAIL", c, invalidation))
                    events.append({"date": _iso(dates[b]), "event_type": "INVALIDATED",
                                   "rule_id": "DE_CLOSE_BEYOND_SECOND_EXTREME",
                                   "observed_values": {"close": c, "second_extreme": invalidation}})
                    break

            out.append(PatternSnapshot(
                pattern_id=f"{symbol}:{ptype}:{_iso(dates[e1.pivot_index])}:{e1.price:.2f}-{e2.price:.2f}",
                pattern_type=ptype, direction=direction, population="CONFIRMED",
                status=status.value, stage=None,
                formation_start=_iso(dates[e1.pivot_index]), formation_end=date_t,
                levels={
                    "neckline": neck.price,
                    "breakout_level" if bullish else "breakdown_level": round(trigger, 6),
                    "invalidation_level": invalidation,
                    # NI-3 §1.6 P-4 research metadata: never gating.
                    "extreme_diff_pct_of_height": round(
                        abs(e1.price - e2.price) / abs(neck.price - base) * 100.0, 6
                    ) if neck.price != base else None,
                },
                pivots=[
                    {"date": _iso(p.pivot_date), "price": p.price, "kind": p.kind,
                     "confirmed_date": _iso(p.confirmed_date)}
                    for p in sorted((e1, neck, e2), key=lambda p: p.pivot_index)
                ],
                components=_components(status == LifecycleState.PRICE_CONFIRMED),
                rules=[r.to_dict() for r in rules],
                events=events,
            ))
    return out


# ── NI-3 §6 / §6b — head & shoulders and inverse head & shoulders ───────────────────────────────
def _head_shoulders_patterns(
    view: pd.DataFrame, t: int, pivots: Sequence[Pivot], atr_arr: np.ndarray, symbol: str, *,
    bearish: bool, ni3: dict,
) -> list[PatternSnapshot]:
    """Head & shoulders (bearish, §6) and its inverse (bullish, §6b) — one mirrored implementation.

    This is the first consumer of `geometry.trendline_value_at`. The neckline is NOT a horizontal
    level: NI-3 §6b says it "may slope; its live value comes from `trendline_value_at`", and the
    breakdown test uses the projected value AT THE BREAKDOWN BAR, not the neckline's value at
    formation. That is exactly why these two families were blocked on one function rather than on
    the whole P-1 engine.

    Structure (bearish): HIGH left shoulder -> LOW -> HIGH head -> LOW -> HIGH right shoulder, with
    the head prominent above both shoulders and the shoulders within tolerance of each other. The
    bullish mirror swaps every kind and every comparison.

    Both stop variants are computed and reported for every event (#110): neither is selected for
    looking better.
    """
    block = ni3["head_and_shoulders"] if bearish else ni3["inverse_head_and_shoulders"]
    shared = ni3["shared"]
    ptype = "HEAD_AND_SHOULDERS" if bearish else "INVERSE_HEAD_AND_SHOULDERS"
    direction = "BEARISH" if bearish else "BULLISH"
    shoulder_kind = "HIGH" if bearish else "LOW"
    neck_kind = "LOW" if bearish else "HIGH"
    thresh_pct = block["breakdown_threshold_pct"] if bearish else block["breakout_threshold_pct"]
    neck_sep = block["neckline_trough_min_separation_bars"] if bearish else block["neckline_peak_min_separation_bars"]

    closes = view["close"].to_numpy()
    dates = view["date"].to_numpy()
    date_t = _iso(dates[t])

    ordered = sorted(pivots, key=lambda p: p.pivot_index)
    out: list[PatternSnapshot] = []

    # Walk consecutive alternating five-pivot windows: shoulder, neck, head, neck, shoulder.
    for i in range(len(ordered) - 4):
        ls, n1, head, n2, rs = ordered[i:i + 5]
        if [p.kind for p in (ls, n1, head, n2, rs)] != [shoulder_kind, neck_kind, shoulder_kind, neck_kind, shoulder_kind]:
            continue

        # H3/I3: the three same-kind peaks must be far enough apart.
        if (head.pivot_index - ls.pivot_index) < block["peak_min_separation_bars"]:
            continue
        if (rs.pivot_index - head.pivot_index) < block["peak_min_separation_bars"]:
            continue
        # H4/I4: the two neckline pivots must be far enough apart.
        if (n2.pivot_index - n1.pivot_index) < neck_sep:
            continue

        # H1/I1: shoulders similar.
        shoulder_diff = _pct_diff(ls.price, rs.price)
        if shoulder_diff > block["shoulder_tolerance_pct"]:
            continue

        # H2/I2: the head is prominent beyond BOTH shoulders (measured against the nearer one, so a
        # head that only clears the lower shoulder is rejected).
        nearer = max(ls.price, rs.price) if bearish else min(ls.price, rs.price)
        prominence = (head.price - nearer) / abs(nearer) * 100.0 if bearish else (nearer - head.price) / abs(nearer) * 100.0
        if prominence < block["head_min_prominence_pct"]:
            continue

        length = t - ls.pivot_index + 1
        if not (shared["min_formation_bars"] <= length <= shared["max_formation_bars"]):
            continue

        # The neckline: a fitted line through the two neck pivots, evaluated live.
        neckline = geometry.fit_line([n1.pivot_index, n2.pivot_index], [n1.price, n2.price])

        rules = [
            RuleRow("HS_SHOULDER_TOLERANCE_PCT", "PASS", round(shoulder_diff, 6), block["shoulder_tolerance_pct"]),
            RuleRow("HS_HEAD_PROMINENCE_PCT", "PASS", round(prominence, 6), block["head_min_prominence_pct"]),
            RuleRow("HS_PEAK_SEPARATION_BARS", "PASS",
                    int(min(head.pivot_index - ls.pivot_index, rs.pivot_index - head.pivot_index)),
                    block["peak_min_separation_bars"]),
            RuleRow("HS_NECKLINE_SEPARATION_BARS", "PASS", int(n2.pivot_index - n1.pivot_index), neck_sep),
            RuleRow("HS_FORMATION_LENGTH", "PASS", int(length),
                    (shared["min_formation_bars"], shared["max_formation_bars"])),
        ]

        ready = max(p.confirmed_index for p in (ls, n1, head, n2, rs))
        status = LifecycleState.GEOMETRY_VALID
        events: list[dict] = []
        breakdown_bar = None
        for b in range(ready, t + 1):
            c = float(closes[b])
            neck_now = geometry.trendline_value_at(neckline, b)
            trigger = neck_now * (1 - thresh_pct / 100.0) if bearish else neck_now * (1 + thresh_pct / 100.0)
            broke = c < trigger if bearish else c > trigger
            invalid = c > rs.price if bearish else c < rs.price
            if broke:
                status = LifecycleState.PRICE_CONFIRMED
                breakdown_bar = b
                rules.append(RuleRow("HS_CLOSE_BEYOND_NECKLINE", "PASS", c, round(trigger, 6)))
                events.append({"date": _iso(dates[b]), "event_type": "PRICE_CONFIRMED",
                               "rule_id": "HS_CLOSE_BEYOND_NECKLINE",
                               "observed_values": {"close": c, "neckline_value": round(neck_now, 6),
                                                   "trigger": round(trigger, 6)}})
                break
            if invalid:
                status = LifecycleState.INVALIDATED
                rules.append(RuleRow("HS_CLOSE_BEYOND_RIGHT_SHOULDER", "FAIL", c, rs.price))
                events.append({"date": _iso(dates[b]), "event_type": "INVALIDATED",
                               "rule_id": "HS_CLOSE_BEYOND_RIGHT_SHOULDER",
                               "observed_values": {"close": c, "right_shoulder": rs.price}})
                break

        # BOTH stop variants, always (#110: "Neither is picked for looking better").
        buf_bar = breakdown_bar if breakdown_bar is not None else t
        atr_now = float(atr_arr[buf_bar]) if buf_bar < len(atr_arr) and np.isfinite(atr_arr[buf_bar]) else float("nan")
        buf = block["stop_buffer_atr"] * atr_now
        neck_at_break = geometry.trendline_value_at(neckline, buf_bar)
        if bearish:
            stop_primary, stop_secondary = rs.price + buf, neck_at_break + buf
        else:
            stop_primary, stop_secondary = rs.price - buf, neck_at_break - buf

        out.append(PatternSnapshot(
            pattern_id=f"{symbol}:{ptype}:{_iso(dates[ls.pivot_index])}:{head.price:.2f}",
            pattern_type=ptype, direction=direction, population="CONFIRMED",
            status=status.value, stage=None,
            formation_start=_iso(dates[ls.pivot_index]), formation_end=date_t,
            levels={
                "neckline_slope": neckline.slope,
                "neckline_intercept": neckline.intercept,
                "neckline_value_at_t": round(geometry.trendline_value_at(neckline, t), 6),
                "head": head.price,
                "left_shoulder": ls.price,
                "right_shoulder": rs.price,
                "invalidation_level": rs.price,
                "stop_primary": None if not np.isfinite(stop_primary) else round(stop_primary, 6),
                "stop_secondary_research": None if not np.isfinite(stop_secondary) else round(stop_secondary, 6),
            },
            pivots=[{"date": _iso(p.pivot_date), "price": p.price, "kind": p.kind,
                     "confirmed_date": _iso(p.confirmed_date)} for p in (ls, n1, head, n2, rs)],
            components=_components(status == LifecycleState.PRICE_CONFIRMED),
            rules=[r.to_dict() for r in rules],
            events=events,
        ))
    return out


# ── NI-3 §7 — cup & handle ──────────────────────────────────────────────────────────────────────
def _cup_and_handle_patterns(
    view: pd.DataFrame, t: int, pivots: Sequence[Pivot], atr_arr: np.ndarray, relvol_arr: np.ndarray,
    symbol: str, *, ni3: dict,
) -> list[PatternSnapshot]:
    """Cup & handle (NI-3 §7, C1–C17). The strictest family: seventeen parameters, all frozen.

    Structure: left rim (HIGH) -> cup low (LOW, in the middle third of the cup) -> right rim (HIGH,
    within C7 of the left) -> handle (a shallow pullback after the right rim) -> breakout above the
    rim resistance.

    `prior_trend_at_cup_start` (BULL or STRONG_BULL) is in the frozen config, so it GATES. When the
    trend class cannot be computed — not enough history at the cup's start — the candidate is
    rejected rather than passed, because silently skipping a frozen gate would be a relaxation.
    """
    block = ni3["cup_and_handle"]
    shared = ni3["shared"]
    closes = view["close"].to_numpy()
    highs = view["high"].to_numpy()
    lows = view["low"].to_numpy()
    dates = view["date"].to_numpy()
    date_t = _iso(dates[t])

    rims = [p for p in pivots if p.kind == "HIGH"]
    cup_lows = [p for p in pivots if p.kind == "LOW"]
    out: list[PatternSnapshot] = []

    for i, left in enumerate(rims):
        for right in rims[i + 1:]:
            cup_bars = right.pivot_index - left.pivot_index
            if not (block["cup_min_bars"] <= cup_bars <= block["cup_max_bars"]):
                continue
            rim_diff = _pct_diff(left.price, right.price)
            if rim_diff > block["cup_rim_tolerance_pct"]:            # C7
                continue

            inner = [p for p in cup_lows if left.pivot_index < p.pivot_index < right.pivot_index]
            if not inner:
                continue
            low = min(inner, key=lambda p: p.price)

            # C8/C9: the cup's low sits in the middle third of the cup's bars.
            frac = (low.pivot_index - left.pivot_index) / cup_bars
            if not (block["cup_low_position_min_frac"] <= frac <= block["cup_low_position_max_frac"]):
                continue

            rim = max(left.price, right.price)
            depth_pct = (rim - low.price) / rim * 100.0
            if not (block["cup_min_depth_pct"] <= depth_pct <= block["cup_max_depth_pct"]):   # C3/C4
                continue

            # C10: no single bar inside the cup may range more than 3 ATR -- a V-spike is not a cup.
            span = slice(left.pivot_index, right.pivot_index + 1)
            rng = highs[span] - lows[span]
            atr_span = atr_arr[span]
            with np.errstate(invalid="ignore", divide="ignore"):
                ratio = np.where(np.isfinite(atr_span) & (atr_span > 0), rng / atr_span, 0.0)
            max_bar_atr = float(np.nanmax(ratio)) if len(ratio) else 0.0
            if max_bar_atr > block["cup_max_single_bar_range_atr"]:
                continue

            # prior trend at the cup's start -- a frozen gate, so an uncomputable value rejects.
            # `trend_classification` is keyed by DATE, not by bar index. Passing an index returns
            # UNAVAILABLE silently, which -- because this gate rejects on an uncomputable value --
            # produced zero cup & handle detections across all 50 symbols and looked exactly like
            # the family simply being rare. Rejecting rather than passing is what surfaced it.
            try:
                tc = regime.trend_classification(view, dates[left.pivot_index])
                cls = tc["class"]
                trend_class = getattr(cls, "value", cls)
            except Exception:
                trend_class = None
            if trend_class not in block["prior_trend_at_cup_start"]:
                continue

            # The handle: everything after the right rim, up to t.
            handle_bars = t - right.pivot_index
            if not (block["handle_min_bars"] <= handle_bars <= block["handle_max_bars"]):      # C13/C14
                continue
            if handle_bars > block["handle_max_pct_of_cup_duration"] / 100.0 * cup_bars:       # C15
                continue

            h_slice = slice(right.pivot_index + 1, t + 1)
            handle_low = float(np.min(lows[h_slice])) if len(lows[h_slice]) else float("nan")
            if not np.isfinite(handle_low):
                continue
            handle_depth = right.price - handle_low
            if handle_depth > (rim - low.price) * block["handle_max_depth_pct_of_cup"] / 100.0:  # C11
                continue
            if handle_depth / right.price * 100.0 > block["handle_max_depth_pct_price"]:        # C12
                continue

            handle_rv = float(np.nanmean(relvol_arr[h_slice])) if len(relvol_arr[h_slice]) else float("nan")

            length = t - left.pivot_index + 1
            if not (shared["min_formation_bars"] <= length <= shared["max_formation_bars"]):
                continue

            trigger = rim * (1 + block["breakout_threshold_pct"] / 100.0)                       # C17
            rules = [
                RuleRow("CAH_RIM_TOLERANCE_PCT", "PASS", round(rim_diff, 6), block["cup_rim_tolerance_pct"]),
                RuleRow("CAH_CUP_DEPTH_PCT", "PASS", round(depth_pct, 6),
                        (block["cup_min_depth_pct"], block["cup_max_depth_pct"])),
                RuleRow("CAH_CUP_BARS", "PASS", int(cup_bars), (block["cup_min_bars"], block["cup_max_bars"])),
                RuleRow("CAH_CUP_LOW_POSITION", "PASS", round(frac, 6),
                        (block["cup_low_position_min_frac"], block["cup_low_position_max_frac"])),
                RuleRow("CAH_MAX_SINGLE_BAR_RANGE_ATR", "PASS", round(max_bar_atr, 6),
                        block["cup_max_single_bar_range_atr"]),
                RuleRow("CAH_PRIOR_TREND", "PASS", trend_class, block["prior_trend_at_cup_start"]),
                RuleRow("CAH_HANDLE_BARS", "PASS", int(handle_bars),
                        (block["handle_min_bars"], block["handle_max_bars"])),
                RuleRow("CAH_HANDLE_DEPTH_PCT_OF_CUP", "PASS",
                        round(handle_depth / (rim - low.price) * 100.0, 6), block["handle_max_depth_pct_of_cup"]),
                # C16 is descriptive, never a gate (NI-3 §1.6).
                RuleRow("CAH_HANDLE_REL_VOLUME", "PASS", None if not np.isfinite(handle_rv) else round(handle_rv, 6),
                        block["handle_max_rel_volume"]),
            ]

            ready = max(left.confirmed_index, low.confirmed_index, right.confirmed_index)
            status = LifecycleState.GEOMETRY_VALID
            events: list[dict] = []
            for b in range(max(ready, right.pivot_index + 1), t + 1):
                c = float(closes[b])
                if c > trigger:
                    status = LifecycleState.PRICE_CONFIRMED
                    rules.append(RuleRow("CAH_CLOSE_ABOVE_RIM", "PASS", c, round(trigger, 6)))
                    events.append({"date": _iso(dates[b]), "event_type": "PRICE_CONFIRMED",
                                   "rule_id": "CAH_CLOSE_ABOVE_RIM",
                                   "observed_values": {"close": c, "trigger": round(trigger, 6)}})
                    break
                if c < handle_low:
                    status = LifecycleState.INVALIDATED
                    rules.append(RuleRow("CAH_CLOSE_BELOW_HANDLE_LOW", "FAIL", c, handle_low))
                    events.append({"date": _iso(dates[b]), "event_type": "INVALIDATED",
                                   "rule_id": "CAH_CLOSE_BELOW_HANDLE_LOW",
                                   "observed_values": {"close": c, "handle_low": handle_low}})
                    break

            out.append(PatternSnapshot(
                pattern_id=f"{symbol}:CUP_AND_HANDLE:{_iso(dates[left.pivot_index])}:{rim:.2f}",
                pattern_type="CUP_AND_HANDLE", direction="BULLISH", population="CONFIRMED",
                status=status.value, stage=None,
                formation_start=_iso(dates[left.pivot_index]), formation_end=date_t,
                levels={"rim": rim, "cup_low": low.price, "handle_low": handle_low,
                        "breakout_level": round(trigger, 6), "invalidation_level": handle_low,
                        "layer1_stop": handle_low, "cup_depth_pct": round(depth_pct, 6)},
                pivots=[{"date": _iso(p.pivot_date), "price": p.price, "kind": p.kind,
                         "confirmed_date": _iso(p.confirmed_date)} for p in (left, low, right)],
                components=_components(status == LifecycleState.PRICE_CONFIRMED),
                rules=[r.to_dict() for r in rules],
                events=events,
            ))
    return out


# ── entry point ─────────────────────────────────────────────────────────────────────────────────
def detect_ni3_as_of(bars: pd.DataFrame, t: int, *, symbol: str = "UNKNOWN") -> list[PatternSnapshot]:
    """Every NI-3 family known at bar `t`, using `bars[0..t]` ONLY.

    Separate entry point from `patterns.detect_as_of` so a caller chooses the frozen v1 families,
    the NI-3 families, or both — and so neither can accidentally change the other's output.
    """
    view = bars.iloc[: t + 1].reset_index(drop=True)
    if len(view) == 0:
        return []
    ni3 = ni3_config.load()
    shared = ni3["shared"]
    pivots = find_swings(view, left_bars=shared["swing_left_bars"], right_bars=shared["swing_right_bars"])

    atr_arr = atr_series_fn(view, period=shared["atr_period"]).to_numpy()

    patterns: list[PatternSnapshot] = []
    patterns.extend(_double_extreme_patterns(view, t, pivots, symbol, bullish=True, ni3=ni3))
    patterns.extend(_double_extreme_patterns(view, t, pivots, symbol, bullish=False, ni3=ni3))
    patterns.extend(_head_shoulders_patterns(view, t, pivots, atr_arr, symbol, bearish=True, ni3=ni3))
    patterns.extend(_head_shoulders_patterns(view, t, pivots, atr_arr, symbol, bearish=False, ni3=ni3))
    relvol_arr = relvol_series_fn(view, n=shared["volume_baseline_bars"]).to_numpy()
    patterns.extend(_cup_and_handle_patterns(view, t, pivots, atr_arr, relvol_arr, symbol, ni3=ni3))
    return patterns
