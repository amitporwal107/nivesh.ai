"""Daily-bar execution simulator (PRD §11, v1.1 §32.6-32.7). No fill at a price the bar did not offer:
- MOO: the open (+ slippage); nothing when the open is locked at the upper circuit.
- BUY_STOP: max(open, trigger) when the high reaches the trigger — a gap over the trigger fills at the open, never at
  the better trigger price.
- MOC: the official close (+ slippage).
- Stops: an open at or below the stop fills at the open (GAP_THROUGH), else at the stop; a session locked at the lower
  circuit cannot be sold. Volume participation caps the quantity (partial fills).
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


def px(x: Decimal) -> Decimal:
    return x.quantize(PAISA, rounding=ROUND_HALF_UP)


def _at_band(gap: Decimal, sign: int) -> bool:
    return any(abs(gap - sign * b) <= BAND_TOL for b in BANDS)


def locked_upper(b: Bar) -> bool:
    return b.prev_close is not None and b.prev_close > 0 and b.open == b.high and _at_band(b.open / b.prev_close - 1, +1)


def locked_lower(b: Bar) -> bool:
    return b.prev_close is not None and b.prev_close > 0 and b.open == b.low and _at_band(b.open / b.prev_close - 1, -1)


def fill_entry(kind: str, bar: Bar, *, qty: int, slippage_pct: Decimal, participation_pct: Decimal,
               trigger: Optional[Decimal] = None) -> Fill:
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
    else:
        raise ValueError(f"unknown order type {kind!r}")
    fillable = int((Decimal(bar.volume) * participation_pct / 100).to_integral_value(rounding=ROUND_FLOOR))
    if fillable < 1:
        return Fill("NO_FILL", None, 0, "NO_VOLUME")
    q = min(qty, fillable)
    price = px(base * (1 + slippage_pct / 100))
    return Fill("FILLED" if q == qty else "PARTIAL", price, q, None if q == qty else "PARTICIPATION_CAP")


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
