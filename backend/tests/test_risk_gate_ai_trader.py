"""The F&O risk gate wired into the AI trader's signals and confirm: TESTCASES W-1, W-9 and W-10.

Reuses tests/test_ai_trader_execution.py's `world` and `api` harness (its in-memory collections, fixed screen,
market and clock); `risk_gate.enabled_for` is replaced to switch the flag per test. The governor still runs for
real: the gate is in addition to it.

MOCK — not real data: MOCKA, its close of 200.00 and the strategy are the execution suite's made-up fixtures.
Worked: capital Rs 10,00,000, a 10% stop on a 200.00 close sizes 500 shares (see that suite), so the gate sees
500 shares and Rs 1,00,000 of capital deployed, under the Rs 2,00,000 cap.
"""
from __future__ import annotations

import pytest

from services import risk_controls as rc
from services import risk_gate
from services.risk_gate import policy
from tests.test_ai_trader_execution import (  # noqa: F401  (`world` and `api` are fixtures)
    A, BASE, NOW, api, assisted_ticket, signals, strategy_record, world,
)


@pytest.fixture
def gate(world, monkeypatch):
    world.gate_on = True
    monkeypatch.setattr(rc, "_indexes_ready", False)
    monkeypatch.setattr(rc, "utcnow", lambda: NOW)

    async def enabled_for(_db, user):
        return world.gate_on
    monkeypatch.setattr(risk_gate, "enabled_for", enabled_for)
    return world


def gate_rows(world, path=None):
    return [r for r in world.db[rc.DECISIONS].docs if r.get("source") == "risk_gate"
            and (path is None or r["path"] == path)]


def test_flag_off_signals_and_confirm_are_as_before(api, gate):
    gate.gate_on = False
    gate.db.strategies.docs.append(strategy_record())
    signals(api)
    assert "risk_decision_id" not in gate.db.tickets.docs[0] and "risk_decision_id" not in gate.db.trades.docs[0]
    assert gate_rows(gate) == []


def test_flag_on_a_paper_signal_is_judged_and_the_ticket_and_trade_are_stamped(api, gate):
    gate.db.strategies.docs.append(strategy_record())
    r = api.post(f"{BASE}/strategies/strat-1/signals", json={"as_of": "2026-10-20", "mode": "paper"},
                 headers={**A, "X-Correlation-ID": "corr-sig"})
    assert r.status_code == 200, r.text
    (row,) = gate_rows(gate, "ai_trader_signal")
    assert (row["mode"], row["outcome"], row["requested_qty"], row["detail"]["capital_at_risk_rs"]) == (
        "paper", "allowed", 500, 100000.0)
    (ticket,) = gate.db.tickets.docs
    (trade,) = gate.db.trades.docs
    assert ticket["risk_decision_id"] == trade["risk_decision_id"] == row["_id"]
    assert ticket["correlation_id"] == trade["correlation_id"] == row["correlation_id"]
    # The governor still ran and kept its own record.
    assert [x["action"] for x in gate.db[rc.DECISIONS].docs if x.get("source") != "risk_gate"] == ["ai_trader_ticket"]


def test_flag_on_a_blocked_signal_run_writes_no_ticket_and_no_trade(api, gate):
    gate.db.strategies.docs.append(strategy_record())
    gate.db[rc.CONTROLS].docs.append({"user_id": "user_a", "kill_switch": True, "halted": False, "reason": "stop"})
    r = api.post(f"{BASE}/strategies/strat-1/signals", json={"as_of": "2026-10-20", "mode": "paper"}, headers=A)
    assert r.status_code == 409
    detail = r.json()["detail"]
    assert detail["code"] == "risk_blocked" and [x["code"] for x in detail["reasons"]] == ["kill_switch_on"]
    assert gate.db.tickets.docs == [] and gate.db.trades.docs == []
    assert [x["outcome"] for x in gate_rows(gate)] == ["blocked"]
    assert [x for x in gate.db[rc.DECISIONS].docs if x.get("source") != "risk_gate"] == []      # governor never ran


def test_flag_on_a_confirm_is_judged_and_the_trade_is_stamped(api, gate):
    gate.gate_on = False
    ticket = assisted_ticket(api, gate)
    gate.gate_on = True
    r = api.post(f"{BASE}/tickets/{ticket['id']}/confirm", headers={**A, "X-Correlation-ID": "corr-conf"})
    assert r.status_code == 200, r.text
    (row,) = gate_rows(gate, "ai_trader_confirm")
    assert (row["mode"], row["outcome"], row["requested_qty"]) == ("assisted", "allowed", 500)
    (trade,) = gate.db.trades.docs
    stored = gate.db.tickets.docs[0]
    assert trade["risk_decision_id"] == stored["risk_decision_id"] == row["_id"]


def test_flag_on_a_blocked_confirm_leaves_the_ticket_waiting_and_records_no_trade(api, gate, monkeypatch):
    gate.gate_on = False
    ticket = assisted_ticket(api, gate)
    gate.gate_on = True
    # A stricter cap than the Rs 1,00,000 the confirm would deploy; the governor itself still approves.
    monkeypatch.setattr(policy, "LIMITS", policy.Limits(max_capital_at_risk_rs=50_000.0))
    r = api.post(f"{BASE}/tickets/{ticket['id']}/confirm", headers=A)
    assert r.status_code == 409
    assert [x["code"] for x in r.json()["detail"]["reasons"]] == ["capital_at_risk_exceeded"]
    assert gate.db.trades.docs == [] and gate.db.tickets.docs[0]["status"] == "awaiting_confirmation"
    assert "risk_decision_id" not in gate.db.tickets.docs[0]
