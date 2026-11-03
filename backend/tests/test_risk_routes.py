"""/api/risk/* and /api/admin/risk/* (routes/risk_controls.py): TESTCASES KS-1 to KS-13.

No network, no real database. Replaced, and by what:
  * `route.db`                     tests.test_risk_gate.FakeDB, holding the `users` the admin checks read
  * `route.get_current_user` and   the test's X-Test-User header names a user in USERS. deps.require_role("admin")
    `deps.get_current_user`        runs for real on top of it, so the admin router's 403 is the real one
  * `risk_gate.enabled_for`        whether the F&O gate is on, per test

MOCK — not real data: the users and their roles are made up.
"""
from __future__ import annotations

import pytest
from fastapi import FastAPI, HTTPException, Request
from fastapi.testclient import TestClient

import deps
from routes import risk_controls as route
from services import execution_modes as modes
from services import risk_controls as rc
from services import risk_gate
from services.risk_gate import gate, reference
from services.risk_gate.contract import RiskRequest
from tests.test_risk_gate import NOW, FakeDB, run, spread

USERS = {
    "u1": {"user_id": "u1", "email": "one@example.com", "role": "user"},
    "admin": {"user_id": "adm", "email": "adm@example.com", "role": "admin"},
    "legacy_admin": {"user_id": "adm2", "email": "adm2@example.com", "is_admin": True},
    # an advisor (not an admin) acting for client1
    "advisor_as_client": {"user_id": "client1", "email": "c1@example.com", "_session_user_id": "adv1"},
    # an admin acting for client1
    "admin_as_client": {"user_id": "client1", "email": "c1@example.com", "_session_user_id": "adm"},
    # a non-admin advisor acting for a client profile that happens to carry the admin role
    "borrowed_admin": {"user_id": "cadm", "email": "cadm@example.com", "role": "admin", "_session_user_id": "adv1"},
}
DB_USERS = [{"user_id": "u1"}, {"user_id": "u2"}, {"user_id": "client1"}, {"user_id": "cadm", "role": "admin"},
            {"user_id": "adv1", "role": "advisor"}, {"user_id": "adm", "role": "admin"},
            {"user_id": "adm2", "is_admin": True}]


@pytest.fixture
def h(monkeypatch):
    db = FakeDB()
    db["users"].docs = [dict(u) for u in DB_USERS]
    monkeypatch.setattr(route, "db", db)
    monkeypatch.setattr(rc, "_indexes_ready", False)
    gate_on = set()

    async def current_user(request: Request):
        who = request.headers.get("X-Test-User")
        if who not in USERS:
            raise HTTPException(status_code=401, detail="Not authenticated")
        return dict(USERS[who])

    async def enabled_for(_db, user):
        return user.get("user_id") in gate_on

    monkeypatch.setattr(route, "get_current_user", current_user)
    monkeypatch.setattr(deps, "get_current_user", current_user)        # what require_role("admin") calls
    monkeypatch.setattr(risk_gate, "enabled_for", enabled_for)
    app = FastAPI()
    app.include_router(route.router)
    app.include_router(route.admin_router)

    class H:
        pass
    out = H()
    out.db, out.http, out.gate_on = db, TestClient(app), gate_on

    def call(method, path, who="u1", json=None):
        headers = {"X-Test-User": who} if who else {}
        return out.http.request(method, path, json=json, headers=headers)
    out.call = call
    return out


def controls(h, uid):
    return next((d for d in h.db[rc.CONTROLS].docs if d.get("user_id") == uid), {})


# ── KS-13 ────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("method, path", [
    ("GET", "/api/risk/status"), ("PUT", "/api/risk/kill-switch"), ("PUT", "/api/risk/halt"),
    ("GET", "/api/risk/audit"), ("GET", "/api/risk/decisions"), ("GET", "/api/risk/policy"),
    ("PUT", "/api/admin/risk/u1/kill-switch"), ("PUT", "/api/admin/risk/u1/halt"),
    ("PUT", "/api/admin/risk/u1/live-authorization")])
