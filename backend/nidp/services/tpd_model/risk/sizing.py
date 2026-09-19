"""Position sizing (PRD §7, BR-002/003/004/005/009).

Q_final = min(Q_risk, Q_stock_cap, Q_sector_cap, Q_cash, Q_deployment, Q_liquidity, Q_portfolio_risk). Every candidate,
the binding constraint and coded reasons are returned so a decision can be explained. Invalid or missing inputs are
rejected, never assumed.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import ROUND_FLOOR, Decimal
from typing import Optional

from .config import RiskConfig

ORDER = ("risk", "stock_cap", "sector_cap", "cash", "deployment", "liquidity", "portfolio_risk")
REJECT_REASON = {"risk": "RISK_BUDGET", "stock_cap": "STOCK_CAP", "sector_cap": "SECTOR_CAP", "cash": "INSUFFICIENT_CASH",
                 "deployment": "DEPLOYMENT_CAP", "liquidity": "LIQUIDITY", "portfolio_risk": "PORTFOLIO_RISK_CAP"}


@dataclass(frozen=True)
class SizingInput:
    capital: Decimal             # capital base for % limits (fixed capital or equity, per config)
    entry: Optional[Decimal]     # reference entry price
    stop: Optional[Decimal]
    cost_per_share: Decimal      # estimated round-trip cost per share
    cash: Decimal
    reserved: Decimal            # cash reserved by pending orders
    deployed_value: Decimal      # market value of positions + pending reservations
    stock_exposure: Decimal
    sector_exposure: Decimal
    open_risk: Decimal
    avg_traded_value: Optional[Decimal]
    holds_symbol: bool
    open_positions: int
    risk_multiplier: Decimal


@dataclass
class SizingResult:
    status: str                  # APPROVED (risk binds) | REDUCED (a cap binds) | REJECTED
    quantity: int
    candidates: dict = field(default_factory=dict)
    binding: Optional[str] = None
    reasons: list = field(default_factory=list)
    risk_amount: Optional[Decimal] = None
    risk_per_share: Optional[Decimal] = None


def _floor(a: Decimal, b: Decimal) -> int:
    if b <= 0:
        return 0
    q = int((a / b).to_integral_value(rounding=ROUND_FLOOR))
    return max(q, 0)


def _bad(x) -> bool:
    return x is None or not isinstance(x, Decimal) or not x.is_finite()


def size(cfg: RiskConfig, x: SizingInput) -> SizingResult:
    for name in ("capital", "entry", "stop", "cost_per_share", "cash", "reserved", "deployed_value", "stock_exposure",
                 "sector_exposure", "open_risk", "avg_traded_value", "risk_multiplier"):
        if _bad(getattr(x, name)):
            return SizingResult("REJECTED", 0, reasons=["MISSING_INPUT", f"invalid {name}"])
    if x.entry <= 0 or x.capital <= 0:
        return SizingResult("REJECTED", 0, reasons=["MISSING_INPUT", "non-positive entry or capital"])
    if cfg.require_valid_stop and x.stop >= x.entry:
        return SizingResult("REJECTED", 0, reasons=["INVALID_STOP"])
    dist_pct = (x.entry - x.stop) / x.entry * 100
    if dist_pct > cfg.max_stop_distance_pct:
        return SizingResult("REJECTED", 0, reasons=["STOP_TOO_WIDE"])
    if dist_pct < cfg.min_stop_distance_pct:
        return SizingResult("REJECTED", 0, reasons=["STOP_TOO_TIGHT"])
    if x.holds_symbol and not cfg.allow_averaging_down:
        return SizingResult("REJECTED", 0, reasons=["DUPLICATE_EXPOSURE"])
    if x.open_positions >= cfg.max_open_positions:
        return SizingResult("REJECTED", 0, reasons=["MAX_POSITIONS"])
    if x.avg_traded_value < cfg.min_avg_traded_value:
        return SizingResult("REJECTED", 0, reasons=["ILLIQUID"])
    if x.entry < cfg.min_stock_price:
        return SizingResult("REJECTED", 0, reasons=["PRICE_BELOW_MIN"])
    if x.risk_multiplier <= 0:
        return SizingResult("REJECTED", 0, reasons=["RISK_STATE_BLOCKS_ENTRY"])

    risk_amount = x.capital * cfg.risk_per_trade_pct / 100 * x.risk_multiplier
    per_share = x.entry - x.stop + x.cost_per_share
    c = x.capital
    cand = {
        "risk": _floor(risk_amount, per_share),
        "stock_cap": _floor(c * cfg.max_stock_allocation_pct / 100 - x.stock_exposure, x.entry),
        "sector_cap": _floor(c * cfg.max_sector_allocation_pct / 100 - x.sector_exposure, x.entry),
        "cash": _floor(x.cash - x.reserved - c * cfg.min_cash_reserve_pct / 100, x.entry + x.cost_per_share),
        "deployment": _floor(c * cfg.max_deployed_capital_pct / 100 - x.deployed_value, x.entry),
        "liquidity": _floor(x.avg_traded_value * cfg.max_volume_participation_pct / 100, x.entry),
        "portfolio_risk": _floor(c * cfg.max_portfolio_risk_pct / 100 - x.open_risk, per_share),
    }
    q = min(cand.values())
    binding = next(k for k in ORDER if cand[k] == q)
    if q < 1:
        return SizingResult("REJECTED", 0, cand, binding, [REJECT_REASON[binding]], risk_amount, per_share)
    return SizingResult("APPROVED" if binding == "risk" else "REDUCED", q, cand, binding, [], risk_amount, per_share)
