"""The P&L accounting: normalized executions in, positions out. Pure (no I/O), so every rule is unit-tested.

Accounting policy: WEIGHTED AVERAGE (the spec's `accounting_method: WEIGHTED_AVERAGE`).
    * Signed quantity: long is positive, short negative.
    * An execution on the same side as the position (or on a flat position) adds to it at a weighted average price.
    * An execution on the other side closes up to the open quantity first and realizes
      (price - average) x closed quantity x sign(position) x multiplier; anything left over opens a new position on the
      other side at the execution's price (a reversal: buy 100 then sell 150 closes 100 and opens a short 50).
    * Unrealized = (last price - average) x signed quantity x multiplier.
    * The same execution id is applied once (a duplicate broker or simulator report never counts twice).

Executions are applied in time order (ties keep the order they were given in).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional

QTY_EPS = 1e-9


@dataclass(frozen=True)
class Execution:
    execution_id: str
    position_key: str
    side: int                     # +1 buy, -1 sell
    quantity: float               # > 0, in units (shares, or lots x lot size)
    price: float
    multiplier: float = 1.0
    at: Optional[str] = None      # ISO time; ordering only
    kind: str = "fill"            # "fill" (opens / adds) or "exit" (as the ledger recorded it); informational

    def __post_init__(self) -> None:
        if self.side not in (1, -1):
            raise ValueError("side must be +1 or -1")
        if not self.quantity > 0:
            raise ValueError("quantity must be positive")
        if not self.price >= 0:
            raise ValueError("price must not be negative")


@dataclass
class Position:
    key: str
    net_quantity: float = 0.0
    average_price: Optional[float] = None
    realized_pnl: float = 0.0
    closed_quantity: float = 0.0
    multiplier: float = 1.0
    executions: List[Execution] = field(default_factory=list)

    @property
    def is_open(self) -> bool:
        return abs(self.net_quantity) > QTY_EPS

    @property
    def side(self) -> Optional[str]:
        if not self.is_open:
            return None
        return "LONG" if self.net_quantity > 0 else "SHORT"

    def unrealized(self, ltp: Optional[float]) -> Optional[float]:
        """(ltp - average) x signed quantity x multiplier; 0 for a flat position; None without a price."""
        if not self.is_open:
            return 0.0
        if ltp is None or self.average_price is None:
            return None
        return round((ltp - self.average_price) * self.net_quantity * self.multiplier, 2) + 0.0   # never -0.0


def _sign(x: float) -> int:
    return 1 if x > 0 else -1


def apply(pos: Position, ex: Execution) -> Position:
    """Apply one execution to a position in place (and return it)."""
    pos.executions.append(ex)
    pos.multiplier = ex.multiplier
    qty = ex.side * ex.quantity
    net = pos.net_quantity
    if abs(net) <= QTY_EPS or _sign(net) == _sign(qty):
        new = net + qty
        prior = (pos.average_price or 0.0) * abs(net)
        pos.average_price = (prior + ex.price * abs(qty)) / abs(new)
        pos.net_quantity = new
        return pos
    closing = min(abs(qty), abs(net))
    pos.realized_pnl = round(pos.realized_pnl + (ex.price - float(pos.average_price)) * closing * _sign(net) * ex.multiplier, 2)
    pos.closed_quantity += closing
    left = abs(qty) - closing
    pos.net_quantity = net + _sign(qty) * closing
    if abs(pos.net_quantity) <= QTY_EPS:
        pos.net_quantity = 0.0
        pos.average_price = None
    if left > QTY_EPS:                     # reversal: what is left opens the other side at this price
        pos.net_quantity = _sign(qty) * left
        pos.average_price = ex.price
    return pos


def build(executions: Iterable[Execution]) -> Dict[str, Position]:
    """{position_key: Position} from executions, each execution id applied once, in time order."""
    seen = set()
    ordered: List[Execution] = []
    for ex in executions:
        if ex.execution_id in seen:
            continue
        seen.add(ex.execution_id)
        ordered.append(ex)
    ordered = [e for _, e in sorted(enumerate(ordered), key=lambda p: (p[1].at or "", p[0]))]
    out: Dict[str, Position] = {}
    for ex in ordered:
        apply(out.setdefault(ex.position_key, Position(key=ex.position_key)), ex)
    return out
