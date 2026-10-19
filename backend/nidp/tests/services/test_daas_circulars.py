"""DaaS GET /v1/circulars/sebi (services/daas_api/routers/circulars.py).

No live Postgres: a fake connection records each query and answers with rows shaped like nidp.sebi_circulars and
the job_log read (MOCK — not real data). The SQL itself is exercised against Postgres in the report's data test.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

UTC = timezone.utc
H = {"X-API-Key": "nvd_t_token"}


class _Conn:
    def __init__(self, db):
        self.db = db
        self.queries = []

    async def fetchrow(self, q, *a):
        self.queries.append(("fetchrow", q, a))
        return self.db["meta"]

    async def fetch(self, q, *a):
        self.queries.append(("fetch", q, a))
        return self.db["rows"][: a[1]]


class _Pool:
    def __init__(self, db):
        self.conn = _Conn(db)

    def acquire(self):
        conn = self.conn

        class _CM:
            async def __aenter__(self): return conn
            async def __aexit__(self, *a): return False
        return _CM()


def _row(title, url, kind, issued_on, source="sebi_rss"):
    return {"title": title, "url": url, "kind": kind, "issued_on": issued_on, "department": None, "source": source}


ROWS = [
    _row("Synthetic circular A", "https://www.sebi.gov.in/legal/circulars/oct-2026/a_1.html", "circular", date(2026, 10, 13)),
    _row("Synthetic master circular B", "https://www.sebi.gov.in/legal/master-circulars/oct-2026/b_2.html", "master_circular",
         date(2026, 10, 7), "sebi_listing"),
    _row("Synthetic circular C", "https://www.sebi.gov.in/legal/circulars/oct-2026/c_3.html", "circular", None),
]


@pytest.fixture
def make_client(monkeypatch):
    """The circulars router alone, mounted under /v1 as daas_api/app.py mounts it, with the real require_api_key.

    The fake pool is swapped in on the router module's own `pg` reference rather than on nidp.shared.storage.pg, and
    the full DaaS app is not imported here: other DaaS routers bind get_pool by name at import, so importing the app
    under a patched pool would leave them holding this test's fake (and break tests that run later)."""
    from fastapi import FastAPI
    from nidp.services.daas_api import auth, keys, ratelimit
    from nidp.services.daas_api.routers import circulars

    def _make(db):
        pool = _Pool(db)
        async def _get_pool(): return pool
        monkeypatch.setattr(circulars, "pg", SimpleNamespace(get_pool=_get_pool))
        rec = keys.KeyRecord(key_id="00000000-0000-0000-0000-000000000011", key_prefix="nvd_t", name="t", owner_email="t@nivesh",
                             plan="standard", rate_limit_rpm=1500, daily_quota=None, status="active", expires_at=None)
        async def _resolve(_t): return rec
        monkeypatch.setattr(auth, "_resolve", _resolve)
        async def _consume(key_id, *, limit_rpm, daily_quota):
            return ratelimit.LimitDecision(allowed=True, limit_rpm=limit_rpm, remaining_rpm=limit_rpm - 1, reset_seconds=60,
                                           daily_quota=daily_quota, daily_used=1, daily_remaining=None, reason=None)
        monkeypatch.setattr(ratelimit, "consume", _consume)
        app = FastAPI()
        app.include_router(circulars.router, prefix="/v1")
        return TestClient(app), pool
    return _make


def _db(checked_at=datetime(2026, 10, 14, 19, 30, tzinfo=UTC), rows=ROWS):
    return {"meta": {"from_day": date(2026, 9, 15), "checked_at": checked_at}, "rows": list(rows)}


def test_rows_source_and_as_of(make_client):
    c, pool = make_client(_db())
    r = c.get("/v1/circulars/sebi", headers=H)
    assert r.status_code == 200, r.text
    body = r.json()
    # 19:30 UTC on the 14th is 01:00 IST on the 15th: as_of is the IST day of the last successful read.
    assert body["as_of"] == "2026-10-15"
    assert body["checked_at"].startswith("2026-10-14T19:30:00")
    assert body["days"] == 30 and body["from"] == "2026-09-15"
    assert body["count"] == 3
    assert body["source"] == ("SEBI RSS (sebi.gov.in) and SEBI Circulars and Master Circulars listings (sebi.gov.in)"
                              " — circulars and master circulars")
    assert body["rows"][0] == {"title": "Synthetic circular A", "url": "https://www.sebi.gov.in/legal/circulars/oct-2026/a_1.html",
                               "kind": "circular", "issued_on": "2026-10-13", "department": None}
    assert body["rows"][2]["issued_on"] is None
    assert all("source" not in row for row in body["rows"])


def test_defaults_and_parameters_reach_the_sql(make_client):
    c, pool = make_client(_db())
    c.get("/v1/circulars/sebi", headers=H)
    c.get("/v1/circulars/sebi?days=7&limit=2", headers=H)
    (_, meta_q, meta_a), (_, rows_q, rows_a), (_, _, meta_a2), (_, _, rows_a2) = pool.conn.queries
    assert "nidp.job_log" in meta_q and meta_a == (30, "sebi_circulars")
    assert "FROM nidp.sebi_circulars" in rows_q and rows_a == (date(2026, 9, 15), 50)
    assert meta_a2 == (7, "sebi_circulars") and rows_a2 == (date(2026, 9, 15), 2)


def test_rss_only_rows_name_only_the_rss(make_client):
    c, _ = make_client(_db(rows=[ROWS[0]]))
    assert c.get("/v1/circulars/sebi", headers=H).json()["source"] == "SEBI RSS (sebi.gov.in) — circulars and master circulars"


def test_empty_window_is_200_with_no_rows_and_a_never_read_feed_has_null_as_of(make_client):
    c, _ = make_client(_db(checked_at=None, rows=[]))
    r = c.get("/v1/circulars/sebi", headers=H)
    assert r.status_code == 200
    body = r.json()
    assert body["rows"] == [] and body["count"] == 0
    assert body["as_of"] is None and body["checked_at"] is None
    assert body["source"] == "SEBI RSS (sebi.gov.in) — circulars and master circulars"


@pytest.mark.parametrize("qs", ["days=0", "days=366", "limit=0", "limit=201", "days=x"])
def test_out_of_range_parameters_are_rejected(make_client, qs):
    c, pool = make_client(_db())
    assert c.get(f"/v1/circulars/sebi?{qs}", headers=H).status_code in (400, 422)
    assert pool.conn.queries == []


def test_needs_an_api_key(make_client):
    c, _ = make_client(_db())
    assert c.get("/v1/circulars/sebi").status_code == 401
