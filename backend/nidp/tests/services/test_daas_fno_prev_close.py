"""DaaS /v1/fno/{symbol} sends each contract's previous close (PRD 17.2 #8).

No live Postgres: a fake connection records the SQL and returns rows. MOCK - not real data, except the column
list, which was read from information_schema.columns for nidp.fno_bhavcopy on the staging warehouse 2026-10-20
(prev_close_price numeric is a column of that table; 4011 of 4011 IDF rows and 160839 of 160839 STF rows on
2026-10-19 had it filled).
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from fastapi import FastAPI
from fastapi.testclient import TestClient

H = {"X-API-Key": "nvd_t_token"}


class _Conn:
    def __init__(self, rows):
        self.rows, self.queries = rows, []

    async def fetchrow(self, q, *a):
        return {"d": date(2026, 10, 19)}

    async def fetch(self, q, *a):
        self.queries.append(q)
        return self.rows


def _client(monkeypatch, rows):
    from nidp.services.daas_api import auth, keys, ratelimit
    from nidp.services.daas_api.routers import fno

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
    app.include_router(fno.router, prefix="/v1")
    return TestClient(app), conn


def test_fno_for_symbol_selects_and_returns_prev_close_price(monkeypatch):
    row = {"as_of_date": date(2026, 10, 19), "ticker_symbol": "TESTCO", "instrument_type": "STF", "expiry_date": date(2026, 10, 27),
           "strike_price": None, "option_type": None, "close_price": Decimal("108.70"), "settle_price": Decimal("108.75"),
           "prev_close_price": Decimal("107.00"), "open_interest": 5000, "change_in_oi": 120}
    c, conn = _client(monkeypatch, [row])
    r = c.get("/v1/fno/TESTCO", headers=H, params={"instrument_type": "STF"})
    assert r.status_code == 200
    assert "prev_close_price" in conn.queries[0]
    assert float(r.json()["data"][0]["prev_close_price"]) == 107.0
