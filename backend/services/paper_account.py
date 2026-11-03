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
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

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
    """Unblock what the trade reserved, apply its net P&L to cash and, when the trade holds a risk reservation
    (reserve_entry), give its risk budget back — all in ONE update.

    A trade that reserved nothing (opened before this existed) releases nothing: the account is not
    credited for a reservation that was never taken. The risk entry is released at most once: the update is
    conditional on the entry still being on the account, so a second release of the same trade moves no risk."""
    inc: Dict[str, float] = {}
    if amount:
        inc["blocked_rs"] = -float(amount)
    if net_pnl is not None:
        inc["cash_rs"] = float(net_pnl)
    doc = await db[ACCOUNTS].find_one({"user_id": user_id})
    entries = [e for e in ((doc or {}).get("reservations") or []) if e.get("trade_id") == trade_id]
    released: list = []
    if entries:
        risk_inc = _entries_inc(entries, sign=-1)
        res = await db[ACCOUNTS].update_one(
            {"user_id": user_id, "reservations.trade_id": trade_id},
            {"$inc": {**_merge(inc, risk_inc)}, "$pull": {"reservations": {"trade_id": trade_id}},
             "$set": {"updated_at": _iso()}})
        if res.matched_count:
            released = [e.get("id") for e in entries]
            await _ledger(db, user_id, action="release", amount_rs=float(amount or 0.0), net_pnl_rs=net_pnl,
                          trade_id=trade_id, symbol=symbol, risk_released=_ledger_risk(entries),
                          reservation_ids=released)
            return
        logger.error("paper_account: the risk reservation of %s was already released; funding and P&L only", trade_id)
    if not inc:
        return
    await ensure(db, user_id)
    await db[ACCOUNTS].update_one(
        {"user_id": user_id},
        {"$inc": inc, "$set": {"updated_at": _iso()}},
    )
    await _ledger(db, user_id, action="release", amount_rs=float(amount or 0.0),
                  net_pnl_rs=net_pnl, trade_id=trade_id, symbol=symbol)


# ── risk reservations (Phase 1, services/risk_gate/service.py) ───────────────
RESERVATION_VERSION = "risk-reservation-v1"
ORPHAN_GRACE_S = 120
_KEY_RE = re.compile(r"[^A-Za-z0-9_]")


def field_key(name: Any) -> str:
    """A symbol or sector as a Mongo field name: letters, digits and _ only (no '.' or '$'), upper-cased."""
    return _KEY_RE.sub("_", str(name or "").strip().upper())[:80] or "_"


def _merge(*parts: Dict[str, float]) -> Dict[str, float]:
    out: Dict[str, float] = {}
    for part in parts:
        for k, v in part.items():
            out[k] = out.get(k, 0.0) + v
    return out


def _entries_inc(entries: list, *, sign: int) -> Dict[str, float]:
    """The account counters these entries hold, times `sign` (-1 to release)."""
    inc: Dict[str, float] = {}
    for e in entries:
        inc = _merge(inc, {"open_risk_rs": sign * float(e.get("risk_rs") or 0.0),
                           "exposure_rs": sign * float(e.get("exposure_rs") or 0.0),
                           "open_positions": sign * int(e.get("positions") or 0)})
        if e.get("sector_key"):
            inc = _merge(inc, {f"sector_rs.{e['sector_key']}": sign * float(e.get("exposure_rs") or 0.0)})
        if e.get("held_key"):
            inc = _merge(inc, {f"held_symbols.{e['held_key']}": sign * 1})
    return {k: (round(v, 2) if not k.startswith(("held_symbols.", "open_positions")) else int(v)) for k, v in inc.items()}


def _ledger_risk(entries: list) -> Dict[str, Any]:
    return {"risk_rs": round(sum(float(e.get("risk_rs") or 0) for e in entries), 2),
            "exposure_rs": round(sum(float(e.get("exposure_rs") or 0) for e in entries), 2),
            "positions": sum(int(e.get("positions") or 0) for e in entries)}


class ReservationRefused(RuntimeError):
    """The atomic reservation did not match: a budget no longer fits (another entry took it first) or funds ran out.
    `which` names the budgets that do not fit when the account is re-read, for the refusal's reason."""

    def __init__(self, which: list, account: Dict[str, Any]) -> None:
        super().__init__("the risk reservation was refused: " + ", ".join(which or ["changed concurrently"]))
        self.which, self.account = which or ["changed_concurrently"], account


