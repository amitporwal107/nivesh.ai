"""Desk paper safety — release gates 1 and 2 (docs/NIVESH_AI_LAB_GUIDELINES_GAP_STUDY.md §9) and the futures validator.

TESTCASES: test_reports/desk_paper_safety_TESTCASES.md (K = kill switch, I = idempotency and duplicates, F = futures,
A = refusal audit). Each case that reproduces a defect found on origin/dev 5b6b3cfd says which probe it came from
(docs/ai_research/guidelines_gap_study_20261027/probe/).

Harness: the desk's own fakes (tests/test_desk_trading.py `world`, in-memory Mongo with the unique partial indexes
modelled) behind the real correlation middleware, with the F&O risk gate switchable and the exchange reference faked
(tests/test_risk_gate_desk_journal.py `gate`, `capi`, `jh`). The bodies are the shapes the UI sends: `trade_body`
(Top 10 / AI watchlist / scanner), `strategy_body` and a Strategy Builder `strategyPaperBody` long future.
The AI trader paths (K-10 to K-12) are in tests/test_risk_gate_ai_trader.py, on that suite's own harness.

MOCK — not real data: FIXA, FIXU, their prices, lots and expiries are the suites' made-up fixtures.
"""
from __future__ import annotations

import pytest

from services import desk_strategy_trades as strat
from services import desk_trading as svc
from services import paper_account as acct
from services import risk_controls as rc
from services.risk_gate import reference
from tests.test_desk_strategy_trades import EXPIRY, call, future, signal, strategy_body
from tests.test_desk_trading import (  # noqa: F401  (`world` and `api` are fixtures)
    A, B, TRADES_URL, _Cursor, api, trade_body, world,
)
from tests.test_risk_gate import run
from tests.test_risk_gate_desk_journal import (  # noqa: F401  (`gate`, `capi`, `jh` are fixtures)
    FILL, JOURNAL, U1, _listed, _trade, capi, decisions, gate, jh, untouched_account,
)

KEY = "3f9c2a7e-5b1d-4c8e-9a6f-0d2e4b7c1a90"


def ledger(world):
    return [(row["action"], row["amount_rs"]) for row in world.db.cols[acct.LEDGER].docs]


def account(world):
    (row,) = world.db.cols[acct.ACCOUNTS].docs
    return row


def code_of(r):
    detail = r.json()["detail"]
    return detail if isinstance(detail, str) else detail["code"]


def builder_long_future_body(**over):
    """The body frontend-v5 strategy/plan-data.ts `strategyPaperBody` sends for a long-futures candidate."""
    body = {
        "kind": "strategy", "underlying": "FIXU", "direction": "bullish", "family": "long_future",
        "strategy_plan_id": "saved-plan-1", "reference_price": 1215.0, "stop_underlying": 1180.0, "target_underlying": 1290.0,
        "legs": [{"kind": "future", "side": "buy", "lots": 1, "lot_size": 250, "entry_price": 1222.5, "expiry": EXPIRY,
                  "strike": None, "option_type": None, "price_source": "NSE F&O bhavcopy settle, 2026-10-09"}],
        "signal": {"signal_at": "2026-10-12T03:30:00Z", "rule_version": "strategy-rules v1.0",
                   "source_refs": [{"kind": "price", "ref": "FIXU", "as_of": "2026-10-09"}],
                   "evidence_summary": "Long futures: build-up with cash confirmation on FIXU, bullish view."},
        "max_hold_sessions": 10,
    }
    body.update(over)
    return body


