"""Charges on a simulated fill: the desk cost card `desk-cost-v2`, as Decimal.

The slippage is IN THE PRICE here (execution/fill_model.py), so the card's slippage component is set to 0 and not charged
twice. Brokerage (a desk assumption of ₹20 per order side) is charged once per order, on its first fill. The card's other
assumptions and sources are stated in services/desk_cost_card.py.
"""
from __future__ import annotations

from decimal import Decimal

from services import desk_cost_card as card

COST_MODEL = f"{card.VERSION} (slippage in the fill price)"
SEGMENT = {"EQ": "equity_delivery", "FUT": "futures", "CE": "options", "PE": "options"}
_MODEL = {**card.SNAPSHOT, "slippage_pct_per_side": 0.0}
_NO_BROKERAGE = {**_MODEL, "brokerage_rs_per_side": 0.0}


def charges(kind: str, side: str, value_rs: Decimal, *, first_fill: bool = True) -> dict[str, Decimal]:
    """{brokerage, stt, exchange, sebi, stamp, gst, slippage, total} on one fill of `value_rs` (premium for options)."""
    out = card.order_side(SEGMENT[kind], side, float(value_rs), _MODEL if first_fill else _NO_BROKERAGE)
    return {k: Decimal(str(v)).quantize(Decimal("0.01")) for k, v in out.items()}
