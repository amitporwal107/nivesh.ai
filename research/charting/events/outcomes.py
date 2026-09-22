"""Entry conventions and forward-looking outcome computation for one event -- docs/charting.md
S18.2 (outcome labels), S18.3 (alternative entry methods), S23.3 (outcome record), S35.2
(adopted additions: forward returns at 1/3/5/10/20 sessions, MFE/MAE, bars to
+2/+5/+10/+15%).

-- Entry convention (task decision) --------------------------------------------------------
patterns.py confirms PRICE_CONFIRMED on a CLOSE rule (e.g. "CLOSE_ABOVE_BREAKOUT"): the
confirmation is only knowable once bar t's own close prints. Trading at that same close would
already be look-ahead for a live strategy -- the next tradeable price actually available after
the signal is known is bar t+1's OPEN.

  PRIMARY entry      = OPEN of bar t+1 (`primary_entry`).
  ALTERNATIVE entry  = CLOSE of bar t itself (`alternative_entry`), clearly labelled
                       `entry_method="close_t"` -- kept only as the PRD's own required
                       "alternative entry methods" comparison group (S18.3), never used as the
                       primary/headline entry or fed into the cost engine as a strategy result.

`primary_entry` returns `None` when bar t is the LAST bar of the frame supplied (no t+1 exists)
-- the event itself is still recorded by extraction.py, only its outcomes/costs are marked
unavailable with a reason, never silently dropped.

-- Horizon convention ------------------------------------------------------------------------
"h sessions from entry" = the bar `h` sessions AFTER the entry bar, i.e. `exit_index =
entry_index + h` (the entry bar itself is session 0). This is the SAME convention
`research.charting.movement.movement_vs_direction_report` already uses for "sessions from
confirmation" elsewhere in this package family (`exit_idx = entry_idx + h`) -- kept identical
here for consistency across the two modules, even though this package's entry bar is the NEXT
bar's open rather than the confirmation bar's own close. A horizon whose `exit_index` falls
outside the bars frame supplied is reported `available: False, reason:
"insufficient_forward_bars"` -- never truncated or interpolated (task hard rule).

-- MFE / MAE -----------------------------------------------------------------------------------
For horizon h, the excursion window is bars[entry_index .. entry_index+h] INCLUSIVE (the entry
bar's own high/low after entering at its open counts too): MFE = (max(high in window) -
entry_price) / entry_price, MAE = (min(low in window) - entry_price) / entry_price.
`highest_price`/`lowest_price` are the same window's absolute max-high / min-low.

-- Direction-aware returns (task item 3) -------------------------------------------------------
`close_return` above is always the RAW, long-perspective price return. `directional` mirrors it
signed for a short: BEARISH flips the sign (a short P&L), BULLISH/NEUTRAL keep it unchanged
(documented convention -- NEUTRAL asserts no direction, so it is treated as "no flip" rather
than dropped).

-- bars_to_+X% / hit_high_N / hit_close_N (S18.2) -----------------------------------------------
`bars_to_targets` scans forward from entry_index (inclusive) through entry_index + max(HORIZONS)
for the first bar whose HIGH reaches `entry_price * (1 + pct)`, for pct in
`schema.BARS_TO_TARGET_PCTS` (2/5/10/15%). `None` if not reached within that window -- this is
always the raw/long-perspective magnitude (mirrors S18.2's "hit_high_N" family, not a P&L
metric), regardless of the pattern's own direction; see the task's own "keep raw long returns
too" instruction.

S18.2 lists `hit_high_5`/`hit_high_10`/`hit_close_5`/`hit_close_10` as bare labels with no
formula attached anywhere in docs/charting.md. This module's documented interpretation (task
decision, not a guess left unstated): pair each label's horizon with the matching percentage
threshold already used elsewhere in the same PRD section family (S18.5's own "moved by 5% or
10%" framing) --
  hit_high_5   = bars_to_+5%  is not None and <= 5   (a >=5% HIGH within the first 5 sessions)
  hit_high_10  = bars_to_+10% is not None and <= 10  (a >=10% HIGH within the first 10 sessions)
  hit_close_5  = horizon-5 raw close_return >= 0.05   (the CLOSE at session 5 is itself >=5% up)
  hit_close_10 = horizon-10 raw close_return >= 0.10
`None` (never False) when the underlying horizon itself is unavailable.

target/stop-based labels (`hit_target_before_stop`, `stop_before_target`, S18.2) are NOT built
here: docs/charting.md S35.1's own conflict-resolution table defers "expected move... target
price language" ("owner-only wording decision pending") -- no target/stop LEVEL policy exists
yet for this engine to evaluate against, so inventing one would be exactly the kind of silent
assumption the project rules forbid. See this package's final report for this NEEDS-INPUT.
"""
from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd

from research.charting.events.schema import BARS_TO_TARGET_PCTS, HIT_HORIZON_PCT_PAIRS, HORIZONS, iso_date


def _finite_positive(x) -> bool:
    return x is not None and np.isfinite(x) and x > 0


def primary_entry(bars: pd.DataFrame, t: int) -> Optional[dict]:
    """OPEN of bar t+1, or None if bar t is the last bar in `bars`."""
    n = len(bars)
    ei = t + 1
    if ei >= n:
        return None
    price = float(bars["open"].iloc[ei])
    if not _finite_positive(price):
        return None
    return {"method": "open_t_plus_1", "index": ei, "date": iso_date(bars["date"].iloc[ei]), "price": price}


def alternative_entry(bars: pd.DataFrame, t: int) -> dict:
    """CLOSE of bar t itself -- always available (bar t exists by construction: it is the
    confirmation bar extraction.py is building a row for)."""
    price = float(bars["close"].iloc[t])
    return {"method": "close_t", "index": t, "date": iso_date(bars["date"].iloc[t]), "price": price}