# ── Gate 1: no paper trade while the kill switch is on ───────────────────────
@pytest.mark.parametrize("gate_on", [False, True])
@pytest.mark.parametrize("field", ["kill_switch", "halted"])
def test_k1_to_k3_the_desk_refuses_cash_and_structures_while_a_control_is_on(capi, gate, gate_on, field):
    gate.gate_on = gate_on
    run(rc.set_control(gate.db, "user_a", field=field, value=True, reason="stop", actor="user_a"))
    for body in (trade_body(), strategy_body()):
        r = capi.post(TRADES_URL, json=body, headers={**A, "X-Correlation-ID": "corr-ks", "Idempotency-Key": KEY})
        assert r.status_code == 409 and r.json()["detail"]["code"] == "risk_blocked", r.text
    assert gate.db.trades.docs == [] and untouched_account(gate)
    rows = decisions(gate)
    assert len(rows) == 2 and {row["outcome"] for row in rows} == {"blocked"}
    if gate_on:
        assert {row["source"] for row in rows} == {"risk_gate"}
    else:
        assert [(row["path"], row["symbol"], row["correlation_id"], row["reasons"][0]["code"]) for row in rows] == [
            ("desk_paper_trade", "FIXA", "corr-ks", "RISK_CONTROL"), ("desk_paper_trade", "FIXU", "corr-ks", "RISK_CONTROL")]


@pytest.mark.parametrize("gate_on", [False, True])
@pytest.mark.parametrize("field", ["kill_switch", "halted"])
def test_k4_to_k8_the_journal_refuses_a_create_and_an_entry_fill_and_lets_an_exit_through(jh, gate_on, field):
    db, state, client = jh
    state["gate_on"] = gate_on
    db["trade_journal"].docs.append(_trade())
    run(rc.set_control(db, "u1", field=field, value=True, reason="stop", actor="u1"))
    created = client.post(JOURNAL, json={"nse_symbol": "FIXA", "capital_alloc_rs": 50000}, headers=U1)
    # The study A probe: a Rs 1 crore ENTRY fill answered 200 with the kill switch on and the flag off.
    fill = client.post(f"{JOURNAL}/t1/fill", json=dict(FILL, qty=100000, price=100), headers=U1)
    assert (created.status_code, fill.status_code) == (409, 409), (created.text, fill.text)
    assert len(db["trade_journal"].docs) == 1 and db["trade_journal"].docs[0]["fills"] == []
    out = client.post(f"{JOURNAL}/t1/fill", json=dict(FILL, kind="EXIT", stage="EXIT"), headers=U1)
    assert out.status_code == 200 and len(db["trade_journal"].docs[0]["fills"]) == 1     # selling out is not blocked
    paths = sorted(row.get("path") for row in db[rc.DECISIONS].docs)
    assert paths == ["journal_create", "journal_fill"]


def test_k9_an_unreadable_control_store_refuses_the_entry_fill(jh):
    db, _, client = jh
    db["trade_journal"].docs.append(_trade())
    db.fail[(rc.CONTROLS, "find_one")] = RuntimeError("down")
    r = client.post(f"{JOURNAL}/t1/fill", json=FILL, headers=U1)
    assert r.status_code == 409 and "could not be read" in r.json()["detail"]["message"]
    assert db["trade_journal"].docs[0]["fills"] == []


# ── Gate 2: one trade and one reservation per submission ─────────────────────
@pytest.mark.parametrize("body", [trade_body(), strategy_body()], ids=["cash", "strategy"])
def test_i1_i2_the_same_key_twice_is_one_trade_and_one_reservation(capi, gate, body):
    gate.gate_on = False
    headers = {**A, "Idempotency-Key": KEY}
    first = capi.post(TRADES_URL, json=body, headers=headers)
    again = capi.post(TRADES_URL, json=body, headers=headers)
    assert first.status_code == 201, first.text
    assert again.status_code == 200 and again.json()["replayed"] is True
    assert again.json()["trade"]["id"] == first.json()["trade"]["id"]
    (doc,) = gate.db.trades.docs
    assert doc["idempotency_key"] == KEY and doc["request_fingerprint"] == svc.request_fingerprint(body)
    assert [a for a, _ in ledger(gate)] == ["reserve"]
    assert account(gate)["blocked_rs"] == doc["paper_reserved_rs"]
    assert decisions(gate) == []                                   # a replay is not a refusal