def test_every_route_needs_a_signed_in_user(h, method, path):
    assert h.call(method, path, who=None, json={"enabled": True, "reason": "x"}).status_code == 401
    assert h.db[rc.AUDIT].docs == [] and h.db[rc.CONTROLS].docs == []


# ── KS-1 to KS-5: who may set and who may clear ──────────────────────────────
@pytest.mark.parametrize("path, field", [("/api/risk/kill-switch", "kill_switch"), ("/api/risk/halt", "halted")])
def test_anyone_may_turn_a_control_on_but_only_an_admin_may_clear_it(h, path, field):
    on = h.call("PUT", path, json={"enabled": True, "reason": "gap risk"})
    assert on.status_code == 200 and on.json()[field] is True
    (row,) = h.db[rc.AUDIT].docs
    assert (row["actor"], row["user_id"], row["after"]) == ("u1", "u1", True)

    off = h.call("PUT", path, json={"enabled": False, "reason": "calmer now"})
    assert off.status_code == 403 and off.json()["detail"]["code"] == "admin_required"
    assert controls(h, "u1")[field] is True and len(h.db[rc.AUDIT].docs) == 1


@pytest.mark.parametrize("who", ["admin", "legacy_admin"])
def test_an_admin_may_clear_their_own_control(h, who):
    assert h.call("PUT", "/api/risk/kill-switch", who=who, json={"enabled": True, "reason": "x"}).status_code == 200
    off = h.call("PUT", "/api/risk/kill-switch", who=who, json={"enabled": False, "reason": "reviewed"})
    assert off.status_code == 200 and off.json()["kill_switch"] is False


def test_under_impersonation_the_control_lands_on_the_client_and_names_the_advisor(h):
    r = h.call("PUT", "/api/risk/kill-switch", who="advisor_as_client", json={"enabled": True, "reason": "x"})
    assert r.status_code == 200 and controls(h, "client1")["kill_switch"] is True
    assert h.db[rc.AUDIT].docs[0]["actor"] == "adv1" and h.db[rc.AUDIT].docs[0]["user_id"] == "client1"
    r = h.call("PUT", "/api/risk/kill-switch", who="advisor_as_client", json={"enabled": False, "reason": "x"})
    assert r.status_code == 403
    # An admin acting for the same client may clear it, and the record names the admin.
    r = h.call("PUT", "/api/risk/kill-switch", who="admin_as_client", json={"enabled": False, "reason": "reviewed"})
    assert r.status_code == 200 and controls(h, "client1")["kill_switch"] is False
    assert h.db[rc.AUDIT].docs[-1]["actor"] == "adm"


def test_a_borrowed_admin_role_cannot_clear(h):
    h.call("PUT", "/api/risk/kill-switch", who="borrowed_admin", json={"enabled": True, "reason": "x"})
    r = h.call("PUT", "/api/risk/kill-switch", who="borrowed_admin", json={"enabled": False, "reason": "x"})
    assert r.status_code == 403 and controls(h, "cadm")["kill_switch"] is True


@pytest.mark.parametrize("body", [{}, {"enabled": "false", "reason": "x"}, {"enabled": True, "reason": " "}])
def test_a_bad_body_is_422(h, body):
    assert h.call("PUT", "/api/risk/kill-switch", json=body).status_code == 422
    assert h.db[rc.AUDIT].docs == []


