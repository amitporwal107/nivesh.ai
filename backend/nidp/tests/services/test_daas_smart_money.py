"""DaaS /v1/desk/smart-money/* — the Smart Money Movement reads
(nidp/services/daas_api/routers/smart_money.py).

No live Postgres: a fake connection answers each query by the table it reads and records the SQL and
the arguments, so the router's own work runs for real — the window and grain choice, the pinned month
pair, the envelope shaping and the empty answers.

MOCK — not real data. The row values below are synthetic; expected figures are worked out from the
payload, not copied from a screen. The REAL staging figures these shapes were designed against are in
test_reports/smart_money_desk_20261022.md (queried from the warehouse, shown there).

Most of this file guards the constraints that silently return a *plausible but wrong* number rather
than an error. Each was a real mistake made while building this: two independent audits of the same
warehouse disagreed on the breadth counts because one of them omitted the point_in_time filter and so
counted both series at once, and a 1Y flows window answered from the daily table truncates to about
6.7 months and looks entirely reasonable. Those are asserted on the SQL text on purpose: a regression
here produces no exception, just a wrong figure on a screen.
"""
from __future__ import annotations

from datetime import date

import pytest
from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

H = {"X-API-Key": "nvd_t_token"}


class _Conn:
    def __init__(self, db):
        self.db = db
        self.calls = []

    async def fetch(self, q, *a):
        self.calls.append((q, a))
        if "fii_dii_flows" in q:
            return self.db.get("flow_rows", [])
        if "DISTINCT period_end" in q:
            return self.db.get("quarter_rows", [])
        if "v_feed_status" in q:
            return self.db.get("feed_rows", [])
        if "mf_scheme_master" in q:
            return self.db.get("scanner_rows", [])
        if "mf_holdings_deltas" in q:
            return self.db.get("sector_rows", [])
        return []

    async def fetchval(self, q, *a):
        self.calls.append((q, a))
        if "promotion_decisions" in q:
            return self.db.get("promoted", False)
        if "fii_dii_flows" in q:
            return self.db.get("flows_latest")
        if "smart_money_scores_daily" in q:
            return self.db.get("score_latest")
        if "prices_eod" in q:
            return self.db.get("price_latest")
        if q.strip().startswith("SELECT max("):
            return self.db.get("table_max")
        return None

    async def fetchrow(self, q, *a):
        self.calls.append((q, a))
        if "smart_money_scores_daily" in q:
            return self.db.get("breadth_row")
        if "mf_holdings_deltas" in q:
            return self.db.get("pair_row")
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
    from nidp.services.daas_api.routers import smart_money

    def _make(db):
        pool = _Pool(db)

        async def _get_pool():
            return pool
        monkeypatch.setattr(smart_money, "get_pool", _get_pool)
        rec = keys.KeyRecord(key_id="00000000-0000-0000-0000-000000000009", key_prefix="nvd_t", name="t",
                             owner_email="t@nivesh", plan="internal", rate_limit_rpm=1500, daily_quota=None,
                             status="active", expires_at=None)

        async def _resolve(_t):
            return rec
        monkeypatch.setattr(auth, "_resolve", _resolve)

        async def _consume(key_id, *, limit_rpm, daily_quota):
            return ratelimit.LimitDecision(allowed=True, limit_rpm=limit_rpm, remaining_rpm=limit_rpm - 1,
                                           reset_seconds=60, daily_quota=daily_quota, daily_used=1,
                                           daily_remaining=None, reason=None)
        monkeypatch.setattr(ratelimit, "consume", _consume)

        app = FastAPI()

        @app.exception_handler(RequestValidationError)
        async def _validation(_request, exc):
            return JSONResponse(status_code=400, content={"error": {"status": 400, "message": "validation_error"}})

        app.include_router(smart_money.router, prefix="/v1")
        return TestClient(app), pool
    return _make


def _sql(pool):
    return "\n".join(q for q, _ in pool.conn.calls)


# ── the study gate: evidence, never a verdict ────────────────────────────

