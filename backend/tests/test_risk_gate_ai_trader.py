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
from services import paper_account as acct
from tests.test_ai_trader_execution import (  # noqa: F401  (`world` and `api` are fixtures)
    A, APPROVED, BASE, NOW, api, assisted_ticket, signals, strategy_record, world,
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
    """The universal risk service's decisions (Phase 1: every AI-trader decision is one, flag on or off)."""
    return [r for r in world.db[rc.DECISIONS].docs if r.get("source") == "risk_service"
            and (path is None or r["path"] == path)]


def reservations(world):
    docs = world.db[acct.ACCOUNTS].docs
    return docs[0].get("reservations", []) if docs else []


@pytest.mark.parametrize("gate_on", [False, True])
def test_a_paper_signal_is_judged_reserved_and_stamped_whatever_the_flag(api, gate, gate_on):
    """Phase 1 (criteria 1.1): the flag no longer decides whether the AI trader is judged."""
    gate.gate_on = gate_on
    gate.db.strategies.docs.append(strategy_record())
    r = api.post(f"{BASE}/strategies/strat-1/signals", json={"as_of": "2026-10-20", "mode": "paper"},
                 headers={**A, "X-Correlation-ID": "corr-sig"})
    assert r.status_code == 200, r.text
    (row,) = gate_rows(gate, "ai_trader_signal")
    # The intent is sized on the gross stop distance (500); the service reduces it for costs and the gap stress.
    assert (row["mode"], row["outcome"], row["requested_qty"]) == ("paper", "reduced", 500) and row["correlation_id"]
    assert row["approved_qty"] == APPROVED and row["budget"]["funding_rs"] == APPROVED * 200.0
    assert row["policy_version"] == "universal-risk-v2"
    assert {c["check"]: c["status"] for c in row["checks"]}["governor"] == "pass"        # the governor is one check
    (ticket,) = gate.db.tickets.docs
    (trade,) = gate.db.trades.docs
    assert ticket["risk_decision_id"] == trade["risk_decision_id"] == row["_id"] == trade["risk_reservation_id"]
    assert [e["trade_id"] for e in reservations(gate)] == [trade["_id"]]
    assert trade["paper_reserved_rs"] == APPROVED * 200.0


def test_the_kill_switch_refuses_every_paper_ticket_and_opens_nothing(api, gate):
    gate.db.strategies.docs.append(strategy_record())
    gate.db[rc.CONTROLS].docs.append({"user_id": "user_a", "kill_switch": True, "halted": False, "reason": "stop"})
    body = signals(api)
    (ticket,) = gate.db.tickets.docs
    assert ticket["status"] == "rejected" and ticket["governor_cleared"] is False
    assert "kill_switch_on" in ticket["reason_codes"] and body["tickets"][0]["trade_id"] is None
    assert gate.db.trades.docs == [] and reservations(gate) == []
    assert [x["outcome"] for x in gate_rows(gate)] == ["blocked"]


@pytest.mark.parametrize("gate_on", [False, True])
def test_a_confirm_is_judged_reserved_and_stamped_whatever_the_flag(api, gate, gate_on):
    gate.gate_on = gate_on
    ticket = assisted_ticket(api, gate)
    assert reservations(gate) == []                                   # assisted: nothing is reserved at the signal
    r = api.post(f"{BASE}/tickets/{ticket['id']}/confirm", headers={**A, "X-Correlation-ID": "corr-conf"})
    assert r.status_code == 200, r.text
    (row,) = gate_rows(gate, "ai_trader_confirm")
    assert (row["mode"], row["outcome"], row["requested_qty"]) == ("assisted", "allowed", APPROVED) and row["correlation_id"]
    (trade,) = gate.db.trades.docs
    stored = gate.db.tickets.docs[0]
    assert trade["risk_decision_id"] == stored["risk_decision_id"] == row["_id"]
    assert [e["trade_id"] for e in reservations(gate)] == [trade["_id"]]


@pytest.mark.parametrize("gate_on", [False, True])
def test_the_kill_switch_stops_a_confirm_whatever_the_flag(api, gate, gate_on):
    gate.gate_on = gate_on
    ticket = assisted_ticket(api, gate)
    gate.db[rc.CONTROLS].docs.append({"user_id": "user_a", "kill_switch": True, "halted": False, "reason": "stop"})
    r = api.post(f"{BASE}/tickets/{ticket['id']}/confirm", headers=A)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "risk_refused"
    assert "kill_switch_on" in r.json()["detail"]["reason_codes"]
    assert gate.db.trades.docs == [] and gate.db.tickets.docs[0]["status"] == "awaiting_confirmation"
    assert reservations(gate) == []
    assert [x["outcome"] for x in gate_rows(gate, "ai_trader_confirm")] == ["blocked"]
