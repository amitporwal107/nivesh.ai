"""DaaS GET /v1/symbols/universe (nidp/services/daas_api/routers/reference.py): the symbol master joined with symbols that have prices.

No live Postgres. MOCK — not real data: the two rows are shaped like the staging warehouse rows read on 2026-10-20
(PCJEWELLER and a price-only symbol with no master row).
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from fastapi import FastAPI
from fastapi.testclient import TestClient

ROWS = [
    {"symbol": "PCJEWELLER", "company_name": "PC Jeweller Limited", "isin": "INE785M01021", "series": "EQ", "sector": "Textiles Apparels & Accessories",
     "industry": "Gems & Jewellery", "last_price_date": date(2026, 10, 19), "fno_eligible": False, "market_cap_cr": Decimal("14711.64")},
    {"symbol": "ABSLLIQUID", "company_name": None, "isin": None, "series": None, "sector": None, "industry": None,
     "last_price_date": date(2026, 10, 19), "fno_eligible": None, "market_cap_cr": None},
]


class _Pool:
    def __init__(self):
        self.queries = []

    def acquire(self):
        pool = self

        class _CM:
            async def __aenter__(self):
                class C:
                    async def fetch(_s, q, *a):
                        pool.queries.append(q)
                        return ROWS
                return C()

            async def __aexit__(self, *a):
                return False
        return _CM()


def _client(monkeypatch):
    from nidp.services.daas_api import auth, keys, ratelimit
    from nidp.services.daas_api.routers import reference
    pool = _Pool()

    async def _get_pool():
        return pool
    monkeypatch.setattr(reference, "get_pool", _get_pool)
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
    app.include_router(reference.router, prefix="/v1")
    return TestClient(app), pool


def test_universe_lists_symbols_with_prices_and_flags(monkeypatch):
    c, pool = _client(monkeypatch)
    r = c.get("/v1/symbols/universe", headers={"X-API-Key": "nvd_t_token"})
    assert r.status_code == 200
    body = r.json()
    assert body["count"] == 2 and [d["symbol"] for d in body["data"]] == ["PCJEWELLER", "ABSLLIQUID"]
    first = body["data"][0]
    assert first["isin"] == "INE785M01021" and first["last_price_date"] == "2026-10-19" and first["fno_eligible"] is False
    assert body["data"][1]["company_name"] is None            # a price-only symbol: no invented name
    assert len(pool.queries) == 1 and "FULL JOIN px" in pool.queries[0] and not any(w in pool.queries[0].upper() for w in ("INSERT", "UPDATE", "DELETE"))


def test_universe_is_not_shadowed_by_the_symbol_detail_route(monkeypatch):
    c, _ = _client(monkeypatch)
    r = c.get("/v1/symbols/universe", headers={"X-API-Key": "nvd_t_token"})
    assert "data" in r.json() and r.json().get("error") != "not_found"


def test_universe_needs_a_key(monkeypatch):
    c, _ = _client(monkeypatch)
    assert c.get("/v1/symbols/universe").status_code in (401, 403)
