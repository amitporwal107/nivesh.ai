"""P1 = B5 + pattern. The PRD's PRIMARY TEST (§10): `P1 vs B5`.

THE QUESTION
------------
Once price, liquidity, volatility, market regime, calendar and technical state are already in the
model, does knowing a chart pattern is present tell you anything MORE?

That is a deliberately hard question, and it is the one §9 exists to make askable: a pattern
detector may be repackaging momentum, relative strength, volume and distance-from-high. If the
"pattern effect" vanishes once those are controlled, it was those variables wearing a label.

WHAT A PATTERN CONTRIBUTES, AS FEATURES
---------------------------------------
Pattern PRESENCE cannot be a feature in this design. Every row in the event dataset already IS a
pattern -- there are no negative rows -- so `pattern_present` would be a constant, and a constant
carries no information by construction. What varies between rows, and is therefore testable, is
WHICH pattern and in what state:

    pattern_type      the family (dictionary-coded)
    direction         BULLISH / BEARISH
    breakout strength how far past the level, in ATR
    volume confirmation whether the breakout bar carried volume
    candle quality    the confirming bar's body/close-location
    retest quality    whether the level was retested

Testing pattern PRESENCE against a no-pattern population needs rows that are not patterns -- which
is exactly what the ATR-decile and buy-next-open control groups are. That is a separate comparison
(§30's G0/G1/G2/G3), not this one, and it is noted here so the limitation is explicit rather than
discovered later.
"""
from __future__ import annotations

from typing import Mapping, Optional


def _get(row: Mapping, *path, default=None):
    cur = row
    for k in path:
        if not isinstance(cur, Mapping):
            return default
        cur = cur.get(k)
        if cur is None:
            return default
    return cur


def _one_hot(value: Optional[str], levels) -> dict:
    """Explicit one-hot rather than an integer code. A pattern family is nominal: coding
    RECTANGLE=0, HH_HL=1, SUPPORT_RESISTANCE=2 would tell a linear model that HH_HL sits between
    the other two, which is meaningless and would let it fit a gradient across a category."""
    return {f"is_{lv.lower()}": (1.0 if value == lv else 0.0) for lv in levels}


PATTERN_FAMILIES = ("RECTANGLE", "SUPPORT_RESISTANCE", "HH_HL")


def pattern_features(row: Mapping) -> dict:
    """The P1 block. Every value read from a real row; nothing derived from the outcome."""
    out: dict = {}
    out.update(_one_hot(row.get("pattern_type"), PATTERN_FAMILIES))
    out["is_bullish"] = 1.0 if row.get("direction") == "BULLISH" else 0.0

    # Breakout strength, in ATR units -- scale-free, so it is comparable across stocks and is not
    # a second copy of the price level that B2 already carries.
    out["breakout_atr"] = _get(row, "research", "breakout_threshold_atr")
    out["breakout_pct"] = _get(row, "research", "breakout_threshold_pct")
    out["breakout_volume_ratio"] = _get(row, "research", "breakout_volume_ratio")

    cq = _get(row, "research", "candle_quality")
    if isinstance(cq, Mapping):
        out["candle_body_pct"] = cq.get("body_pct")
        out["candle_close_location"] = cq.get("close_location")
    rq = _get(row, "research", "retest_quality")
    if isinstance(rq, Mapping):
        out["retest_depth_atr"] = rq.get("depth_atr")

    # Stock trend class at confirmation, as the detector saw it.
    out["stock_adx_at_t"] = _get(row, "research", "stock_trend_class_adx_14")
    out["stock_slope_at_t"] = _get(row, "research", "stock_trend_class_slope_pct_per_day")
    return out


def p1_features(base: Mapping) -> dict:
    """B5's features plus the pattern block -- a strict SUPERSET of B5, which is what makes the
    increment interpretable."""
    return {**base, **{}}


#: Names only, for building the design matrix.
def pattern_feature_names(rows) -> list:
    seen: dict = {}
    for r in rows:
        for k in pattern_features(r):
            seen[k] = True
    return list(seen)
