"""In-memory fakes for the SPT slice C suites (tests/test_spt_c_*.py). No network, no real database.

  FakeCollection / FakeDb   Mongo's filter and update semantics through tests/mongo_ops.py (the same reader the paper
                            account, desk and risk suites use), plus `$min`, unique indexes (compound and partial, equality
                            partial filters) and `_id` collisions raising pymongo's DuplicateKeyError — the SPT idempotency
                            rules lean on Mongo refusing the second insert, so a fake that accepted it would hide that path.
  World                     one test's database, clock, quotes and bars, and helpers that go through the REAL code:
                            `paper_account.reserve_entry` takes the reservation (as slice B's risk_gate.enter would) and
                            `orders.create_entry_order` creates the order exactly as slice B calls it (DESIGN.md §4).

MOCK — not real data: the FIXA / FIXB symbols, their quotes and bars are made up for these tests.
"""
from __future__ import annotations

import copy
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from pymongo.errors import DuplicateKeyError

from services import paper_account as acct
from services.spt import events as ev
from services.spt.paper import orders, store
from tests import mongo_ops

IST = timezone(timedelta(hours=5, minutes=30))
# Thursday 5 Nov 2026, 10:00 IST: in the session
NOW = datetime(2026, 11, 5, 4, 30, tzinfo=timezone.utc)


class _Cursor:
    def __init__(self, docs: List[Dict[str, Any]]):
        self._docs = docs

    def sort(self, key, direction: int = 1) -> "_Cursor":
        if isinstance(key, list):
            for k, d in reversed(key):
                self._docs = sorted(self._docs, key=lambda x: str(x.get(k) or ""), reverse=d < 0)
            return self
        self._docs = sorted(self._docs, key=lambda x: (str(type(x.get(key)).__name__), x.get(key) if x.get(key) is not None else ""),
                            reverse=direction < 0)
        return self

    def limit(self, n: int) -> "_Cursor":
        self._docs = self._docs[:n]
        return self

    async def to_list(self, length: Optional[int]) -> List[Dict[str, Any]]:
        return self._docs if length is None else self._docs[:length]


class _Result:
    def __init__(self, matched: int = 0, upserted_id: Any = None):
        self.matched_count = self.modified_count = matched
        self.upserted_id = upserted_id


def _keys(keys) -> List[str]:
    if isinstance(keys, str):
        return [keys]
    return [k for k, _ in keys]


def _in_partial(doc: Dict[str, Any], partial: Optional[Dict[str, Any]]) -> bool:
    return True if not partial else mongo_ops.match(doc, partial)


class FakeCollection:
    def __init__(self, name: str):
        self.name = name
        self.docs: List[Dict[str, Any]] = []
        self.unique: List[Any] = []
        self.fail_next: Dict[str, Exception] = {}       # op name → exception raised once

    def _maybe_fail(self, op: str) -> None:
        if op in self.fail_next:
            raise self.fail_next.pop(op)

    async def create_index(self, keys, **kw):
        if kw.get("unique"):
            self.unique.append((_keys(keys), kw.get("partialFilterExpression")))

    def find(self, query=None, projection=None):
        self._maybe_fail("find")
        return _Cursor([copy.deepcopy(d) for d in self.docs if mongo_ops.match(d, query or {})])

    async def find_one(self, query=None, projection=None):
        self._maybe_fail("find_one")
        return next((copy.deepcopy(d) for d in self.docs if mongo_ops.match(d, query or {})), None)

    async def count_documents(self, query):
        return sum(1 for d in self.docs if mongo_ops.match(d, query))

    def _check_unique(self, doc: Dict[str, Any], skip: Optional[Dict[str, Any]] = None) -> None:
        if "_id" in doc and any(d is not skip and d.get("_id") == doc["_id"] for d in self.docs):
            raise DuplicateKeyError("E11000 duplicate key: _id")
        for fields, partial in self.unique:
            if not _in_partial(doc, partial):
                continue
            for d in self.docs:
                if d is skip or not _in_partial(d, partial):
                    continue
                if all(d.get(f) == doc.get(f) for f in fields):
                    raise DuplicateKeyError(f"E11000 duplicate key: {fields}")

    async def insert_one(self, doc):
        self._maybe_fail("insert_one")
        doc = copy.deepcopy(doc)
        doc.setdefault("_id", str(uuid.uuid4()))
        self._check_unique(doc)
        self.docs.append(doc)
        return _Result(1)

    def _apply(self, d: Dict[str, Any], update: Dict[str, Any], inserting: bool = False) -> None:
        upd = {k: v for k, v in update.items() if k != "$min"}
        mongo_ops.apply(d, upd, inserting=inserting)
        for k, v in (update.get("$min") or {}).items():
            have = mongo_ops._get_one(d, k)
            if have is None or v < have:
                mongo_ops._set_path(d, k, v)

    async def update_one(self, query, update, upsert=False):
        self._maybe_fail("update_one")
        for d in self.docs:
            if mongo_ops.match(d, query):
                trial = copy.deepcopy(d)
                self._apply(trial, update)
                self._check_unique(trial, skip=d)
                d.clear()
                d.update(trial)
                return _Result(1)
        if upsert:
            doc: Dict[str, Any] = {k: v for k, v in query.items() if not k.startswith("$") and not isinstance(v, dict)}
            self._apply(doc, update, inserting=True)
            doc.setdefault("_id", str(uuid.uuid4()))
            self._check_unique(doc)
            self.docs.append(doc)
            return _Result(0, upserted_id=doc["_id"])
        return _Result(0)


