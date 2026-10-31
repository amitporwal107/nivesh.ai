"""The user's BROKER trades for the Copilot's daily review (owner, 31 Oct 2026: "This should also consider broker trades").

Brokers' trade books hold only the CURRENT day, so a week can be reviewed only from what was kept. This module reads the day's
fills of a live account (hub_reads.read_account_trades: Zerodha `trades()` and ICICI Direct's `/trades` are the only readers;
every other broker is "not supported" with its reason, never an empty list), keeps ONE document per account and IST day
(`broker_trade_days`, change-only: a read identical to the kept one only moves `last_seen_at`), and matches buys with sells into
round trips.

    broker_trade_days   {_id "bt_<account>_<day>", user_id, account_id, broker, day, trades:[BrokerTrade dicts], trades_hash,
                         count, first_seen_at, last_seen_at, changed_at, version}
                        Tenant-scoped: every read and write filters on user_id AND account_id. Holds what the broker said was
                        traded (symbol, side, quantity, price, time, ids); never a token, a key or an account number.
                        Kept by the 17:30 IST broker daily sync (while the day's session is live) and by any review that asks.

Matching (`match`): per account and contract, fills in time order, FIFO. A fill against an open lot of the OTHER side closes it
(a partial fill closes part of it: the lot keeps the rest); what is left is OPEN and is shown unmatched. Partial fills of one
order are one round trip (trips are summed by contract, exit day and direction). A sell with nothing to close is NOT assumed to
be a short: its other side may be a position carried from before the book was kept, so it is shown as an unmatched leg. Lots
carry across the days on record; a day nobody captured is simply absent (the answer says which days it has).
Realised P&L is the broker's own fill prices only, gross: quantity × (exit − entry) for a long, × (entry − exit) for a short,
quantity in UNITS (an F&O lot's units, as the broker sends them). Charges are never estimated: `fees_rs` is summed only when every
fill of both sides carries the broker's own figure.

Read-only: nothing here places, modifies or cancels an order.
"""
from __future__ import annotations

import hashlib
import json
import logging
from collections import deque
from datetime import datetime, timedelta, timezone
from typing import Any, Deque, Dict, List, Optional, Tuple

from fastapi import HTTPException

from . import symbols

logger = logging.getLogger(__name__)

COLL = "broker_trade_days"
TRADES_TTL_S = 60.0            # a broker's trade book is read at most this often per account
STORED_DAYS_MAX = 90           # newest days of an account read for a review
EPS = 1e-9
IST = timezone(timedelta(hours=5, minutes=30))

# account states in a review
CAPTURED, CACHED, ENDED, UNSUPPORTED, FAILED, UNREADABLE = "captured", "cached", "session_ended", "not_supported", "read_failed", "not_readable"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def ist_day(now: Optional[datetime] = None) -> str:
    return (now or _now()).astimezone(IST).date().isoformat()


def _num(v: Any) -> Optional[float]:
    if isinstance(v, bool) or v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if f == f and f not in (float("inf"), float("-inf")) else None


def _dt(iso: Any) -> Optional[datetime]:
    if not isinstance(iso, str):
        return None
    try:
        d = datetime.fromisoformat(iso)
    except ValueError:
        return None
    return d if d.tzinfo else d.replace(tzinfo=IST if len(iso) <= 10 else timezone.utc)


def trades_hash(trades: List[Dict[str, Any]]) -> str:
    return hashlib.sha256(json.dumps(trades, sort_keys=True, default=str).encode()).hexdigest()


def _order(t: Dict[str, Any]) -> Tuple[str, str]:
    d = _dt(t.get("traded_at"))
    return (d.astimezone(timezone.utc).isoformat() if d else "", str(t.get("trade_id") or t.get("order_id") or ""))


# ── keeping the day ──────────────────────────────────────────────────────────

async def ensure_indexes(db) -> None:
    await db[COLL].create_index([("user_id", 1), ("account_id", 1), ("day", -1)], unique=True)


