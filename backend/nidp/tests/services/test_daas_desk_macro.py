"""DaaS /v1/desk/macro-calendar* (nidp/services/daas_api/routers/desk_macro.py).

No live Postgres: a fake connection answers each query by the table it reads. MOCK — not real data (rows are shaped like
nidp.macro_releases; the real rows the ingester produces are in test_reports/desk_macro_calendar_backend_20261021.md).

Worked example (hand-checked): US CPI is released 2026-10-14 at 08:30 New York (EDT) = 18:00 IST, after the 15:30 close, so
Nifty's reaction session is the next one, 2026-10-15. Closes 100 (14th), 101 (15th), 102.01 (16th), … 106.06 (20th):
  event day  prev_close 100 → close 101      → +1.00 %
  1 day      102.01 ÷ 101 − 1                → +1.00 %
  1 week     close(+5 sessions) 106.06 ÷ 101 − 1 → +5.01 %
"""
from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from nidp.services.daas_api.routers import desk_macro as dm

H = {"X-API-Key": "nvd_t_token"}
D = date


def rel(code, day, *, country="US", name="CPI inflation YoY", short="CPI", time="08:30", tz="America/New_York", period="Sep 2026",
        previous=None, actual=None, impact="H", unit="%", estimate=None):
    return {"indicator_code": code, "release_date": day, "country": country, "name": name, "short_name": short, "release_time": time,
            "release_tz": tz, "period": period, "previous": previous, "estimate": estimate, "actual": actual, "unit": unit,
            "impact": impact, "source": "FRED", "source_url": "https://fred.stlouisfed.org/release?rid=10"}


# ── pure helpers ─────────────────────────────────────────────────────────────

def test_parse_csv_orders_dedups_and_uppercases():
    assert dm.parse_csv("us, in,US", dm.COUNTRIES, "country") == ["IN", "US"]
    assert dm.parse_csv("l,H", dm.IMPACTS, "impact") == ["H", "L"]


@pytest.mark.parametrize("bad", ["", " ", ",", "UK", "IN,UK"])
def test_parse_csv_rejects(bad):
    with pytest.raises(HTTPException) as e:
        dm.parse_csv(bad, dm.COUNTRIES, "country")
    assert e.value.status_code == 400


@pytest.mark.parametrize("day,t,tz,want", [
    (D(2026, 10, 14), "08:30", "America/New_York", (D(2026, 10, 14), "18:00")),      # EDT: UTC−4
    (D(2026, 12, 10), "08:30", "America/New_York", (D(2026, 12, 10), "19:00")),      # EST: UTC−5
    (D(2026, 12, 9), "14:00", "America/New_York", (D(2026, 12, 10), "00:30")),       # FOMC in winter lands the next IST day
    (D(2026, 10, 28), "14:00", "America/New_York", (D(2026, 10, 28), "23:30")),      # FOMC in summer
    (D(2026, 10, 7), "10:00", "Asia/Kolkata", (D(2026, 10, 7), "10:00")),
    (D(2026, 11, 15), None, None, (D(2026, 11, 15), None)),                          # PLFS: no usual time
])
def test_to_ist(day, t, tz, want):
    assert dm.to_ist(day, t, tz) == want


@pytest.mark.parametrize("day,t,tz,want", [
    (D(2026, 10, 14), "08:30", "America/New_York", D(2026, 10, 15)),   # 18:00 IST: after the close
    (D(2026, 10, 7), "10:00", "Asia/Kolkata", D(2026, 10, 7)),         # RBI 10:00: same session
    (D(2026, 11, 12), "16:00", "Asia/Kolkata", D(2026, 11, 13)),       # India CPI 16:00: after the close
    (D(2026, 12, 9), "14:00", "America/New_York", D(2026, 12, 10)),    # 00:30 IST on the 10th: that day's session
    (D(2026, 11, 15), None, None, D(2026, 11, 15)),
])
def test_reaction_day(day, t, tz, want):
    assert dm.reaction_day(day, t, tz) == want


def test_shape_event_converts_and_never_invents_an_estimate():
    e = dm.shape_event(rel("US_CPI_YOY", D(2026, 10, 14), previous=Decimal("3.4"), actual=Decimal("3.74")))
    assert e["id"] == "2026-10-14|US_CPI_YOY" and e["date"] == D(2026, 10, 14) and e["date_ist"] == D(2026, 10, 14)
    assert (e["time"], e["time_basis"]) == ("18:00", "usual time")
    assert (e["previous"], e["estimate"], e["actual"]) == (3.4, None, 3.74)
    n = dm.shape_event(rel("IN_PLFS", D(2026, 11, 15), country="IN", time=None, tz=None))
    assert (n["time"], n["time_basis"]) == (None, None)


