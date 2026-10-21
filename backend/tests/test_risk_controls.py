"""The kill switch, now that it can actually be set.

Before this change `routes/ai_trader.py` built its Portfolio without `kill_switch` or `halted`, so
both held their dataclass defaults of False on every evaluation: `risk_governor.py:112-115` enforced
them correctly and could never fire. These tests pin the three properties that make the control real
— it can be set, it blocks, and it fails CLOSED — and the one that makes it reviewable afterwards:
every change is recorded with a reason.
"""
from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Optional

import pytest

from services import risk_controls as rc
from services.ai_trader.risk_governor import DEFAULT_LIMITS, Intent, Market, Portfolio, evaluate


# ── a minimal async Mongo stand-in ──────────────────────────────────────────

class FakeCollection:
    def __init__(self) -> None:
        self.docs: List[Dict[str, Any]] = []

    async def find_one(self, q):
        return next((d for d in self.docs if all(d.get(k) == v for k, v in q.items())), None)

    async def insert_one(self, doc):
        self.docs.append(dict(doc))

    async def update_one(self, q, update, upsert=False):
        doc = await self.find_one(q)
        if doc is None:
            if not upsert:
                return
            doc = dict(update.get("$setOnInsert") or {})
            self.docs.append(doc)
        doc.update(update.get("$set") or {})

    def find(self, q):
        rows = [d for d in self.docs if all(d.get(k) == v for k, v in q.items())]
        return _Cursor(rows)


class _Cursor:
    def __init__(self, rows): self.rows = rows
    def sort(self, key, direction): self.rows = sorted(self.rows, key=lambda r: r.get(key) or "", reverse=direction < 0); return self
    def limit(self, n): self.rows = self.rows[:n]; return self
    async def to_list(self, n): return [dict(r) for r in self.rows[:n]]


class FakeDB:
    def __init__(self) -> None:
        self.cols: Dict[str, FakeCollection] = {}

    def __getitem__(self, name):
        return self.cols.setdefault(name, FakeCollection())


class BrokenDB:
    def __getitem__(self, name):
        raise RuntimeError("mongo unreachable")


@pytest.fixture
def db():
    return FakeDB()


def run(coro):
    return asyncio.get_event_loop_policy().new_event_loop().run_until_complete(coro)


# ── the control can be set, and blocks ──────────────────────────────────────

def test_a_user_with_no_row_is_not_blocked_and_says_so(db):
    state = run(rc.read(db, "u1"))
    assert state["kill_switch"] is False and state["halted"] is False
    assert state["stored"] is False


def test_setting_the_kill_switch_blocks_every_position_creating_action(db):
    run(rc.set_control(db, "u1", field="kill_switch", value=True, reason="market gap", actor="u1"))
    state = run(rc.read(db, "u1"))
    assert state["kill_switch"] is True and state["blocking"] is True
    assert set(state["blocked_actions"]) == set(rc.BLOCKED_ACTIONS)
    for action in rc.BLOCKED_ACTIONS:
        with pytest.raises(rc.RiskBlocked):
            run(rc.assert_allowed(db, "u1", action))


def test_the_halt_blocks_independently_of_the_kill_switch(db):
    run(rc.set_control(db, "u1", field="halted", value=True, reason="drawdown review", actor="u1"))
    assert run(rc.read(db, "u1"))["kill_switch"] is False
    with pytest.raises(rc.RiskBlocked):
        run(rc.assert_allowed(db, "u1", "desk_paper_trade"))


def test_clearing_it_unblocks(db):
    run(rc.set_control(db, "u1", field="kill_switch", value=True, reason="on", actor="u1"))
    run(rc.set_control(db, "u1", field="kill_switch", value=False, reason="reviewed and cleared", actor="u1"))
    run(rc.assert_allowed(db, "u1", "desk_paper_trade"))      # must not raise


def test_one_user_s_switch_does_not_block_another(db):
    run(rc.set_control(db, "u1", field="kill_switch", value=True, reason="x", actor="u1"))
    run(rc.assert_allowed(db, "u2", "desk_paper_trade"))      # must not raise


