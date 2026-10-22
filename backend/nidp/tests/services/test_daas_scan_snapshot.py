"""DaaS GET /v1/features/scan-snapshot — the opportunity scanner's one-row-per-stock snapshot
(nidp/services/daas_api/routers/features.py).

No live Postgres: a fake connection returns rows in the shape the SQL selects (MOCK — not real data) and records the
query, so the router's own work runs for real: the traded value (₹ crore, only with all 20 sessions), relative volume,
the as-of dates and the 503 on an empty store. The SQL itself was run read-only on the staging warehouse on 2026-10-14
(2,469 rows, every one priced on the features date, 2,452 with a 20-session traded value).

Worked examples
  traded value  mean(close × volume) = 1,234,567,890 ₹ → / 1e7 = 123.4567890 → 123.46 ₹ crore a day
  RVOL          volume 3,000,000 ÷ avg_volume_20 1,200,000 = 2.50
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

H = {"X-API-Key": "nvd_t_token"}
DAY = date(2026, 10, 12)


def _row(sym, **over):
    r = {"symbol": sym, "as_of_date": DAY, "sector": None, "industry": "Information Technology",
         "close": Decimal("100.00"), "sma50": Decimal("95.0"), "sma50_slope": Decimal("0.12"), "sma200": None,
         "rsi14": Decimal("61.2"), "macd_hist": Decimal("0.4"), "return_5d_pct": Decimal("3.1"),
         "return_20d_pct": Decimal("7.5"), "return_60d_pct": Decimal("12.0"), "vol_z20": Decimal("2.4"),
         "avg_volume_20": Decimal("1200000"), "atr_pct": Decimal("2.6"), "volatility_1y_pct": Decimal("28.0"),
         "beta_1y": Decimal("1.1"), "max_drawdown_1y_pct": Decimal("-18.0"), "market_cap_cr": None, "market_cap_bucket": None,
         "price_date": DAY, "price_series": "EQ", "open_price": Decimal("99.0"), "high_price": Decimal("101.0"),
         "low_price": Decimal("98.5"), "close_price": Decimal("100.00"), "prev_close": Decimal("98.00"), "volume": 3_000_000,
         "traded_sessions": 20, "valued_sessions": 20, "avg_traded_value": Decimal("1234567890"),
         "has_reference": True, "series": "EQ", "price_band_pct": Decimal("20.00"), "band_raw": "20", "fno_eligible": False,
         "is_etf": False, "reference_as_of": DAY, "last_results_date": date(2026, 10, 9), "next_results_date": None}
    r.update(over)
    return r


class _Conn:
    def __init__(self, rows):
        self.rows, self.calls = rows, []

    async def fetch(self, q, *a):
        self.calls.append((q, a))
        return self.rows


class _Pool:
    def __init__(self, rows):
        self.conn = _Conn(rows)

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
    from nidp.services.daas_api.routers import features

    def _make(rows):
        pool = _Pool(rows)

        async def _get_pool():
            return pool
        monkeypatch.setattr(features, "get_pool", _get_pool)
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
        app.include_router(features.router, prefix="/v1")
        return TestClient(app), pool
    return _make


def test_snapshot_rows_traded_value_rvol_and_dates(make_client):
    c, pool = make_client([_row("AAA"), _row("SHORT", traded_sessions=19, valued_sessions=19),
                           _row("NOVOL", valued_sessions=19, volume=None)])
    r = c.get("/v1/features/scan-snapshot", headers=H)
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["as_of"] == "2026-10-12" and d["reference_as_of"] == "2026-10-12" and d["sessions"] == 20 and d["count"] == 3
    assert "nidp.stock_features_daily" in d["source"] and "nidp.security_reference_daily" in d["source"]
    a, short, novol = d["rows"]
    assert a["traded_value_cr_20d"] == 123.46 and a["rvol20"] == 2.5
    assert short["traded_value_cr_20d"] is None                     # 19 sessions → none, never a short mean
    assert novol["traded_value_cr_20d"] is None and novol["rvol20"] is None
    assert a["price_band_pct"] == 20.0 and a["fno_eligible"] is False and a["has_reference"] is True
    assert a["last_results_date"] == "2026-10-09" and a["next_results_date"] is None
    for k in ("traded_sessions", "valued_sessions", "avg_traded_value"):
        assert k not in a
    sql, args = pool.conn.calls[0]
    assert args == (20,)
    # Price and indicators are the same day (PRD §5.6): the bhavcopy row is joined on the features date.
    assert "p.as_of_date = f.as_of_date" in sql
    assert "quarterly_results" in sql and "nidp.security_reference_daily" in sql


def test_an_empty_feature_store_is_503(make_client):
    c, _ = make_client([])
    r = c.get("/v1/features/scan-snapshot", headers=H)
    assert r.status_code == 503


def test_snapshot_needs_a_key(make_client):
    c, _ = make_client([_row("AAA")])
    assert c.get("/v1/features/scan-snapshot").status_code in (401, 403)