async def _keep(db, doc: Dict[str, Any], day: str, trades: List[Dict[str, Any]], now: datetime) -> Tuple[str, bool]:
    """Store the day's trade list for the account; (document id, whether it changed what was kept)."""
    user_id, account_id = doc["user_id"], doc["account_id"]
    trades = sorted(trades, key=_order)
    h, stamp = trades_hash(trades), now.isoformat()
    cur = await db[COLL].find_one({"user_id": user_id, "account_id": account_id, "day": day})
    if cur and cur.get("trades_hash") == h:
        await db[COLL].update_one({"_id": cur["_id"], "user_id": user_id}, {"$set": {"last_seen_at": stamp}})
        return cur["_id"], False
    if cur:
        await db[COLL].update_one({"_id": cur["_id"], "user_id": user_id},
                                  {"$set": {"trades": trades, "trades_hash": h, "count": len(trades), "last_seen_at": stamp,
                                            "changed_at": stamp, "version": int(cur.get("version") or 1) + 1}})
        return cur["_id"], True
    sid = f"bt_{account_id}_{day}"
    await db[COLL].insert_one({"_id": sid, "user_id": user_id, "account_id": account_id, "broker": doc.get("broker") or "", "day": day,
                               "trades": trades, "trades_hash": h, "count": len(trades), "first_seen_at": stamp, "last_seen_at": stamp,
                               "changed_at": stamp, "version": 1})
    return sid, True


async def capture(db, doc: Dict[str, Any], *, now: Optional[datetime] = None) -> Dict[str, Any]:
    """Read today's trade book of a live native account and keep it. Returns {state, day, count, changed}; raises what the
    read raises (SessionEnded, BrokerSessionExpired, BrokerNotSupported, others) for the caller to map."""
    from services.brokers import hub_reads as hub
    now = now or _now()
    day = ist_day(now)
    cur = await db[COLL].find_one({"user_id": doc["user_id"], "account_id": doc["account_id"], "day": day})
    last = _dt((cur or {}).get("last_seen_at"))
    if cur and last and 0 <= (now - last).total_seconds() < TRADES_TTL_S:
        return {"state": CACHED, "day": day, "count": cur.get("count", 0), "changed": False}
    trades = await hub.read_account_trades(db, doc)
    try:
        await ensure_indexes(db)
    except Exception as e:  # noqa: BLE001 — an index is a convenience
        logger.info("trade book: index not ensured (%s)", type(e).__name__)
    _, changed = await _keep(db, doc, day, trades, now)
    return {"state": CAPTURED, "day": day, "count": len(trades), "changed": changed}


async def stored_days(db, user_id: str, account_id: str) -> List[Dict[str, Any]]:
    """The account's kept days, oldest first (at most STORED_DAYS_MAX newest)."""
    out = [d async for d in db[COLL].find({"user_id": user_id, "account_id": account_id})]
    out.sort(key=lambda d: d.get("day") or "")
    return out[-STORED_DAYS_MAX:]


