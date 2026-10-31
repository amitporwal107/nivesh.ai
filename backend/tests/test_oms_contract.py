"""The order lifecycle contract (test_reports/oms_contract_TESTCASES.md).

No broker is involved: these tests pin the state machine and the idempotent store that a paper path and a
later Kite Connect adapter will both use.
"""
from __future__ import annotations

import asyncio
from typing import Any, Dict, List

import pytest
from pymongo.errors import DuplicateKeyError

from services.oms import orders, states


class FakeCollection:
    """In-memory stand-in that enforces the unique (user_id, client_order_id) index once declared."""

    def __init__(self) -> None:
        self.docs: List[Dict[str, Any]] = []
        self.indexes: List[Dict[str, Any]] = []
        self.unique: List[tuple] = []

    async def create_index(self, keys, unique=False, name=None):
        fields = tuple(k for k, _ in keys) if isinstance(keys, list) else (keys,)
        self.indexes.append({"fields": fields, "unique": unique, "name": name})
        if unique:
            self.unique.append(fields)

    async def insert_one(self, doc):
        for fields in self.unique:
            if any(all(d.get(f) == doc.get(f) for f in fields) for d in self.docs):
                raise DuplicateKeyError("E11000 duplicate key")
        self.docs.append(dict(doc))

    async def find_one(self, q):
        return next((dict(d) for d in self.docs if all(d.get(k) == v for k, v in q.items())), None)

    async def update_one(self, q, update):
        for d in self.docs:
            if all(d.get(k) == v for k, v in q.items()):
                d.update(update.get("$set") or {})
                for k, v in (update.get("$push") or {}).items():
                    d.setdefault(k, []).append(v)
                return type("R", (), {"matched_count": 1})()
        return type("R", (), {"matched_count": 0})()


class FakeDB:
    def __init__(self) -> None:
        self.cols: Dict[str, FakeCollection] = {}

    def __getitem__(self, name):
        return self.cols.setdefault(name, FakeCollection())


@pytest.fixture
def db():
    d = FakeDB()
    run(orders.ensure_indexes(d))
    return d


def run(coro):
    return asyncio.get_event_loop_policy().new_event_loop().run_until_complete(coro)


LEGS = [{"kind": "option", "side": "buy", "underlying": "NIFTY", "expiry": "2026-10-27", "strike": 24500,
         "option_type": "CE", "lots": 1, "lot_size": 75, "limit_price": 120.5}]


def new(db, user="u1", cid="c-1", mode="paper", legs=None):
    return run(orders.create_order(db, user_id=user, client_order_id=cid, mode=mode,
                                   legs=LEGS if legs is None else legs, correlation_id="corr-1",
                                   risk_decision_id="dec-1"))


# ── the state machine ───────────────────────────────────────────────────────

def test_every_prd_state_exists():                                                   # OMS-1
    assert len(states.STATES) == 13
    assert set(states.STATES) == set(states.TRANSITIONS)


def test_the_happy_path_is_allowed_step_by_step():                                   # OMS-2
    path = [states.CREATED, states.VALIDATED, states.AUTHORIZED, states.SUBMITTED, states.ACKNOWLEDGED,
            states.PARTIALLY_FILLED, states.FILLED]
    for a, b in zip(path, path[1:]):
        states.check_transition(a, b)


@pytest.mark.parametrize("terminal", sorted(states.TERMINAL))
def test_terminal_states_have_no_way_out(terminal):                                 # OMS-3
    for target in states.STATES:
        assert not states.can_transition(terminal, target)


def test_unknown_goes_only_to_reconciliation_never_back_to_submitted():              # OMS-4
    assert states.TRANSITIONS[states.UNKNOWN] == frozenset({states.RECONCILIATION_REQUIRED})
    with pytest.raises(states.IllegalTransition):
        states.check_transition(states.UNKNOWN, states.SUBMITTED)
    assert states.SUBMITTED not in states.TRANSITIONS[states.RECONCILIATION_REQUIRED]


def test_a_cancel_can_still_lose_the_race_to_a_fill():                               # OMS-5
    states.check_transition(states.CANCEL_PENDING, states.PARTIALLY_FILLED)
    states.check_transition(states.CANCEL_PENDING, states.FILLED)


def test_skipping_states_is_refused():                                               # OMS-6
    with pytest.raises(states.IllegalTransition) as e:
        states.check_transition(states.CREATED, states.SUBMITTED)
    assert (e.value.current, e.value.target) == (states.CREATED, states.SUBMITTED)


def test_only_a_partial_fill_may_repeat():                                           # OMS-7
    states.check_transition(states.PARTIALLY_FILLED, states.PARTIALLY_FILLED)
    for s in states.STATES:
        if s != states.PARTIALLY_FILLED:
            assert not states.can_transition(s, s)


def test_unknown_state_names_are_refused():                                          # OMS-8
    with pytest.raises(states.IllegalTransition):
        states.check_transition("PENDING", states.VALIDATED)
    with pytest.raises(states.IllegalTransition):
        states.check_transition(states.CREATED, "DONE")