# ── KS-6, KS-11: status, and the indexes it asks for ─────────────────────────
def test_status_says_who_may_reset_the_live_grant_the_modes_and_the_gate(h):
    body = h.call("GET", "/api/risk/status").json()
    assert body["kill_switch"] is False and body["halted"] is False and body["policy_version"] == rc.POLICY_VERSION
    assert body["can_reset"] is False
    assert body["live_authorization"]["granted"] is False and body["live_authorization"]["stored"] is False
    assert body["modes"] == ["paper", "shadow", "assisted", "live"]
    assert body["live_execution_available"] is False
    assert {k: body["gate"][k] for k in ("enabled", "policy_version")} == {"enabled": False, "policy_version": "fno-risk-v1"}
    assert "core risk checks always run" in body["gate"]["scope"] and body["risk_policy_version"] == "universal-risk-v2"
    h.gate_on.add("adm")
    admin = h.call("GET", "/api/risk/status", who="admin").json()
    assert admin["can_reset"] is True and admin["gate"]["enabled"] is True
    assert h.call("GET", "/api/risk/status", who="admin_as_client").json()["can_reset"] is True
    assert h.call("GET", "/api/risk/status", who="borrowed_admin").json()["can_reset"] is False


def test_the_indexes_are_asked_for_once_and_retried_after_a_failure(h):
    h.db.fail[(rc.AUDIT, "create_index")] = RuntimeError("no privilege")
    assert h.call("GET", "/api/risk/status").status_code == 200          # an index failure never blocks a read
    assert rc._indexes_ready is False
    del h.db.fail[(rc.AUDIT, "create_index")]
    h.call("GET", "/api/risk/status")
    assert rc._indexes_ready is True
    got = {name: col.indexes for name, col in h.db.cols.items() if col.indexes}
    assert got[rc.CONTROLS][-1] == ((("user_id", 1),), {"unique": True})
    assert got[rc.AUDIT][-1] == ((("user_id", 1), ("at", -1)), {})
    assert got[rc.DECISIONS][-2:] == [((("user_id", 1), ("at", -1)), {}), ((("correlation_id", 1),), {})]
    assert got[modes.AUTHORIZATIONS][-1] == ((("user_id", 1),), {"unique": True})
    before = sum(len(v) for v in got.values())
    h.call("GET", "/api/risk/status")
    assert sum(len(col.indexes) for col in h.db.cols.values()) == before


# ── KS-7 to KS-10: the admin router ──────────────────────────────────────────
ADMIN_PATHS = [("/api/admin/risk/u1/kill-switch", {"enabled": True, "reason": "ops"}),
               ("/api/admin/risk/u1/halt", {"enabled": True, "reason": "ops"}),
               ("/api/admin/risk/u1/live-authorization", {"granted": True, "reason": "ops"})]


@pytest.mark.parametrize("path, body", ADMIN_PATHS)
@pytest.mark.parametrize("who", ["u1", "advisor_as_client", "admin_as_client"])
def test_a_non_admin_is_refused_by_the_admin_router(h, path, body, who):
    r = h.call("PUT", path, who=who, json=body)
    assert r.status_code == 403
    assert h.db[rc.AUDIT].docs == [] and h.db[rc.CONTROLS].docs == [] and h.db[modes.AUTHORIZATIONS].docs == []


@pytest.mark.parametrize("path, body", ADMIN_PATHS)
def test_an_admin_role_borrowed_from_a_client_profile_is_refused(h, path, body):
    r = h.call("PUT", path, who="borrowed_admin", json=body)
    assert r.status_code == 403 and r.json()["detail"]["code"] == "admin_required"
    assert h.db[rc.AUDIT].docs == []


@pytest.mark.parametrize("path, field", [("/api/admin/risk/u1/kill-switch", "kill_switch"),
                                         ("/api/admin/risk/u1/halt", "halted")])
def test_an_admin_sets_and_clears_another_users_control(h, path, field):
    on = h.call("PUT", path, who="admin", json={"enabled": True, "reason": "margin call"})
    assert on.status_code == 200 and on.json()[field] is True and on.json()["user_id"] == "u1"
    off = h.call("PUT", path, who="admin", json={"enabled": False, "reason": "reviewed with the user"})
    assert off.status_code == 200 and controls(h, "u1")[field] is False
    assert [(r["actor"], r["user_id"], r["after"]) for r in h.db[rc.AUDIT].docs] == [
        ("adm", "u1", True), ("adm", "u1", False)]
    assert controls(h, "adm") == {}


