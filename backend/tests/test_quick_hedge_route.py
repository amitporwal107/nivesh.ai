"""POST /api/portfolio/quick-hedge: the fail-closed flag gate, request validation, and that the account is the logged-in one.
No Mongo, no DaaS: the user resolver, the flag store and the service call are injected, so the gate and validation run for real."""
import copy

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

import feature_flags as ff
import feature_gate


class _Coll:
    def __init__(self, docs): self.docs = docs
    async def find_one(self, q, proj=None):
        for d in self.docs:
            if all(d.get(k) == v for k, v in q.items()):
                return copy.deepcopy(d)
        return None


class _DB:
    def __init__(self, flags=None):
        self.system_config = _Coll([{"key": "feature_flags", "flags": flags or {}}])
        self.users = _Coll([])


USERS = {"owner": {"user_id": "u1", "email": "owner@example.com"}, "other": {"user_id": "u2", "email": "other@example.com"}}
OK = {"status": "ok", "modes": [{"mode": "balanced"}]}
BODY = {"expected_fall_pct": 15, "tenor": "1m", "tolerance_rs": 100000}


@pytest.fixture(autouse=True)
def _reset_flags():
    saved = copy.deepcopy(ff._flags); feature_gate._state["at"] = float("-inf")
    yield
    ff._flags.clear(); ff._flags.update(saved); feature_gate._state["at"] = float("-inf")


def _client(monkeypatch, db):
    import routes.portfolio_hedge as ph

    async def resolve(request: Request):
        return copy.deepcopy(USERS[request.headers["X-Test-User"]])
    calls = []

    async def fake_run(db_, uid, **kw):
        calls.append((uid, kw))
        return OK
    monkeypatch.setattr(ph.service, "run", fake_run)
    monkeypatch.setattr(ph, "get_current_user", resolve)
    gate = feature_gate.require_feature("portfolio_hedge", resolve_user=resolve, get_db=lambda: db, clock=lambda: 0.0)
    app = FastAPI(); app.include_router(ph.router)
    for route in app.routes:
        for dep in getattr(route, "dependant", None).dependencies if getattr(route, "dependant", None) else []:
            if dep.call is not None and getattr(dep.call, "__qualname__", "").startswith("require_feature"):
                app.dependency_overrides[dep.call] = gate
    return TestClient(app), calls


def _post(c, who, body):
    return c.post("/api/portfolio/quick-hedge", json=body, headers={"X-Test-User": who})


def test_the_flag_is_off_for_everyone_but_the_owner_by_default_and_the_service_is_never_called(monkeypatch):
    meta = ff.KNOWN_FEATURES["portfolio_hedge"]
    assert meta["default_mode"] == "allowlist" and "everyone" in meta["allowed_modes"]
    c, calls = _client(monkeypatch, _DB())                                    # no stored flag: the defaults apply
    r = _post(c, "other", BODY)
    assert r.status_code == 403 and r.json()["detail"] == "feature_not_enabled"
    assert calls == []


def test_an_allowlisted_user_gets_the_service_result_for_their_own_account(monkeypatch):
    db = _DB(flags={"portfolio_hedge": {"mode": "allowlist", "allowlist": ["owner@example.com"]}})
    c, calls = _client(monkeypatch, db)
    r = _post(c, "owner", {**BODY, "account": "someone-else", "user_id": "u2"})      # extra fields are never read
    assert r.status_code == 200 and r.json() == OK
    assert calls == [("u1", {"expected_fall_pct": 15.0, "tenor": "1m", "tolerance_rs": 100000.0, "tolerance_pct": None})]
    assert _post(c, "other", BODY).status_code == 403


def test_switching_the_flag_off_denies_even_the_owner(monkeypatch):
    c, calls = _client(monkeypatch, _DB(flags={"portfolio_hedge": {"mode": "off", "allowlist": ["owner@example.com"]}}))
    assert _post(c, "owner", BODY).status_code == 403 and calls == []


@pytest.mark.parametrize("body,code", [
    ({"expected_fall_pct": 15, "tenor": "1m"}, "tolerance_required"),
    ({"expected_fall_pct": 0, "tolerance_rs": 1}, None), ({"expected_fall_pct": 60, "tolerance_rs": 1}, None),
    ({"expected_fall_pct": 15, "tolerance_rs": -5}, None), ({"expected_fall_pct": 15, "tolerance_pct": 101}, None),
    ({"expected_fall_pct": 15, "tolerance_rs": 1, "tenor": "5y"}, None), ({"tolerance_rs": 1}, None),
])
def test_bad_requests_are_rejected_before_any_work(monkeypatch, body, code):
    db = _DB(flags={"portfolio_hedge": {"mode": "allowlist", "allowlist": ["owner@example.com"]}})
    c, calls = _client(monkeypatch, db)
    r = _post(c, "owner", body)
    assert r.status_code == 422 and calls == []
    if code:
        assert r.json()["detail"]["code"] == code


def test_a_percent_tolerance_alone_is_accepted(monkeypatch):
    db = _DB(flags={"portfolio_hedge": {"mode": "allowlist", "allowlist": ["owner@example.com"]}})
    c, calls = _client(monkeypatch, db)
    assert _post(c, "owner", {"expected_fall_pct": 10, "tolerance_pct": 5}).status_code == 200
    assert calls[0][1]["tolerance_pct"] == 5.0 and calls[0][1]["tolerance_rs"] is None
