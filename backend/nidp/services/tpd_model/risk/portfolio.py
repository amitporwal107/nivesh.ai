"""Portfolio state (PRD §9): positions, cash, order reservations, stop-based open risk and exposures."""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Optional


@dataclass
class Position:
    symbol: str
    sector: str
    qty: int
    entry_price: Decimal
    stop: Decimal
    entry_date: dt.date
    initial_stop: Optional[Decimal] = None
    entry_index: int = 0
    entry_costs: Decimal = Decimal(0)
    signal_id: Optional[str] = None
    arm: Optional[str] = None
    atr: Optional[Decimal] = None
    highest_close: Optional[Decimal] = None
    binding_constraint: Optional[str] = None
    retroactive_costs: bool = False
    stop_kind: str = "INITIAL"             # INITIAL | BREAKEVEN | TRAILING (which rule set the live stop)

    def __post_init__(self):
        if self.initial_stop is None:
            self.initial_stop = self.stop
        if self.highest_close is None:
            self.highest_close = self.entry_price

    @property
    def r_per_share(self) -> Decimal:
        """Initial risk per share (R) from the actual fill; the basis of R-multiples and the trailing rules."""
        return self.entry_price - self.initial_stop


@dataclass
class Portfolio:
    cash: Decimal
    positions: dict = field(default_factory=dict)       # symbol -> Position
    reservations: dict = field(default_factory=dict)    # order id -> (symbol, sector, value, risk)

    def add(self, p: Position) -> None:
        if p.symbol in self.positions:
            raise ValueError(f"duplicate position in {p.symbol}")   # BR-004: averaging down is not supported in v1
        self.positions[p.symbol] = p

    def remove(self, symbol: str) -> Position:
        return self.positions.pop(symbol)

    def open_risk(self) -> Decimal:
        """Σ Q × max(entry − stop, 0): a stop trailed above entry carries no stop-based risk (§9.1)."""
        return sum((Decimal(p.qty) * max(p.entry_price - p.stop, Decimal(0)) for p in self.positions.values()), Decimal(0))

    def market_value(self, prices: dict) -> Decimal:
        return sum((Decimal(p.qty) * prices[p.symbol] for p in self.positions.values()), Decimal(0))

    def equity(self, prices: dict) -> Decimal:
        return self.cash + self.market_value(prices)

    def sector_value(self, sector: str, prices: dict) -> Decimal:
        return sum((Decimal(p.qty) * prices[p.symbol] for p in self.positions.values() if p.sector == sector), Decimal(0))

    def reserved_value(self) -> Decimal:
        return sum((v for _, _, v, _ in self.reservations.values()), Decimal(0))

    def reserved_sector(self, sector: str) -> Decimal:
        return sum((v for _, s, v, _ in self.reservations.values() if s == sector), Decimal(0))

    def reserved_risk(self) -> Decimal:
        return sum((r for _, _, _, r in self.reservations.values()), Decimal(0))

    def stress_loss(self, prices: dict, gap_pct: Decimal) -> Decimal:
        """Scenario risk (§9.1 item 2): every position gaps down by gap_pct at once, stops not honoured."""
        return self.market_value(prices) * gap_pct / 100
