"""Liquidity filter: position value vs average daily traded value (ADV).

`adv_inr` must be a trailing figure the caller already computed from bars strictly before the
signal/trade date (point-in-time discipline lives in the caller; this module only takes scalars).
"""
from __future__ import annotations

from decimal import Decimal
from typing import Optional


def _d(x) -> Decimal:
    return x if isinstance(x, Decimal) else Decimal(str(x))


def participation_ratio(position_value_inr: Decimal, adv_inr: Decimal) -> Decimal:
    """position_value / ADV. Returns Decimal('Infinity') if ADV is zero (an illiquid/untraded name),
    never raises and never silently returns 0 -- a caller must handle infinity explicitly rather
    than have a zero-ADV name look artificially liquid."""
    adv = _d(adv_inr)
    if adv <= 0:
        return Decimal("Infinity")
    return _d(position_value_inr) / adv


def is_liquid(position_value_inr: Decimal, adv_inr: Decimal, max_participation_pct: Decimal) -> bool:
    """True if the position would be at or below `max_participation_pct` of ADV. This is a FILTER
    (should this trade be allowed at all), independent of the slippage penalty a volume_dependent
    slippage model may separately charge for the same participation ratio."""
    ratio = participation_ratio(position_value_inr, adv_inr)
    if ratio.is_infinite():
        return False
    return ratio * 100 <= _d(max_participation_pct)