def test_breadth_serves_no_score_and_says_the_study_is_unvalidated(make_client):
    """No promotion decision exists, so validated_study is false and no score field is served."""
    c, pool = make_client({
        "score_latest": date(2026, 10, 21),
        "promoted": False,
        "breadth_row": {"evaluated": 976, "disclosed_rising": 449, "disclosed_falling": 424,
                        "rising_direct_and_proxy": 417, "rising_direct_only": 32, "proxy_only": 0,
                        "single_amc": 379, "fresh": 963, "ageing": 8, "stale": 5,
                        "disclosure_as_of": "2026-09-01"},
    })
    r = c.get("/v1/desk/smart-money/breadth", headers=H)
    assert r.status_code == 200
    b = r.json()
    assert b["validated_study"] is False
    assert b["metrics"]["evaluated"] == 976
    assert b["metrics"]["single_amc"] == 379
    # The honest date is the disclosure's, weeks behind the compute date.
    assert b["as_of"] == "2026-10-21"
    assert b["disclosure_as_of"] == "2026-09-01"
    flat = r.text.lower()
    for banned in ("accumulation_score", "distribution_score", "shadow_score", "hit_rate", "win_rate"):
        assert banned not in flat, f"{banned} must never be served"


def test_breadth_counts_only_the_point_in_time_series(make_client):
    """Without this filter both series are counted at once and every figure roughly doubles."""
    c, pool = make_client({"score_latest": date(2026, 10, 21), "breadth_row": None, "promoted": False})
    c.get("/v1/desk/smart-money/breadth", headers=H)
    s = _sql(pool)
    assert "point_in_time IS TRUE" in s
    # The look-ahead series must never be read, and neither must the two broken sources.
    assert "v_smart_money_shadow_rank" not in s
    assert "evidence_class" not in s


# ── flows: one grain per window, never mixed ─────────────────────────────

def test_flows_1y_switches_to_monthly_and_spans_twelve_months(make_client):
    """A 1Y window answered from the daily table truncates to ~6.7 months and looks plausible."""
    c, pool = make_client({
        "flows_latest": date(2026, 10, 1),
        "flow_rows": [{"date": "2026-10-01", "fii_net_cr": -48895.0, "dii_net_cr": 52984.0,
                       "fii_cum_cr": -503813.0, "dii_cum_cr": 849222.0}],
    })
    r = c.get("/v1/desk/smart-money/flows", params={"window": "1Y"}, headers=H)
    assert r.status_code == 200
    d = r.json()
    assert d["grain"] == "monthly"
    assert d["start"] == "2025-11-01" and d["as_of"] == "2026-10-01"
    assert d["fii_net_cr"] == -503813.0 and d["dii_net_cr"] == 849222.0
    args = [a for q, a in pool.conn.calls if "fii_dii_flows" in q and len(a) == 3]
    assert args and args[0][0] == "SENSIBULL_MONTHLY"


def test_flows_short_windows_use_the_daily_source(make_client):
    c, pool = make_client({"flows_latest": date(2026, 10, 21), "flow_rows": []})
    for w in ("1M", "3M", "6M"):
        pool.conn.calls.clear()
        r = c.get("/v1/desk/smart-money/flows", params={"window": w}, headers=H)
        assert r.json()["grain"] == "daily"
        args = [a for q, a in pool.conn.calls if "fii_dii_flows" in q and len(a) == 3]
        assert args and args[0][0] == "SENSIBULL", f"{w} must not read the monthly grain"


def test_flows_rejects_an_unknown_window(make_client):
    c, _ = make_client({})
    assert c.get("/v1/desk/smart-money/flows", params={"window": "5Y"}, headers=H).status_code == 400


# ── sectors and scanner: the traps that return a wrong number ────────────

def test_sectors_pins_both_months_of_the_pair(make_client):
    """current_month alone matches several previous_month values, mixing 1-, 4- and 5-month lookbacks."""
    c, pool = make_client({
        "pair_row": {"current_month": date(2026, 9, 1), "previous_month": date(2026, 8, 1)},
        "sector_rows": [{"industry": "Financial Services", "stocks": 98, "stocks_priced": 98,
                         "net_value_cr": 45225.0, "schemes_up": 7000, "schemes_dn": 5849}],
    })
    r = c.get("/v1/desk/smart-money/sectors", headers=H)
    assert r.status_code == 200
    d = r.json()
    assert d["as_of"] == "2026-09-01" and d["previous_month"] == "2026-08-01"
    assert d["rows"][0]["net_value_cr"] == 45225.0
    s = _sql(pool)
    assert "current_month = $3 AND previous_month = $4" in s
    # 55 series values share (symbol, as_of_date); an unfiltered price aggregate double-counts.
    assert "series IN ('EQ', 'BE')" in s
    assert "DUMMYHEG" in s


