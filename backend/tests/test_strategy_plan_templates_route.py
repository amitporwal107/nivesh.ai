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
    assert b["calculation_version"] == CALCULATION_VERSION == "payoff-v2"   # desk cost card since 2026-10-27
    assert b["count"] == len(b["templates"]) == len(tp.CATALOG)
    for t in b["templates"]:
        assert set(t) >= {"name", "label", "kind", "legs", "params", "calculation_version"}
        assert t["kind"] in ("option", "future", "cash")
        assert t["legs"] and all(l["side"] in ("buy", "sell") for l in t["legs"])
        assert t["calculation_version"] == "payoff-v2"
        assert t["risk"]["max_loss"] in ("defined", "to_zero", "unbounded") and t["risk"]["note"]
        assert all(l["instrument"] in ("option", "future", "cash") for l in t["legs"])


def test_catalog_matches_the_template_functions():
    assert {e["name"] for e in tp.CATALOG} == _public_template_functions()


def test_params_come_from_each_signature_and_strike_params_exist():
    for t in tp.catalog():
        sig = inspect.signature(getattr(tp, t["name"])).parameters
        assert set(t["params"]) <= set(sig)
        assert not set(t["params"]) & {"chain", "spot", "lot_size", "expiry", "underlying", "today", "costs"}
        for leg in t["legs"]:
            if leg["instrument"] == "option":
                assert t["kind"] == "option"
                assert leg["option_type"] in ("call", "put") and leg["strike_param"] in t["params"]
            else:
                assert leg["option_type"] is None and leg["strike_param"] is None
        if t["kind"] != "option":
            assert all(leg["instrument"] == t["kind"] for leg in t["legs"])


def test_the_owners_first_wave_is_in_the_catalog_with_its_risk_shape():
    """docs/AUTONOMOUS_PAPER_AGENTS_WORKFLOW.md §2/§10: covered call, bull put / bear call credit spreads, iron condor,
    protective put / collar. Each has a defined maximum loss except the covered call, whose risk is the shares'."""
    risk = {t["name"]: t["risk"]["max_loss"] for t in tp.catalog()}
    assert {n: risk[n] for n in ("covered_call", "bull_put_spread", "bear_call_spread", "iron_condor", "protective_put",
                                 "collar")} == {"covered_call": "to_zero", "bull_put_spread": "defined",
                                                "bear_call_spread": "defined", "iron_condor": "defined",
                                                "protective_put": "defined", "collar": "defined"}
    legs = {t["name"]: [(l["instrument"], l["side"], l["option_type"]) for l in t["legs"]] for t in tp.catalog()}
    assert legs["covered_call"] == [("cash", "buy", None), ("option", "sell", "call")]
    assert legs["protective_put"] == [("cash", "buy", None), ("option", "buy", "put")]
    assert legs["collar"] == [("cash", "buy", None), ("option", "buy", "put"), ("option", "sell", "call")]
    assert legs["bull_put_spread"] == [("option", "buy", "put"), ("option", "sell", "put")]
    assert legs["bear_call_spread"] == [("option", "sell", "call"), ("option", "buy", "call")]
    assert not any(l[1] == "sell" and l[0] == "option" for l in legs["long_call"] + legs["long_put"])


def test_option_leg_sides_match_what_the_function_builds():
    """Build each option template on a small chain and compare the legs it returns with the catalog's legs.
    MOCK — not real data: round prices chosen only so every strike has a premium."""
    chain = {"as_of": "2026-10-23", "strikes": [
        {"strike": float(k), "call": {"close": 50.0}, "put": {"close": 50.0}} for k in (900, 950, 1000, 1050, 1100)]}
    strikes = {"strike": 1000.0, "long_strike": 950.0, "short_strike": 1050.0,
               "long_put_strike": 900.0, "short_put_strike": 950.0, "short_call_strike": 1050.0, "long_call_strike": 1100.0,
               "put_strike": 950.0, "call_strike": 1050.0}
    # templates whose strike order differs from a debit call spread's (long below short)
    flipped = {"bear_put_spread": {"long_strike": 1050.0, "short_strike": 950.0},
               "bear_call_spread": {"short_strike": 950.0, "long_strike": 1050.0},
               "bull_put_spread": {"long_strike": 950.0, "short_strike": 1050.0}}
    for t in tp.catalog():
        if t["kind"] != "option":
            continue
        kw = flipped.get(t["name"]) or {p: strikes[p] for p in t["params"] if p in strikes}
        built = getattr(tp, t["name"])(chain, 1000.0, 50, "2099-01-27", **kw)
        assert [(l["kind"], l["side"], l.get("option_type")) for l in built["legs"]] == \
            [(l["instrument"], l["side"], l["option_type"]) for l in t["legs"]]
        for leg, entry in zip(built["legs"], t["legs"]):
            if entry["strike_param"]:
                assert leg["strike"] == kw[entry["strike_param"]]


def test_route_is_get_only(monkeypatch):
    assert _client(monkeypatch).post(URL, json={}).status_code == 405
