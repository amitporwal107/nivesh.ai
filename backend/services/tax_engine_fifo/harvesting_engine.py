"""Lot-level loss harvesting.

Operates on FIFOMatcher's open_lots — for each lot, compares its
buy_price against the current market NAV/price. Lots with negative
unrealised P&L are surfaced as harvesting candidates with their
holding period (so the user knows whether selling triggers ST or LT).

Higher fidelity than the Phase-1 heuristic: instead of one classification
per HOLDING, we get one per LOT. A user might have 24 SIP installments
in HDFC Balanced Advantage where the first 18 are in profit but the
last 6 (recent NAV drop) are in loss — Phase 1 would flag the holding
as net-positive; this engine surfaces the 6 losing lots.
"""
from __future__ import annotations
from datetime import datetime, timezone
from typing import Dict, List, Optional

from .models import HoldingLot

LT_THRESHOLD_DAYS = 365


class TaxHarvestingEngine:
    def __init__(self, holdings: Dict[str, List[HoldingLot]],
                 lt_threshold_days: int = LT_THRESHOLD_DAYS):
        self.holdings = holdings
        self.lt_threshold_days = lt_threshold_days

    def identify_losses(self, current_prices: Dict[str, float],
                          as_of: Optional[datetime] = None) -> List[Dict]:
        """Returns lots in unrealised loss, each tagged with the LT/ST
        bucket it would fall into IF sold today."""
        as_of = as_of or datetime.now(timezone.utc)
        opportunities: List[Dict] = []
        for symbol, lots in self.holdings.items():
            current_price = current_prices.get(symbol)
            if current_price is None:
                continue
            for lot in lots:
                unrealized = (current_price - lot.buy_price) * lot.quantity
                if unrealized >= 0:
                    continue
                buy_dt = lot.buy_date
                if buy_dt.tzinfo is None:
                    buy_dt = buy_dt.replace(tzinfo=timezone.utc)
                holding_days = (as_of - buy_dt).days
                bucket = "LTCG" if holding_days >= self.lt_threshold_days else "STCG"
                opportunities.append({
                    "symbol": symbol,
                    "scheme_name": lot.scheme_name,
                    "folio": lot.folio,
                    "qty": round(lot.quantity, 4),
                    "buy_price": round(lot.buy_price, 4),
                    "current_price": round(current_price, 4),
                    "loss_rs": round(unrealized, 2),
                    "buy_date": lot.buy_date.date().isoformat(),
                    "holding_days": holding_days,
                    "bucket_if_sold_today": bucket,
                })
        # Largest loss first
        opportunities.sort(key=lambda x: x["loss_rs"])
        return opportunities

    def aggregate_unrealized(self, current_prices: Dict[str, float]) -> Dict:
        """Per-symbol summary: total open units, weighted avg cost,
        unrealised P&L, current value."""
        out: Dict[str, Dict] = {}
        for symbol, lots in self.holdings.items():
            cp = current_prices.get(symbol)
            tot_qty = sum(l.quantity for l in lots)
            if tot_qty <= 0:
                continue
            invested = sum(l.quantity * l.buy_price for l in lots)
            avg_cost = invested / tot_qty if tot_qty > 0 else 0
            current_val = tot_qty * cp if cp is not None else None
            unrealised = (current_val - invested) if current_val is not None else None
            out[symbol] = {
                "scheme_name": lots[0].scheme_name if lots else None,
                "folio": lots[0].folio if lots else None,
                "open_units": round(tot_qty, 4),
                "avg_cost": round(avg_cost, 4),
                "invested_rs": round(invested, 2),
                "current_value_rs": round(current_val, 2) if current_val is not None else None,
                "unrealized_rs": round(unrealised, 2) if unrealised is not None else None,
                "n_lots": len(lots),
            }
        return out