def forward_outcome_block(
    bars: pd.DataFrame, entry_index: int, entry_price: float, direction: str, horizons=HORIZONS
) -> dict:
    """{"raw": {h: {...}}, "directional": {h: {...}}} for every horizon in `horizons`. See
    module docstring for the exact horizon/MFE/MAE/direction conventions."""
    n = len(bars)
    highs = bars["high"].to_numpy(dtype=float)
    lows = bars["low"].to_numpy(dtype=float)
    closes = bars["close"].to_numpy(dtype=float)
    dates = bars["date"]

    raw: dict = {}
    directional: dict = {}
    for h in horizons:
        exit_index = entry_index + h
        if exit_index >= n or entry_index < 0 or not _finite_positive(entry_price):
            raw[h] = {"available": False, "reason": "insufficient_forward_bars"}
            directional[h] = {"available": False, "reason": "insufficient_forward_bars"}
            continue
        window_hi = highs[entry_index : exit_index + 1]
        window_lo = lows[entry_index : exit_index + 1]
        exit_close = float(closes[exit_index])
        close_return = (exit_close - entry_price) / entry_price
        highest_price = float(np.max(window_hi))
        lowest_price = float(np.min(window_lo))
        raw[h] = {
            "available": True,
            "exit_index": exit_index,
            "exit_date": iso_date(dates.iloc[exit_index]),
            "exit_close": exit_close,
            "close_return": close_return,
            "mfe": (highest_price - entry_price) / entry_price,
            "mae": (lowest_price - entry_price) / entry_price,
            "highest_price": highest_price,
            "lowest_price": lowest_price,
        }
        if direction == "BEARISH":
            directional_return = -close_return
        else:  # BULLISH and NEUTRAL: unchanged, see module docstring
            directional_return = close_return
        directional[h] = {"available": True, "close_return_directional": directional_return}
    return {"raw": raw, "directional": directional}


def bars_to_targets(
    bars: pd.DataFrame, entry_index: int, entry_price: float, targets=BARS_TO_TARGET_PCTS, max_horizon: int = max(HORIZONS)
) -> dict:
    """{pct: {"bars": int|None, "reason": None|"not_reached_within_horizon"|
    "insufficient_forward_bars"}} -- first bar (entry_index inclusive) whose HIGH reaches
    entry_price*(1+pct), scanning at most `max_horizon` bars forward.

    Two distinct reasons collapse to "None" in the task's own shorthand ("None if not reached
    within 20") but are NOT the same fact and must not be conflated (task hard rule: "never
    truncated silently"): `"not_reached_within_horizon"` means the full max_horizon-bar window
    was actually available and the target genuinely never printed; `"insufficient_forward_bars"`
    means the bars frame ran out before max_horizon bars had elapsed, so absence of a hit is not
    informative -- the window was truncated by data availability, not by price action.
    """
    n = len(bars)
    if not _finite_positive(entry_price) or entry_index < 0 or entry_index >= n:
        return {pct: {"bars": None, "reason": "insufficient_forward_bars"} for pct in targets}
    highs = bars["high"].to_numpy(dtype=float)
    window_end = entry_index + max_horizon
    truncated = window_end >= n  # fewer than max_horizon forward bars actually exist
    scan_end = min(window_end, n - 1)
    out: dict = {}
    for pct in targets:
        target_price = entry_price * (1 + pct)
        found = None
        for i in range(entry_index, scan_end + 1):
            if highs[i] >= target_price:
                found = i - entry_index
                break
        if found is not None:
            out[pct] = {"bars": found, "reason": None}
        elif truncated:
            out[pct] = {"bars": None, "reason": "insufficient_forward_bars"}
        else:
            out[pct] = {"bars": None, "reason": "not_reached_within_horizon"}
    return out


def hit_flags(raw: dict, bars_to: dict) -> dict:
    """hit_high_N / hit_close_N -- see module docstring for the documented pairing. `None`
    (never a guessed True/False) whenever the underlying horizon/target is unavailable due to
    insufficient forward data; a genuine "target not reached in time" is reported `False`, not
    `None` -- it is real information, not a data gap."""
    out: dict = {}
    for h, pct in HIT_HORIZON_PCT_PAIRS:
        bt = bars_to.get(pct)
        if bt is None or bt["reason"] == "insufficient_forward_bars":
            out[f"hit_high_{h}"] = None
        elif bt["bars"] is not None:
            out[f"hit_high_{h}"] = bt["bars"] <= h
        else:  # not_reached_within_horizon (definitely never printed within the full 20-bar scan)
            out[f"hit_high_{h}"] = False
        r = raw.get(h)
        if r is not None and r.get("available"):
            out[f"hit_close_{h}"] = bool(r["close_return"] >= pct)
        else:
            out[f"hit_close_{h}"] = None
    return out


def adv_inr_at(bars: pd.DataFrame, t: int, n: int) -> Optional[float]:
    """20-day (config-driven `n`) average TRADED VALUE (close * volume) up to and including bar
    t only -- task item 4's own wording. `None` if fewer than `n` bars are available up to t, or
    if any close/volume inside the window is non-finite (never silently drop a bad row from the
    average -- an unreliable ADV reports as unavailable, not as a number computed over fewer
    bars than asked for)."""
    start = t - n + 1
    if start < 0 or t >= len(bars):
        return None
    closes = bars["close"].to_numpy(dtype=float)[start : t + 1]
    vols = bars["volume"].to_numpy(dtype=float)[start : t + 1]
    if not (np.all(np.isfinite(closes)) and np.all(np.isfinite(vols))):
        return None
    return float(np.mean(closes * vols))