def test_scanner_dedupes_shareholding_by_value_not_by_source(make_client):
    """shareholding_pattern is not unique on (symbol, period_end); preferring a source by name loses
    40 of 73 computable deltas, because the preferred source holds NULL where the other holds a value."""
    c, pool = make_client({
        "pair_row": {"current_month": date(2026, 9, 1), "previous_month": date(2026, 8, 1)},
        "quarter_rows": [{"period_end": date(2026, 9, 30)}, {"period_end": date(2026, 6, 30)}],
        "price_latest": date(2026, 10, 21),
        "scanner_rows": [{"symbol": "GROWW", "industry": "Financial Services", "mf_shares_pct_chg": 8.60,
                          "net_shares_delta": 1234.0, "schemes_up": 82, "schemes_dn": 16, "amcs_up": 7,
                          "fii_delta_pp": 4.01, "dii_delta_pp": 2.65, "deal_net_qty": -279513109.0,
                          "deal_gross_inr": None, "deal_days": 2, "transfer_days": 0, "deals_checked": True,
                          "deliv_10d": 48.9, "deliv_60d": 52.3, "deliv_vs_base_pp": -3.4}],
    })
    r = c.get("/v1/desk/smart-money/scanner", headers=H)
    assert r.status_code == 200
    d = r.json()
    assert d["quarters"] == {"current": "2026-09-30", "previous": "2026-06-30"}
    assert d["rows"][0]["symbol"] == "GROWW" and d["rows"][0]["deals_checked"] is True
    s = _sql(pool)
    assert "DISTINCT ON (symbol, period_end)" in s
    assert "(fii_pct IS NOT NULL) DESC" in s
    # The netting view, not the raw leg tables: block_deals holds 12 rows in total.
    assert "v_trendlyne_deals_net" in s
    # "Never asked" must be representable, distinct from "no deals".
    assert "trendlyne_deal_fetch_log" in s


def test_scanner_marks_a_symbol_that_was_never_queried_for_deals(make_client):
    """deals_checked false with a null net is 'not checked', not 'no institutional activity'."""
    c, _ = make_client({
        "pair_row": {"current_month": date(2026, 9, 1), "previous_month": date(2026, 8, 1)},
        "quarter_rows": [{"period_end": date(2026, 9, 30)}, {"period_end": date(2026, 6, 30)}],
        "price_latest": date(2026, 10, 21),
        "scanner_rows": [{"symbol": "ABC", "industry": "Power", "mf_shares_pct_chg": 1.0,
                          "net_shares_delta": 5.0, "schemes_up": 1, "schemes_dn": 0, "amcs_up": 1,
                          "fii_delta_pp": None, "dii_delta_pp": None, "deal_net_qty": None,
                          "deal_gross_inr": None, "deal_days": None, "transfer_days": None,
                          "deals_checked": False, "deliv_10d": 30.0, "deliv_60d": 31.0,
                          "deliv_vs_base_pp": -1.0}],
    })
    row = c.get("/v1/desk/smart-money/scanner", headers=H).json()["rows"][0]
    assert row["deals_checked"] is False and row["deal_net_qty"] is None


# ── feeds and the empty answers ──────────────────────────────────────────

def test_feeds_reports_the_data_date_apart_from_the_ingest_date(make_client):
    """The feed view's date is when the loader ran. Printing it as "data as of" overstates freshness
    by weeks on the quarterly feeds."""
    c, _ = make_client({
        "feed_rows": [{"source_name": "NSE_SHAREHOLDING", "effective_status": "OK", "expected_freq": "quarterly",
                       "staleness_days": 0, "staleness_budget_days": 120, "ingested_for": "2026-10-22",
                       "last_success": "2026-10-22"}],
        "table_max": "2026-09-30",
    })
    r = c.get("/v1/desk/smart-money/feeds", headers=H)
    assert r.status_code == 200
    shp = next(x for x in r.json()["rows"] if x["source_name"] == "NSE_SHAREHOLDING")
    assert shp["ingested_for"] == "2026-10-22"
    assert shp["data_as_of"] == "2026-09-30"
    assert shp["ingested_for"] != shp["data_as_of"]
    # A feed with no status row still gets a strip, flagged, rather than disappearing.
    missing = next(x for x in r.json()["rows"] if x["source_name"] == "trendlyne_deals")
    assert missing["status_row_present"] is False


@pytest.mark.parametrize("path,params", [
    ("/v1/desk/smart-money/flows", {"window": "3M"}),
    ("/v1/desk/smart-money/sectors", {}),
    ("/v1/desk/smart-money/breadth", {}),
    ("/v1/desk/smart-money/scanner", {}),
])
def test_no_data_is_200_with_an_empty_answer_never_a_500(make_client, path, params):
    c, _ = make_client({})
    r = c.get(path, headers=H, params=params)
    assert r.status_code == 200
    d = r.json()
    assert d.get("as_of") is None
    assert d.get("rows", []) == [] or d.get("metrics") is None
    assert d["source"] and d["disclosure"]