def test_gaps_follow_the_countries_and_say_when_the_month_is_empty():
    us = dm.build_gaps(["US"], 5)
    assert dm.GAP_ESTIMATE in us and dm.GAP_US_LISTED in us and dm.GAP_IN_VALUES not in us and dm.GAP_EMPTY not in us
    both = dm.build_gaps(["IN", "US"], 0)
    assert dm.GAP_IN_VALUES in both and dm.GAP_RBI in both and dm.GAP_IN_LISTED in both and dm.GAP_EMPTY in both


def test_bars_with_prev_derives_the_previous_close_from_the_points_change():
    out = dm.bars_with_prev([{"as_of_date": D(2026, 10, 15), "close_price": Decimal("101"), "pts_change": Decimal("1")},
                             {"as_of_date": D(2026, 10, 16), "close_price": Decimal("102"), "pts_change": None}])
    assert out[0]["prev_close"] == 100.0 and out[1]["prev_close"] is None


# ── routes (fake connection) ─────────────────────────────────────────────────

class _Conn:
    def __init__(self, db):
        self.db, self.calls = db, []

    async def fetch(self, q, *a):
        self.calls.append((q, a))
        for marker, key in (("FROM nidp.macro_releases\n     WHERE release_date", "rel"), ("FROM nidp.macro_releases\n     WHERE indicator_code", "hist"),
                            ("nidp.nse_holidays", "hols"), ("pct_change", "idx_month"), ("pts_change", "bars")):
            if marker in q:
                v = self.db.get(key, [])
                if isinstance(v, Exception):
                    raise v
                return v
        raise AssertionError("unexpected query: " + q[:80])


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

    def _make(db):
        pool = _Pool(db)

        async def _get_pool():
            return pool
        monkeypatch.setattr(dm, "get_pool", _get_pool)
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

        app.include_router(dm.router, prefix="/v1")
        return TestClient(app), pool
    return _make


MONTH_DB = {
    "rel": [rel("US_CPI_YOY", D(2026, 10, 14), previous=Decimal("3.4"), actual=Decimal("3.74")),
            rel("IN_RBI_MPC", D(2026, 10, 7), country="IN", name="RBI interest rate decision", short="RBI rate", time="10:00",
                tz="Asia/Kolkata", period="Oct meeting", actual=Decimal("5.5")),
            rel("US_FOMC", D(2026, 12, 9), name="Fed interest rate decision", short="Fed decision", time="14:00", period="Dec meeting")],
    "hols": [{"holiday_date": D(2026, 10, 20), "description": "Dussehra"}],
    "idx_month": [{"as_of_date": D(2026, 10, 14), "pct_change": Decimal("-0.46")}],
}


def test_calendar_shapes_events_holidays_closes_and_gaps(make_client):
    c, pool = make_client(MONTH_DB)
    r = c.get("/v1/desk/macro-calendar?month=2026-10&country=IN,US&impact=H,M,L", headers=H)
    assert r.status_code == 200
    j = r.json()
    assert j["month"] == "2026-10" and j["count"] == 3 and j["country"] == ["IN", "US"] and j["impact"] == ["H", "M", "L"]
    assert [e["code"] for e in j["events"]] == ["US_CPI_YOY", "IN_RBI_MPC", "US_FOMC"]
    assert all(e["estimate"] is None for e in j["events"])
    assert j["events"][2]["date"] == "2026-12-09" and j["events"][2]["date_ist"] == "2026-12-10" and j["events"][2]["time"] == "00:30"
    assert j["holidays"] == [{"date": "2026-10-20", "description": "Dussehra", "muhurat": False}]
    assert j["index_closes"] == [{"date": "2026-10-14", "pct": -0.46}]
    assert dm.GAP_ESTIMATE in j["gaps"] and dm.GAP_IN_VALUES in j["gaps"] and dm.GAP_EMPTY not in j["gaps"]
    q, args = next(x for x in pool.conn.calls if "macro_releases" in x[0])
    assert args == (D(2026, 10, 1), D(2026, 10, 31), ["IN", "US"], ["H", "M", "L"])


def test_calendar_passes_the_filters_to_the_query(make_client):
    c, pool = make_client({})
    c.get("/v1/desk/macro-calendar?month=2026-11&country=us&impact=h", headers=H)
    _, args = next(x for x in pool.conn.calls if "macro_releases" in x[0])
    assert args[2:] == (["US"], ["H"])


