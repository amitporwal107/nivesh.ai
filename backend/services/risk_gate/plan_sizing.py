"""How the universal risk service would size a TradePlan for ONE account (the Phase 3 release blocker: "a displayed trade
plan that materially differs from the plan used for sizing or risk approval").

A plan is shared (its id is a digest of its levels), so it carries no account's size. The size a card shows is worked
out here, for the signed-in user, by the risk service's OWN code on the same snapshot a submission would read
(service.gather: the risk profile and paper equity, the instrument's last close and traded value, the sector, the
market state), so it cannot drift from it:

    1. size     decide() on a NEUTRAL book (the account's equity, profile, controls and loss periods; no open positions,
                nothing reserved) with a request larger than any limit allows: the per-trade budget
                (estimate.py est-risk-v1: loss at the stop + desk-cost-v2 costs + 1% gap stress, within
                per_trade_risk_pct of paper equity), the governor's per-instrument caps (position size, liquidity), its
                VIX / BEAR factors and the share / lot rounding cut it to the size the service allows.
                A structure is sized at the lot count its surface records (an idea's legs cannot be resized there).
    2. confirm  decide() again on the neutral book at exactly that size: "sized" only when the service ALLOWS it as is.
                When it does not (the governor re-applies its BEAR / VIX factor to a size already cut, so no submitted
                size is allowed in those regimes) the status is "not_confirmed" with the service's reasons.
    3. now      decide() on the account's REAL book at that size: what open-risk, exposure, sector, position-count and
                funding limits would cut today, and the budgets left. Those limits can still cut the size at submission.

Nothing is recorded or reserved: this is sizing, not a decision (no risk_decisions row). The decision is made, and
recorded, when the paper trade is submitted. Nothing here places an order.
"""
from __future__ import annotations

import copy
import logging
import math
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from services import desk_trading as desk

from . import estimate as est
from . import service as svc

logger = logging.getLogger(__name__)

SIZING_VERSION = "plan-sizing-v1"
#: Checks / governor codes that depend on the open book, not on the plan and the account's limits.
PORTFOLIO_CHECKS = {"open_risk", "exposure", "sector", "funding"}
PORTFOLIO_GOVERNOR = {"NET_EXPOSURE", "SECTOR_LIMIT", "MAX_POSITIONS", "ALREADY_HELD", "HEDGE_SUGGESTED", "SECTOR_EXPOSURE_UNKNOWN"}
FACTOR_CODES = {"BEAR_REGIME", "VIX_REDUCE"}
PORTFOLIO_NOTE = "May be reduced by portfolio limits at submission (open risk, exposure, sector, open positions, funds)."
BASIS = ("The universal risk service's own sizing (services/risk_gate/service.decide on the snapshot a submission reads), "
         "on your account with no open positions: per-trade budget, position and liquidity caps, the VIX / BEAR factors and "
         "the share / lot rounding. Not a decision: the decision is made when the paper trade is submitted.")

def _reasons(rs: List[Dict[str, Any]], keep) -> List[Dict[str, Any]]:
    return [{k: r.get(k) for k in ("code", "check", "severity", "message")} for r in rs if keep(r)]


_LIMIT_TEXT = {
    "POSITION_SIZE": "Position size: at most {limit:g}% of your paper equity in one position",
    "LIQUIDITY": "Liquidity: at most {limit:g}% of the stock's average daily traded value",
    "RISK_PER_TRADE": "Risk per trade: the stop distance within {limit:g}% of your paper equity",
    "NET_EXPOSURE": "Net exposure: at most {limit:g}% of your paper equity in the market",
    "SECTOR_LIMIT": "Sector: at most {limit:g}% of your paper equity in one sector",
}


def _binding(rs: List[Dict[str, Any]], budget: Optional[float], size: int, unit: str) -> List[Dict[str, Any]]:
    """The limits that set the size, in words about the size found (the service's own messages describe the sizing probe,
    a request nobody made)."""
    out = []
    for r in rs:
        if r.get("severity") != "reduce" or r.get("code") in FACTOR_CODES:
            continue
        code, limit = r.get("code"), r.get("limit")
        if code == "per_trade_risk_exceeded":
            text = (f"Per-trade risk budget Rs {budget:,.2f} (the stop's loss + costs + {est.GAP_STRESS_PCT:g}% gap stress)"
                    if budget is not None else "Per-trade risk budget")
        elif code in _LIMIT_TEXT and isinstance(limit, (int, float)):
            text = _LIMIT_TEXT[code].format(limit=limit)
        else:
            text = r.get("message")
        out.append({"code": code, "check": r.get("check"), "severity": "reduce", "message": text})
    return out


