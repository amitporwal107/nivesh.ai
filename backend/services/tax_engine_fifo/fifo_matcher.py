"""FIFO matcher — consumes Trade events in chronological order and
maintains an open-lot ledger per symbol. Sells are matched against
the oldest open lots first.

Mirrors the `services/fifo_matcher.py` shape from the architecture
spec, with the key difference that quantities can be fractional
(critical for MFs where SIP units come in 11.842, 12.103, etc.).
"""
from __future__ import annotations
from collections import defaultdict
from typing import Dict, List, Tuple

from .models import HoldingLot, Trade

# Floating-point quantity reconciliation tolerance — anything inside
# this is treated as "fully consumed" so we don't leave 0.0001-unit
# orphan lots on the books.
_FP_TOL = 1e-6


class FIFOMatcher:
    """Stateful matcher. Construct one per user, feed trades in order."""

    def __init__(self):
        self.holdings: Dict[str, List[HoldingLot]] = defaultdict(list)

    def process_trade(self, trade: Trade) -> List[Tuple[HoldingLot, float]]:
        """Apply one trade; return the list of (lot, qty_consumed) tuples
        for SELLs (empty for BUYs)."""
        if trade.trade_type == "BUY":
            self.holdings[trade.symbol].append(HoldingLot(
                symbol=trade.symbol,
                quantity=trade.quantity,
                buy_price=trade.price,
                buy_date=trade.trade_date,
                folio=trade.folio,
                scheme_name=trade.scheme_name,
            ))
            return []
        if trade.trade_type == "SELL":
            return self._match_sell(trade)
        # Unknown trade type — treat as no-op (caller decides whether
        # to log or raise).
        return []

    def _match_sell(self, trade: Trade) -> List[Tuple[HoldingLot, float]]:
        matched: List[Tuple[HoldingLot, float]] = []
        qty_to_sell = float(trade.quantity)
        lots = self.holdings.get(trade.symbol, [])
        while qty_to_sell > _FP_TOL and lots:
            lot = lots[0]
            if lot.quantity <= qty_to_sell + _FP_TOL:
                # Lot fully consumed
                matched.append((lot, lot.quantity))
                qty_to_sell -= lot.quantity
                lots.pop(0)
            else:
                # Partial consumption — emit a copy so the caller's
                # tax calc doesn't see the post-decrement lot.qty.
                matched.append((HoldingLot(
                    symbol=lot.symbol, quantity=qty_to_sell,
                    buy_price=lot.buy_price, buy_date=lot.buy_date,
                    folio=lot.folio, scheme_name=lot.scheme_name,
                ), qty_to_sell))
                lot.quantity -= qty_to_sell
                qty_to_sell = 0.0
        return matched

    # ── Read accessors ───────────────────────────────────────────────
    def open_lots(self, symbol: str = None) -> List[HoldingLot]:
        if symbol is not None:
            return list(self.holdings.get(symbol, []))
        return [lot for lots in self.holdings.values() for lot in lots]

    def total_units(self, symbol: str) -> float:
        return sum(lot.quantity for lot in self.holdings.get(symbol, []))