async def review_data(request: Any, db, user_id: str) -> Dict[str, Any]:
    """Every account's state for a review and the days kept: {hub, accounts: [...], stored: [day docs with broker names]}.
    A live account's day is read now (cached TRADES_TTL_S); an ended account keeps what was kept; a broker with no trade-book
    reader says so. One account's failure is its own entry."""
    from routes import broker_connect as bc
    from services.brokers import hub_reads as hub, sessions
    from services.brokers.fenix_reader import BrokerNotSupported, BrokerSessionExpired
    try:
        await bc._hub_user(request)
    except HTTPException as e:
        if e.status_code == 403:
            return {"hub": "off", "accounts": [], "stored": []}
        raise
    accounts: List[Dict[str, Any]] = []
    stored: List[Dict[str, Any]] = []
    for doc in await bc._user_accounts(user_id):
        a = {**bc._account_entry(doc), "state": None, "error": None, "days": 0, "last_day": None}
        slug = doc.get("broker") or ""
        if not doc.get("native"):
            a.update(state=UNREADABLE, error={"code": hub.CODE_NOT_SUPPORTED, "message": bc._NOT_NATIVE_POSITIONS.replace("positions", "trades")})
        elif not hub.supports_trades(slug):
            a.update(state=UNSUPPORTED, error={"code": hub.CODE_NOT_SUPPORTED,
                                               "message": f"{a['broker_display']} has no trade-book reader yet, so its trades are not in this review."})
        elif not sessions.is_live(doc):
            code, msg = hub.describe_failure(sessions.SessionEnded("ended"), slug, "trades")
            a.update(state=ENDED, error={"code": code, "message": msg})
        else:
            try:
                a["state"] = (await capture(db, {**doc, "user_id": user_id}))["state"]
            except (sessions.SessionEnded, BrokerSessionExpired) as e:
                code, msg = hub.describe_failure(e, slug, "trades")
                a.update(state=ENDED, error={"code": code, "message": msg})
            except BrokerNotSupported as e:
                code, msg = hub.describe_failure(e, slug, "trades")
                a.update(state=UNSUPPORTED, error={"code": code, "message": msg})
            except Exception as e:  # noqa: BLE001 — this account fails alone
                code, msg = hub.describe_failure(e, slug, "trades")
                a.update(state=FAILED, error={"code": code, "message": msg})
        days = await stored_days(db, user_id, doc["account_id"]) if doc.get("native") else []
        a["days"], a["last_day"] = len(days), days[-1]["day"] if days else None
        for d in days:
            stored.append({"account_id": doc["account_id"], "broker": slug, "broker_display": a["broker_display"], "day": d["day"],
                           "trades": d.get("trades") or [], "last_seen_at": d.get("last_seen_at")})
        accounts.append(a)
    return {"hub": "on", "accounts": accounts, "stored": stored}


# ── matching ─────────────────────────────────────────────────────────────────

def instrument_of(t: Dict[str, Any], broker: str) -> Dict[str, Any]:
    """{key, underlying, label, mapped, kind}: the contract a fill is in. `key` identifies it within the account."""
    ex = str(t.get("exchange") or "").upper()
    row = {"symbol": t.get("symbol"), "segment": "fno" if ex in ("NFO", "BFO") else "equity", "instrument_type": t.get("instrument_type"),
           "expiry": t.get("expiry"), "strike": t.get("strike")}
    c = symbols.normalise(row, broker)
    key = (ex, t.get("symbol"), t.get("instrument_type"), t.get("expiry"), t.get("strike"))
    return {"key": key, "underlying": c.underlying if c.mapped else None, "label": symbols.label(c) if c.mapped else str(t.get("symbol")),
            "mapped": c.mapped, "instrument": c.instrument if c.mapped else None,
            "kind": {"EQ": "cash", "FUT": "future"}.get(c.instrument, "option") if c.mapped else "unknown"}


