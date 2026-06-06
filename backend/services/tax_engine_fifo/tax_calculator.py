"""Tax calculator — converts FIFO match output into typed tax events.

Per FY2025-26 Indian regime (Finance Act 2024, eff. 23-Jul-2024):
  • STCG (equity / equity-MF): < 365 days → 20%.
  • LTCG (equity / equity-MF): ≥ 365 days → 12.5% above ₹1.25L exemption per FY.
  • Debt / non-equity-MF: handled separately at slab rate (TODO when
    we differentiate categorically).
  • Gold/SGB: ≥ 36 months for LTCG; this calculator currently treats
    them with the equity threshold — that's wrong long-term, accept-
    able for v1 because gold tax classification needs SGB-specific
    rules anyway.

Rates are imported from services.tax_constants (the single source of truth)
so a Budget change only has to be made in one place.

The calculator is stateful within a single FY so the LTCG exemption
is consumed cumulatively (₹1.25L exemption applied once across all LT
events). Caller should construct one calculator per user-FY pair.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime
from typing import Iterable, List, Tuple

from .models import HoldingLot, TaxEvent
from services.tax_constants import (
    EQUITY_STCG_RATE as STCG_RATE,
    EQUITY_LTCG_RATE as LTCG_RATE,
    EQUITY_LTCG_EXEMPTION as LTCG_EXEMPTION_RS,
    EQUITY_LT_DAYS as LT_THRESHOLD_DAYS,
)


class TaxCalculator:
    def __init__(self, lt_threshold_days: int = LT_THRESHOLD_DAYS):
        self.lt_threshold_days = lt_threshold_days
        self.events: List[TaxEvent] = []
        self.ltcg_realised_total_rs: float = 0.0
        self.stcg_realised_total_rs: float = 0.0

    def calculate(
        self,
        matched_trades: Iterable[Tuple[HoldingLot, float]],
        sell_price: float,
        sell_date: datetime,
    ) -> List[TaxEvent]:
        """Convert one SELL's matched lots into tax events. Updates
        the running LT/ST totals."""
        results: List[TaxEvent] = []
        for lot, qty in matched_trades:
            if qty <= 0:
                continue
            holding_period = (sell_date - lot.buy_date).days
            gain = (sell_price - lot.buy_price) * qty

            if holding_period < self.lt_threshold_days:
                tax_type = "STCG"
                self.stcg_realised_total_rs += gain
                tax = max(0.0, gain * STCG_RATE) if gain > 0 else 0.0
            else:
                tax_type = "LTCG"
                # Apply running exemption: tax only the portion that
                # pushes cumulative LT gain ABOVE ₹1L.
                prior_lt = self.ltcg_realised_total_rs
                self.ltcg_realised_total_rs += gain
                if gain <= 0:
                    tax = 0.0
                else:
                    pre_exempt_used = min(prior_lt, LTCG_EXEMPTION_RS)
                    exemption_left = max(0.0, LTCG_EXEMPTION_RS - pre_exempt_used)
                    taxable_now = max(0.0, gain - exemption_left)
                    tax = taxable_now * LTCG_RATE

            evt = TaxEvent(
                symbol=lot.symbol, scheme_name=lot.scheme_name,
                qty=qty, buy_price=lot.buy_price, sell_price=sell_price,
                buy_date=lot.buy_date, sell_date=sell_date,
                holding_period_days=holding_period,
                gain_rs=gain, tax_type=tax_type, tax_rs=tax,
            )
            results.append(evt)
            self.events.append(evt)
        return results

    # ── Summary helpers ────────────────────────────────────────────
    @property
    def total_tax_rs(self) -> float:
        return sum(e.tax_rs for e in self.events)

    def summary(self) -> dict:
        return {
            "n_events": len(self.events),
            "stcg_total_rs": round(self.stcg_realised_total_rs, 2),
            "ltcg_total_rs": round(self.ltcg_realised_total_rs, 2),
            "ltcg_exemption_remaining_rs": round(
                max(0.0, LTCG_EXEMPTION_RS - self.ltcg_realised_total_rs), 2,
            ),
            "total_tax_rs": round(self.total_tax_rs, 2),
        }
