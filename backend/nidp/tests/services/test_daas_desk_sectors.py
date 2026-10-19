"""DaaS /v1/desk — breadth within a sector and a sector's constituents (nidp/services/daas_api/routers/desk_market.py).

    GET /v1/desk/sector-returns        `in_sector_breadth.indices` for every sector index that has a constituent list
    GET /v1/desk/sector-constituents   one index's latest list, each stock's move on the index's latest close day

No live Postgres: a fake connection answers each query by the table it reads and records the arguments. MOCK — not
real data, except the Nifty Bank rows, which were copied from the staging warehouse on 2026-10-14 (read-only check):
6 of the 14 constituents closed above their previous close and 8 below.
"""
from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

import pytest
from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

H = {"X-API-Key": "nvd_t_token"}
DAY = date(2026, 10, 14)
LIST_DAY = date(2026, 10, 13)

# nidp.index_constituents ⨝ nidp.prices_eod for Nifty Bank on 2026-10-14 (staging, read-only, 2026-10-14):
# symbol, close, prev_close
BANK = [
    ("AUBANK", "999.5", "991.5"), ("AXISBANK", "1264.6", "1268.4"), ("BANKBARODA", "229.0", "238.43"),
    ("CANBK", "124.76", "120.44"), ("FEDERALBNK", "330.0", "329.5"), ("HDFCBANK", "710.7", "714.0"),
    ("ICICIBANK", "1338.6", "1360.2"), ("IDFCFIRSTB", "78.74", "78.83"), ("INDUSINDBK", "866.0", "877.35"),
    ("KOTAKBANK", "438.05", "439.0"), ("PNB", "118.5", "116.55"), ("SBIN", "954.9", "957.0"),
    ("UNIONBANK", "174.0", "172.22"), ("YESBANK", "21.2", "20.85"),
]


def _member(index, symbol, close, prev, on=DAY):
    return {"index_name": index, "on_date": on, "list_date": LIST_DAY, "symbol": symbol, "company_name": f"{symbol} Ltd",
            "industry": "Financial Services", "weight_pct": None,
            "close_price": Decimal(close) if close is not None else None,
            "prev_close": Decimal(prev) if prev is not None else None}


BANK_ROWS = [_member("Nifty Bank", s, c, p) for s, c, p in BANK]
# Hand-made: an unchanged close, and a constituent with no bar that day (no price — never "unchanged").
IT_ROWS = [_member("Nifty IT", "TCS", "3000", "2950"), _member("Nifty IT", "INFY", "1500", "1500"),
           _member("Nifty IT", "WIPRO", None, None)]


class _Conn:
    def __init__(self, db):
        self.db, self.calls = db, []

    async def fetch(self, q, *a):
        self.calls.append((q, a))
        if "nidp.index_constituents" in q:
            names = set(a[0])
            return [r for r in self.db.get("members", []) if r["index_name"] in names]
        if "nidp.index_eod" in q:
            return self.db.get("index_rows", [])
        return []

    async def fetchval(self, q, *a):
        self.calls.append((q, a))
        if "nidp.index_eod" in q:
            return self.db.get("latest", {}).get(a[0])
        return None


class _Pool:
    def __init__(self, db):
        self.conn = _Conn(db)

    def acquire(self):
        conn = self.conn

        class _CM:
            async def __aenter__(self):
                return conn

            async def __aexit__(self, *a):
                return False
        return _CM()


@pytest.fixture
def make_client(monkeypatch):
    from nidp.services.daas_api import auth, keys, ratelimit
    from nidp.services.daas_api.routers import desk_market

    def _make(db):
        pool = _Pool(db)

        async def _get_pool():
            return pool
        monkeypatch.setattr(desk_market, "get_pool", _get_pool)
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

        app.include_router(desk_market.router, prefix="/v1")
        return TestClient(app), pool
    return _make


def _series(name, closes, last=DAY):
    return [{"index_name": name, "as_of_date": last - timedelta(days=i), "close_price": Decimal(str(c))} for i, c in enumerate(closes)]


# ── breadth within each sector on /sector-returns ────────────────────────────

