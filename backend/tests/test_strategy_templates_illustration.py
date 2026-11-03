"""GET /api/desk/strategy/templates for Trade Desk › Strategy Lab › Build a trade, step 1 (the template cards): each
template's market intent, its intent-chip tags, its desk direction, and its mini payoff, which must be the template's OWN
payoff (its function in services/strategy_plan/templates.py priced by the payoff engine), never drawn art.

No fixture data: the illustration chain is Black-76 at 20% volatility (services/option_pricing.py), so the shapes are
checked by their kinks and signs, which follow from the strikes alone, and the long call's loss is checked against the
Black-76 premium worked out here independently.
"""
from __future__ import annotations

import inspect
import math

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

import routes.strategy_plan as route
from services import option_pricing as op
from services.strategy_plan import templates as tp

TAGS = {"bullish", "bearish", "neutral", "income", "hedging", "volatility"}


def _by_name():
    return {t["name"]: t for t in tp.catalog()}


def _at(t, price):
    pts = {round(x, 6): y for x, y in t["illustration"]["points"]}
    return pts[round(price, 6)]


def test_every_template_has_an_intent_tags_and_a_direction():
    for t in tp.catalog():
        assert isinstance(t["intent"], str) and 0 < len(t["intent"]) <= 60, t["name"]
        assert t["tags"] and set(t["tags"]) <= TAGS, t["name"]
        assert t["direction"] in ("bullish", "bearish", "neutral"), t["name"]
    got = _by_name()
    assert got["bull_put_spread"]["intent"] == "Mildly bullish, collect premium"
    assert got["covered_call"]["intent"] == "Hold the stock, earn premium"
    assert got["iron_condor"]["tags"] == ["neutral", "income"] and got["iron_condor"]["direction"] == "neutral"
    assert got["protective_put"]["tags"] == ["bullish", "hedging"]
    # No volatility template is in the catalog (no straddle or strangle): the tag is not claimed.
    assert not any("volatility" in t["tags"] for t in tp.catalog())


def test_every_template_has_an_illustration_from_its_own_function():
    for t in tp.catalog():
        ill = t["illustration"]
        assert ill is not None, (t["name"], t.get("illustration_error"))
        assert "illustration_error" not in t
        sig = inspect.signature(getattr(tp, t["name"])).parameters
        assert set(ill["params"]) <= set(sig), t["name"]
        assert ill["spot"] == 100.0 and len(ill["points"]) == 41
        xs = [x for x, _ in ill["points"]]
        assert xs[0] == 70.0 and xs[-1] == 130.0 and xs == sorted(xs)
        assert "Black-76" in ill["basis"] and "not a price or a forecast" in ill["basis"]


def test_the_shapes_follow_from_the_strikes():
    t = _by_name()
    bcs = t["bull_call_spread"]
    assert _at(bcs, 79.0) < 0 < _at(bcs, 121.0)
    assert _at(bcs, 112.0) == _at(bcs, 130.0) == bcs["illustration"]["max_profit"]     # flat above the 110 short call
    assert _at(bcs, 70.0) == _at(bcs, 100.0) == bcs["illustration"]["max_loss"]         # flat below the 100 long call
    bps = t["bear_put_spread"]
    assert _at(bps, 121.0) < 0 < _at(bps, 79.0)
    assert _at(bps, 70.0) == _at(bps, 88.0) == bps["illustration"]["max_profit"]
    ic = t["iron_condor"]
    assert _at(ic, 100.0) > 0 > _at(ic, 70.0) and _at(ic, 130.0) < 0
    assert len(ic["illustration"]["breakevens"]) == 2
    cc = t["covered_call"]
    assert _at(cc, 112.0) == _at(cc, 130.0) == cc["illustration"]["max_profit"]         # capped above the 110 call
    assert cc["illustration"]["loss_unbounded"] is False and cc["illustration"]["max_loss"] < -90   # the shares' risk
    sf = t["short_future"]
    assert sf["illustration"]["loss_unbounded"] is True and _at(sf, 130.0) == -30.0


def test_the_long_call_loses_exactly_its_black_76_premium():
    t = op.year_fraction(30)
    fwd = 100.0 * math.exp(op.RISK_FREE_RATE * t)
    premium = round(op.price("CE", fwd, 100.0, t, 0.20, op.RISK_FREE_RATE), 4)
    lc = _by_name()["long_call"]
    assert _at(lc, 70.0) == _at(lc, 100.0) == round(-premium, 2) == lc["illustration"]["max_loss"]
    assert lc["illustration"]["profit_unbounded"] is True and lc["illustration"]["max_profit"] is None


def test_the_catalog_is_the_same_on_every_call_and_a_copy():
    a, b = tp.catalog(), tp.catalog()
    assert a == b
    a[0]["illustration"]["points"][0][1] = 999.0
    a[0]["tags"].append("volatility")
    assert tp.catalog() == b                                        # a caller cannot change the cached curve


def test_the_route_answers_the_new_fields(monkeypatch):
    async def fake_user(request: Request):
        return {"user_id": "u1"}
    monkeypatch.setattr(route, "get_current_user", fake_user)
    app = FastAPI()
    app.include_router(route.router)
    res = TestClient(app).get("/api/desk/strategy/templates")
    assert res.status_code == 200
    body = res.json()
    assert body["count"] == 13
    for t in body["templates"]:
        assert {"intent", "tags", "direction", "illustration"} <= set(t)
        assert len(t["illustration"]["points"]) == 41