def match(stored: List[Dict[str, Any]], through_day: Optional[str] = None) -> Dict[str, Any]:
    """Round trips and open lots from the kept days of ONE OR MORE accounts (each account matched on its own).

    Returns {trips: [...], open: [...], days: {account_id: [day,...]}}. A trip: {account_id, broker_display, key, underlying,
    label, kind, direction long|short, quantity, entry_price, exit_price, entry_at, exit_at, entry_day, exit_day, pnl_rs,
    fees_rs, fills}. An open lot: {account_id, broker_display, label, underlying, side, quantity, avg_price, since_day, note}."""
    by_acct: Dict[str, List[Dict[str, Any]]] = {}
    for d in stored:
        if through_day and d["day"] > through_day:
            continue
        by_acct.setdefault(d["account_id"], []).append(d)
    trips: List[Dict[str, Any]] = []
    open_lots: List[Dict[str, Any]] = []
    days: Dict[str, List[str]] = {}
    for acct, ds in by_acct.items():
        ds.sort(key=lambda d: d["day"])
        days[acct] = [d["day"] for d in ds]
        broker, display = ds[0].get("broker") or "", ds[0].get("broker_display") or ds[0].get("broker") or ""
        fills: List[Tuple[str, Dict[str, Any]]] = [(d["day"], t) for d in ds for t in sorted(d.get("trades") or [], key=_order)]
        lots: Dict[Tuple, Deque[Dict[str, Any]]] = {}
        meta: Dict[Tuple, Dict[str, Any]] = {}
        raw: List[Dict[str, Any]] = []
        for day, t in fills:
            qty, px = _num(t.get("quantity")), _num(t.get("price"))
            side = str(t.get("side") or "").lower()
            if not qty or qty <= 0 or not px or side not in ("buy", "sell"):
                continue
            ins = instrument_of(t, broker)
            meta[ins["key"]] = ins
            q = lots.setdefault(ins["key"], deque())
            remaining = qty
            while remaining > EPS and q and q[0]["side"] != side:
                lot = q[0]
                take = min(remaining, lot["qty"])
                long = lot["side"] == "buy"
                raw.append({"key": ins["key"], "direction": "long" if long else "short", "qty": take, "entry": lot["price"], "exit": px,
                            "entry_at": lot["at"], "exit_at": t.get("traded_at"), "entry_day": lot["day"], "exit_day": day,
                            "pnl": take * ((px - lot["price"]) if long else (lot["price"] - px)),
                            "fee": None if lot["fee"] is None or _num(t.get("fees_rs")) is None else lot["fee"] * take / lot["orig"] + _num(t["fees_rs"]) * take / qty})
                lot["qty"] -= take
                remaining -= take
                if lot["qty"] <= EPS:
                    q.popleft()
            if remaining > EPS:
                q.append({"side": side, "qty": remaining, "orig": qty, "price": px, "at": t.get("traded_at"), "day": day, "fee": _num(t.get("fees_rs"))})
        # partial fills of one order are ONE round trip: sum by contract, exit day and direction
        agg: Dict[Tuple, Dict[str, Any]] = {}
        for r in raw:
            k = (r["key"], r["exit_day"], r["direction"])
            a = agg.get(k)
            if a is None:
                a = agg[k] = {"qty": 0.0, "entry_value": 0.0, "exit_value": 0.0, "pnl": 0.0, "fills": 0, "entry_at": r["entry_at"], "exit_at": r["exit_at"],
                              "entry_day": r["entry_day"], "fee": 0.0, "fee_known": True}
            a["qty"] += r["qty"]
            a["entry_value"] += r["qty"] * r["entry"]
            a["exit_value"] += r["qty"] * r["exit"]
            a["pnl"] += r["pnl"]
            a["fills"] += 1
            a["exit_at"] = r["exit_at"] or a["exit_at"]
            a["entry_day"] = min(a["entry_day"], r["entry_day"])
            if r["fee"] is None:
                a["fee_known"] = False
            else:
                a["fee"] += r["fee"]
        for (key, exit_day, direction), a in agg.items():
            ins = meta[key]
            trips.append({"account_id": acct, "broker_display": display, "key": list(key), "underlying": ins["underlying"], "label": ins["label"],
                          "kind": ins["kind"], "instrument": ins["instrument"], "direction": direction, "quantity": round(a["qty"], 6),
                          "entry_price": round(a["entry_value"] / a["qty"], 4), "exit_price": round(a["exit_value"] / a["qty"], 4),
                          "entry_at": a["entry_at"], "exit_at": a["exit_at"], "entry_day": a["entry_day"], "exit_day": exit_day,
                          "pnl_rs": round(a["pnl"], 2), "fees_rs": round(a["fee"], 2) if a["fee_known"] else None, "fills": a["fills"]})
        for key, q in lots.items():
            if not q:
                continue
            ins = meta[key]
            tot = sum(l["qty"] for l in q)
            sides = {l["side"] for l in q}
            open_lots.append({"account_id": acct, "broker_display": display, "label": ins["label"], "underlying": ins["underlying"],
                              "side": next(iter(sides)), "quantity": round(tot, 6),
                              "avg_price": round(sum(l["qty"] * l["price"] for l in q) / tot, 4), "since_day": min(l["day"] for l in q),
                              "note": "Its other side is not in the trade books on record: a position carried from before the book was kept, "
                                      "or still open. Not treated as a short."})
    trips.sort(key=lambda t: (t["exit_day"], t["exit_at"] or ""))
    return {"trips": trips, "open": open_lots, "days": days}