# ── the store ───────────────────────────────────────────────────────────────

def test_create_stores_the_contract_fields(db):                                      # OMS-9
    out = new(db)
    o = out["order"]
    assert out["created"] is True
    assert o["state"] == states.CREATED and o["history"][0]["state"] == states.CREATED
    assert (o["correlation_id"], o["risk_decision_id"], o["mode"]) == ("corr-1", "dec-1", "paper")
    assert o["broker_order_id"] is None
    assert o["contract_version"] == orders.CONTRACT_VERSION
    assert len(db[orders.ORDERS].docs) == 1


def test_a_replay_returns_the_first_order_and_stores_nothing_new(db):                # OMS-10
    first = new(db)["order"]
    again = new(db)
    assert again["created"] is False and again["order"]["_id"] == first["_id"]
    assert len(db[orders.ORDERS].docs) == 1


def test_the_same_key_with_a_different_request_is_a_conflict(db):                    # OMS-11
    new(db)
    with pytest.raises(orders.IdempotencyConflict):
        new(db, legs=[{**LEGS[0], "lots": 2}])
    assert len(db[orders.ORDERS].docs) == 1


def test_the_key_is_per_user(db):                                                    # OMS-12
    a, b = new(db, user="u1")["order"], new(db, user="u2")["order"]
    assert a["_id"] != b["_id"] and len(db[orders.ORDERS].docs) == 2


@pytest.mark.parametrize("cid,legs,code", [
    (None, LEGS, "client_order_id_required"),
    ("   ", LEGS, "client_order_id_required"),
    ("x" * 65, LEGS, "client_order_id_too_long"),
    ("c-1", [], "legs_required"),
])
def test_bad_requests_are_refused(db, cid, legs, code):                             # OMS-13
    with pytest.raises(orders.InvalidOrder) as e:
        new(db, cid=cid, legs=legs)
    assert e.value.code == code
    assert db[orders.ORDERS].docs == []


def test_live_orders_cannot_be_created(db):                                          # OMS-14
    with pytest.raises(orders.InvalidOrder) as e:
        new(db, mode="live")
    assert e.value.code == "live_not_available"
    assert db[orders.ORDERS].docs == []


@pytest.mark.parametrize("mode", ["assisted", "real", ""])
def test_modes_outside_the_creatable_set_are_refused(db, mode):                     # OMS-15
    with pytest.raises(orders.InvalidOrder) as e:
        new(db, mode=mode)
    assert e.value.code == "invalid_mode"


def test_transition_moves_state_and_appends_history(db):                            # OMS-16
    o = new(db)["order"]
    run(orders.transition(db, user_id="u1", order_id=o["_id"], target=states.VALIDATED, note="schema ok"))
    run(orders.transition(db, user_id="u1", order_id=o["_id"], target=states.AUTHORIZED))
    run(orders.transition(db, user_id="u1", order_id=o["_id"], target=states.SUBMITTED, broker_order_id="B1"))
    stored = db[orders.ORDERS].docs[0]
    assert stored["state"] == states.SUBMITTED and stored["broker_order_id"] == "B1"
    assert [h["state"] for h in stored["history"]] == [states.CREATED, states.VALIDATED,
                                                       states.AUTHORIZED, states.SUBMITTED]
    assert stored["history"][1]["note"] == "schema ok"


def test_a_concurrent_change_is_detected_and_nothing_is_written(db, monkeypatch):    # OMS-17
    o = new(db)["order"]
    col = db[orders.ORDERS]
    real_find = col.find_one

    async def stale_find(q):            # the read sees CREATED, but another writer has moved it on
        doc = await real_find(q)
        col.docs[0]["state"] = states.REJECTED
        return doc

    monkeypatch.setattr(col, "find_one", stale_find)
    with pytest.raises(orders.StaleOrderState):
        run(orders.transition(db, user_id="u1", order_id=o["_id"], target=states.VALIDATED))
    assert col.docs[0]["state"] == states.REJECTED and len(col.docs[0]["history"]) == 1


def test_an_illegal_transition_writes_nothing(db):                                  # OMS-18
    o = new(db)["order"]
    with pytest.raises(states.IllegalTransition):
        run(orders.transition(db, user_id="u1", order_id=o["_id"], target=states.FILLED))
    assert db[orders.ORDERS].docs[0]["state"] == states.CREATED


def test_another_users_order_is_not_found(db):                                      # OMS-19
    o = new(db, user="u1")["order"]
    with pytest.raises(orders.OrderNotFound):
        run(orders.transition(db, user_id="u2", order_id=o["_id"], target=states.VALIDATED))


def test_the_idempotency_index_is_unique(db):                                       # OMS-20
    idx = {i["fields"]: i for i in db[orders.ORDERS].indexes}
    assert idx[("user_id", "client_order_id")]["unique"] is True
