"""Strategy instances (Strategy Lab › Build a trade, step 4: Save version · Clone · Adjust legs): the pure validator in
services/strategy_plan/instances.py and the routes in routes/strategy_instances.py.

No network, no real database: `route.db` is the in-memory collection from tests/test_desk_trading.py (FakeCollection,
the Mongo operators the desk uses). MOCK — not real data: FIXU, its strikes, prices and expiries are made up.
"""
from __future__ import annotations

import pytest
from fastapi import FastAPI, HTTPException, Request
from fastapi.testclient import TestClient

import routes.strategy_instances as route
from services.strategy_plan import instances as inst
from tests.test_desk_trading import FakeCollection

URL = "/api/desk/strategy/instances"
A = {"X-Test-User": "user_a"}
B = {"X-Test-User": "user_b"}
EXPIRY = "2026-11-24"


def opt(side, strike, price, option_type="call", lots=1):
    return {"kind": "option", "side": side, "lots": lots, "lot_size": 250, "entry_price": price, "expiry": EXPIRY,
            "strike": strike, "option_type": option_type, "price_source": "MOCK chain close"}


def struct(**config):
    return {"legs": [opt("buy", 1300, 40), opt("sell", 1360, 15)], "config": {"strike_rule": "atm", "width": 2, **config}}


def body(**over):
    b = {"name": "Bull call spread · FIXU", "template": "bull_call_spread", "underlying": "fixu",
         "source": {"kind": "template", "ref": "bull_call_spread"}, "structure": struct(), "note": "first cut"}
    b.update(over)
    return b


class FakeDb:
    def __init__(self):
        self.col = FakeCollection()

    def __getitem__(self, name):
        assert name == inst.COLLECTION, f"the route touched db[{name!r}]"
        return self.col


@pytest.fixture
def h(monkeypatch):
    db = FakeDb()
    monkeypatch.setattr(route, "db", db)
    clock = {"n": 0}

    def stamp():
        clock["n"] += 1
        return f"2026-10-28T05:00:{clock['n']:02d}+00:00"
    monkeypatch.setattr(route, "_stamp", stamp)

    async def user(request: Request):
        uid = request.headers.get("X-Test-User")
        if not uid:
            raise HTTPException(status_code=401, detail="Not authenticated")
        return {"user_id": uid}
    monkeypatch.setattr(route, "get_current_user", user)
    app = FastAPI()
    app.include_router(route.router)
    return TestClient(app), db


# ── the validator ────────────────────────────────────────────────────────────
def test_a_valid_body_becomes_version_one():
    d = inst.new_instance("u", body(), instance_id="i1", at="T")
    assert d["underlying"] == "FIXU" and d["template"] == "bull_call_spread" and d["latest_version"] == 1
    assert d["versions"] == [{"version": 1, "saved_at": "T", "structure": struct(), "note": "first cut"}]
    assert d["source"] == {"kind": "template", "ref": "bull_call_spread"} and d["cloned_from"] is None


@pytest.mark.parametrize("over,code", [
    ({"extra": 1}, "unknown_field"),
    ({"template": "short_strangle"}, "invalid_template"),
    ({"underlying": "not a symbol!"}, "invalid_underlying"),
    ({"source": {"kind": "rumour", "ref": None}}, "invalid_source"),
    ({"name": "x" * 81}, "invalid_name"),
    ({"structure": {"legs": []}}, "invalid_leg_count"),
    ({"structure": {"legs": [opt("buy", 1300, 40)] * 5}}, "invalid_leg_count"),
    ({"structure": {"legs": [{**opt("buy", 1300, 40), "qty": 1}]}}, "unknown_field"),
    ({"structure": {"legs": [{**opt("buy", 1300, 40), "side": "hold"}]}}, "invalid_leg_side"),
    ({"structure": {"legs": [opt("buy", 1300, 0)]}}, "invalid_entry_price"),
    ({"structure": {"legs": [opt("buy", 1300, 40, lots=0)]}}, "invalid_lots"),
    ({"structure": {"legs": [{**opt("buy", 1300, 40), "expiry": "2026-13-01"}]}}, "invalid_expiry"),
    ({"structure": {"legs": [{**opt("buy", 1300, 40), "option_type": "CE"}]}}, "invalid_option_type"),
    ({"structure": {"legs": [{"kind": "cash", "side": "buy", "lots": 1, "lot_size": 250, "entry_price": 1215,
                              "expiry": EXPIRY}]}}, "invalid_cash_leg"),
    ({"structure": {"legs": [opt("buy", 1300, 40)], "config": {"x": "y" * 5000}}}, "config_too_large"),
])
def test_bad_bodies_are_refused_with_a_code(over, code):
    with pytest.raises(inst.InstanceInputError) as e:
        inst.new_instance("u", body(**over), instance_id="i1", at="T")
    assert e.value.code == code and e.value.message


def test_cash_and_future_legs_are_normalised():
    legs = [{"kind": "cash", "side": "buy", "lots": 1, "lot_size": 250, "entry_price": 1215},
            {"kind": "future", "side": "sell", "lots": 1, "lot_size": 250, "entry_price": 1220, "expiry": EXPIRY}]
    d = inst.new_instance("u", body(template="covered_call", structure={"legs": legs}), instance_id="i1", at="T")
    got = d["versions"][0]["structure"]
    assert got["config"] == {}
    assert got["legs"][0] == {"kind": "cash", "side": "buy", "lots": 1, "lot_size": 250, "entry_price": 1215.0,
                              "expiry": None, "strike": None, "option_type": None, "price_source": None}
    assert got["legs"][1]["expiry"] == EXPIRY and got["legs"][1]["strike"] is None


