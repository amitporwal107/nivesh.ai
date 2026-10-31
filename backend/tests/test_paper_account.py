"""The paper account: a paper trade now costs something and can be refused.

Before this, `POST /api/desk/paper-trades` checked the symbol, the levels and a cap of 100 open
trades and nothing else: a hundred positions of any size all succeeded. Paper results therefore came
from an account that could never run out of money — and the promotion gates in
`ai_trader/strategy.py` read those results.
"""
from __future__ import annotations

import asyncio
from typing import Any, Dict, List

import pytest

from services import paper_account as acct


def mongo_expr(doc: Dict[str, Any], e: Any) -> Any:
    """Evaluate the aggregation expression in the account's conditional reserve ($gte, $subtract, "$field",
    numbers) against one document. Shared by the other desk fakes. Anything else fails loudly: a fake that
    silently matched an expression it cannot read would pass a refusal it never checked."""
    if isinstance(e, str) and e.startswith("$"):
        return doc.get(e[1:])
    if isinstance(e, (int, float)) and not isinstance(e, bool):
        return e
    assert isinstance(e, dict) and len(e) == 1, f"the fake does not know the expression {e!r}"
    [(op, args)] = e.items()
    a, b = (mongo_expr(doc, x) for x in args)
    if op == "$subtract":
        return a - b
    assert op == "$gte", f"the fake does not know {op}"
    return a >= b


def _match(d: Dict[str, Any], q: Dict[str, Any]) -> bool:
    from tests import mongo_ops                     # Mongo's filter semantics, shared by every risk fake
    return mongo_ops.match(d, q)


class _Res:
    def __init__(self, matched: int = 0) -> None:
        self.matched_count = matched


class FakeCollection:
    """Each call yields to the event loop BEFORE it touches the documents, so two coroutines run with
    asyncio.gather interleave between their awaits the way two requests do. A single update_one is atomic
    (match and apply with no await between), as one Mongo update on one document is."""

    def __init__(self) -> None:
        self.docs: List[Dict[str, Any]] = []
        self.updates: List[Dict[str, Any]] = []

    async def find_one(self, q):
        await asyncio.sleep(0)
        return next((dict(d) for d in self.docs if _match(d, q)), None)

    async def insert_one(self, doc):
        await asyncio.sleep(0)
        self.docs.append(dict(doc))

    async def update_one(self, q, update, upsert=False):
        await asyncio.sleep(0)
        self.updates.append(q)
        from tests import mongo_ops
        doc = next((d for d in self.docs if _match(d, q)), None)
        matched = doc is not None
        if doc is None:
            if not upsert:
                return _Res()
            doc = {}
            self.docs.append(doc)
        mongo_ops.apply(doc, update, inserting=not matched)
        return _Res(int(matched))


class FakeDB:
    def __init__(self) -> None:
        self.cols: Dict[str, FakeCollection] = {}

    def __getitem__(self, name):
        return self.cols.setdefault(name, FakeCollection())


@pytest.fixture
def db():
    return FakeDB()


def run(coro):
    return asyncio.get_event_loop_policy().new_event_loop().run_until_complete(coro)


# ── what a trade costs ──────────────────────────────────────────────────────

def test_a_cash_trade_reserves_quantity_times_price():
    assert acct.reservation_for({"kind": "cash", "quantity": 10, "entry_price": 100.0}, None) == 1000.0
    assert acct.reservation_for({"quantity": 10, "entry_price": 100.0}, None) == 1000.0   # kind absent


def test_a_structure_reserves_its_capital_at_risk():
    """Not exchange margin: this system has no SPAN or exposure feed, so the figure is the upper
    bound on what the structure can lose and its basis travels with it."""
    assert acct.reservation_for({"kind": "strategy"}, 5000.0) == 5000.0
    assert "not exchange margin" in acct.BLOCKED_BASIS


def test_a_trade_that_cannot_be_priced_reserves_nothing_and_is_refused(db):
    """A position whose cost is unknown is exactly the one that should not be opened."""
    assert acct.reservation_for({"kind": "cash", "quantity": None, "entry_price": 100.0}, None) is None
    assert acct.reservation_for({"kind": "strategy"}, None) is None
    with pytest.raises(acct.InsufficientFunds):
        run(acct.reserve(db, "u1", None, trade_id="t1"))


# ── the account moves ───────────────────────────────────────────────────────

def test_a_new_account_starts_with_the_default_and_nothing_blocked(db):
    a = run(acct.read(db, "u1"))
    assert a["cash_rs"] == acct.DEFAULT_CAPITAL
    assert a["blocked_rs"] == 0.0
    assert a["available_rs"] == acct.DEFAULT_CAPITAL
    assert a["stored"] is False


def test_opening_blocks_capital_and_reduces_what_is_available(db):
    run(acct.reserve(db, "u1", 250_000.0, trade_id="t1", symbol="TCS"))
    a = run(acct.read(db, "u1"))
    assert a["blocked_rs"] == 250_000.0
    assert a["available_rs"] == acct.DEFAULT_CAPITAL - 250_000.0
    assert a["cash_rs"] == acct.DEFAULT_CAPITAL, "blocking is not spending"


