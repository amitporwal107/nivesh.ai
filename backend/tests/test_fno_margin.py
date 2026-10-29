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
    assert s["hedge_benefit"] == 1388.75          # 78,908.0625 − 77,519.3125: Kite's initial less its final (spread benefit)
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
    assert order == ["refresh", "calc", "kite"]
    async def boom(db, now=None):
        raise RuntimeError("mongo down")
    monkeypatch.setattr(pt, "refresh_cache", boom)
    assert TestClient(app).post("/api/fno/margin", json=_body()).status_code == 200        # a failed reload does not break the route


def test_hedge_benefit_is_none_without_both_figures():
    """Chart Analysis v2: the hedge benefit is Kite's initial less its final margin, and None when either is missing (never a guess)."""
    assert fm.shape({"final": {"total": 1000.0}}, "2026-10-29")["hedge_benefit"] is None
    assert fm.shape({"initial": {"total": 1000.0}}, "2026-10-29")["hedge_benefit"] is None
    assert fm.shape({"initial": {"total": 1500.5}, "final": {"total": 1000.25}}, "2026-10-29")["hedge_benefit"] == 500.25