def test_i3_the_same_key_with_another_body_is_a_conflict_and_records_it(capi, gate):
    gate.gate_on = False
    headers = {**A, "Idempotency-Key": KEY, "X-Correlation-ID": "corr-i3"}
    first = capi.post(TRADES_URL, json=trade_body(), headers=headers).json()["trade"]
    r = capi.post(TRADES_URL, json=trade_body(quantity=20), headers=headers)
    assert r.status_code == 409
    assert r.json()["detail"]["code"] == "idempotency_conflict" and r.json()["detail"]["existing_trade_id"] == first["id"]
    assert len(gate.db.trades.docs) == 1 and [a for a, _ in ledger(gate)] == ["reserve"]
    (row,) = decisions(gate)
    assert (row["reasons"][0]["code"], row["correlation_id"], row["requested_qty"]) == ("idempotency_conflict", "corr-i3", 20)


@pytest.mark.parametrize("bad", ["short", "x" * 65, "has space key", "semi;colon-key"])
def test_i4_a_malformed_key_is_refused_before_anything_is_written(capi, gate, bad):
    gate.gate_on = False
    r = capi.post(TRADES_URL, json=trade_body(), headers={**A, "Idempotency-Key": bad})
    assert r.status_code == 422 and code_of(r) == "invalid_idempotency_key"
    assert gate.db.trades.docs == [] and untouched_account(gate)


def test_i5_a_race_on_one_key_answers_with_the_winners_trade_and_returns_the_losers_reservation(capi, gate, monkeypatch):
    gate.gate_on = False
    headers = {**A, "Idempotency-Key": KEY}
    first = capi.post(TRADES_URL, json=trade_body(), headers=headers).json()["trade"]
    col = gate.db.trades
    real_find_one, real_find = col.find_one, col.find
    stale = {"find_one": 1, "find": 1}

    async def find_one(query):                    # the second request read before the first one's insert landed
        if stale["find_one"] and "idempotency_key" in query:
            stale["find_one"] -= 1
            return None
        return await real_find_one(query)

    def find(query):
        if stale["find"]:
            stale["find"] -= 1
            return _Cursor([])
        return real_find(query)

    monkeypatch.setattr(col, "find_one", find_one)
    monkeypatch.setattr(col, "find", find)
    r = capi.post(TRADES_URL, json=trade_body(), headers=headers)
    assert r.status_code == 200 and r.json()["replayed"] is True and r.json()["trade"]["id"] == first["id"]
    assert len(col.docs) == 1
    assert ledger(gate) == [("reserve", 1000.0), ("reserve", 1000.0), ("release", 1000.0)]
    assert account(gate)["blocked_rs"] == 1000.0                     # net: one reservation


def test_i6_i7_a_second_open_trade_in_the_symbol_is_refused_with_the_existing_id(capi, gate):
    # The staging HAL x3 / ICICIBANK x2 case: identical POSTs with no key used to answer 201 201 201.
    gate.gate_on = False
    first = capi.post(TRADES_URL, json=trade_body(), headers=A).json()["trade"]
    for body in (trade_body(), trade_body(quantity=90, entry_price=101.0, stop_price=96.0)):
        r = capi.post(TRADES_URL, json=body, headers={**A, "X-Correlation-ID": "corr-dup"})
        assert r.status_code == 409
        detail = r.json()["detail"]
        assert (detail["code"], detail["existing_trade_id"], detail["symbol"]) == ("duplicate_open_trade", first["id"], "FIXA")
        assert "not supported yet" in detail["message"]
    assert len(gate.db.trades.docs) == 1 and [a for a, _ in ledger(gate)] == ["reserve"]
    assert [(row["reasons"][0]["code"], row["correlation_id"]) for row in decisions(gate)] == [
        ("duplicate_open_trade", "corr-dup")] * 2


def test_i8_i14_closing_frees_the_symbol_and_another_symbol_is_never_a_duplicate(capi, gate):
    gate.gate_on = False
    first = capi.post(TRADES_URL, json=trade_body(), headers=A).json()["trade"]
    other = capi.post(TRADES_URL, json=trade_body(symbol="FIXB", entry_price=500.0, stop_price=480.0, target_price=520.0),
                      headers=A)
    assert other.status_code == 201
    assert capi.post(TRADES_URL, json=trade_body(), headers=B).status_code == 201          # another user
    closed = capi.post(f"{TRADES_URL}/{first['id']}/close", json={"exit_price": 101.0}, headers=A)
    assert closed.status_code == 200, closed.text
    stored = next(d for d in gate.db.trades.docs if d["_id"] == first["id"])
    assert stored["status"] == "closed" and stored["open_key"] is None
    assert capi.post(TRADES_URL, json=trade_body(), headers=A).status_code == 201