def test_closing_returns_the_block_and_applies_the_net_pnl(db):
    run(acct.reserve(db, "u1", 250_000.0, trade_id="t1"))
    run(acct.release(db, "u1", 250_000.0, net_pnl=-5_000.0, trade_id="t1"))
    a = run(acct.read(db, "u1"))
    assert a["blocked_rs"] == 0.0
    assert a["cash_rs"] == acct.DEFAULT_CAPITAL - 5_000.0
    assert a["available_rs"] == a["cash_rs"]


def test_a_winning_trade_increases_cash(db):
    run(acct.reserve(db, "u1", 100_000.0, trade_id="t1"))
    run(acct.release(db, "u1", 100_000.0, net_pnl=7_500.0, trade_id="t1"))
    assert run(acct.read(db, "u1"))["cash_rs"] == acct.DEFAULT_CAPITAL + 7_500.0


# ── the refusal ─────────────────────────────────────────────────────────────

def test_a_trade_larger_than_the_account_is_refused_with_the_numbers(db):
    with pytest.raises(acct.InsufficientFunds) as e:
        run(acct.reserve(db, "u1", acct.DEFAULT_CAPITAL + 1, trade_id="t1"))
    d = e.value.detail()
    assert d["code"] == "insufficient_paper_funds"
    assert d["needed_rs"] == acct.DEFAULT_CAPITAL + 1
    assert d["available_rs"] == acct.DEFAULT_CAPITAL
    assert "Nothing was opened" in d["note"]


def test_blocked_capital_cannot_be_used_twice(db):
    run(acct.reserve(db, "u1", 600_000.0, trade_id="t1"))
    with pytest.raises(acct.InsufficientFunds):
        run(acct.reserve(db, "u1", 600_000.0, trade_id="t2"))
    assert run(acct.read(db, "u1"))["blocked_rs"] == 600_000.0, "the refused trade must block nothing"


def test_the_refusal_carries_the_numbers_as_they_stand(db):
    """After the conditional update misses, the account is re-read: the refusal reports what is really
    there, not what an earlier read saw."""
    run(acct.reserve(db, "u1", 600_000.0, trade_id="t1"))
    with pytest.raises(acct.InsufficientFunds) as e:
        run(acct.reserve(db, "u1", 600_000.0, trade_id="t2"))
    d = e.value.detail()
    assert (d["needed_rs"], d["available_rs"], d["cash_rs"], d["blocked_rs"]) == (600_000.0, 400_000.0,
                                                                                 acct.DEFAULT_CAPITAL, 600_000.0)


def test_two_concurrent_reserves_cannot_overdraw(db):
    """Two ₹6 lakh trades against a ₹10 lakh account, at the same moment: only one fits. The fake yields
    before every call, so both requests read before either writes. The old read-then-increment reserve
    let BOTH pass the check and blocked ₹12 lakh against ₹10 lakh of cash; the conditional update lets
    exactly one through. (The account row exists first: the race in ensure() on a user's very first
    trade is a separate matter.)"""
    run(acct.ensure(db, "u1"))

    async def both():
        return await asyncio.gather(acct.reserve(db, "u1", 600_000.0, trade_id="t1"),
                                    acct.reserve(db, "u1", 600_000.0, trade_id="t2"),
                                    return_exceptions=True)

    results = run(both())
    assert sorted(type(r).__name__ for r in results) == ["InsufficientFunds", "float"], results
    a = run(acct.read(db, "u1"))
    assert a["blocked_rs"] == 600_000.0 and a["available_rs"] == 400_000.0, "the account was overdrawn"
    assert [r["action"] for r in db[acct.LEDGER].docs] == ["reserve"], "the refused trade must not be recorded"
    [refused] = [r for r in results if isinstance(r, acct.InsufficientFunds)]
    assert (refused.needed, refused.available) == (600_000.0, 400_000.0)


def test_the_check_and_the_block_are_one_write(db):
    """The guard lives in the update's filter, so Mongo checks and increments in one operation."""
    run(acct.reserve(db, "u1", 1_000.0, trade_id="t1"))
    [gate] = [q for q in db[acct.ACCOUNTS].updates if "$expr" in q]
    assert gate == {"user_id": "u1", "$expr": {"$gte": [{"$subtract": ["$cash_rs", "$blocked_rs"]}, 1_000.0]}}


def test_exactly_the_available_amount_is_allowed(db):
    run(acct.reserve(db, "u1", acct.DEFAULT_CAPITAL, trade_id="t1"))
    assert run(acct.read(db, "u1"))["available_rs"] == 0.0


def test_one_user_s_account_is_not_another_s(db):
    run(acct.reserve(db, "u1", 900_000.0, trade_id="t1"))
    assert run(acct.read(db, "u2"))["available_rs"] == acct.DEFAULT_CAPITAL


# ── reserve what you release ────────────────────────────────────────────────