def test_an_admin_grant_is_stored_and_audited_but_live_stays_unavailable(h, monkeypatch):
    r = h.call("PUT", "/api/admin/risk/u1/live-authorization", who="admin", json={"granted": True, "reason": "pilot"})
    assert r.status_code == 200
    assert r.json()["live_authorization"]["granted"] is True and r.json()["live_execution_available"] is False
    (row,) = h.db[rc.AUDIT].docs
    assert (row["field"], row["actor"], row["user_id"], row["after"]) == ("live_authorization", "adm", "u1", True)
    status = h.call("GET", "/api/risk/status").json()
    assert status["live_authorization"]["granted"] is True and status["live_execution_available"] is False

    async def lookup(underlying, expiries, today):
        return {e: {"listed": True, "lot_size": 50, "source": "test", "as_of": "2026-10-20", "error": None}
                for e in expiries}
    monkeypatch.setattr(reference, "lookup", lookup)
    req = RiskRequest(correlation_id="c", user_id="u1", actor_id="u1", mode="live", path="desk_paper_trade",
                      action="open", instrument="structure", symbol="MOCKU", legs=spread())
    decision = run(gate.check(h.db, req, now=NOW))
    assert [r.code for r in decision.reasons] == ["live_execution_unavailable"]


@pytest.mark.parametrize("path, body, status", [
    ("/api/admin/risk/u1/kill-switch", {"enabled": True}, 422),
    ("/api/admin/risk/u1/kill-switch", {"enabled": False, "reason": ""}, 422),
    ("/api/admin/risk/u1/kill-switch", {"reason": "x"}, 422),
    ("/api/admin/risk/u1/halt", {"enabled": 1, "reason": "x"}, 422),
    ("/api/admin/risk/u1/live-authorization", {"granted": "yes", "reason": "x"}, 422),
    ("/api/admin/risk/u1/live-authorization", {"granted": True}, 422),
    ("/api/admin/risk/nobody/kill-switch", {"enabled": True, "reason": "x"}, 404),
    ("/api/admin/risk/nobody/live-authorization", {"granted": True, "reason": "x"}, 404),
])
def test_admin_input_errors_write_nothing(h, path, body, status):
    assert h.call("PUT", path, who="admin", json=body).status_code == status
    assert h.db[rc.AUDIT].docs == [] and h.db[rc.CONTROLS].docs == [] and h.db[modes.AUTHORIZATIONS].docs == []


# ── KS-12: the policy and this user's usage ──────────────────────────────────
def test_policy_shows_the_limits_and_the_users_open_structures(h):
    h.db["desk_paper_trades"].docs = [
        {"_id": "a", "user_id": "u1", "kind": "strategy", "status": "open", "legs": spread()},
        {"_id": "b", "user_id": "u2", "kind": "strategy", "status": "open", "legs": spread()}]
    body = h.call("GET", "/api/risk/policy").json()
    assert body["policy_version"] == "fno-risk-v1"
    limits = body["limits"]
    assert (limits["max_legs"], limits["max_lots_per_leg"], limits["max_open_structures"],
            limits["max_capital_at_risk_rs"], limits["require_defined_risk"], limits["allowed_modes"]) == (
        4, 10, 10, 200000.0, True, ["paper", "assisted"])
    assert "not calibrated" in limits["basis"]
    assert body["usage"] == {"open_structures": 1, "capital_at_risk_rs": 200.0, "capital_at_risk_unknown": 0}


def test_audit_and_decisions_still_list_the_users_own_rows(h):
    h.call("PUT", "/api/risk/kill-switch", json={"enabled": True, "reason": "x"})
    run(rc.record_decision(h.db, "u1", action="desk_paper_trade", outcome="blocked"))
    run(rc.record_decision(h.db, "u2", action="desk_paper_trade", outcome="blocked"))
    assert h.call("GET", "/api/risk/audit").json()["count"] == 1
    assert h.call("GET", "/api/risk/decisions").json()["count"] == 1
