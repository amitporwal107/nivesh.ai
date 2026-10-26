"""GET /api/desk/strategy/templates: the template catalog the F&O lab's program library reads (test case B-1 in
test_reports/fno_lab_screens_TESTCASES.md). No fixture data: the catalog is checked against the template functions
themselves."""
from __future__ import annotations

import inspect

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

import routes.strategy_plan as route
from services.strategy_plan import templates as tp
from services.strategy_plan.engine import CALCULATION_VERSION

URL = "/api/desk/strategy/templates"


def _client(monkeypatch, signed_in=True):
    if signed_in:
        async def fake_user(request: Request):
            return {"user_id": "u1", "email": "u1@example.com"}
        monkeypatch.setattr(route, "get_current_user", fake_user)
    app = FastAPI()
    app.include_router(route.router)
    return TestClient(app)


def _public_template_functions():
    return {n for n, f in inspect.getmembers(tp, inspect.isfunction)
            if not n.startswith("_") and f.__module__ == tp.__name__ and n != "catalog"}


def test_requires_sign_in(monkeypatch):
    assert _client(monkeypatch, signed_in=False).get(URL).status_code == 401


def test_shape(monkeypatch):
    res = _client(monkeypatch).get(URL)
    assert res.status_code == 200
    b = res.json()
    assert b["read_only"] is True and b["status"] == "template"
    assert b["calculation_version"] == CALCULATION_VERSION == "payoff-v1"
    assert b["count"] == len(b["templates"]) == len(tp.CATALOG)
    for t in b["templates"]:
        assert set(t) >= {"name", "label", "kind", "legs", "params", "calculation_version"}
        assert t["kind"] in ("option", "future", "cash")
        assert t["legs"] and all(l["side"] in ("buy", "sell") for l in t["legs"])
        assert t["calculation_version"] == "payoff-v1"


def test_catalog_matches_the_template_functions():
    assert {e["name"] for e in tp.CATALOG} == _public_template_functions()


def test_params_come_from_each_signature_and_strike_params_exist():
    for t in tp.catalog():
        sig = inspect.signature(getattr(tp, t["name"])).parameters
        assert set(t["params"]) <= set(sig)
        assert not set(t["params"]) & {"chain", "spot", "lot_size", "expiry", "underlying", "today", "costs"}
        for leg in t["legs"]:
            if t["kind"] == "option":
                assert leg["option_type"] in ("call", "put") and leg["strike_param"] in t["params"]
            else:
                assert leg["option_type"] is None and leg["strike_param"] is None


def test_option_leg_sides_match_what_the_function_builds():
    """Build each option template on a small chain and compare the legs it returns with the catalog's legs.
    MOCK — not real data: round prices chosen only so every strike has a premium."""
    chain = {"as_of": "2026-10-23", "strikes": [
        {"strike": float(k), "call": {"close": 50.0}, "put": {"close": 50.0}} for k in (900, 950, 1000, 1050, 1100)]}
    strikes = {"strike": 1000.0, "long_strike": 950.0, "short_strike": 1050.0,
               "long_put_strike": 900.0, "short_put_strike": 950.0, "short_call_strike": 1050.0, "long_call_strike": 1100.0}
    for t in tp.catalog():
        if t["kind"] != "option":
            continue
        kw = {p: strikes[p] for p in t["params"] if p in strikes}
        if t["name"] == "bear_put_spread":
            kw = {"long_strike": 1050.0, "short_strike": 950.0}
        built = getattr(tp, t["name"])(chain, 1000.0, 50, "2099-01-27", **kw)
        assert [(l["side"], l["option_type"]) for l in built["legs"]] == [(l["side"], l["option_type"]) for l in t["legs"]]


def test_route_is_get_only(monkeypatch):
    assert _client(monkeypatch).post(URL, json={}).status_code == 405