def _is_portfolio(r: Dict[str, Any]) -> bool:
    return r.get("check") in PORTFOLIO_CHECKS or (r.get("check") == "governor" and r.get("code") in PORTFOLIO_GOVERNOR)


def _blocking(r: Dict[str, Any]) -> bool:
    return r.get("severity") in svc.BLOCKING


def neutral(snap: Dict[str, Any]) -> Dict[str, Any]:
    """The snapshot with an empty book: same equity, profile, controls, peak and day / week loss; no open position,
    reservation or blocked funds."""
    s = copy.deepcopy(snap)
    book = s.get("book")
    if isinstance(book, dict):
        book["open"] = {"positions": 0, "reserved_positions": 0, "legacy_positions": 0, "risk_rs": 0.0, "reserved_risk_rs": 0.0,
                        "legacy_risk_rs": 0.0, "legacy_risk_unknown": [], "exposure_rs": 0.0, "reserved_exposure_rs": 0.0,
                        "legacy_exposure_rs": 0.0, "sector_rs": {}, "unclassified_exposure_rs": 0.0, "held_symbols": []}
        book["positions"], book["reservations"] = [], []
        acct = book.get("account") or {}
        if acct.get("cash_rs") is not None:
            book["account"] = {**acct, "blocked_rs": 0.0, "available_rs": acct["cash_rs"]}
    if s.get("open_structures") not in (None, "n/a"):
        s["open_structures"] = 0
    return s


def _primary(tp: Dict[str, Any]) -> Optional[float]:
    t = next((t for t in tp.get("targets") or [] if t.get("primary")), None)
    return (t or {}).get("price")


def request_for(tp: Dict[str, Any], user_id: str, *, quantity: Optional[int] = None,
                lots: Optional[int] = None) -> Optional[svc.EntryRequest]:
    """The request the desk would send for this plan (routes/desk_trading._entry_request), at `quantity` shares or with
    every leg at `lots`. None when the plan has nothing to size (no entry or stop, or no legs)."""
    seg = (tp.get("strategy") or {}).get("segment")
    ins = tp.get("instrument") or {}
    common = dict(correlation_id=f"plan-sizing:{tp.get('plan_id')}", user_id=user_id, actor_id=user_id, mode="paper",
                  path="desk_paper_trade", action="open", trade_id=None, store=desk.TRADES, cost_model=dict(desk.COST_MODEL))
    if seg == "cash":
        entry, stop = (tp.get("entry") or {}).get("price"), (tp.get("stop") or {}).get("price")
        if entry is None or stop is None or quantity is None:
            return None
        return svc.EntryRequest(**common, instrument="cash", symbol=ins.get("symbol"), quantity=quantity,
                                entry_price=entry, stop_price=stop, target_price=_primary(tp))
    legs = []
    for leg in ins.get("legs") or []:
        n = lots if lots is not None else int(leg.get("lots") or (tp.get("size") or {}).get("lots") or 1)
        legs.append({"kind": leg.get("kind"), "side": leg.get("side"), "lots": n, "lot_size": leg.get("lot_size"),
                     "entry_price": leg.get("entry_price"), "expiry": leg.get("expiry"), "strike": leg.get("strike"),
                     "option_type": leg.get("option_type"),
                     "price_source": leg.get("price_source") or "the plan's end-of-day price"})
    if not legs:
        return None
    stop = tp.get("stop") or {}
    return svc.EntryRequest(**common, instrument="structure", symbol=ins.get("symbol"), legs=legs,
                            direction=(tp.get("strategy") or {}).get("direction"),
                            reference_price=(tp.get("entry") or {}).get("reference_close"),
                            stop_underlying=stop.get("price") if stop.get("method") == "underlying" or seg == "futures" else None,
                            target_underlying=_primary(tp))


def _size_of(decision: Dict[str, Any], cash: bool) -> int:
    v = decision.get("approved_qty") if cash else decision.get("approved_lots")
    return int(v) if isinstance(v, (int, float)) and v >= 0 else 0


def _remaining(budget: Dict[str, Any]) -> Dict[str, Any]:
    def left(cap: str, used: str) -> Optional[float]:
        c, u = budget.get(cap), budget.get(used)
        return None if c is None or u is None else round(float(c) - float(u), 2)
    pos = budget.get("max_open_positions"), budget.get("open_positions_before")
    return {"open_risk_rs": left("open_risk_cap_rs", "open_risk_before_rs"), "exposure_rs": left("exposure_cap_rs", "exposure_before_rs"),
            "sector": budget.get("sector"), "sector_rs": left("sector_cap_rs", "sector_before_rs"),
            "positions": None if None in pos else int(pos[0]) - int(pos[1]), "position_cap_rs": budget.get("position_cap_rs"),
            "per_trade_budget_rs": budget.get("per_trade_budget_rs")}


