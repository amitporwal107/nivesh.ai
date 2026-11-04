"""Shared fakes for the SPT slice-B suites (tests/test_spt_b_*.py). Not a test module (no `test_` prefix).

MOCK — not real data. Every user, symbol, price, opportunity and order here is made up. What is replaced, and by what:
  * Mongo                    FakeDB: tests/test_desk_trading.FakeCollection per collection (unique indexes modelled, so
                             the proposal's (user, opportunity) key and the event log's idempotency key really refuse a
                             second insert), created on first use
  * slice A's store          FakeOppStore (get / list_by_state / transition, the DESIGN §4 contract)
  * slice C's orders         FakeOrders.create_entry_order (writes a spt_orders document under the order id it is given)
  * the live quote cache     quote_cache.read_quotes → QUOTES rows stamped QUOTE_AGE_S before NOW
  * the risk inputs          risk_gate.inputs.instrument → a fresh last close and a large ADV (conftest's autouse
                             fixture already gives a sector and a calm market)
  * the clock                desk_trading.utcnow → NOW (Thursday 5 Nov 2026, 10:30 IST, in session)
Everything else runs for real: the universal risk service (gather, decide, enter, the reservation on the paper account),
risk_book, risk_profile, risk_controls, the cost card and the SPT modules.
"""
from __future__ import annotations

import copy
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import pytest

from services import desk_trading as desk
from services.kite_live_feed import quote_cache
from services.risk_gate import inputs
from services.spt import constants as C
from services.spt import events, pipeline, proposals
from tests.test_desk_trading import FakeCollection

NOW = datetime(2026, 11, 5, 5, 0, tzinfo=timezone.utc)          # Thursday 10:30 IST
IST = timezone(timedelta(hours=5, minutes=30))
LAST_SESSION = "2026-11-04"
U1, U2 = "spt-user-1", "spt-user-2"


class FakeDB:
    def __init__(self) -> None:
        self.cols: Dict[str, FakeCollection] = {}

    def __getitem__(self, name: str) -> FakeCollection:
        if name not in self.cols:
            self.cols[name] = FakeCollection()
        return self.cols[name]

    def __getattr__(self, name: str) -> FakeCollection:
        if name.startswith("_"):
            raise AttributeError(name)
        return self[name]

    def docs(self, name: str) -> List[Dict[str, Any]]:
        return self[name].docs


def plan(entry=500.0, stop=480.0, t1=540.0, t2=580.0, **over) -> Dict[str, Any]:
    p = {"rules": "scan-plan-v3", "entry": entry, "stop_loss": stop, "target_1": t1, "target_2": t2, "atr": 10.0,
         "sma20": 490.0, "trend_exit": "A daily close below the 20-day average", "plan_ok": True, "plan_note": None}
    p.update(over)
    return p


def opportunity(sym: str = "FIXA", *, score: Optional[float] = 72.0, adv: Optional[float] = 5e9, state=C.OPP_QUALIFIED,
                scanner_score: float = 80.0, **over) -> Dict[str, Any]:
    """MOCK — an opportunity document in the DESIGN §4 shape."""
    o = {"_id": f"opp-{sym}", "consolidation_key": f"NSE:{sym}:long:positional", "symbol": sym, "exchange": "NSE",
         "direction": "long", "family": "breakout", "category": "Breakout", "horizon": "positional", "day": "2026-11-05",
         "first_seen_at": "2026-11-05T04:00:00+00:00", "window_until": "2026-11-07T10:00:00+00:00",
         "expires_at": "2026-11-10T10:00:00+00:00", "state": state, "version": 3,
         "signals": [{"signal_id": f"sig:2026-11-05:strong:{sym}", "scanner_id": "dt_vol_price_breakout",
                      "scanner_name": "MOCK breakout", "detected_at": "2026-11-05T04:00:00+00:00",
                      "detected_price": 500.0, "scanner_score": scanner_score, "score_version": "mock",
                      "category": "Breakout", "family": "breakout"}],
         "conflicts": [],
         "strong": {"signal_id": f"sig:2026-11-05:strong:{sym}", "first_strong": "2026-11-05T04:00:00+00:00",
                    "score_at": scanner_score, "plan": plan()},
         "validation": {"at": "2026-11-05T04:05:00+00:00", "version": C.VALIDATION_VERSION, "decision": C.OPP_QUALIFIED,
                        "reason_codes": [], "explanations": [], "opportunity_score": score,
                        "liquidity": {"adv_rs": adv}},
         "created_at": "2026-11-05T04:00:00+00:00", "updated_at": "2026-11-05T04:05:00+00:00"}
    o.update(over)
    return o