def test_i8b_a_trade_closed_by_older_code_with_its_key_still_set_never_blocks(capi, gate):
    # Rollback-then-redeploy safety: older code closes a trade without clearing `open_key`; the index only covers
    # open trades, so the symbol is free again.
    gate.gate_on = False
    old = {**svc.new_trade("user_a", trade_body(), gate.now), "open_key": "cash:FIXA", "status": "closed"}
    gate.db.trades.docs.append(old)
    r = capi.post(TRADES_URL, json=trade_body(), headers=A)
    assert r.status_code == 201, r.text
    assert len(gate.db.trades.docs) == 2


def test_i9_a_trade_stored_before_this_change_still_counts_as_open(capi, gate):
    gate.gate_on = False
    old = svc.new_trade("user_a", trade_body(), gate.now)              # no open_key: the staging ICICIBANK shape
    gate.db.trades.docs.append(old)
    r = capi.post(TRADES_URL, json=trade_body(), headers=A)
    assert r.status_code == 409 and r.json()["detail"]["existing_trade_id"] == old["_id"]
    assert len(gate.db.trades.docs) == 1 and untouched_account(gate)


def test_i10_i11_an_identical_open_structure_is_refused_and_another_is_not(capi, gate):
    gate.gate_on = False
    first = capi.post(TRADES_URL, json=strategy_body(), headers=A).json()["trade"]
    repriced = strategy_body(legs=[call("buy", 1300, 42), call("sell", 1360, 16)])        # same legs, other premiums
    r = capi.post(TRADES_URL, json=repriced, headers=A)
    assert r.status_code == 409
    assert (r.json()["detail"]["code"], r.json()["detail"]["existing_trade_id"]) == ("duplicate_open_structure", first["id"])
    reordered = strategy_body(legs=[call("sell", 1360, 15), call("buy", 1300, 40)])        # leg order does not matter
    assert capi.post(TRADES_URL, json=reordered, headers=A).status_code == 409
    other = strategy_body(legs=[call("buy", 1310, 35), call("sell", 1370, 12)])
    assert capi.post(TRADES_URL, json=other, headers=A).status_code == 201
    assert len(gate.db.trades.docs) == 2


def test_i12_a_race_on_the_open_position_index_is_a_duplicate_and_returns_the_reservation(capi, gate, monkeypatch):
    gate.gate_on = False
    first = capi.post(TRADES_URL, json=trade_body(), headers=A).json()["trade"]
    col = gate.db.trades
    real_find = col.find
    stale = {"find": 1}

    def find(query):                               # the duplicate check read before the first insert landed
        if stale["find"]:
            stale["find"] -= 1
            return _Cursor([])
        return real_find(query)

    monkeypatch.setattr(col, "find", find)
    r = capi.post(TRADES_URL, json=trade_body(quantity=5), headers=A)
    assert r.status_code == 409 and r.json()["detail"]["existing_trade_id"] == first["id"]
    assert len(col.docs) == 1
    assert ledger(gate) == [("reserve", 1000.0), ("reserve", 500.0), ("release", 500.0)]
    assert account(gate)["blocked_rs"] == 1000.0


def test_i14_a_strategy_close_frees_the_structure():
    from tests.test_desk_trading import FakeDb
    db = FakeDb()
    doc = strat.new_strategy_trade("user_a", strategy_body())
    doc["open_key"] = strat.structure_key(doc)
    db.trades.docs.append(doc)
    sim = {"legs": [{"mark": None, "mark_date": None, "mark_basis": None}] * 2, "gross_pnl_rs": None, "mfe_rs": None,
           "mae_rs": None, "observations": 0, "held_sessions": 0, "flags": [], "checked_through": None}
    stored, mine = run(strat.close_strategy_trade(db, doc, exit_reason="manual", exit_session=None, exit_note=None, sim=sim))
    assert mine and stored["open_key"] is None and db.trades.docs[0]["open_key"] is None