async def size_for(db, tp: Dict[str, Any], user_id: str, *, now: Optional[datetime] = None) -> Dict[str, Any]:
    """The account size of this plan for `user_id` (module docstring). Never raises: an unreadable input is
    `status: unavailable` with the reason."""
    try:
        return await _size_for(db, tp, user_id, now or desk.utcnow())          # the clock a submission decides on
    except Exception as exc:  # noqa: BLE001 — the card says the size is unavailable; the submission still decides
        logger.warning("plan_sizing: %s for %s failed: %s: %s", tp.get("plan_id"), user_id, type(exc).__name__, str(exc)[:200])
        return {"status": "unavailable", "reason": f"the sizing could not be worked out ({type(exc).__name__})",
                "version": SIZING_VERSION}


async def _size_for(db, tp: Dict[str, Any], user_id: str, now: datetime) -> Dict[str, Any]:
    seg = (tp.get("strategy") or {}).get("segment")
    cash = seg == "cash"
    base: Dict[str, Any] = {"version": SIZING_VERSION, "policy_version": svc.POLICY_VERSION, "estimate_version": est.ESTIMATE_VERSION,
                            "basis": BASIS, "portfolio_note": PORTFOLIO_NOTE, "unit": "shares" if cash else "lots per leg",
                            "as_of": now.astimezone(timezone.utc).isoformat()}
    probe = request_for(tp, user_id, quantity=1) if cash else request_for(tp, user_id)
    if probe is None:
        return {**base, "status": "unavailable", "reason": "the plan has no entry and stop (or no legs) to size"}
    snap = await svc.gather(db, probe, now)
    book = snap.get("book") or {}
    equity = (book.get("equity") or {}).get("equity_rs")
    profile = book.get("profile") or {}
    if equity is None or not profile:
        return {**base, "status": "unavailable",
                "reason": snap.get("book_error") or "; ".join((book.get("equity") or {}).get("unknown_reasons") or [])
                or "your paper equity or risk profile could not be read"}
    base.update(equity_rs=equity, limits_version=profile.get("limits_version"), profile=profile.get("profile"))
    flat = neutral(snap)
    if cash:
        entry = float(tp["entry"]["price"])
        upper = max(1, int(math.floor(float(equity) / entry)))          # every share the whole equity buys
        first = svc.decide(request_for(tp, user_id, quantity=upper), flat)
    else:
        first = svc.decide(probe, flat)
    size = _size_of(first, cash)
    first_reasons = first.get("reasons") or []
    blocks = _reasons(first_reasons, lambda r: _blocking(r) and not _is_portfolio(r))
    factors = _reasons(first_reasons, lambda r: r.get("code") in FACTOR_CODES)
    per_budget = (first.get("budget") or {}).get("per_trade_budget_rs")
    binding = _binding(first_reasons, per_budget, size, base["unit"])
    base.update(per_trade_budget_rs=per_budget, factors=factors, binding=binding)
    if first["outcome"] == "block" or size < 1:
        return {**base, "status": "not_sizable", "quantity": None, "lots": None, "blocking": blocks or _reasons(
            first_reasons, _blocking), "estimated_risk_rs": first.get("estimated_risk_rs")}
    req = request_for(tp, user_id, quantity=size) if cash else request_for(tp, user_id, lots=size)
    confirm = svc.decide(req, flat)
    est_rs = confirm.get("estimated_risk_rs") or first.get("estimated_risk_rs")
    total = (est_rs or {}).get("total")
    out = {**base, "quantity": size if cash else None, "lots": None if cash else size,
           "lot_size": None if cash else next((l.get("lot_size") for l in req.legs), None),
           "requested_lots": None if cash else est.common_lots(probe.legs),
           "estimated_risk_rs": est_rs,
           "risk_pct_of_equity": round(float(total) / float(equity) * 100, 3) if total is not None and equity else None,
           "blocking": blocks}
    if confirm["outcome"] != "allow":
        out.update(status="not_confirmed", confirm_outcome=confirm["outcome"],
                   confirm_size=_size_of(confirm, cash),
                   confirm_reasons=_reasons(confirm.get("reasons") or [], lambda r: r.get("severity") != "info"))
    else:
        out["status"] = "sized"
    now_d = svc.decide(req, snap)                                         # the real book, today
    out["portfolio"] = {"outcome": now_d["outcome"], "size_now": _size_of(now_d, cash),
                        "reasons": _reasons(now_d.get("reasons") or [], lambda r: _is_portfolio(r) and r.get("severity") != "info"),
                        "remaining": _remaining(now_d.get("budget") or {})}
    return out
