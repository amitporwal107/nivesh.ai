"""DaaS GET /v1/fno/{symbol}/history — one contract's daily rows, the paper trades' marks (routers/fno.py).

No live Postgres: a fake connection records the query and its arguments and answers with MOCK — not real data rows.
Checks what the router itself does: validation, the instrument-type set per kind, the strike/option filters, order.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

H = {"X-API-Key": "nvd_t_token"}


class _Conn:
    def __init__(self, rows):
        self.rows, self.calls = rows, []

    async def fetch(self, q, *a):
        self.calls.append((q, a))
        return self.rows


@pytest.fixture
def make_client(monkeypatch):
    from nidp.services.daas_api import auth, keys, ratelimit
    from nidp.services.daas_api.routers import fno

    def _make(rows):
        conn = _Conn(rows)

        class _Pool:
            def acquire(self):
                class _CM:
                    async def __aenter__(self_):
                        return conn

                    async def __aexit__(self_, *a):
                        return False
                return _CM()

        async def _get_pool():
            return _Pool()
        monkeypatch.setattr(fno, "get_pool", _get_pool)
        rec = keys.KeyRecord(key_id="00000000-0000-0000-0000-000000000009", key_prefix="nvd_t", name="t", owner_email="t@nivesh",
                             plan="internal", rate_limit_rpm=1500, daily_quota=None, status="active", expires_at=None)

        async def _resolve(_t):
            return rec
        monkeypatch.setattr(auth, "_resolve", _resolve)

        async def _consume(key_id, *, limit_rpm, daily_quota):
            return ratelimit.LimitDecision(allowed=True, limit_rpm=limit_rpm, remaining_rpm=limit_rpm - 1, reset_seconds=60,
                                           daily_quota=daily_quota, daily_used=1, daily_remaining=None, reason=None)
        monkeypatch.setattr(ratelimit, "consume", _consume)
        app = FastAPI()

        @app.exception_handler(RequestValidationError)
        async def _validation(_request, exc):
            return JSONResponse(status_code=400, content={"error": {"status": 400, "message": "validation_error"}})

        app.include_router(fno.router, prefix="/v1")
        return TestClient(app), conn
    return _make


ROW = {"as_of_date": date(2026, 10, 13), "ticker_symbol": "FIXU", "instrument_type": "STO", "expiry_date": date(2026, 10, 27),
       "strike_price": Decimal("1300"), "option_type": "CE", "close_price": Decimal("49"), "settle_price": Decimal("50"),
       "prev_close_price": None, "underlying_price": Decimal("1240"), "open_interest": 10, "traded_volume": 5, "new_board_lot_qty": 250}


def test_an_option_is_read_by_strike_and_type_over_the_option_instrument_types(make_client):
    client, conn = make_client([ROW])
    r = client.get("/v1/fno/fixu/history", headers=H, params={"kind": "option", "expiry": "2026-10-27", "start": "2026-10-12",
                                                               "strike": 1300, "option_type": "CE"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["symbol"] == "FIXU" and body["data"][0]["settle_price"] == 50.0 and body["data"][0]["as_of_date"] == "2026-10-13"
    sql, args = conn.calls[0]
    assert "ORDER BY as_of_date" in sql and "nidp.fno_bhavcopy" in sql
    assert args[0] == "FIXU" and "STO" in args[1] and "STF" not in args[1]
    assert args[2] == date(2026, 10, 27) and args[3] == date(2026, 10, 12) and args[4] == 1300 and args[5] == "CE"


def test_a_future_ignores_strike_filters_and_uses_the_future_types(make_client):
    client, conn = make_client([])
    r = client.get("/v1/fno/FIXU/history", headers=H, params={"kind": "future", "expiry": "2026-10-27", "start": "2026-10-12"})
    assert r.status_code == 200 and r.json()["data"] == []
    _, args = conn.calls[0]
    assert "STF" in args[1] and "STO" not in args[1] and args[4] is None and args[5] is None


@pytest.mark.parametrize("params", [
    {"kind": "swap", "expiry": "2026-10-27", "start": "2026-10-12"},
    {"kind": "option", "expiry": "2026-10-27", "start": "2026-10-12"},
    {"kind": "option", "expiry": "2026-10-27", "start": "2026-10-12", "strike": 1300, "option_type": "XX"},
    {"kind": "future", "expiry": "27-10-2026", "start": "2026-10-12"},
])
def test_bad_requests_are_400_and_never_query(make_client, params):
    client, conn = make_client([])
    assert client.get("/v1/fno/FIXU/history", headers=H, params=params).status_code == 400
    assert conn.calls == []
