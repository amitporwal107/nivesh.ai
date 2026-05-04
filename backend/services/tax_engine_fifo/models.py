"""Data models for the lot-level tax engine.

Aligned with the spec the user shared on 2026-04-30. `Trade` is what
comes in (one row per CAS transaction or broker fill). `HoldingLot`
is what FIFOMatcher emits — one open lot per remaining BUY.

Both use plain dataclasses (no Pydantic) because they're pure
in-memory and we want zero-overhead inner loops in FIFO matching.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class Trade:
    symbol: str               # ISIN preferred, scheme_name fallback
    quantity: float           # units (fractional for MFs)
    price: float              # NAV / buy price per unit
    trade_date: datetime
    trade_type: str           # "BUY" | "SELL"
    is_intraday: bool = False
    folio: Optional[str] = None
    scheme_name: Optional[str] = None  # human label for the LLM/UI


@dataclass
class HoldingLot:
    symbol: str
    quantity: float
    buy_price: float
    buy_date: datetime
    folio: Optional[str] = None
    scheme_name: Optional[str] = None


@dataclass
class TaxEvent:
    """One realised gain/loss event from a SELL match."""
    symbol: str
    scheme_name: Optional[str]
    qty: float
    buy_price: float
    sell_price: float
    buy_date: datetime
    sell_date: datetime
    holding_period_days: int
    gain_rs: float                # qty * (sell_price - buy_price)
    tax_type: str                 # "STCG" | "LTCG"
    tax_rs: float                 # computed tax (post LTCG exemption)
