"""Daily-bar execution simulator (PRD §11, v1.1 §32.6-32.7). No fill at a price the bar did not offer:
- MOO: the open (+ slippage); nothing when the open is locked at the upper circuit.
- BUY_STOP: max(open, trigger) when the high reaches the trigger — a gap over the trigger fills at the open, never at
  the better trigger price.
- MOC: the official close (+ slippage).
- LIMIT (buy): min(open, limit) when the low reaches the limit, never above the limit.
- TYPICAL: (high + low + close) / 3, the VWAP proxy (an approximation: true VWAP needs intraday data).
- Stops: an open at or below the stop fills at the open (GAP_THROUGH), else at the stop; a session locked at the lower
  circuit cannot be sold. Volume participation caps the quantity (partial fills).
- Targets: an open at or above the target fills at the open (GAP_OVER_TARGET), else at the target.
- exit_on_bar orders one bar's stop and target checks and flags a bar that reached both (INTRABAR ambiguity; daily bars
  cannot say which came first, so a versioned policy decides: STOP_FIRST by default).
Prices are rounded to the paisa, ROUND_HALF_UP. Circuit logic follows tpd_model/paper/sim.py (bands 2/5/10/20%, 0.25pp).
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_FLOOR, ROUND_HALF_UP, Decimal
from typing import Optional

BANDS = (Decimal("0.02"), Decimal("0.05"), Decimal("0.10"), Decimal("0.20"))
BAND_TOL = Decimal("0.0025")
PAISA = Decimal("0.01")


@dataclass(frozen=True)
class Bar:
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: int
    prev_close: Optional[Decimal]


@dataclass(frozen=True)
class Fill:
    status: str                  # FILLED | PARTIAL | NO_FILL
    price: Optional[Decimal]
    qty: int
    reason: Optional[str]
    base: Optional[Decimal] = None   # the raw price the fill keyed on, before slippage and paisa rounding


def px(x: Decimal) -> Decimal:
    return x.quantize(PAISA, rounding=ROUND_HALF_UP)


def _at_band(gap: Decimal, sign: int) -> bool:
    return any(abs(gap - sign * b) <= BAND_TOL for b in BANDS)


def locked_upper(b: Bar) -> bool:
    return b.prev_close is not None and b.prev_close > 0 and b.open == b.high and _at_band(b.open / b.prev_close - 1, +1)


def locked_lower(b: Bar) -> bool:
    return b.prev_close is not None and b.prev_close > 0 and b.open == b.low and _at_band(b.open / b.prev_close - 1, -1)


def fill_entry(kind: str, bar: Bar, *, qty: int, slippage_pct: Decimal, participation_pct: Decimal,
               trigger: Optional[Decimal] = None, limit: Optional[Decimal] = None) -> Fill:
    if qty < 1:
        return Fill("NO_FILL", None, 0, "ZERO_QTY")
    if bar.volume is None or bar.volume <= 0:
        return Fill("NO_FILL", None, 0, "NO_VOLUME")
    if kind == "MOO":
        if locked_upper(bar):
            return Fill("NO_FILL", None, 0, "LOCKED_UPPER")
        base = bar.open
    elif kind == "BUY_STOP":
        if trigger is None:
            raise ValueError("BUY_STOP needs a trigger")
        if bar.high < trigger:
            return Fill("NO_FILL", None, 0, "NOT_TRIGGERED")
        if locked_upper(bar):
            return Fill("NO_FILL", None, 0, "LOCKED_UPPER")
        base = max(bar.open, trigger)
    elif kind == "MOC":
        if bar.prev_close and bar.close == bar.high and _at_band(bar.close / bar.prev_close - 1, +1):
            return Fill("NO_FILL", None, 0, "LOCKED_UPPER_AT_CLOSE")
        base = bar.close
    elif kind == "LIMIT":
        if limit is None:
            raise ValueError("LIMIT needs a limit price")
        if bar.low > limit:
            return Fill("NO_FILL", None, 0, "NOT_REACHED")
        base = min(bar.open, limit)
    elif kind == "TYPICAL":
        if locked_upper(bar):
            return Fill("NO_FILL", None, 0, "LOCKED_UPPER")
        base = (bar.high + bar.low + bar.close) / 3
    else:
        raise ValueError(f"unknown order type {kind!r}")
    fillable = int((Decimal(bar.volume) * participation_pct / 100).to_integral_value(rounding=ROUND_FLOOR))
    if fillable < 1:
        return Fill("NO_FILL", None, 0, "NO_VOLUME")
    q = min(qty, fillable)
    price = px(base * (1 + slippage_pct / 100))
    if kind == "LIMIT":
        price = min(price, px(limit))                 # a limit order never fills above its limit
    return Fill("FILLED" if q == qty else "PARTIAL", price, q, None if q == qty else "PARTICIPATION_CAP", base)


def check_stop(bar: Bar, stop: Decimal, slippage_pct: Decimal) -> Optional[Fill]:
    """Stop exit for a long position on this bar, or None if the stop was not reached."""
    if bar.low > stop:
        return None
    if locked_lower(bar) and bar.open <= stop:
        return Fill("NO_FILL", None, 0, "LOCKED_LOWER")
    if bar.open <= stop:
        return Fill("FILLED", px(bar.open * (1 - slippage_pct / 100)), 0, "GAP_THROUGH")
    return Fill("FILLED", px(stop * (1 - slippage_pct / 100)), 0, "STOP")


def close_exit(bar: Bar, slippage_pct: Decimal, reason: str = "TIME") -> Fill:
    """Exit at the official close (time exit); a close locked at the lower circuit cannot be sold."""
    if bar.prev_close and bar.close == bar.low and _at_band(bar.close / bar.prev_close - 1, -1):
        return Fill("NO_FILL", None, 0, "LOCKED_LOWER_AT_CLOSE")
    return Fill("FILLED", px(bar.close * (1 - slippage_pct / 100)), 0, reason)


def check_target(bar: Bar, target: Decimal, slippage_pct: Decimal) -> Optional[Fill]:
    """Target exit for a long position on this bar, or None if the target was not reached."""
    if bar.high < target:
        return None
    if bar.open >= target:
        return Fill("FILLED", px(bar.open * (1 - slippage_pct / 100)), 0, "GAP_OVER_TARGET")
    return Fill("FILLED", px(target * (1 - slippage_pct / 100)), 0, "TARGET")


INTRABAR_POLICIES = ("STOP_FIRST", "TARGET_FIRST")


@dataclass(frozen=True)
class BarExit:
    fill: Optional[Fill]              # None: still open after this bar
    level: Optional[Decimal]          # the raw price the exit keyed on (open, stop or target), before slippage/rounding
    ambiguous: bool                   # the bar reached both levels and its open decided neither


def exit_on_bar(bar: Bar, stop: Optional[Decimal], target: Optional[Decimal], slippage_pct: Decimal,
                policy: str = "STOP_FIRST") -> BarExit:
    """One bar of a long position with a stop and/or a target: gap-through, gap-over, then the intrabar touches."""
    if policy not in INTRABAR_POLICIES:
        raise ValueError(f"unknown intrabar policy {policy!r}")
    if stop is not None and bar.open <= stop:
        f = check_stop(bar, stop, slippage_pct)
        return BarExit(f, bar.open if f.status == "FILLED" else None, False)
    if target is not None and bar.open >= target:
        return BarExit(check_target(bar, target, slippage_pct), bar.open, False)
    hit_stop = stop is not None and bar.low <= stop
    hit_target = target is not None and bar.high >= target
    if hit_stop and hit_target:
        if policy == "STOP_FIRST":
            return BarExit(check_stop(bar, stop, slippage_pct), stop, True)
        return BarExit(check_target(bar, target, slippage_pct), target, True)
    if hit_stop:
        return BarExit(check_stop(bar, stop, slippage_pct), stop, False)
    if hit_target:
        return BarExit(check_target(bar, target, slippage_pct), target, False)
    return BarExit(None, None, False)