def _budget_conditions(b: Dict[str, Any], e: Dict[str, Any]) -> list:
    conds = [{"$gte": [{"$subtract": ["$cash_rs", "$blocked_rs"]}, float(e["funding_rs"])]},
             {"$lte": [{"$add": [{"$ifNull": ["$open_risk_rs", 0]}, float(e["risk_rs"])]}, float(b["open_risk_cap_rs"])]},
             {"$lte": [{"$add": [{"$ifNull": ["$exposure_rs", 0]}, float(e["exposure_rs"])]}, float(b["exposure_cap_rs"])]}]
    if e.get("positions"):
        conds.append({"$lt": [{"$ifNull": ["$open_positions", 0]}, int(b["max_positions"])]})
    if e.get("sector_key"):
        conds.append({"$lte": [{"$add": [{"$ifNull": [f"$sector_rs.{e['sector_key']}", 0]}, float(e["exposure_rs"])]},
                               float(b["sector_cap_rs"])]})
    if e.get("held_key"):
        conds.append({"$lte": [{"$ifNull": [f"$held_symbols.{e['held_key']}", 0]}, 0]})
    return conds


def which_budgets_fail(account: Optional[Dict[str, Any]], b: Dict[str, Any], e: Dict[str, Any]) -> list:
    """The budgets the entry no longer fits, read from the account as it stands (for the refusal's reason)."""
    a = account or {}
    out = []
    if float(a.get("cash_rs", DEFAULT_CAPITAL)) - float(a.get("blocked_rs", 0.0)) < float(e["funding_rs"]):
        out.append("insufficient_paper_funds")
    if float(a.get("open_risk_rs") or 0) + float(e["risk_rs"]) > float(b["open_risk_cap_rs"]) + 1e-9:
        out.append("open_risk_exceeded")
    if float(a.get("exposure_rs") or 0) + float(e["exposure_rs"]) > float(b["exposure_cap_rs"]) + 1e-9:
        out.append("exposure_exceeded")
    if e.get("positions") and int(a.get("open_positions") or 0) >= int(b["max_positions"]):
        out.append("max_positions")
    if e.get("sector_key") and float((a.get("sector_rs") or {}).get(e["sector_key"]) or 0) + float(e["exposure_rs"]) \
            > float(b["sector_cap_rs"]) + 1e-9:
        out.append("sector_exceeded")
    if e.get("held_key") and int((a.get("held_symbols") or {}).get(e["held_key"]) or 0) > 0:
        out.append("already_held")
    return out


async def reserve_entry(db, user_id: str, entry: Dict[str, Any], budgets: Dict[str, Any]) -> Dict[str, Any]:
    """Reserve an entry's funding AND its risk in ONE conditional update on the account, or raise ReservationRefused.

    `entry`: {id (the reservation id = the decision id), trade_id, store, path, kind, symbol, sector, funding_rs,
    risk_rs, exposure_rs, positions (1 for a new position, 0 for an add), held (True for a share position)}.
    `budgets`: the caps the decision computed, in rupees and counts, ALREADY NET of positions the counters do not hold
    (legacy positions): {open_risk_cap_rs, exposure_cap_rs, sector_cap_rs, max_positions}.

    The filter encodes every budget (funds, open risk, exposure, positions, the sector, the symbol not already held)
    and the update increments every counter and pushes the entry, so Mongo's single-document atomicity makes the
    check-and-reserve race-free: two concurrent entries can never both take the same remaining budget. The filter
    also requires the reservation id to be absent, so a retried reserve of the same decision cannot count twice."""
    await ensure(db, user_id)
    e = dict(entry)
    e.update(sector_key=field_key(e["sector"]) if e.get("sector") else None,
             held_key=field_key(e["symbol"]) if e.get("held") else None, at=_iso(), version=RESERVATION_VERSION)
    e["funding_rs"], e["risk_rs"], e["exposure_rs"] = (round(float(e[k]), 2) for k in ("funding_rs", "risk_rs", "exposure_rs"))
    inc = _merge({"blocked_rs": e["funding_rs"]}, _entries_inc([e], sign=1))
    res = await db[ACCOUNTS].update_one(
        {"user_id": user_id, "reservations.id": {"$ne": e["id"]}, "$expr": {"$and": _budget_conditions(budgets, e)}},
        {"$inc": inc, "$push": {"reservations": e}, "$set": {"updated_at": _iso()}})
    if not res.matched_count:
        account = await db[ACCOUNTS].find_one({"user_id": user_id})
        if account and any(r.get("id") == e["id"] for r in account.get("reservations") or []):
            return e                                     # this reservation is already on the account (a retry)
        raise ReservationRefused(which_budgets_fail(account, budgets, e), account or {})
    await _ledger(db, user_id, action="reserve", amount_rs=e["funding_rs"], trade_id=e["trade_id"], symbol=e.get("symbol"),
                  reservation_id=e["id"], risk_rs=e["risk_rs"], exposure_rs=e["exposure_rs"], sector=e.get("sector"))
    return e