def test_a_trade_that_reserved_nothing_releases_nothing(db):
    """Trades opened before the account existed carry no reservation; the account must not be
    credited for capital it never took."""
    run(acct.release(db, "u1", None, net_pnl=None, trade_id="old"))
    a = run(acct.read(db, "u1"))
    assert a["cash_rs"] == acct.DEFAULT_CAPITAL and a["blocked_rs"] == 0.0


def test_an_old_trade_still_applies_its_pnl(db):
    run(acct.release(db, "u1", None, net_pnl=-1_000.0, trade_id="old"))
    assert run(acct.read(db, "u1"))["cash_rs"] == acct.DEFAULT_CAPITAL - 1_000.0


def test_every_movement_is_recorded(db):
    run(acct.reserve(db, "u1", 1_000.0, trade_id="t1", symbol="TCS"))
    run(acct.release(db, "u1", 1_000.0, net_pnl=50.0, trade_id="t1", symbol="TCS"))
    rows = db[acct.LEDGER].docs
    assert [r["action"] for r in rows] == ["reserve", "release"]
    assert rows[1]["net_pnl_rs"] == 50.0


# ── a structured refusal must reach the client as data ──────────────────────

def test_a_dict_detail_survives_the_error_envelope():
    """`core/error_handlers` used to flatten every non-string HTTPException detail with str(), which
    emits PYTHON repr — single quotes and True/False — so a client could not parse the fields back
    out. The refusal carries needed/available/cash/blocked precisely so a screen can say "you need X
    and have Y"; a repr string makes that unreadable."""
    import json as _json

    from fastapi import FastAPI, HTTPException
    from fastapi.testclient import TestClient

    from core.error_handlers import register_error_handlers

    app = FastAPI()
    register_error_handlers(app)

    @app.get("/boom")
    def boom():
        raise HTTPException(status_code=409, detail=acct.InsufficientFunds(
            needed=50_000_000.0, available=999_959.0, cash=999_959.0, blocked=0.0).detail())

    @app.get("/plain")
    def plain():
        raise HTTPException(status_code=409, detail="open_trade_limit")

    client = TestClient(app, raise_server_exceptions=False)

    body = client.get("/boom").json()
    assert body["status"] == 409
    # The structured detail is DATA, not a stringified dict.
    assert body["details"] and isinstance(body["details"][0], dict)
    d = body["details"][0]
    assert d["code"] == "insufficient_paper_funds"
    assert d["needed_rs"] == 50_000_000.0 and d["available_rs"] == 999_959.0
    # and the whole envelope round-trips as JSON, which a repr string would not
    assert _json.loads(_json.dumps(body))["details"][0]["blocked_rs"] == 0.0
    # `message` stays a string, because every existing caller reads it that way
    assert isinstance(body["message"], str)

    # A plain string detail is unchanged.
    plain_body = client.get("/plain").json()
    assert plain_body["message"] == "open_trade_limit"
    assert plain_body["details"] == []


# ── both creation paths are funded ──────────────────────────────────────────

def test_the_ai_trader_path_charges_the_same_account():
    """routes/ai_trader._open_paper_trade inserts into desk.TRADES DIRECTLY rather than through
    POST /api/desk/paper-trades, so it must charge the account itself. Without this the AI trader
    could open positions the account never funded while the desk route was constrained — the same
    "governed on one path only" shape docs/RISK_CONTROL_INVENTORY.md describes."""
    import inspect

    from routes import ai_trader

    # Phase 1: the funds AND the risk budget are reserved by the universal risk service before the trade is written
    # (services/risk_gate/service.enter -> paper_account.reserve_entry); the trade records what was reserved.
    src = inspect.getsource(ai_trader._open_paper_trade)
    assert 'trade["paper_reserved_rs"]' in src and "risk_service.stamp" in src
    signals = inspect.getsource(ai_trader.strategy_signals) + inspect.getsource(ai_trader.confirm_ticket)
    assert signals.count("risk_service.enter(") == 2 and "reserve=True" in signals and 'reserve=body.mode == "paper"' in signals
    # the reservation is stored on the trade, so the close returns exactly what was taken
    assert "paper_reserved_rs" in src


def test_a_position_reports_what_it_blocks():
    """The figure is stored on the trade; a screen cannot show "this position blocks X" unless the
    public shape carries it. Asserted on the real output rather than on the source, so moving the
    field between helpers cannot quietly pass."""
    from services import desk_trading as svc

    doc = {"_id": "t1", "user_id": "u1", "status": "open", "kind": "cash", "symbol": "TCS",
           "quantity": 10, "entry_price": 100.0, "stop_price": 95.0, "target_price": 110.0,
           "opened_at": "2026-10-21T00:00:00+00:00", "paper_reserved_rs": 1000.0,
           "entry_rule": "at_once"}
    out = svc.public_trade(doc)
    assert out["paper_reserved_rs"] == 1000.0

    # A trade opened before the account existed reports None, not zero: the account never took it.
    legacy = dict(doc); legacy.pop("paper_reserved_rs")
    assert svc.public_trade(legacy)["paper_reserved_rs"] is None
