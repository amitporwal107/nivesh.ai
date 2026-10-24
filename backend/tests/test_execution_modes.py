"""Execution modes and the live-execution grant (services/execution_modes.py): TESTCASES EM-1 to EM-8.

No network, no real database: tests.test_risk_gate.FakeDB. Nothing here can make live execution possible: the
constant is False in this release and the tests that force it True do so through monkeypatch, undone afterwards.
"""
from __future__ import annotations

import importlib
from datetime import datetime, timezone

import pytest

from services import execution_modes as modes
from services import risk_controls as rc
from tests.test_risk_gate import FakeDB, run


@pytest.fixture
def db():
    return FakeDB()


def test_the_modes_and_live_is_not_available_in_this_release():
    assert modes.MODES == ("paper", "shadow", "assisted", "live")
    assert modes.LIVE_EXECUTION_AVAILABLE is False


def test_a_user_with_no_row_is_not_granted_and_says_so(db):
    assert run(modes.read_live_authorization(db, "u1")) == {
        "user_id": "u1", "granted": False, "granted_by": None, "reason": None, "at": None, "stored": False}


@pytest.mark.parametrize("granted", [True, False])
@pytest.mark.parametrize("reason", [None, "", "   "])
def test_a_change_without_a_reason_is_refused_and_writes_nothing(db, granted, reason):
    with pytest.raises(rc.RiskControlError):
        run(modes.set_live_authorization(db, "u1", granted, reason, "admin1"))
    assert db[rc.AUDIT].docs == [] and db[modes.AUTHORIZATIONS].docs == []


def test_a_non_bool_grant_is_refused(db):
    with pytest.raises(rc.RiskControlError):
        run(modes.set_live_authorization(db, "u1", "yes", "pilot", "admin1"))
    assert db[rc.AUDIT].docs == []


def test_every_change_is_audited_and_the_grant_row_holds_who_why_and_when(db):
    t1 = datetime(2026, 10, 21, 5, 0, tzinfo=timezone.utc)
    t2 = datetime(2026, 10, 22, 5, 0, tzinfo=timezone.utc)
    run(modes.set_live_authorization(db, "u1", True, "pilot cohort", "admin1", now=t1))
    after = run(modes.set_live_authorization(db, "u1", False, "pilot ended", "admin2", now=t2))
    assert after == {"user_id": "u1", "granted": False, "granted_by": "admin2", "reason": "pilot ended",
                     "at": t2.isoformat(), "stored": True}
    (row,) = db[modes.AUTHORIZATIONS].docs
    assert set(row) == {"user_id", "granted", "granted_by", "reason", "at"}
    first, second = db[rc.AUDIT].docs
    assert (first["field"], first["before"], first["after"], first["actor"], first["reason"]) == (
        "live_authorization", False, True, "admin1", "pilot cohort")
    assert (second["field"], second["before"], second["after"], second["actor"]) == (
        "live_authorization", True, False, "admin2")


def test_the_audit_row_is_written_before_the_grant(db):
    db.fail[(modes.AUTHORIZATIONS, "update_one")] = RuntimeError("write failed")
    with pytest.raises(RuntimeError):
        run(modes.set_live_authorization(db, "u1", True, "pilot", "admin1"))
    assert len(db[rc.AUDIT].docs) == 1 and db[modes.AUTHORIZATIONS].docs == []


def test_a_grant_alone_does_not_allow_live(db):
    run(modes.set_live_authorization(db, "u1", True, "pilot", "admin1"))
    assert run(modes.is_live_allowed(db, "u1")) is False


def test_live_needs_the_build_and_the_grant(db, monkeypatch):
    monkeypatch.setattr(modes, "LIVE_EXECUTION_AVAILABLE", True)
    assert run(modes.is_live_allowed(db, "u1")) is False
    run(modes.set_live_authorization(db, "u1", True, "pilot", "admin1"))
    assert run(modes.is_live_allowed(db, "u1")) is True
    assert run(modes.is_live_allowed(db, "u2")) is False


def test_an_unreadable_grant_is_no_grant(db, monkeypatch):
    monkeypatch.setattr(modes, "LIVE_EXECUTION_AVAILABLE", True)
    run(modes.set_live_authorization(db, "u1", True, "pilot", "admin1"))
    db.fail[(modes.AUTHORIZATIONS, "find_one")] = RuntimeError("mongo unreachable")
    assert run(modes.is_live_allowed(db, "u1")) is False


def test_a_restart_does_not_grant_live(db, monkeypatch):
    monkeypatch.setattr(modes, "LIVE_EXECUTION_AVAILABLE", True)
    run(modes.set_live_authorization(db, "u1", True, "pilot", "admin1"))
    assert run(modes.is_live_allowed(db, "u1")) is True
    importlib.reload(modes)                      # a fresh process: the constant is whatever the code says
    assert modes.LIVE_EXECUTION_AVAILABLE is False
    assert run(modes.is_live_allowed(db, "u1")) is False
    assert run(modes.read_live_authorization(db, "u1"))["granted"] is True      # the grant survives, unused