# ── Futures are not defined risk (gate off unless said) ──────────────────────
def test_f1_f9_the_builders_long_future_is_recorded_and_not_called_defined_risk(capi, gate):
    gate.gate_on = False
    r = capi.post(TRADES_URL, json=builder_long_future_body(), headers=A)
    assert r.status_code == 201, r.text
    risk = r.json()["trade"]["risk"]
    assert risk == {"defined_risk": False, "futures_exposure": True, "note": strat.UNBOUNDED_NOTE}


def test_f2_a_short_future_alone_is_refused_and_recorded(capi, gate):
    # Study A probe D1: accepted and stamped defined_risk: True, reserving the notional.
    gate.gate_on = False
    body = strategy_body(family="short_future", direction="bearish", stop_underlying=1250.0, target_underlying=1150.0,
                         legs=[future("sell", 1215)])
    r = capi.post(TRADES_URL, json=body, headers={**A, "X-Correlation-ID": "corr-f2"})
    assert r.status_code == 422 and code_of(r) == "short_futures_not_supported"
    assert "no limit on its loss" in r.json()["detail"]["message"]
    assert gate.db.trades.docs == [] and untouched_account(gate)
    (row,) = decisions(gate)
    assert (row["reasons"][0]["code"], row["symbol"], row["correlation_id"]) == ("short_futures_not_supported", "FIXU", "corr-f2")


def test_f3_a_futures_leg_without_a_stop_is_refused(capi, gate):
    gate.gate_on = False
    r = capi.post(TRADES_URL, json=builder_long_future_body(stop_underlying=None), headers=A)
    assert r.status_code == 422 and code_of(r) == "futures_stop_required"
    assert gate.db.trades.docs == []


@pytest.mark.parametrize("body", [builder_long_future_body(legs=[dict(builder_long_future_body()["legs"][0], lot_size=1)]),
                                  strategy_body(legs=[call("buy", 1300, 40, lot_size=1), call("sell", 1360, 15, lot_size=1)])],
                         ids=["future", "spread"])
def test_f4_a_made_up_lot_size_is_refused_with_the_exchange_lot_even_with_the_gate_off(capi, gate, body):
    # Study A probe D2: NIFTY at lot size 1 was accepted with the gate off and reserved Rs 25,000.
    gate.gate_on = False
    r = capi.post(TRADES_URL, json=body, headers=A)
    assert r.status_code == 422 and code_of(r) == "lot_size_mismatch"
    message = r.json()["detail"]["message"]
    assert "lot size 1 is not the exchange lot 250" in message and reference.BHAVCOPY_SOURCE in message
    assert gate.db.trades.docs == [] and untouched_account(gate)


def test_f5_an_unreadable_exchange_reference_fails_closed_with_the_reason(capi, gate, monkeypatch):
    gate.gate_on = False
    gate.refs[EXPIRY] = _listed(None)
    r = capi.post(TRADES_URL, json=strategy_body(), headers=A)
    assert r.status_code == 422 and code_of(r) == "lot_size_unverified"
    assert "no single lot size" in r.json()["detail"]["message"]

    async def down(underlying, expiries, today):
        raise RuntimeError("platform down")
    monkeypatch.setattr(reference, "lookup", down)
    r = capi.post(TRADES_URL, json=strategy_body(), headers=A)
    assert r.status_code == 422 and code_of(r) == "lot_size_unverified"
    assert "no source could be read" in r.json()["detail"]["message"]
    assert gate.db.trades.docs == [] and untouched_account(gate)


def test_f6_f7_an_option_spread_stays_defined_risk_and_a_hedged_future_does_not(capi, gate):
    gate.gate_on = False
    spread = capi.post(TRADES_URL, json=strategy_body(), headers=A)
    assert spread.status_code == 201 and spread.json()["trade"]["risk"]["defined_risk"] is True
    hedged = strategy_body(family="hedged_future", direction="bearish", stop_underlying=1250.0, target_underlying=1150.0,
                           legs=[future("sell", 1215), call("buy", 1300, 20)])
    r = capi.post(TRADES_URL, json=hedged, headers=A)
    assert r.status_code == 201, r.text
    assert r.json()["trade"]["risk"] == {"defined_risk": False, "futures_exposure": True, "note": strat.FUTURES_HEDGED_NOTE}


