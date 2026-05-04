"""Tier-2/3 lot-level Tax Engine (FIFO).

Public surface:
    build_user_tax_state(user_id) → TaxState
        .matcher           — FIFOMatcher with all open lots
        .calculator        — TaxCalculator with realised events + summary
        .harvesting        — TaxHarvestingEngine bound to current NAVs
        .symbol_metadata   — {isin → {scheme_name, asset_type, current_price}}
        .lot_count         — total open lots
        .data_quality      — "HIGH" | "MEDIUM" | "LOW" — driven by trade coverage

Trades are sourced from `db.cas_transactions` (CAS PDF imports) +
optional manual TXN events from `db.holdings` (when only end-state
holding rows exist, we synthesise a single BUY at buy_date+buy_price).

If a user has zero cas_transactions, this engine still builds lots
from the holdings collection — but flags data_quality=MEDIUM because
each holding becomes a single lot at avg cost (Phase-1-equivalent
fidelity, just expressed as lot objects).
"""
from __future__ import annotations
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from deps import db
from .models import Trade, HoldingLot, TaxEvent
from .fifo_matcher import FIFOMatcher
from .tax_calculator import TaxCalculator
from .harvesting_engine import TaxHarvestingEngine
from .corporate_actions import CorporateActions

logger = logging.getLogger(__name__)


@dataclass
class TaxState:
    matcher: FIFOMatcher
    calculator: TaxCalculator
    harvesting: TaxHarvestingEngine
    symbol_metadata: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    lot_count: int = 0
    data_quality: str = "LOW"
    n_transactions: int = 0
    n_holdings_seeded: int = 0


def _parse_dt(v) -> Optional[datetime]:
    if v is None or v == "":
        return None
    if isinstance(v, datetime):
        return v if v.tzinfo else v.replace(tzinfo=timezone.utc)
    try:
        s = str(v).replace("Z", "+00:00")
        d = datetime.fromisoformat(s)
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except Exception:  # noqa: BLE001
        return None


_BUY_TYPES = {"PURCHASE", "BUY", "SIP_PURCHASE", "SIP", "DIV_REINVEST"}
_SELL_TYPES = {"REDEMPTION", "REDEEM", "SELL", "SWITCH_OUT"}


async def _load_cas_trades(user_id: str) -> List[Trade]:
    """Pull cas_transactions in chronological order; convert to Trade
    objects keyed by ISIN (preferred) or scheme_name."""
    cursor = db.cas_transactions.find(
        {"user_id": user_id},
        {"_id": 0, "type": 1, "units": 1, "amount": 1, "nav": 1,
         "date": 1, "isin": 1, "scheme_name": 1, "amc": 1, "folio": 1,
         "folio_number": 1},
    ).sort("date", 1)
    trades: List[Trade] = []
    async for t in cursor:
        ttype_raw = (t.get("type") or "").upper()
        if ttype_raw in _BUY_TYPES:
            ttype = "BUY"
        elif ttype_raw in _SELL_TYPES:
            ttype = "SELL"
        else:
            continue
        units = float(t.get("units") or 0)
        if units <= 0:
            continue
        nav = float(t.get("nav") or 0)
        if nav <= 0:
            # Reconstruct from amount/units when NAV is missing.
            amt = float(t.get("amount") or 0)
            if amt > 0:
                nav = amt / units
            else:
                continue
        date = _parse_dt(t.get("date"))
        if date is None:
            continue
        symbol = t.get("isin") or t.get("scheme_name") or ""
        if not symbol:
            continue
        trades.append(Trade(
            symbol=symbol, quantity=units, price=nav, trade_date=date,
            trade_type=ttype, folio=t.get("folio") or t.get("folio_number"),
            scheme_name=t.get("scheme_name"),
        ))
    return trades


