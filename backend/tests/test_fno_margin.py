"""Margin and charges from the margin calculator (test_reports/fno_margin_TESTCASES.md). No network: the calculator is a stub."""
from __future__ import annotations

from datetime import date, datetime

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from routes import fno as route
from services import fno_margin as fm

ROWS = [
    {"name": "GODFRYPHLP", "instrument_type": "PE", "expiry": date(2026, 10, 27), "strike": 1700.0, "tradingsymbol": "GODFRYPHLP26OCT1700PE", "lot_size": 275},
    {"name": "GODFRYPHLP", "instrument_type": "PE", "expiry": datetime(2026, 10, 27), "strike": 1600.0, "tradingsymbol": "GODFRYPHLP26OCT1600PE", "lot_size": 275},
    {"name": "GODFRYPHLP", "instrument_type": "FUT", "expiry": date(2026, 10, 27), "strike": 0.0, "tradingsymbol": "GODFRYPHLP26OCTFUT", "lot_size": 275},
    {"name": "OTHER", "instrument_type": "PE", "expiry": date(2026, 10, 27), "strike": 1700.0, "tradingsymbol": "OTHER26OCT1700PE", "lot_size": 10},
]
LEGS = [{"side": "buy", "option_type": "put", "expiry": "2026-10-27", "strike": 1700, "lots": 1}, {"side": "sell", "option_type": "put", "expiry": "2026-10-27", "strike": 1600, "lots": 2}]
RAW = {"initial": {"total": 78908.0625}, "final": {"total": 77519.3125},
       "orders": [{"tradingsymbol": "GODFRYPHLP26OCT1700PE", "charges": {"brokerage": 20, "transaction_tax": 0, "exchange_turnover_charge": 4.65, "sebi_turnover_charge": 0.01, "stamp_duty": 0, "gst": {"total": 4.44}, "total": 29.1}},
                  {"tradingsymbol": "GODFRYPHLP26OCT1600PE", "charges": {"brokerage": 20, "transaction_tax": 5.5, "exchange_turnover_charge": 1.0, "sebi_turnover_charge": 0.0, "stamp_duty": 0, "gst": {"total": 3.8}, "total": 30.3}}]}


class Stub:
    def __init__(self, raw=RAW, raises=None):
        self.raw, self.raises, self.calls, self.inst_calls = raw, raises, [], 0

    def instruments(self):
        self.inst_calls += 1
        return ROWS

    def basket_margins(self, params):
        self.calls.append(params)
        if self.raises:
            raise self.raises
        return self.raw


def test_tc1_legs_map_to_tradingsymbols_with_lot_size_quantity():
    fm._INSTRUMENTS.update({"day": None, "rows": None})
    params, missing = fm.map_legs(fm.instruments_today(Stub()), LEGS, "GODFRYPHLP")
    assert missing == [] and [(p["tradingsymbol"], p["transaction_type"], p["quantity"]) for p in params] == [("GODFRYPHLP26OCT1700PE", "BUY", 275), ("GODFRYPHLP26OCT1600PE", "SELL", 550)]
    assert all(p["exchange"] == "NFO" and p["order_type"] == "MARKET" for p in params)
    out = fm.run(Stub(), "GODFRYPHLP", [{"side": "buy", "option_type": "call", "expiry": "2026-10-27", "strike": 1700, "lots": 1}])
    assert out == {"ok": False, "missing_contracts": ["2026-10-27 1700 CE"]}


def test_tc2_shape_totals_and_nulls():
    s = fm.shape(RAW, "2026-10-24")
    assert s["required_margin"] == 77519.3125 and s["initial_margin"] == 78908.0625 and s["sent_to_broker"] is False
    assert s["hedge_benefit"] is None and s["standalone_margin"] is None     # filled in by run(), which prices each leg alone
    assert s["charges"]["total"] == {"brokerage": 40.0, "stt": 5.5, "exchange": 5.65, "sebi": 0.01, "stamp_duty": 0.0, "gst": 8.24, "total": 59.4}
    empty = fm.shape({}, "2026-10-24")
    assert empty["required_margin"] is None and empty["charges"]["total"]["total"] is None and empty["charges"]["per_order"] == []


def _client(monkeypatch, calc=None, no_session=False):
    fm._INSTRUMENTS.update({"day": None, "rows": None})
    async def _noop():
        return None
    monkeypatch.setattr(route, "_refresh_platform_token", _noop)
    async def fake_user(request: Request):
        return {"user_id": "u1"}
    def make():
        if no_session:
            raise fm.NoSession("no_token")
        return calc
    monkeypatch.setattr(route, "get_current_user", fake_user)
    monkeypatch.setattr(fm, "default_calculator", make)
    app = FastAPI()
    app.include_router(route.router)
    return TestClient(app)


def _body(**kw):
    return {"underlying": "GODFRYPHLP", "legs": LEGS, **kw}


