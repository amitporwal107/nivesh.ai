"""Corporate actions adjustments — applied lot-by-lot before tax calc.

Currently a skeleton. The two we'll see most often in MFs:
  • Stock split (rare in MFs, common in equity holdings).
  • Bonus units (some MFs declare bonus, equity stocks declare bonus).

Future events to add: rights issues, mergers (transfer cost basis from
acquired to acquirer), dividend reinvestment (which is just a BUY at
the dividend NAV, often already in cas_transactions).
"""
from __future__ import annotations
from typing import Iterable

from .models import HoldingLot


class CorporateActions:
    """Stateless transforms; caller picks which to apply per lot."""

    @staticmethod
    def apply_split(lot: HoldingLot, ratio: float) -> None:
        """e.g. 2:1 split → ratio=2 → quantity doubles, buy_price halves."""
        if ratio <= 0:
            return
        lot.quantity *= ratio
        lot.buy_price /= ratio

    @staticmethod
    def apply_bonus(lot: HoldingLot, bonus_ratio: float) -> None:
        """e.g. 1:1 bonus → bonus_ratio=1.0 → quantity doubles, original
        buy_price stays (bonus units have zero cost basis at allotment;
        we average it across the original lot's cost for simplicity —
        Indian tax law treats bonus units as zero cost basis at their
        allotment date, with their own holding period, but we'll wire
        that as a separate `apply_bonus_zero_cost` later if needed)."""
        if bonus_ratio <= 0:
            return
        bonus_qty = lot.quantity * bonus_ratio
        lot.quantity += bonus_qty

    @staticmethod
    def apply_bonus_zero_cost(lot: HoldingLot, bonus_ratio: float,
                                bonus_date) -> "HoldingLot":
        """Strict-correct version: returns a NEW lot with zero cost
        basis and its own buy_date. Use this when computing precise
        Indian tax — bonus units have separate holding period."""
        from .models import HoldingLot as _HL
        return _HL(
            symbol=lot.symbol,
            quantity=lot.quantity * bonus_ratio,
            buy_price=0.0,
            buy_date=bonus_date,
            folio=lot.folio,
            scheme_name=lot.scheme_name,
        )