def test_f8_with_the_gate_on_its_own_lot_check_decides_and_the_desk_does_not_look_again(capi, gate, monkeypatch):
    calls = []
    real = reference.lookup

    async def counting(underlying, expiries, today):
        calls.append(underlying)
        return await real(underlying, expiries, today)
    monkeypatch.setattr(reference, "lookup", counting)
    gate.refs[EXPIRY] = _listed(75)
    r = capi.post(TRADES_URL, json=strategy_body(), headers=A)
    assert r.status_code == 409 and [x["code"] for x in r.json()["detail"]["reasons"]] == ["lot_size_mismatch"] * 2
    assert calls == ["FIXU"]                                          # the gate's one lookup


# ── The refusal audit ────────────────────────────────────────────────────────
def _fill_the_book(world):
    for i in range(svc.MAX_OPEN_TRADES):
        world.db.trades.docs.append({**svc.new_trade("user_a", trade_body(symbol=f"FX{i}"), world.now), "_id": f"t{i}"})


REFUSALS = [
    ("kill switch", lambda w: run(rc.set_control(w.db, "user_a", field="kill_switch", value=True, reason="s", actor="user_a")),
     trade_body(), 409, "RISK_CONTROL", "FIXA"),
    ("validator", None, trade_body(stop_price=120.0), 422, "stop_not_below_entry", "FIXA"),
    ("unparseable body", None, None, 422, "invalid_body", None),
    ("duplicate", lambda w: w.db.trades.docs.append({**svc.new_trade("user_a", trade_body(), w.now), "open_key": "cash:FIXA"}),
     trade_body(), 409, "duplicate_open_trade", "FIXA"),
    ("funds", None, trade_body(quantity=200_000), 409, "insufficient_paper_funds", "FIXA"),
    ("open-trade limit", _fill_the_book, trade_body(), 409, "open_trade_limit", "FIXA"),
    ("lot size", None, strategy_body(legs=[call("buy", 1300, 40, lot_size=1), call("sell", 1360, 15, lot_size=1)]), 422,
     "lot_size_mismatch", "FIXU"),
]


@pytest.mark.parametrize("name,setup,body,status,code,symbol", REFUSALS, ids=[x[0] for x in REFUSALS])
def test_a1_every_refusal_is_recorded_with_its_code_path_and_correlation_id(capi, gate, name, setup, body, status, code, symbol):
    gate.gate_on = False
    if setup:
        setup(gate)
    before = len(gate.db.trades.docs)
    headers = {**A, "X-Correlation-ID": "corr-a1"}
    r = (capi.post(TRADES_URL, json=body, headers=headers) if body is not None else
         capi.post(TRADES_URL, content=b"not json", headers={**headers, "Content-Type": "application/json"}))
    assert r.status_code == status, r.text
    assert len(gate.db.trades.docs) == before
    (row,) = decisions(gate)
    assert (row["action"], row["outcome"], row["path"], row["correlation_id"]) == (
        "desk_paper_trade", "blocked", "desk_paper_trade", "corr-a1")
    assert row["reasons"][0]["code"] == code and row["symbol"] == symbol and row["detail"]["http_status"] == status


def test_a2_a_refusal_stands_when_its_record_cannot_be_written(capi, gate, monkeypatch):
    gate.gate_on = False
    capi.post(TRADES_URL, json=trade_body(), headers=A)

    async def down(doc):
        raise RuntimeError("write concern timeout")
    monkeypatch.setattr(gate.db.cols[rc.DECISIONS], "insert_one", down)
    r = capi.post(TRADES_URL, json=trade_body(), headers=A)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "duplicate_open_trade"
    assert len(gate.db.trades.docs) == 1


def test_the_live_execution_constant_is_untouched():
    from services import execution_modes
    assert execution_modes.LIVE_EXECUTION_AVAILABLE is False