class FakeDb:
    def __init__(self):
        self.cols: Dict[str, FakeCollection] = {}

    def __getitem__(self, name: str) -> FakeCollection:
        if name not in self.cols:
            self.cols[name] = FakeCollection(name)
        return self.cols[name]

    def __getattr__(self, name: str) -> FakeCollection:
        if name.startswith("_"):
            raise AttributeError(name)
        return self[name]

    def docs(self, name: str) -> List[Dict[str, Any]]:
        return self[name].docs


class FakeLeader:
    def __init__(self, me_is_leader: bool = True):
        self.ok = me_is_leader
        self.calls = 0

    async def lead(self, key: str, me: str, ttl: int, now: float) -> bool:
        self.calls += 1
        return self.ok


def ist(h: int, m: int = 0, s: int = 0, day: date = date(2026, 11, 5)) -> datetime:
    return datetime(day.year, day.month, day.day, h, m, s, tzinfo=IST).astimezone(timezone.utc)


def quote(ltp: float, *, bid: Optional[float] = None, ask: Optional[float] = None, bid_qty: Optional[int] = None,
          ask_qty: Optional[int] = None, at: Optional[datetime] = None, open_: Optional[float] = None,
          depth: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """MOCK — a quote in the snapshot's flat shape (services/kite_live_feed/quote_cache.as_quote), received at `at`."""
    stamp = (at or NOW).astimezone(IST).isoformat(timespec="milliseconds")
    q = {"ltp": ltp, "bid": bid, "ask": ask, "bid_qty": bid_qty, "ask_qty": ask_qty, "open": open_, "high": None,
         "low": None, "close": None, "volume": 100000.0, "received_at": stamp, "source": "kite_ws"}
    if depth is not None:
        q["depth"] = depth
    return q


class World:
    """One test's world. `now` is the clock the code is given; `quotes` what the feed answers."""

    def __init__(self):
        self.db = FakeDb()
        self.now = NOW
        self.quotes: Dict[str, Dict[str, Any]] = {}
        self.feed_why: Optional[str] = None
        self.bars: Dict[str, List[Dict[str, Any]]] = {}
        self.quote_calls: List[List[str]] = []

    async def read_quotes(self, symbols: List[str], now: datetime) -> Dict[str, Any]:
        self.quote_calls.append(list(symbols))
        return {"quotes": {s: copy.deepcopy(self.quotes[s]) for s in symbols if s in self.quotes}, "why": self.feed_why}

    async def read_bars(self, symbol: str, start: date) -> List[Dict[str, Any]]:
        return copy.deepcopy(self.bars.get(symbol, []))

    def deps(self):
        from services.spt.paper import monitor
        return monitor.Deps(db=self.db, quotes=self.read_quotes, bars=self.read_bars)

    async def account(self, user_id: str) -> Dict[str, Any]:
        return await self.db[acct.ACCOUNTS].find_one({"user_id": user_id}) or {}

    def ledger(self, user_id: str, action: Optional[str] = None) -> List[Dict[str, Any]]:
        return [r for r in self.db.docs(acct.LEDGER) if r.get("user_id") == user_id and (action is None or r.get("action") == action)]

    def events(self, event_type: Optional[str] = None) -> List[Dict[str, Any]]:
        return [e for e in self.db.docs(ev.C.EVENTS) if event_type is None or e["event_type"] == event_type]

    async def reserve(self, user_id: str, order_id: str, *, qty: int, entry: float, stop: float, symbol: str) -> Dict[str, Any]:
        """The reservation slice B's risk_gate.enter takes (through the real paper_account.reserve_entry), and the
        decision dict enter returns (the fields create_entry_order reads)."""
        decision_id = str(uuid.uuid4())
        funding = round(qty * entry, 2)
        await acct.reserve_entry(self.db, user_id,
                                 {"id": decision_id, "trade_id": order_id, "store": "spt_orders", "path": "spt_entry",
                                  "kind": "cash", "symbol": symbol, "sector": "Information Technology",
                                  "funding_rs": funding, "risk_rs": round((entry - stop) * qty, 2), "exposure_rs": funding,
                                  "positions": 1, "held": True},
                                 {"open_risk_cap_rs": 1e9, "exposure_cap_rs": 1e9, "sector_cap_rs": 1e9,
                                  "max_positions": 100})
        return {"decision_id": decision_id, "outcome": "allow", "reservation_id": decision_id, "approved_qty": qty,
                "planned_entry_price": entry, "budget": {"funding_rs": funding},
                "estimated_risk_rs": {"total": round((entry - stop) * qty, 2)}, "correlation_id": f"corr-{order_id}",
                "policy_version": "universal-risk-v2", "limits_version": "test-limits", "sector": "Information Technology"}

    async def entry(self, user_id: str = "user_a", *, symbol: str = "FIXA", qty: int = 100, entry: float = 100.0,
                    stop: float = 96.0, t1: Optional[float] = 108.0, t2: Optional[float] = 116.0,
                    order_type: str = "MARKET", limit_price: Optional[float] = None,
                    trigger_price: Optional[float] = None, tif: str = "DAY", expires_at: Any = None,
                    key: Optional[str] = None, order_id: Optional[str] = None, decision: Optional[Dict[str, Any]] = None,
                    trail: Optional[Dict[str, Any]] = None, trend: Optional[Dict[str, Any]] = None,
                    max_hold: Optional[int] = 20, reserve: bool = True) -> Dict[str, Any]:
        oid = order_id or str(uuid.uuid4())
        rd = decision
        if rd is None:
            rd = await self.reserve(user_id, oid, qty=qty, entry=entry, stop=stop, symbol=symbol) if reserve else \
                {"decision_id": "d-none", "outcome": "block", "reservation_id": None}
        plan = {"stop_loss": stop, "target_1": t1, "target_2": t2, "t1_exit_fraction": 0.5,
                "move_stop_to_breakeven_at_t1": True, "trail": trail, "trend_exit": trend, "max_hold_sessions": max_hold,
                "rules": "scan-plan-v3"}
        return await orders.create_entry_order(
            self.db, user_id=user_id, proposal_id=f"prop-{oid}", opportunity_id=f"opp-{symbol}", risk_decision=rd,
            symbol=symbol, side="BUY", order_type=order_type, quantity=qty, limit_price=limit_price,
            trigger_price=trigger_price, time_in_force=tif, expires_at=expires_at, exit_plan=plan,
            idempotency_key=key or f"key-{oid}", order_id=oid, now=self.now)

    async def position_of(self, order_id: str) -> Optional[Dict[str, Any]]:
        return await self.db[store.POSITIONS].find_one({"entry_order_id": order_id})


def reset_module_state(monkeypatch) -> None:
    """Per-process 'indexes created' flags would skip the unique indexes on a fresh FakeDb."""
    monkeypatch.setattr(ev, "_indexed", False)
    monkeypatch.setattr(store, "_indexed", False)
