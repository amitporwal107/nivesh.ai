"""LC-13: the lifecycle backfill (scripts/backfill_trade_lifecycle.py) — the dry run is the default and writes nothing;
--apply writes only documents without a state, and a second run writes nothing.

MOCK — not real data: the documents mirror the shapes of the staging rows the gap study counted (B §4a: cash trades
closed by stop / manual, open cash trades, one strategy trade closed manual) plus AI Trader tickets of each status.
"""
from __future__ import annotations

import asyncio
import copy

from scripts import backfill_trade_lifecycle as bf
from services import trade_lifecycle as lc
from tests.test_desk_trading import FakeDb, FakeCollection

T0 = "2026-10-19T05:00:00+00:00"


def docs():
    cash = {"user_id": "u", "symbol": "HAL", "quantity": 1, "entry_price": 4989.0, "stop_price": 4822.25, "target_price": 5322.51,
            "entry_rule": "at_once", "opened_at": T0, "rules_version": "desk-paper-v2"}
    return [
        {**cash, "_id": "c1", "status": "closed", "exit_reason": "stop", "exit_price": 4790.0, "exit_session": "2026-10-22",
         "closed_at": "2026-10-22T14:00:00+00:00", "entry_status": "assumed", "sim_entry_price": 4989.0},
        {**cash, "_id": "c2", "status": "open"},
        {**cash, "_id": "c3", "status": "closed", "exit_reason": "manual", "exit_price": 5000.0, "closed_at": "2026-10-23T10:00:00+00:00"},
        {"_id": "s1", "user_id": "u", "kind": "strategy", "underlying": "NIFTY", "status": "closed", "exit_reason": "manual",
         "opened_at": T0, "closed_at": "2026-10-24T10:00:00+00:00", "legs": [], "signal": {"signal_at": "2026-10-19"}},
        {**cash, "_id": "c4", "status": "open", "state": "POSITION_OPEN", "transitions": []},          # already has a state
    ]


def tickets():
    base = {"user_id": "u", "created_at": T0, "signal_date": "2026-10-19", "quantity": 5, "entry_price": 100.0, "stop_price": 95.0}
    return [{**base, "_id": "k1", "status": "executed_paper", "trade_id": "x"}, {**base, "_id": "k2", "status": "rejected",
            "rejected_by": "risk_governor", "reason_codes": ["MAX_POSITION"]}, {**base, "_id": "k3", "status": "expired"}]


def world():
    db = FakeDb()
    db.cols["ai_trader_tickets"] = FakeCollection()
    db.trades.docs.extend(copy.deepcopy(docs()))
    db.cols["ai_trader_tickets"].docs.extend(copy.deepcopy(tickets()))
    return db


def test_the_dry_run_counts_and_writes_nothing():
    db = world()
    before = copy.deepcopy(db.trades.docs), copy.deepcopy(db["ai_trader_tickets"].docs)
    rep = asyncio.run(bf.run(db, apply=False))
    trades, tix = rep["collections"]
    assert rep["mode"] == "dry-run" and trades["written"] == 0 and tix["written"] == 0
    assert (trades["total"], trades["already_have_state"], trades["to_backfill"]) == (5, 1, 4)
    assert trades["by_state"] == {"CLOSED": 3, "POSITION_OPEN": 1} and trades["problems"] == []
    assert tix["by_state"] == {"POSITION_OPEN": 1, "REJECTED": 2}
    assert (copy.deepcopy(db.trades.docs), copy.deepcopy(db["ai_trader_tickets"].docs)) == before
    assert db.trades.writes == 0


def test_apply_writes_only_documents_without_a_state_and_a_second_run_writes_nothing():
    db = world()
    rep = asyncio.run(bf.run(db, apply=True))
    assert [c["written"] for c in rep["collections"]] == [4, 3]
    for d in db.trades.docs + db["ai_trader_tickets"].docs:
        if d["_id"] == "c4":
            assert d["transitions"] == []                                   # untouched
            continue
        assert lc.consistent(d) == (True, []) and all(e["derived"] for e in d["transitions"])
    again = asyncio.run(bf.run(db, apply=True))
    assert [c["written"] for c in again["collections"]] == [0, 0] and [c["to_backfill"] for c in again["collections"]] == [0, 0]