class FakeOppStore:
    """Slice A's services.spt.opportunities.store (DESIGN §4)."""

    def __init__(self) -> None:
        self.opps: Dict[str, Dict[str, Any]] = {}
        self.transitions: List[Dict[str, Any]] = []

    def add(self, *opps: Dict[str, Any]) -> None:
        for o in opps:
            self.opps[o["_id"]] = copy.deepcopy(o)

    async def get(self, db, opp_id):
        o = self.opps.get(opp_id)
        return copy.deepcopy(o) if o else None

    async def list_by_state(self, db, states, *, day=None, limit=500):
        return [copy.deepcopy(o) for o in self.opps.values() if o["state"] in states][:limit]

    async def transition(self, db, opp_id, *, expect_states, to_state, reason, extra=None):
        o = self.opps.get(opp_id)
        if o is None or o["state"] not in expect_states:
            return None
        o["state"] = to_state
        self.transitions.append({"opp_id": opp_id, "to": to_state, "reason": reason})
        return copy.deepcopy(o)


class FakeOrders:
    """Slice C's services.spt.paper.orders.create_entry_order (DESIGN §4)."""

    def __init__(self) -> None:
        self.calls: List[Dict[str, Any]] = []
        self.fail: Optional[Exception] = None
        self.write_before_fail = False

    async def create_entry_order(self, db, **kw):
        self.calls.append(copy.deepcopy(kw))
        doc = {"_id": kw["order_id"], "order_id": kw["order_id"], "user_id": kw["user_id"], "state": C.ORD_PENDING,
               "order_type": kw["order_type"], "quantity": kw["quantity"], "filled_qty": 0,
               "idempotency_key": kw["idempotency_key"], "reservation_id": (kw["risk_decision"] or {}).get("reservation_id"),
               "created_at": NOW.isoformat()}
        if self.fail is not None:
            if self.write_before_fail:
                await db[C.ORDERS].insert_one(doc)
            raise self.fail
        await db[C.ORDERS].insert_one(doc)
        return doc


def quote_row(sym: str, *, ltp: float, ask: Optional[float] = None, bid: Optional[float] = None, age_s: float = 5.0):
    """MOCK — a quote-cache row (services/kite_live_feed/quote_cache.cache_row shape)."""
    return {"symbol": sym, "exchange": "NSE", "kind": "EQ", "ltp": ltp, "bid": bid if bid is not None else ltp - 0.05,
            "ask": ask if ask is not None else ltp + 0.05,
            "received_at": (NOW - timedelta(seconds=age_s)).astimezone(IST).isoformat(timespec="milliseconds"),
            "source": "MOCK"}


def mock_instrument(close: float = 500.0, adv: Optional[float] = 5e9, as_of: str = LAST_SESSION):
    async def instrument(symbol, today):
        from datetime import date
        d = date.fromisoformat(as_of)
        bars = [{"date": d, "open": close, "high": close * 1.01, "low": close * 0.99, "close": close, "volume": 1e6,
                 "series": "EQ"}]
        return {"bars": bars, "last_close": close, "last_close_as_of": as_of, "adv_rs": adv, "adv_sessions": 20,
                "source": "MOCK bars", "error": None}
    return instrument


class World:
    def __init__(self, monkeypatch) -> None:
        self.db = FakeDB()
        self.store = FakeOppStore()
        self.orders = FakeOrders()
        self.quotes: Dict[str, Dict[str, Any]] = {}
        self.quote_cache_down = False
        monkeypatch.setattr(desk, "utcnow", lambda: NOW)
        monkeypatch.setattr(pipeline, "opportunity_store", lambda: self.store)
        monkeypatch.setattr(pipeline, "paper_orders", lambda: self.orders)
        monkeypatch.setattr(inputs, "instrument", mock_instrument())
        monkeypatch.setattr(events, "_indexed", False)
        monkeypatch.setattr(proposals, "_indexed", False)

        async def read_quotes(symbols):
            if self.quote_cache_down:
                return None
            return {s: copy.deepcopy(self.quotes[s]) for s in symbols if s in self.quotes}
        monkeypatch.setattr(quote_cache, "read_quotes", read_quotes)

    def quote(self, sym: str, ltp: float, **kw) -> None:
        self.quotes[sym] = quote_row(sym, ltp=ltp, **kw)

    async def set_mode(self, user: str, mode: str, **extras) -> Dict[str, Any]:
        from services.spt import policy
        return await policy.update(self.db, user, actor=user, mode=mode, extras=extras or None,
                                   reason="MOCK test opt-in", now=NOW)

    def proposals(self, user: Optional[str] = None) -> List[Dict[str, Any]]:
        return [p for p in self.db.docs(C.PROPOSALS) if user is None or p["user_id"] == user]

    def events(self, etype: Optional[str] = None) -> List[Dict[str, Any]]:
        return [e for e in self.db.docs(C.EVENTS) if etype is None or e["event_type"] == etype]

    def account(self, user: str) -> Dict[str, Any]:
        return next((a for a in self.db.docs("paper_accounts") if a["user_id"] == user), {})

    def decisions(self) -> List[Dict[str, Any]]:
        return self.db.docs("risk_decisions")


@pytest.fixture
def world(monkeypatch):
    return World(monkeypatch)