async def _load_current_prices_and_metadata(
    user_id: str, fallback_symbols: List[str],
) -> Dict[str, Dict[str, Any]]:
    """Build {symbol → {current_price, scheme_name, asset_type}} from
    db.holdings (which has live NAV / CMP). Prefer ISIN as the join key;
    fall back to scheme_name when ISIN is absent on the holdings doc."""
    holdings_cursor = db.holdings.find(
        {"user_id": user_id},
        {"_id": 0, "name": 1, "ticker": 1, "isin": 1, "asset_type": 1,
         "current_price": 1, "buy_price": 1, "buy_date": 1, "quantity": 1},
    )
    meta: Dict[str, Dict[str, Any]] = {}
    async for h in holdings_cursor:
        cp = float(h.get("current_price") or 0)
        if cp <= 0:
            continue
        # Try ISIN, then ticker (sometimes carries ISIN), then name.
        keys = []
        for k in (h.get("isin"), h.get("ticker"), h.get("name")):
            if k:
                keys.append(str(k))
        for key in keys:
            meta.setdefault(key, {
                "current_price": cp,
                "scheme_name": h.get("name"),
                "asset_type": (h.get("asset_type") or "").lower(),
                "buy_price": float(h.get("buy_price") or 0),
                "buy_date": h.get("buy_date"),
                "quantity": float(h.get("quantity") or 0),
            })
    # Fallback: if a transaction symbol isn't in the holdings index, we
    # have no current price for it. Caller's harvesting view skips it.
    return meta


def _seed_lot_from_holding(meta: Dict[str, Any], symbol: str) -> Optional[Trade]:
    """When a holding has no cas_transactions backing it, synthesise a
    single BUY trade at (buy_price, buy_date) — Phase-1-equivalent
    fidelity, still queryable through the same FIFO API."""
    qty = meta.get("quantity") or 0
    bp = meta.get("buy_price") or 0
    if qty <= 0 or bp <= 0:
        return None
    bdt = _parse_dt(meta.get("buy_date"))
    if bdt is None:
        return None  # caller marks data_quality=LOW for these
    return Trade(
        symbol=symbol, quantity=float(qty), price=float(bp),
        trade_date=bdt, trade_type="BUY",
        scheme_name=meta.get("scheme_name"),
    )


async def build_user_tax_state(user_id: str) -> TaxState:
    """Top-level entry — produces a fully-populated TaxState the chat
    retriever and the action generator can both use."""
    trades = await _load_cas_trades(user_id)
    n_tx = len(trades)

    # Track which symbols got real CAS-transaction coverage so we don't
    # double-count when seeding from holdings.
    covered_symbols = {t.symbol for t in trades}

    matcher = FIFOMatcher()
    calculator = TaxCalculator()
    for trade in trades:
        if trade.trade_type == "BUY":
            matcher.process_trade(trade)
        else:
            matched = matcher.process_trade(trade)
            calculator.calculate(matched, trade.price, trade.trade_date)

    # Seed remaining holdings as single lots
    meta_map = await _load_current_prices_and_metadata(
        user_id, fallback_symbols=list(covered_symbols),
    )
    n_seeded = 0
    for symbol, meta in meta_map.items():
        if symbol in covered_symbols:
            continue
        seed = _seed_lot_from_holding(meta, symbol)
        if seed is not None:
            matcher.process_trade(seed)
            n_seeded += 1

    # Build current_prices map keyed by the symbols our matcher actually
    # has open lots for. For ISIN-keyed lots, pick up the ISIN price;
    # also expose the same price under the scheme_name and ticker so
    # harvesting works regardless of which key the matcher sees.
    current_prices: Dict[str, float] = {}
    for symbol in matcher.holdings.keys():
        meta = meta_map.get(symbol) or {}
        cp = meta.get("current_price")
        if not cp:
            # Last resort — search by partial scheme_name match
            for k, v in meta_map.items():
                if symbol == v.get("scheme_name"):
                    cp = v.get("current_price")
                    break
        if cp:
            current_prices[symbol] = cp

    harvesting = TaxHarvestingEngine(matcher.holdings)
    # Stash the prices on the engine instance for downstream
    harvesting._current_prices = current_prices  # noqa: SLF001 — internal cache

    # Data-quality assessment
    if n_tx >= 5 and len(covered_symbols) >= 1:
        # Real CAS-transaction coverage on at least one instrument
        if len(covered_symbols) >= 5 or n_tx >= 20:
            quality = "HIGH"
        else:
            quality = "MEDIUM"
    elif n_seeded > 0:
        quality = "MEDIUM"  # holdings-seeded — same as Phase 1 heuristic
    else:
        quality = "LOW"

    return TaxState(
        matcher=matcher, calculator=calculator, harvesting=harvesting,
        symbol_metadata=meta_map, lot_count=len(matcher.open_lots()),
        data_quality=quality, n_transactions=n_tx,
        n_holdings_seeded=n_seeded,
    )


__all__ = [
    "build_user_tax_state", "TaxState",
    "Trade", "HoldingLot", "TaxEvent",
    "FIFOMatcher", "TaxCalculator", "TaxHarvestingEngine", "CorporateActions",
]