def test_tc3_statuses(monkeypatch):
    stub = Stub()
    c = _client(monkeypatch, stub)
    ok = c.post("/api/fno/margin", json=_body())
    assert ok.status_code == 200 and ok.json()["required_margin"] == 77519.3125 and len(stub.calls[0]) == 2
    assert _client(monkeypatch, no_session=True).post("/api/fno/margin", json=_body()).json()["detail"] == "kite_session_unavailable"
    class TokenException(Exception): ...
    assert _client(monkeypatch, Stub(raises=TokenException("secret provider text"))).post("/api/fno/margin", json=_body()).status_code == 503
    bad = _client(monkeypatch, Stub(raises=RuntimeError("secret provider text"))).post("/api/fno/margin", json=_body())
    assert bad.status_code == 502 and "secret" not in bad.text
    c = _client(monkeypatch, Stub())
    assert c.post("/api/fno/margin", json=_body(legs=[])).status_code == 422
    assert c.post("/api/fno/margin", json=_body(legs=[LEGS[0]] * 11)).status_code == 422
    assert c.post("/api/fno/margin", json=_body(legs=[{**LEGS[0], "lots": 0}])).status_code == 422
    assert c.post("/api/fno/margin", json=_body(legs=[{**LEGS[0], "option_type": "swap"}])).status_code == 422
    nf = c.post("/api/fno/margin", json=_body(legs=[{**LEGS[0], "strike": 999}]))
    assert nf.status_code == 404 and "999" in nf.json()["detail"]


def test_tc4_the_calculator_exposes_no_order_surface():
    assert {n for n in dir(fm.Calculator) if not n.startswith("_")} == {"instruments", "basket_margins"}
    src = open(fm.__file__).read()
    for bad in ("place_order", "modify_order", "cancel_order", "place_gtt", "convert_position", ".orders(", ".positions(", ".holdings(", "invalidate_access_token"):
        assert bad not in src


def test_tc5_instruments_are_read_once_a_day():
    fm._INSTRUMENTS.update({"day": None, "rows": None})
    s = Stub()
    fm.instruments_today(s, date(2026, 10, 24)); fm.instruments_today(s, date(2026, 10, 24))
    assert s.inst_calls == 1
    fm.instruments_today(s, date(2026, 10, 25))
    assert s.inst_calls == 2


def test_the_route_reloads_the_platform_token_before_asking_kite_and_survives_a_failed_reload(monkeypatch):
    """With several workers only the feed leader reloads the token, so every margin call reloads this worker's copy first (a worker holding yesterday's token answered 503 on staging)."""
    import deps
    from services.kite_live_feed import platform_token as pt
    order = []

    async def fake_refresh(db, now=None):
        order.append("refresh")
        return True

    class Calc(Stub):
        def basket_margins(self, params):
            order.append("kite")
            return super().basket_margins(params)

    monkeypatch.setattr(pt, "refresh_cache", fake_refresh)
    monkeypatch.setattr(deps, "db", object())
    fm._INSTRUMENTS.update({"day": None, "rows": None})
    async def fake_user(request: Request):
        return {"user_id": "u1"}
    monkeypatch.setattr(route, "get_current_user", fake_user)
    monkeypatch.setattr(fm, "default_calculator", lambda: (order.append("calc"), Calc())[1])
    app = FastAPI(); app.include_router(route.router)
    assert TestClient(app).post("/api/fno/margin", json=_body()).status_code == 200
    assert order == ["refresh", "calc", "kite", "kite", "kite"]       # the basket, then each leg alone for the hedge benefit
    async def boom(db, now=None):
        raise RuntimeError("mongo down")
    monkeypatch.setattr(pt, "refresh_cache", boom)
    assert TestClient(app).post("/api/fno/margin", json=_body()).status_code == 200        # a failed reload does not break the route


class ByLegs(Stub):
    """MOCK — not real data, in the figures of Zerodha's calculator read on staging on 29 Oct 2026 (TVSMOTOR Nov 4300/4400 CE, 1 lot):
    the basket final 33,267.5 (initial 47,075); the bought leg alone 20,860; the sold leg alone final 101,727.5 (initial 115,535)."""
    def __init__(self, fail_alone=False):
        super().__init__()
        self.fail_alone = fail_alone

    def basket_margins(self, params):
        self.calls.append(params)
        if len(params) == 2:
            return {"initial": {"total": 47075}, "final": {"total": 33267.5}, "orders": []}
        if self.fail_alone:
            raise RuntimeError("kite down")
        return {"initial": {"total": 20860}, "final": {"total": 20860}} if params[0]["transaction_type"] == "BUY" else {"initial": {"total": 115535}, "final": {"total": 101727.5}}


def test_m1_hedge_benefit_is_the_legs_alone_less_the_basket():
    """Chart Analysis v2 (BE-4): hedge benefit = Σ each leg's margin alone − the basket's margin. Kite's own initial − final is NOT it (13,807.5 here,
    the sold call's premium credit, which a single sold option shows too)."""
    fm._INSTRUMENTS.update({"day": None, "rows": None})
    calc = ByLegs()
    out = fm.run(calc, "GODFRYPHLP", LEGS)
    assert out["required_margin"] == 33267.5 and out["standalone_margin"] == 122587.5 and out["hedge_benefit"] == 89320.0
    assert [len(c) for c in calc.calls] == [2, 1, 1]
    assert out["hedge_benefit"] != round(out["initial_margin"] - out["required_margin"], 2)


def test_m2_one_leg_has_no_hedge_and_a_failed_leg_leaves_the_basket():
    fm._INSTRUMENTS.update({"day": None, "rows": None})
    one = Stub()
    out = fm.run(one, "GODFRYPHLP", LEGS[:1])
    assert out["hedge_benefit"] == 0.0 and out["standalone_margin"] == out["required_margin"] and len(one.calls) == 1   # no extra call
    fm._INSTRUMENTS.update({"day": None, "rows": None})
    out = fm.run(ByLegs(fail_alone=True), "GODFRYPHLP", LEGS)
    assert out["ok"] and out["required_margin"] == 33267.5 and out["hedge_benefit"] is None and out["standalone_margin"] is None
    assert fm.hedge_benefit(Stub(), [{}], None) == (None, None)       # no basket figure: nothing to subtract from