def test_empty_month_says_so_instead_of_an_empty_success(make_client):
    c, _ = make_client({})
    j = c.get("/v1/desk/macro-calendar?month=2027-06", headers=H).json()
    assert j["events"] == [] and dm.GAP_EMPTY in j["gaps"]


def test_missing_table_is_a_named_gap_not_a_500(make_client):
    class UndefinedTableError(Exception):
        pass
    c, _ = make_client({"rel": UndefinedTableError("relation does not exist")})
    r = c.get("/v1/desk/macro-calendar?month=2026-10", headers=H)
    j = r.json()
    assert r.status_code == 200 and j["events"] == [] and dm.GAP_NO_TABLE in j["gaps"]


@pytest.mark.parametrize("qs", ["", "?month=2026-13", "?month=2026-10&country=UK", "?month=2026-10&impact=X", "?month=2026-10&country="])
def test_calendar_bad_params_are_400(make_client, qs):
    c, _ = make_client({})
    assert c.get("/v1/desk/macro-calendar" + qs, headers=H).status_code == 400


def _nifty():
    start = D(2026, 10, 13)
    closes = ["99", "100", "101", "102.01", "103", "104", "105", "106.06", "107"]
    pts = [None, "1", "1", "1.01", "0.99", "1", "1", "1.06", "0.94"]
    return [{"as_of_date": start + timedelta(days=i), "close_price": Decimal(c), "pts_change": Decimal(p) if p else None}
            for i, (c, p) in enumerate(zip(closes, pts))]


def test_history_uses_the_first_session_after_the_release(make_client):
    c, _ = make_client({"hist": [rel("US_CPI_YOY", D(2026, 10, 14), previous=Decimal("3.4"), actual=Decimal("3.74"))], "bars": _nifty()})
    j = c.get("/v1/desk/macro-calendar/history?code=US_CPI_YOY&country=US", headers=H).json()
    assert (j["code"], j["country"], j["n"], j["coverage_from"], j["coverage_to"]) == ("US_CPI_YOY", "US", 1, "2026-10-13", "2026-10-21")
    o = j["occurrences"][0]
    assert (o["date"], o["session"], o["previous"], o["actual"]) == ("2026-10-14", "2026-10-15", 3.4, 3.74)
    assert (o["event_day_pct"], o["d1_pct"], o["w1_pct"]) == (1.0, 1.0, 5.01)
    assert j["stats"]["event_day"] == {"avg": 1.0, "min": 1.0, "max": 1.0}
    assert "not a forecast" in j["basis"] and "2026-10-13" in j["basis"]


def test_history_an_rbi_morning_decision_reacts_the_same_day_and_a_release_before_coverage_is_not_counted(make_client):
    rows = [rel("IN_RBI_MPC", D(2026, 10, 15), country="IN", time="10:00", tz="Asia/Kolkata", period="Oct meeting"),
            rel("IN_RBI_MPC", D(2026, 8, 5), country="IN", time="10:00", tz="Asia/Kolkata", period="Aug meeting")]
    c, _ = make_client({"hist": rows, "bars": _nifty()})
    j = c.get("/v1/desk/macro-calendar/history?code=IN_RBI_MPC", headers=H).json()
    assert j["n"] == 1 and j["occurrences"][0]["session"] == "2026-10-15"      # August is before the first bar: not counted, not padded


def test_history_a_release_with_no_later_bar_has_null_not_zero(make_client):
    c, _ = make_client({"hist": [rel("US_CPI_YOY", D(2026, 10, 20))], "bars": _nifty()})       # reaction session 21st = last bar
    o = c.get("/v1/desk/macro-calendar/history?code=US_CPI_YOY", headers=H).json()["occurrences"][0]
    assert o["event_day_pct"] is not None and o["d1_pct"] is None and o["w1_pct"] is None


def test_history_no_prices_is_empty_with_null_coverage(make_client):
    c, _ = make_client({"hist": [rel("US_CPI_YOY", D(2026, 10, 14))], "bars": []})
    j = c.get("/v1/desk/macro-calendar/history?code=US_CPI_YOY", headers=H).json()
    assert j["n"] == 0 and j["occurrences"] == [] and j["coverage_from"] is None


@pytest.mark.parametrize("qs", ["?code=NOPE", "?code=US_CPI_YOY&country=IN", "?code=IN_CPI&country=US", ""])
def test_history_bad_params_are_400(make_client, qs):
    c, _ = make_client({})
    assert c.get("/v1/desk/macro-calendar/history" + qs, headers=H).status_code == 400
