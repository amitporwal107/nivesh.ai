"""Loss, reward and capital of a plan's legs — one calculator for the Trading Assistant (to size and state a plan) and
the risk engine (to check it). Built on services/risk_gate/estimate.py (est-risk-v1) and the desk cost card.

Loss (owner rule 30 Oct: never "price to zero"):
  shares / futures  loss at the invalidation level + round-trip costs + the existing 1% gap stress
  options only      maximum loss at expiry from the payoff + round-trip costs
Capital used (what the position ties up):
  shares            notional (delivery uses full cash)
  futures           notional × futures_margin_pct — an ESTIMATE, not exchange SPAN
  options           the debit paid, or for a credit structure its maximum loss (width − credit) — an estimate
"""
from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Optional

from services.risk_gate import estimate as est

from ..contracts import CREDIT_STRATEGIES, Direction, InstrumentKind, LegSide, PlanLeg, StrategyType

SIZE_CHECKS = ("per_trade_risk", "position", "open_risk", "sector", "margin_utilization")


def rs(x: Any) -> Decimal:
    return Decimal(str(x)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def raw_legs(legs: list[PlanLeg]) -> list[dict]:
    """PlanLeg → the leg dicts services/risk_gate understands."""
    out = []
    for lg in legs:
        side = "buy" if lg.side == LegSide.LONG else "sell"
        if lg.kind == InstrumentKind.EQ:
            out.append({"kind": "cash", "side": side, "lots": lg.quantity, "lot_size": 1,
                        "entry_price": float(lg.ref_price)})
        elif lg.kind == InstrumentKind.FUT:
            out.append({"kind": "future", "side": side, "lots": lg.lots, "lot_size": lg.lot_size,
                        "entry_price": float(lg.ref_price), "expiry": lg.expiry.isoformat()})
        else:
            out.append({"kind": "option", "side": side, "lots": lg.lots, "lot_size": lg.lot_size,
                        "entry_price": float(lg.ref_price), "expiry": lg.expiry.isoformat(),
                        "strike": float(lg.strike), "option_type": "call" if lg.kind == InstrumentKind.CE else "put"})
    return out


def scale(legs: list[PlanLeg], multiple: int) -> list[PlanLeg]:
    """Legs at `multiple` (shares for a cash-only plan, lots per leg for derivatives; every leg scales together)."""
    out = []
    for lg in legs:
        lots = multiple
        qty = lots * lg.lot_size
        out.append(lg.model_copy(update={"lots": lots, "quantity": qty}))
    return out


def size_of(legs: list[PlanLeg]) -> Optional[int]:
    """The common size multiple (shares or lots), or None when the legs differ."""
    sizes = {lg.lots for lg in legs}
    return sizes.pop() if len(sizes) == 1 else None


def loss(legs: list[PlanLeg], *, strategy: StrategyType, direction: Direction,
         invalidation: Optional[Decimal]) -> tuple[Optional[dict], Optional[str]]:
    """(estimate dict with gross/costs/gap_stress/total, None) or (None, why)."""
    raw = raw_legs(legs)
    if all(lg.kind == InstrumentKind.EQ for lg in legs):
        if invalidation is None:
            return None, "a share plan needs an invalidation level"
        lg = legs[0]
        if lg.side != LegSide.LONG:
            return None, "short shares are not supported for positional plans"
        if invalidation >= lg.ref_price:
            return None, "the invalidation level must be below the plan level for a long position"
        return est.cash_risk(lg.quantity, float(lg.ref_price), float(invalidation)), None
    d = "bearish" if direction == Direction.BEARISH else "bullish"
    return est.structure_risk(raw, direction=d, stop_underlying=float(invalidation) if invalidation else None)


def reward(legs: list[PlanLeg], *, direction: Direction, target: Optional[Decimal]) -> Optional[float]:
    if target is None:
        return None
    if all(lg.kind == InstrumentKind.EQ for lg in legs):
        lg = legs[0]
        return est.cash_reward(lg.quantity, float(lg.ref_price), float(target))
    d = "bearish" if direction == Direction.BEARISH else "bullish"
    r, _basis = est.structure_reward(raw_legs(legs), direction=d, target_underlying=float(target))
    return r


def credit(legs: list[PlanLeg]) -> Optional[dict]:
    return est.credit_terms(raw_legs(legs))


def capital_used(legs: list[PlanLeg], *, strategy: StrategyType, futures_margin_pct: Decimal,
                 max_loss_rs: Optional[Decimal] = None) -> dict:
    """{"amount_rs", "method", "estimate": bool} — what the position ties up (see module docstring)."""
    if all(lg.kind == InstrumentKind.EQ for lg in legs):
        amt = sum(lg.ref_price * lg.quantity for lg in legs)
        return {"amount_rs": rs(amt), "method": "share notional", "estimate": False, "fno": False}
    fut = [lg for lg in legs if lg.kind == InstrumentKind.FUT]
    opts = [lg for lg in legs if lg.kind in (InstrumentKind.CE, InstrumentKind.PE)]
    amt = Decimal("0")
    parts = []
    if fut:
        notional = sum(lg.ref_price * lg.quantity for lg in fut)
        amt += notional * futures_margin_pct / 100
        parts.append(f"futures notional × {futures_margin_pct}% (estimate, not SPAN)")
    if opts:
        net = sum((lg.ref_price * lg.quantity) * (1 if lg.side == LegSide.LONG else -1) for lg in opts)
        if net > 0:
            amt += net
            parts.append("net option premium paid")
        else:
            c = credit(legs)
            ml = Decimal(str(c["max_loss_at_expiry_rs"])) if c else (max_loss_rs or Decimal("0"))
            amt += ml
            parts.append("credit structure: maximum loss at expiry (estimate of the blocked margin)")
    return {"amount_rs": rs(amt), "method": "; ".join(parts), "estimate": True, "fno": True}


def is_credit(strategy: StrategyType, legs: list[PlanLeg]) -> bool:
    return strategy in CREDIT_STRATEGIES or credit(legs) is not None
