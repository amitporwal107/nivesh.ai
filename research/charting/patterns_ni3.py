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

    patterns: list[PatternSnapshot] = []
    patterns.extend(_double_extreme_patterns(view, t, pivots, symbol, bullish=True, ni3=ni3))
    patterns.extend(_double_extreme_patterns(view, t, pivots, symbol, bullish=False, ni3=ni3))
    return patterns
