"""DaaS /v1/desk/events-calendar* (nidp/services/daas_api/routers/desk_events.py).

No live Postgres: a fake connection answers each query by the table it reads. MOCK — not real data, except fixtures
marked "staging 2026-10-21", copied from the warehouse the same day (rows checked in the data test of
test_reports/desk_events_calendar_backend_20261021.md).

Worked examples (hand-checked)
  event day   prev_close 100.00, close 104.50  → +4.50 %
  1 day       close(t) 104.50, close(t+1) 100.32 → 100.32 / 104.50 − 1 = −4.00 %
  1 week      close(t) 104.50, close(t+5) 109.725 → +5.00 %
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from nidp.services.daas_api.routers import desk_events as de

H = {"X-API-Key": "nvd_t_token"}
D = date


def cal(sym, typ, day, period=None, name=None, at=None):
    return {"symbol": sym, "company_name": name or sym, "event_type": typ, "event_date": day, "period": period, "intimated_at": at}


def act(sym, typ, ex, rec=None, **kw):
    base = {"symbol": sym, "action_type": typ, "action_subtype": None, "purpose": None, "ratio": None,
            "face_value_pre": None, "face_value_post": None, "dividend_amount": None, "ex_date": ex, "record_date": rec}
    base.update(kw)
    return base


# ── pure helpers ─────────────────────────────────────────────────────────────

@pytest.mark.parametrize("month,lo,hi", [
    ("2026-10", D(2026, 10, 1), D(2026, 10, 31)),
    ("2026-12", D(2026, 12, 1), D(2026, 12, 31)),
    ("2026-02", D(2026, 2, 1), D(2026, 2, 28)),
    ("2028-02", D(2028, 2, 1), D(2028, 2, 29)),
])
def test_month_bounds(month, lo, hi):
    assert de.month_bounds(month) == (lo, hi)


@pytest.mark.parametrize("bad", ["2026-13", "2026-00", "abc", "2026-1", "", "1999-05", "2026-10-01"])
def test_month_bounds_rejects(bad):
    with pytest.raises(HTTPException) as e:
        de.month_bounds(bad)
    assert e.value.status_code == 400


def bars(closes, prevs=None, start=D(2026, 1, 5)):
    """Daily bars one calendar day apart (the helper counts bars, not days)."""
    out = []
    for i, c in enumerate(closes):
        out.append({"as_of_date": start + timedelta(days=i), "close_price": Decimal(str(c)),
                    "prev_close": Decimal(str(prevs[i])) if prevs and prevs[i] is not None else None})
    return out


def test_reaction_hand_example():
    b = bars([100, 104.5, 100.32, 100, 100, 100, 109.725], prevs=[None, 100, 104.5, 100.32, 100, 100, 100])
    r = de.reaction(b, D(2026, 1, 6))
    assert r == {"session": D(2026, 1, 6), "event_day_pct": 4.5, "d1_pct": -4.0, "w1_pct": 5.0}


def test_reaction_uses_previous_bar_when_prev_close_missing():
    b = bars([100, 110, 121])
    assert de.reaction(b, D(2026, 1, 6))["event_day_pct"] == 10.0


def test_reaction_non_session_date_uses_next_session_and_missing_later_bars_are_null_not_zero():
    b = [{"as_of_date": D(2026, 1, 5), "close_price": 100, "prev_close": 99},
         {"as_of_date": D(2026, 1, 8), "close_price": 102, "prev_close": 100}]      # 6th and 7th are a gap
    r = de.reaction(b, D(2026, 1, 6))
    assert r["session"] == D(2026, 1, 8) and r["event_day_pct"] == 2.0 and r["d1_pct"] is None and r["w1_pct"] is None


def test_reaction_outside_coverage_is_none():
    b = bars([100, 101, 102])
    assert de.reaction(b, D(2025, 12, 1)) is None            # before the first price
    assert de.reaction(b, D(2026, 3, 1)) is None             # after the last
    assert de.reaction([], D(2026, 1, 6)) is None


def test_stat_ignores_nulls_and_is_null_when_empty():
    assert de.stat([1.0, None, 3.0, -2.0]) == {"avg": 0.67, "min": -2.0, "max": 3.0}
    assert de.stat([None]) == {"avg": None, "min": None, "max": None}


def test_merge_drops_board_meeting_shadowing_results_and_collapses_period_duplicates():
    rows = [cal("TCS", "quarterly_results", D(2026, 10, 9), "Q2 FY27"), cal("TCS", "quarterly_results", D(2026, 10, 9), None),
            cal("TCS", "board_meeting", D(2026, 10, 9)), cal("INFY", "board_meeting", D(2026, 10, 9))]
    ev = de.merge_events(rows, [], D(2026, 10, 1), D(2026, 10, 31))
    assert [(e["symbol"], e["type"]) for e in ev] == [("INFY", "BOARD"), ("TCS", "RESULTS")]
    assert ev[1]["detail"] == "Board meeting on financial results, Q2 FY27" and ev[1]["timing"] is None


def test_merge_keeps_board_and_ex_date_separate_and_splits_record_date():
    cal_rows = [cal("VEDL", "dividend", D(2026, 10, 8))]
    acts = [act("VEDL", "DIVIDEND", D(2026, 10, 30), D(2026, 10, 30), dividend_amount=Decimal("16"), action_subtype="INTERIM"),
            act("IGL", "DIVIDEND", D(2026, 10, 2), D(2026, 10, 3), dividend_amount=Decimal("1.5"))]
    ev = de.merge_events(cal_rows, acts, D(2026, 10, 1), D(2026, 10, 31))
    key = [(e["date"].day, e["symbol"], e["timing"]) for e in ev]
    assert key == [(2, "IGL", "ex"), (3, "IGL", "rec"), (8, "VEDL", "board"), (30, "VEDL", "ex")]     # no 'rec' twin for VEDL
    by = {(e["symbol"], e["timing"]): e for e in ev}
    assert by[("VEDL", "ex")]["detail"] == "Dividend ₹16 a share (interim)"
    assert by[("IGL", "rec")]["detail"] == "Record date, Dividend ₹1.5 a share"
    assert by[("VEDL", "board")]["detail"] == "Board meeting to consider a dividend"


def test_merge_excludes_non_equity_actions_other_events_and_out_of_month_days():
    acts = [act("706GS2046", "INTEREST_PAYMENT", D(2026, 10, 9)), act("X", "DISTRIBUTION", D(2026, 10, 9)),
            act("X", "OTHER", D(2026, 10, 9)),
            act("OLD", "BONUS", D(2026, 9, 30), D(2026, 10, 1), ratio="1:1")]       # ex outside, record inside
    ev = de.merge_events([cal("Z", "other", D(2026, 10, 9)), cal("Z", "quarterly_results", D(2026, 11, 1))], acts,
                         D(2026, 10, 1), D(2026, 10, 31))
    assert [(e["symbol"], e["type"], e["timing"]) for e in ev] == [("OLD", "BONUS", "rec")]


def test_split_and_rights_details():
    ev = de.merge_events([], [act("BLSE", "SPLIT", D(2026, 10, 6), face_value_pre=Decimal("10"), face_value_post=Decimal("5")),
                              act("NATCOPHARM", "RIGHTS", D(2026, 10, 1), ratio="2:21")], D(2026, 10, 1), D(2026, 10, 31))
    assert [e["detail"] for e in ev] == ["Rights issue 2:21", "Split, face value ₹10 → ₹5"]


def test_holiday_rows_flag_muhurat():
    out = de.holiday_rows([{"holiday_date": D(2026, 11, 10), "description": "Diwali-Balipratipada"},
                           {"holiday_date": D(2026, 11, 8), "description": "Diwali Laxmi Pujan*"}])
    assert out == [{"date": D(2026, 11, 8), "description": "Diwali Laxmi Pujan", "muhurat": True},
                   {"date": D(2026, 11, 10), "description": "Diwali-Balipratipada", "muhurat": False}]


# ── routes (fake connection) ─────────────────────────────────────────────────

class _Conn:
    def __init__(self, db):
        self.db, self.calls = db, []

    async def fetch(self, q, *a):
        self.calls.append((q, a))
        for marker, key in (("FROM nidp.event_calendar\n     WHERE event_date", "cal"), ("nidp.corporate_actions\n     WHERE (ex_date", "acts"),
                            ("nidp.nse_holidays", "hols"), ("nidp.index_eod", "idx"), ("nidp.index_constituents\n     WHERE index_name", "n50"),
                            ("nidp.security_reference_daily", "fno"), ("WITH latest", "ind"),
                            ("FROM nidp.event_calendar\n     WHERE symbol", "occ_cal"), ("FROM nidp.corporate_actions\n     WHERE symbol", "occ_act"),
                            ("nidp.prices_eod", "bars")):
            if marker in q:
                return self.db.get(key, [])
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
        monkeypatch.setattr(de, "get_pool", _get_pool)
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

        app.include_router(de.router, prefix="/v1")
        return TestClient(app), pool
    return _make


MONTH_DB = {
    "cal": [cal("TCS", "quarterly_results", D(2026, 10, 9), "Q2 FY27", "Tata Consultancy Services",
                datetime(2026, 9, 28, 12, 0, tzinfo=timezone.utc)),
            cal("PERSISTENT", "quarterly_results", D(2026, 10, 21), None, "Persistent Systems"),
            cal("SMALLCO", "quarterly_results", D(2026, 10, 22), None, "Small Co"),
            cal("Z", "other", D(2026, 10, 9))],
    "acts": [act("INFY", "DIVIDEND", D(2026, 10, 27), D(2026, 10, 27), dividend_amount=Decimal("23"))],
    "hols": [{"holiday_date": D(2026, 10, 20), "description": "Dussehra"}],
    "idx": [{"as_of_date": D(2026, 10, 19), "pct_change": Decimal("-0.39")}],
    "n50": [{"symbol": "TCS"}, {"symbol": "INFY"}],
    "fno": [{"symbol": "TCS", "fno_eligible": True}, {"symbol": "INFY", "fno_eligible": True},
            {"symbol": "PERSISTENT", "fno_eligible": True}, {"symbol": "SMALLCO", "fno_eligible": False}],
    "ind": [{"symbol": "TCS", "industry": "Information Technology", "company_name": "Tata Consultancy Services"},
            {"symbol": "INFY", "industry": "Information Technology", "company_name": "Infosys"}],
}


def test_calendar_fno_default_filters_universe_and_fills_sector_name_and_flags(make_client):
    c, pool = make_client(MONTH_DB)
    r = c.get("/v1/desk/events-calendar?month=2026-10", headers=H)
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["month"] == "2026-10" and d["universe"] == "fno"
    assert [(e["symbol"], e["type"]) for e in d["events"]] == [("TCS", "RESULTS"), ("PERSISTENT", "RESULTS"), ("INFY", "DIVIDEND")]
    tcs = d["events"][0]
    assert tcs["sector"] == "Information Technology" and tcs["universe"] == {"n50": True, "fno": True}
    assert tcs["announced_at"].startswith("2026-09-28") and tcs["date"] == "2026-10-09" and tcs["timing"] is None
    assert d["events"][1]["universe"] == {"n50": False, "fno": True} and d["events"][1]["sector"] is None
    assert d["events"][1]["name"] == "Persistent Systems"
    assert d["holidays"] == [{"date": "2026-10-20", "description": "Dussehra", "muhurat": False}]
    assert d["index_closes"] == [{"date": "2026-10-19", "pct": -0.39}]
    assert any("INTEREST_PAYMENT" in g for g in d["gaps"]) and any("'other'" in g for g in d["gaps"])
    assert d["count"] == 3
    # the month bounds reached the SQL
    assert pool.conn.calls[0][1] == (D(2026, 10, 1), D(2026, 10, 31))


def test_calendar_n50_and_all(make_client):
    c, _ = make_client(MONTH_DB)
    n50 = c.get("/v1/desk/events-calendar?month=2026-10&universe=n50", headers=H).json()
    assert [e["symbol"] for e in n50["events"]] == ["TCS", "INFY"]
    allu = c.get("/v1/desk/events-calendar?month=2026-10&universe=all", headers=H).json()
    assert [e["symbol"] for e in allu["events"]] == ["TCS", "PERSISTENT", "SMALLCO", "INFY"]
    assert allu["events"][2]["universe"]["fno"] is False


def test_calendar_empty_fno_master_is_null_flag_and_a_stated_gap_not_a_guess(make_client):
    db = dict(MONTH_DB, fno=[])
    c, _ = make_client(db)
    fno = c.get("/v1/desk/events-calendar?month=2026-10", headers=H).json()
    assert fno["events"] == [] and any("F&O master" in g for g in fno["gaps"])
    allu = c.get("/v1/desk/events-calendar?month=2026-10&universe=all", headers=H).json()
    assert allu["events"][0]["universe"]["fno"] is None


def test_calendar_empty_month_is_200(make_client):
    c, _ = make_client({})
    r = c.get("/v1/desk/events-calendar?month=2026-12&universe=all", headers=H)
    assert r.status_code == 200 and r.json()["events"] == [] and r.json()["holidays"] == []


@pytest.mark.parametrize("qs", ["", "?month=2026-13", "?month=abc", "?month=2026-10&universe=nse"])
def test_calendar_bad_params_400(make_client, qs):
    c, _ = make_client({})
    assert c.get("/v1/desk/events-calendar" + qs, headers=H).status_code in (400,)


def test_calendar_needs_api_key(make_client):
    c, _ = make_client({})
    assert c.get("/v1/desk/events-calendar?month=2026-10").status_code in (401, 403)


def test_history_results_from_calendar_dates_with_coverage(make_client):
    # prices from 2026-01-05; one occurrence before coverage, two inside
    b = bars([100, 104.5, 100.32, 100, 100, 100, 109.725, 110, 111, 112, 113, 114, 115],
             prevs=[None, 100, 104.5, 100.32, 100, 100, 100, 109.725, 110, 111, 112, 113, 114])
    db = {"occ_cal": [{"d": D(2026, 1, 6)}, {"d": D(2026, 1, 9)}, {"d": D(2025, 7, 10)}], "bars": b}
    c, pool = make_client(db)
    d = c.get("/v1/desk/events-calendar/history?symbol=tcs&type=results", headers=H).json()
    assert d["symbol"] == "TCS" and d["type"] == "RESULTS" and d["coverage_from"] == "2026-01-05"
    assert d["n"] == 2                                  # 2025-07-10 is before the prices and is not counted
    o = {x["date"]: x for x in d["occurrences"]}
    assert o["2026-01-06"]["event_day_pct"] == 4.5 and o["2026-01-06"]["d1_pct"] == -4.0 and o["2026-01-06"]["w1_pct"] == 5.0
    assert o["2026-01-09"]["event_day_pct"] == 0.0 and o["2026-01-09"]["w1_pct"] is not None
    assert d["stats"]["event_day"]["max"] == 4.5 and d["stats"]["d1"]["min"] is not None
    assert "not a forecast" in d["basis"] and "2026-01-05" in d["basis"]
    assert pool.conn.calls[0][1][:2] == ("TCS", "quarterly_results")


def test_history_dividend_uses_ex_dates_and_no_prices_means_n_zero(make_client):
    c, pool = make_client({"occ_act": [{"d": D(2026, 3, 2)}], "bars": []})
    d = c.get("/v1/desk/events-calendar/history?symbol=INFY&type=DIVIDEND", headers=H).json()
    assert d["n"] == 0 and d["occurrences"] == [] and d["coverage_from"] is None
    assert d["stats"]["event_day"] == {"avg": None, "min": None, "max": None}
    assert pool.conn.calls[0][1][:2] == ("INFY", "DIVIDEND")


@pytest.mark.parametrize("qs", ["?symbol=TCS&type=NOPE", "?type=RESULTS", "?symbol=TCS"])
def test_history_bad_params_400(make_client, qs):
    c, _ = make_client({})
    assert c.get("/v1/desk/events-calendar/history" + qs, headers=H).status_code == 400
