"""The paper account: cash, blocked capital, and a refusal when there is not enough.

WHY THIS EXISTS
A paper trade cost nothing. `POST /api/desk/paper-trades` checked the symbol, the levels and a cap
of 100 open trades, and nothing else: a user could open a hundred positions of any size and every
one succeeded. So paper results were produced by an account that could never run out of money,
which makes position sizing unconstrained and the P&L a sum of trades rather than the behaviour of
a portfolio. The promotion gates in `ai_trader/strategy.py` read those numbers.

WHAT IS MODELLED
    available = cash - blocked
A cash trade reserves `quantity x entry price`. A multi-leg F&O structure reserves its CAPITAL AT
RISK — `desk_strategy_trades.exposure_rs`, an upper bound on what the structure can lose.

WHAT THAT IS NOT: it is not exchange margin. `strategy_plan/engine.py` records why — the SPAN and
exposure margin are not in the data platform, and the broker margin APIs are account-level rather
than per structure. Calling the reserved figure "margin" would be a number this system cannot
compute, so it is named `blocked_rs` and its basis travels with it.

RESERVE WHAT YOU RELEASE
The amount reserved is written on the trade, and the close releases THAT figure rather than
recomputing it from prices that have since moved. Recomputing is how an account silently drifts.

CORRECTIONS ARE ADDED, NEVER OVERWRITTEN
`adjust` is the only way a reconciliation (services/paper_reconcile.py) moves an account: a compensating
movement with a reason, the original trade id and an idempotency key, recorded as an "adjust" ledger row.
Nothing here deletes or rewrites a ledger row.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

ACCOUNTS = "paper_accounts"
LEDGER = "paper_account_ledger"
#: The ledger action of a reconciliation's compensating movement (`adjust`).
ADJUST = "adjust"

#: What a new paper account starts with. Matches the AI trader's own `initial_capital` default so a
#: strategy backtested at that size can be paper-traded at the same size.
DEFAULT_CAPITAL = 1_000_000.0

POLICY_VERSION = "paper-account-v1"

BLOCKED_BASIS = ("capital at risk, not exchange margin: SPAN and exposure margin are not in the data "
                 "platform and the broker margin APIs are account-level, not per structure")


class InsufficientFunds(RuntimeError):
    """Not enough available capital for this trade. Carries the numbers so the caller can say so."""

    def __init__(self, *, needed: float, available: float, cash: float, blocked: float) -> None:
        super().__init__("the paper account does not have enough available capital for this trade")
        self.needed, self.available, self.cash, self.blocked = needed, available, cash, blocked

    def detail(self) -> Dict[str, Any]:
        return {
            "code": "insufficient_paper_funds",
            "message": str(self),
            "needed_rs": round(self.needed, 2),
            "available_rs": round(self.available, 2),
            "cash_rs": round(self.cash, 2),
            "blocked_rs": round(self.blocked, 2),
            "blocked_basis": BLOCKED_BASIS,
            "note": "Close a position or reduce the size. Nothing was opened.",
        }


def _iso(dt: Optional[datetime] = None) -> str:
    return (dt or datetime.now(timezone.utc)).astimezone(timezone.utc).isoformat()


def public(doc: Optional[Dict[str, Any]], user_id: str) -> Dict[str, Any]:
    cash = float((doc or {}).get("cash_rs", DEFAULT_CAPITAL))
    blocked = float((doc or {}).get("blocked_rs", 0.0))
    capital = float((doc or {}).get("starting_capital_rs", DEFAULT_CAPITAL))
    return {
        "user_id": user_id,
        "starting_capital_rs": round(capital, 2),
        "cash_rs": round(cash, 2),
        "blocked_rs": round(blocked, 2),
        "available_rs": round(cash - blocked, 2),
        "blocked_basis": BLOCKED_BASIS,
        "stored": doc is not None,
        "policy_version": POLICY_VERSION,
    }


async def read(db, user_id: str) -> Dict[str, Any]:
    return public(await db[ACCOUNTS].find_one({"user_id": user_id}), user_id)


async def ensure(db, user_id: str) -> None:
    """Create the account with its opening balance if it does not exist yet.

    Called before every $inc, because an increment against a MISSING row starts from zero: the first
    release on a fresh account would have set cash to the P&L alone, wiping the opening balance.
    `$setOnInsert` cannot do this in the same update — Mongo refuses $setOnInsert and $inc on one
    field — so the row is created first and incremented second."""
    if await db[ACCOUNTS].find_one({"user_id": user_id}) is not None:
        return
    await db[ACCOUNTS].update_one(
        {"user_id": user_id},
        {"$setOnInsert": {"user_id": user_id, "cash_rs": DEFAULT_CAPITAL, "blocked_rs": 0.0,
                          "starting_capital_rs": DEFAULT_CAPITAL, "created_at": _iso(),
                          "policy_version": POLICY_VERSION}},
        upsert=True,
    )


async def _ledger(db, user_id: str, **row: Any) -> None:
    try:
        await db[LEDGER].insert_one({"user_id": user_id, "at": _iso(), "policy_version": POLICY_VERSION, **row})
    except Exception as e:  # noqa: BLE001 — the ledger is a record, not a gate
        logger.error("paper_account: ledger NOT written for %s (%s)", user_id, type(e).__name__)


def reservation_for(doc: Dict[str, Any], exposure: Optional[float]) -> Optional[float]:
    """What this trade must reserve, or None when it cannot be priced.

    None is refused by the caller rather than treated as free: a position whose cost is unknown is
    exactly the one that should not be opened against an account."""
    kind = doc.get("kind")
    if kind in (None, "cash"):
        qty, price = doc.get("quantity"), doc.get("entry_price")
        if qty is None or price is None:
            return None
        return round(float(qty) * float(price), 2)
    return None if exposure is None else round(float(exposure), 2)


async def reserve(db, user_id: str, amount: Optional[float], *, trade_id: str,
                  symbol: Optional[str] = None) -> float:
    """Block `amount` against the account, or raise InsufficientFunds. Returns the amount blocked.

    ONE conditional update: the filter matches only while cash - blocked >= amount, and the $inc is in the
    same write. Reading the balance and then incrementing let two concurrent requests both see the same
    free cash and both block it, overdrawing the account."""
    if amount is None:
        acct = await read(db, user_id)
        raise InsufficientFunds(needed=0.0, available=acct["available_rs"],
                                cash=acct["cash_rs"], blocked=acct["blocked_rs"])
    await ensure(db, user_id)
    res = await db[ACCOUNTS].update_one(
        {"user_id": user_id,
         "$expr": {"$gte": [{"$subtract": ["$cash_rs", "$blocked_rs"]}, float(amount)]}},
        {"$inc": {"blocked_rs": float(amount)}, "$set": {"updated_at": _iso()}},
    )
    if not res.matched_count:
        acct = await read(db, user_id)          # the numbers as they stand after the refusal
        raise InsufficientFunds(needed=amount, available=acct["available_rs"],
                                cash=acct["cash_rs"], blocked=acct["blocked_rs"])
    await _ledger(db, user_id, action="reserve", amount_rs=float(amount), trade_id=trade_id, symbol=symbol)
    return float(amount)


async def release(db, user_id: str, amount: Optional[float], *, net_pnl: Optional[float],
                  trade_id: str, symbol: Optional[str] = None) -> None:
    """Unblock what the trade reserved and apply its net P&L to cash.

    A trade that reserved nothing (opened before this existed) releases nothing: the account is not
    credited for a reservation that was never taken."""
    inc: Dict[str, float] = {}
    if amount:
        inc["blocked_rs"] = -float(amount)
    if net_pnl is not None:
        inc["cash_rs"] = float(net_pnl)
    if not inc:
        return
    await ensure(db, user_id)
    await db[ACCOUNTS].update_one(
        {"user_id": user_id},
        {"$inc": inc, "$set": {"updated_at": _iso()}},
    )
    await _ledger(db, user_id, action="release", amount_rs=float(amount or 0.0),
                  net_pnl_rs=net_pnl, trade_id=trade_id, symbol=symbol)


async def adjust(db, user_id: str, *, key: str, cash_delta: float = 0.0, blocked_delta: float = 0.0,
                 row: Dict[str, Any]) -> bool:
    """Apply a reconciliation's compensating movement at most once per `key`. True when THIS call moved the account.

    ONE conditional update moves the account and records the key on it (`adjustment_keys`): the filter matches only
    while the key is absent. So a retry cannot move the account twice, and neither can a run that died after the
    account write and before the ledger row. The ledger row's `_id` is the key, so it too is written once; a retry
    writes it when it is missing. Unlike `_ledger`, a failed ledger write is raised, not logged: a correction without
    its record is exactly what this exists to prevent, and the retry completes it.

    No funds check: a correction records a position or a result that already exists; refusing it would leave the
    account misstated. Raises LookupError when the user has no account (a correction never creates one)."""
    from pymongo.errors import DuplicateKeyError

    res = await db[ACCOUNTS].update_one(
        {"user_id": user_id, "adjustment_keys": {"$ne": key}},
        {"$inc": {"cash_rs": float(cash_delta), "blocked_rs": float(blocked_delta)},
         "$push": {"adjustment_keys": key}, "$set": {"updated_at": _iso()}},
    )
    moved = bool(res.matched_count)
    if not moved and await db[ACCOUNTS].find_one({"user_id": user_id, "adjustment_keys": key}) is None:
        raise LookupError("this user has no paper account; a correction never creates one")
    try:
        await db[LEDGER].insert_one({**row, "_id": key, "user_id": user_id, "at": _iso(), "policy_version": POLICY_VERSION,
                                     "action": ADJUST, "idempotency_key": key, "cash_delta_rs": float(cash_delta),
                                     "blocked_delta_rs": float(blocked_delta)})
    except DuplicateKeyError:
        pass                                    # recorded by an earlier attempt
    return moved