# ── the routes ───────────────────────────────────────────────────────────────
def test_every_route_needs_a_signed_in_user(h):
    c, db = h
    for method, url, b in (("post", URL, body()), ("get", URL, None), ("get", f"{URL}/x", None),
                           ("post", f"{URL}/x/versions", {"structure": struct()}), ("post", f"{URL}/x/clone", {})):
        r = c.request(method, url, json=b) if b is not None else c.request(method, url)
        assert r.status_code == 401, (method, url)
    assert db.col.docs == []


def test_save_then_add_versions_then_read(h):
    c, db = h
    r = c.post(URL, json=body(), headers=A)
    assert r.status_code == 201, r.text
    i = r.json()["instance"]
    assert i["latest_version"] == 1 and len(i["versions"]) == 1 and i["sent_to_broker"] is False
    assert i["underlying"] == "FIXU" and i["cloned_from"] is None
    wider = {"legs": [opt("buy", 1300, 40), opt("sell", 1400, 6)], "config": {"width": 4}}
    r = c.post(f"{URL}/{i['id']}/versions", json={"structure": wider, "note": "wider"}, headers=A)
    assert r.status_code == 201, r.text
    j = r.json()["instance"]
    assert j["latest_version"] == 2 and [v["version"] for v in j["versions"]] == [1, 2]
    assert j["versions"][0]["structure"] == struct()                   # version 1 is unchanged
    assert j["versions"][1]["structure"]["legs"][1]["strike"] == 1400.0 and j["versions"][1]["note"] == "wider"
    assert j["updated_at"] > j["created_at"]
    got = c.get(f"{URL}/{i['id']}", headers=A).json()["instance"]
    assert got == j
    listed = c.get(URL, headers=A).json()
    assert listed["count"] == 1 and listed["instances"][0]["latest_version"] == 2
    assert [v["version"] for v in listed["instances"][0]["versions"]] == [2]          # the list carries the latest only


def test_clone_copies_the_latest_version_into_a_new_instance(h):
    c, _ = h
    i = c.post(URL, json=body(), headers=A).json()["instance"]
    c.post(f"{URL}/{i['id']}/versions", json={"structure": struct(width=3)}, headers=A)
    r = c.post(f"{URL}/{i['id']}/clone", headers=A)
    assert r.status_code == 201, r.text
    k = r.json()["instance"]
    assert k["id"] != i["id"] and k["latest_version"] == 1
    assert k["cloned_from"] == {"id": i["id"], "version": 2}
    assert k["source"] == {"kind": "clone", "ref": f"{i['id']}@v2"}
    assert k["versions"][0]["structure"]["config"]["width"] == 3
    listed = c.get(URL, headers=A).json()["instances"]
    assert [x["id"] for x in listed] == [k["id"], i["id"]]                         # most recently updated first


def test_another_users_instance_is_404_and_untouched(h):
    c, db = h
    i = c.post(URL, json=body(), headers=A).json()["instance"]
    for method, url, b in (("get", f"{URL}/{i['id']}", None), ("post", f"{URL}/{i['id']}/versions", {"structure": struct()}),
                           ("post", f"{URL}/{i['id']}/clone", None)):
        r = c.request(method, url, json=b, headers=B) if b is not None else c.request(method, url, headers=B)
        assert (r.status_code, r.json()["detail"]) == (404, "instance_not_found"), (method, url)
    assert c.get(URL, headers=B).json()["instances"] == []
    assert len(db.col.docs) == 1 and db.col.docs[0]["latest_version"] == 1


def test_bad_bodies_answer_422_and_write_nothing(h):
    c, db = h
    r = c.post(URL, json=body(template="nonsense"), headers=A)
    assert r.status_code == 422 and r.json()["detail"]["code"] == "invalid_template"
    r = c.post(URL, content=b"{", headers={**A, "Content-Type": "application/json"})
    assert r.status_code == 422 and r.json()["detail"]["code"] == "invalid_body"
    i = c.post(URL, json=body(), headers=A).json()["instance"]
    r = c.post(f"{URL}/{i['id']}/versions", json={"structure": struct(), "name": "x"}, headers=A)
    assert r.status_code == 422 and r.json()["detail"]["code"] == "unknown_field"
    assert len(db.col.docs) == 1 and db.col.docs[0]["latest_version"] == 1


def test_the_version_and_instance_limits(h, monkeypatch):
    c, db = h
    monkeypatch.setattr(inst, "MAX_VERSIONS", 2)
    monkeypatch.setattr(inst, "MAX_INSTANCES", 2)
    i = c.post(URL, json=body(), headers=A).json()["instance"]
    assert c.post(f"{URL}/{i['id']}/versions", json={"structure": struct()}, headers=A).status_code == 201
    r = c.post(f"{URL}/{i['id']}/versions", json={"structure": struct()}, headers=A)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "version_limit"
    assert c.post(URL, json=body(), headers=A).status_code == 201
    r = c.post(URL, json=body(), headers=A)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "instance_limit"
    r = c.post(f"{URL}/{i['id']}/clone", headers=A)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "instance_limit"
    assert len(db.col.docs) == 2


def test_a_version_saved_on_a_stale_read_is_refused(h, monkeypatch):
    """Two saves of version N+1 at once: the second one's update finds latest_version moved on and is refused."""
    c, db = h
    i = c.post(URL, json=body(), headers=A).json()["instance"]
    real_own = route._own

    async def stale_own(uid, iid):
        doc = await real_own(uid, iid)
        db.col.docs[0]["latest_version"] = 7          # another save landed between the read and the update
        return doc
    monkeypatch.setattr(route, "_own", stale_own)
    r = c.post(f"{URL}/{i['id']}/versions", json={"structure": struct()}, headers=A)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "version_conflict"
    assert len(db.col.docs[0]["versions"]) == 1