# ── it fails CLOSED ─────────────────────────────────────────────────────────

def test_an_unreadable_store_refuses_new_risk(db):
    """A kill switch that reads as 'off' when the database is unreachable is not a kill switch."""
    with pytest.raises(rc.RiskBlocked) as e:
        run(rc.assert_allowed(BrokenDB(), "u1", "desk_paper_trade"))
    assert e.value.state.get("readable") is False
    assert "refused" in str(e.value)


# ── every change is recorded ────────────────────────────────────────────────

def test_a_change_without_a_reason_is_refused_in_both_directions(db):
    for value in (True, False):
        with pytest.raises(rc.RiskControlError):
            run(rc.set_control(db, "u1", field="kill_switch", value=value, reason="  ", actor="u1"))


def test_every_change_is_appended_with_before_after_who_and_why(db):
    run(rc.set_control(db, "u1", field="kill_switch", value=True, reason="gap risk", actor="u1"))
    run(rc.set_control(db, "u1", field="kill_switch", value=False, reason="reviewed", actor="ops"))
    rows = run(rc.audit_rows(db, "u1"))
    assert len(rows) == 2
    newest, oldest = rows[0], rows[1]
    assert oldest["before"] is False and oldest["after"] is True and oldest["reason"] == "gap risk"
    assert newest["before"] is True and newest["after"] is False and newest["actor"] == "ops"
    assert all(r["policy_version"] == rc.POLICY_VERSION for r in rows)


def test_the_audit_is_never_rewritten_only_appended(db):
    run(rc.set_control(db, "u1", field="kill_switch", value=True, reason="a", actor="u1"))
    run(rc.set_control(db, "u1", field="kill_switch", value=True, reason="b", actor="u1"))
    rows = run(rc.audit_rows(db, "u1"))
    assert len(rows) == 2, "a repeated set must add a row, not overwrite the first"


def test_an_overlong_reason_is_refused(db):
    with pytest.raises(rc.RiskControlError):
        run(rc.set_control(db, "u1", field="kill_switch", value=True, reason="x" * 5000, actor="u1"))


def test_an_unknown_field_is_refused(db):
    with pytest.raises(rc.RiskControlError):
        run(rc.set_control(db, "u1", field="whatever", value=True, reason="x", actor="u1"))


# ── the governor actually fires now ─────────────────────────────────────────

def _intent():
    return Intent(symbol="TCS", quantity=1, entry_price=100.0, stop_price=95.0,
                  target_price=110.0, sector="IT")


def test_the_governor_rejects_when_the_switch_is_on():
    """The property that was missing: with kill_switch True the governor's existing enforcement
    (risk_governor.py:112) fires. It never could before, because nothing set the field."""
    blocked = Portfolio(capital=1_000_000, positions=[], realized_pnl_today=0.0, kill_switch=True)
    d = evaluate(_intent(), blocked, Market(vix=12.0), DEFAULT_LIMITS)
    assert any(r.code == "KILL_SWITCH" for r in d.reasons), [r.code for r in d.reasons]
    # A halt must not merely be noted: no quantity may be approved.
    assert d.approved_qty == 0, d.to_dict()
    assert d.action != "allow", d.action


def test_the_governor_allows_the_same_intent_with_the_switch_off():
    ok = Portfolio(capital=1_000_000, positions=[], realized_pnl_today=0.0, kill_switch=False)
    d = evaluate(_intent(), ok, Market(vix=12.0), DEFAULT_LIMITS)
    assert not any(r.code == "KILL_SWITCH" for r in d.reasons)


def test_a_halt_is_reported_as_its_own_reason():
    halted = Portfolio(capital=1_000_000, positions=[], realized_pnl_today=0.0, halted=True)
    d = evaluate(_intent(), halted, Market(vix=12.0), DEFAULT_LIMITS)
    assert any(r.code == "HALTED" for r in d.reasons)
    assert d.approved_qty == 0, d.to_dict()