async def cancel_reservation(db, user_id: str, reservation_id: str, *, reason: str) -> bool:
    """Give back a reservation whose position was never written (the insert failed, the caller refused it, or the
    process died before the write: sweep_orphans). Funding and risk, exactly once. True when THIS call released it."""
    doc = await db[ACCOUNTS].find_one({"user_id": user_id})
    entries = [e for e in ((doc or {}).get("reservations") or []) if e.get("id") == reservation_id]
    if not entries:
        return False
    inc = _merge({"blocked_rs": -float(entries[0].get("funding_rs") or 0.0)}, _entries_inc(entries, sign=-1))
    res = await db[ACCOUNTS].update_one(
        {"user_id": user_id, "reservations.id": reservation_id},
        {"$inc": inc, "$pull": {"reservations": {"id": reservation_id}}, "$set": {"updated_at": _iso()}})
    if res.matched_count:
        await _ledger(db, user_id, action="cancel_reservation", amount_rs=float(entries[0].get("funding_rs") or 0.0),
                      trade_id=entries[0].get("trade_id"), symbol=entries[0].get("symbol"), reservation_id=reservation_id,
                      risk_released=_ledger_risk(entries), reason=reason)
    return bool(res.matched_count)


async def sweep_orphans(db, user_id: str, *, exists, now: Optional[datetime] = None,
                        grace_s: int = ORPHAN_GRACE_S) -> list:
    """Release reservations whose position was never written and is older than `grace_s` (the process stopped
    between the reservation and the write). `exists(entry)` is awaited and says whether the entry's trade exists.
    Returns the released reservation ids. A reservation younger than the grace may belong to a write in flight and
    is left alone."""
    doc = await db[ACCOUNTS].find_one({"user_id": user_id})
    released = []
    moment = now or datetime.now(timezone.utc)
    for e in (doc or {}).get("reservations") or []:
        try:
            at = datetime.fromisoformat(str(e.get("at")))
        except ValueError:
            continue
        if (moment - at).total_seconds() < grace_s:
            continue
        if await exists(e):
            continue
        if await cancel_reservation(db, user_id, e["id"], reason="orphan: no position was written for this reservation"):
            released.append(e["id"])
            logger.warning("paper_account: released orphan reservation %s (%s) for %s", e["id"], e.get("symbol"), user_id)
    return released


def reservation_summary(doc: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """The account's reservation counters and entries, with the sector exposure keyed by the sector's name."""
    entries = list((doc or {}).get("reservations") or [])
    by_name: Dict[str, float] = {}
    for e in entries:
        if e.get("sector"):
            by_name[e["sector"]] = round(by_name.get(e["sector"], 0.0) + float(e.get("exposure_rs") or 0.0), 2)
    return {"entries": entries,
            "risk_rs": round(float((doc or {}).get("open_risk_rs") or 0.0), 2),
            "exposure_rs": round(float((doc or {}).get("exposure_rs") or 0.0), 2),
            "positions": int((doc or {}).get("open_positions") or 0),
            "sector_rs": dict((doc or {}).get("sector_rs") or {}),
            "sector_rs_by_name": by_name,
            "held_symbols": {k: v for k, v in ((doc or {}).get("held_symbols") or {}).items() if v}}


def reservation_invariants(doc: Optional[Dict[str, Any]]) -> list:
    """Counters that do not equal the sum of their entries (a leaked or double-counted reservation). [] when clean."""
    entries = list((doc or {}).get("reservations") or [])
    want = _entries_inc(entries, sign=1)
    out = []
    for key in ("open_risk_rs", "exposure_rs", "open_positions"):
        have = float((doc or {}).get(key) or 0.0)
        if abs(have - float(want.get(key, 0.0))) > 0.01:
            out.append({"counter": key, "account": have, "entries": want.get(key, 0.0)})
    for group in ("sector_rs", "held_symbols"):
        have_map = (doc or {}).get(group) or {}
        keys = set(have_map) | {k.split(".", 1)[1] for k in want if k.startswith(group + ".")}
        for k in keys:
            have, exp = float(have_map.get(k) or 0.0), float(want.get(f"{group}.{k}", 0.0))
            if abs(have - exp) > 0.01:
                out.append({"counter": f"{group}.{k}", "account": have, "entries": exp})
    return out


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
