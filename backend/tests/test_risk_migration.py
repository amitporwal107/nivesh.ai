"""scripts/migrate_risk_reservations.py (TESTCASES G-1, G-3): the dry run reads only; apply and rollback are exact.

MOCK — not real data: the users, symbols, prices and amounts are made up (shaped like staging's ICICIBANK / HAL rows).
"""
from __future__ import annotations

import asyncio
import copy
import json

from scripts import migrate_risk_reservations as mig
from services import desk_strategy_trades as strat
from services import desk_trading as desk
from services import paper_account as acct
from tests import mongo_ops


class _Cur:
    def __init__(self, docs):
        self.docs = docs

    def __aiter__(self):
        self._it = iter(self.docs)
        return self

    async def __anext__(self):
        try:
            return copy.deepcopy(next(self._it))
        except StopIteration:
            raise StopAsyncIteration


class Coll:
    def __init__(self, writable):
        self.docs, self.writable, self.writes = [], writable, 0

    def find(self, q, projection=None):
        return _Cur([d for d in self.docs if mongo_ops.match(d, q)])

    async def find_one(self, q, projection=None):
        return next((copy.deepcopy(d) for d in self.docs if mongo_ops.match(d, q)), None)

    def _w(self):
        if not self.writable:
            raise AssertionError("the dry run wrote to the database")
        self.writes += 1

    async def update_one(self, q, u, upsert=False):
        self._w()
        for d in self.docs:
            if mongo_ops.match(d, q):
                mongo_ops.apply(d, u)
                return type("R", (), {"matched_count": 1})()
        if upsert:
            doc = {k: v for k, v in q.items() if not k.startswith("$") and not isinstance(v, dict)}
            mongo_ops.apply(doc, u, inserting=True)
            self.docs.append(doc)
        return type("R", (), {"matched_count": 0})()

    async def insert_one(self, doc):
        self._w()
        self.docs.append(copy.deepcopy(doc))

    async def delete_one(self, q):
        self._w()


class Db:
    def __init__(self, writable=False):
        self.cols, self.writable = {}, writable

    def __getitem__(self, name):
        return self.cols.setdefault(name, Coll(self.writable))


def seed(db):
    db[acct.ACCOUNTS].docs.append({"user_id": "u1", "cash_rs": 984547.28, "blocked_rs": 124617.8,
                                   "starting_capital_rs": 1_000_000.0})
    a = desk.new_trade("u1", {"symbol": "ICICIBANK", "quantity": 89, "entry_price": 1400.2, "stop_price": 1363.26,
                              "target_price": 1480.0})
    b = {**desk.new_trade("u1", {"symbol": "ICICIBANK", "quantity": 89, "entry_price": 1400.2, "stop_price": 1363.26,
                                 "target_price": 1480.0}), "paper_reserved_rs": 124617.8}
    db[desk.TRADES].docs.extend([a, b])
    db["trade_journal"].docs.append({"_id": "j1", "user_id": "u1", "nse_symbol": "HAL", "status": "OPEN",
                                     "capital_alloc_rs": 50000.0, "stop_loss": 0.0,
                                     "fills": [{"kind": "ENTRY", "qty": 10, "price": 4900.0}]})
    return a, b


def run(c):
    return asyncio.new_event_loop().run_until_complete(c)


def test_g1_the_dry_run_reads_only_and_lists_every_unreserved_position():
    db = Db(writable=False)
    a, b = seed(db)
    p = run(mig.plan(db, sectors={"ICICIBANK": "Financial Services"}))
    assert p["counts"] == {"accounts": 1, "open_desk_trades": 2, "open_journal_trades": 1, "already_reserved": 0,
                           "to_reserve": 3, "risk_unknown": 0, "accounts_affected": 1}
    rows = {r["trade_id"]: r for r in p["rows"]}
    assert rows[a["_id"]]["sector"] == "Financial Services" and rows["j1"]["sector"] is None
    assert rows["j1"]["risk_rs"] == rows["j1"]["exposure_rs"] == 49000.0         # no stop: the whole amount is at risk
    (acc,) = p["accounts"]
    assert acc["unfunded_trades"] == [a["_id"]]                                   # the Phase 0 reconciliation's case
    assert all(c.writes == 0 for c in db.cols.values())


def test_g3_apply_then_rollback_is_exact_and_rerunning_apply_changes_nothing(tmp_path):
    db = Db(writable=True)
    seed(db)
    before = copy.deepcopy(db[acct.ACCOUNTS].docs[0])
    p = run(mig.plan(db, sectors={"ICICIBANK": "Financial Services", "HAL": "Capital Goods"}))
    snap = tmp_path / "snap.json"
    out = run(mig.apply(db, p, "run-1", str(snap)))
    assert out["reserved"] == 3 and all(v == [] for v in out["validation"].values())
    acc = db[acct.ACCOUNTS].docs[0]
    assert acc["open_positions"] == 3 and acc["held_symbols"]["ICICIBANK"] == 2 and acc["blocked_rs"] == before["blocked_rs"]
    assert json.loads(snap.read_text())["accounts"][0]["blocked_rs"] == before["blocked_rs"]
    again = run(mig.apply(db, run(mig.plan(db)), "run-2", str(tmp_path / "snap2.json")))
    assert again["reserved"] == 0                                                  # every position is already reserved
    undone = run(mig.rollback(db, "run-1"))
    assert undone["undone"] == 3
    acc = db[acct.ACCOUNTS].docs[0]
    assert acc["reservations"] == [] and acc["open_risk_rs"] == 0 and acc["open_positions"] == 0
    assert acc["blocked_rs"] == before["blocked_rs"] and acc["cash_rs"] == before["cash_rs"]
    assert all("risk_reservation_id" not in d for d in db[desk.TRADES].docs)
    assert strat.KIND == "strategy"
