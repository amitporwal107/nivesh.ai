"""Read-side: assemble a PortfolioResponse from a freshly-activated snapshot.

T1.5 produced a list of HoldingRows; T1.6 needs to send back something
human-friendly. This module computes totals, per-bucket allocation and a
top-N list. No I/O.
"""
from __future__ import annotations

from decimal import Decimal

from ..schemas.portfolio import AllocationItem, PortfolioResponse, TopHolding
from ..schemas.snapshot import HoldingRow


def assemble(holdings: list[HoldingRow], top_n: int = 10) -> PortfolioResponse:
    if not holdings:
        return PortfolioResponse(
            total_value=Decimal("0"),
            holdings_count=0,
            allocation=[],
            top_holdings=[],
        )

    total = sum((h.value for h in holdings), Decimal("0"))

    # Allocation by asset_class
    bucket: dict[str, Decimal] = {}
    for h in holdings:
        bucket[h.asset_class] = bucket.get(h.asset_class, Decimal("0")) + h.value
    allocation = [
        AllocationItem(
            asset_class=cls,
            value=val,
            pct=(val / total * Decimal("100")).quantize(Decimal("0.01"))
                if total else Decimal("0"),
        )
        for cls, val in sorted(bucket.items(), key=lambda kv: -kv[1])
    ]

    top = sorted(holdings, key=lambda h: -h.value)[:top_n]
    top_holdings = [
        TopHolding(
            name=h.name,
            asset_class=h.asset_class,
            value=h.value,
            pct=(h.value / total * Decimal("100")).quantize(Decimal("0.01"))
                if total else Decimal("0"),
        )
        for h in top
    ]

    return PortfolioResponse(
        total_value=total.quantize(Decimal("0.01")),
        holdings_count=len(holdings),
        allocation=allocation,
        top_holdings=top_holdings,
    )