def test_sector_returns_adds_breadth_for_the_indices_with_a_list(make_client):
    db = {"index_rows": _series("Nifty Bank", [56000, 55800]) + _series("Nifty IT", [35000, 34500])
          + _series("Nifty Auto", [24000, 23900]),
          "members": BANK_ROWS + IT_ROWS}
    c, pool = make_client(db)
    d = c.get("/v1/desk/sector-returns", headers=H).json()
    isb = d["in_sector_breadth"]
    assert isb["source"] == "NSE index lists (nidp.index_constituents) with NSE bhavcopy closes (nidp.prices_eod)"
    assert "never counted as unchanged" in isb["rule"]
    # worked out from BANK: advances AUBANK, CANBK, FEDERALBNK, PNB, UNIONBANK, YESBANK; the other 8 declined
    adv = sum(1 for _, c_, p in BANK if Decimal(c_) > Decimal(p))
    dec = sum(1 for _, c_, p in BANK if Decimal(c_) < Decimal(p))
    assert (adv, dec) == (6, 8)
    assert isb["indices"]["Nifty Bank"] == {"list_date": "2026-10-13", "date": "2026-10-14", "members": 14,
                                            "advances": adv, "declines": dec, "unchanged": 0, "no_price": 0}
    assert isb["indices"]["Nifty IT"] == {"list_date": "2026-10-13", "date": "2026-10-14", "members": 3,
                                          "advances": 1, "declines": 0, "unchanged": 1, "no_price": 1}
    # an index without a list has no breadth: absent, never zero
    assert "Nifty Auto" not in isb["indices"]
    # each index is priced on its own latest close day; only indices with closes are asked for
    q, args = pool.conn.calls[1]
    assert "nidp.index_constituents" in q and "nidp.prices_eod" in q
    assert args == (["Nifty Auto", "Nifty Bank", "Nifty IT"], [DAY, DAY, DAY])


def test_sector_returns_with_no_closes_asks_for_no_constituents(make_client):
    c, pool = make_client({})
    d = c.get("/v1/desk/sector-returns", headers=H).json()
    assert d["in_sector_breadth"]["indices"] == {} and len(pool.conn.calls) == 1


# ── /sector-constituents ─────────────────────────────────────────────────────

def test_constituents_of_an_index_with_a_list(make_client):
    c, pool = make_client({"latest": {"Nifty IT": DAY}, "members": IT_ROWS})
    r = c.get("/v1/desk/sector-constituents", params={"index": "nifty it"}, headers=H)
    assert r.status_code == 200, r.text
    d = r.json()
    assert (d["index"], d["sector"], d["available"], d["reason"]) == ("Nifty IT", "IT", True, None)
    assert (d["list_date"], d["date"], d["count"]) == ("2026-10-13", "2026-10-14", 3)
    assert d["breadth"] == {"members": 3, "advances": 1, "declines": 0, "unchanged": 1, "no_price": 1}
    tcs, infy, wipro = d["rows"]
    # (3000 / 2950 − 1) × 100 = 1.69 %
    assert tcs == {"symbol": "TCS", "company_name": "TCS Ltd", "industry": "Financial Services", "weight_pct": None,
                   "close": 3000.0, "prev_close": 2950.0, "change_pct": 1.69, "move": "advance"}
    assert (infy["change_pct"], infy["move"]) == (0.0, "unchanged")
    assert (wipro["close"], wipro["change_pct"], wipro["move"]) == (None, None, None)
    q, args = pool.conn.calls[-1]
    assert args == (["Nifty IT"], [DAY])


def test_constituents_of_an_index_without_a_list_says_so(make_client):
    c, _ = make_client({"latest": {"Nifty Auto": DAY}, "members": []})
    d = c.get("/v1/desk/sector-constituents?index=Nifty%20Auto", headers=H).json()
    assert (d["available"], d["count"], d["rows"], d["breadth"]) == (False, 0, [], None)
    assert d["reason"] == "no constituent list for Nifty Auto in nidp.index_constituents" and d["date"] == "2026-10-14"


def test_constituents_of_an_index_that_is_not_a_desk_sector(make_client):
    c, pool = make_client({})
    d = c.get("/v1/desk/sector-constituents?index=Nifty%20500", headers=H).json()
    assert d["available"] is False and d["reason"] == "not one of the desk's sector indices" and pool.conn.calls == []


@pytest.mark.parametrize("qs", ["", "index=ab", "index=Nifty%3BDROP", "index=" + "A" * 61])
def test_constituents_validates_the_index(make_client, qs):
    c, pool = make_client({})
    assert c.get(f"/v1/desk/sector-constituents?{qs}", headers=H).status_code == 400 and pool.conn.calls == []


def test_constituents_needs_an_api_key(make_client):
    c, pool = make_client({})
    assert c.get("/v1/desk/sector-constituents?index=Nifty%20IT").status_code == 401 and pool.conn.calls == []
