"""DaaS /v1/desk/events-calendar/expectations (the desk's "results today & tomorrow" board).

No live Postgres. Every fixture is MOCK — not real data. Real-data runs are in test_reports/desk_results_today_20261021.md.
Quarter fixtures come from test_daas_desk_expectation.py (hand-computable numbers).
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest
from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from nidp.services.daas_api.routers import desk_expectation as dx
from nidp.tests.services.test_daas_desk_expectation import H, rows_for, universe_rows

D = date
UTC = timezone.utc
IST = dx.IST
TODAY = D(2026, 10, 21)
PURPOSE = "To consider and approve the financial results for the period ended September 30, 2026"


def cal(sym, day, name=None, purpose=PURPOSE):
    return {"symbol": sym, "company_name": name or f"{sym} Ltd", "event_date": day, "period": None, "purpose": purpose, "intimated_at": None}


def filing(sym, hour_ist=14, minute=0, day=TODAY, subject="Outcome of Board Meeting"):
    fa = datetime(day.year, day.month, day.day, hour_ist, minute, tzinfo=IST)
    return {"ticker_symbol": sym, "filed_at": fa.astimezone(UTC), "subject": subject, "attachment_url": "https://nsearchives.nseindia.com/o.pdf"}


class _Conn:
    def __init__(self, db):
        self.db = db
        self.calls = []

    async def fetch(self, q, *a):
        self.calls.append((q, a))
        if q == dx.BATCH_EVENT_SQL:
            lo, hi = a
            return [r for r in self.db["cal"] if lo <= r["event_date"] <= hi]
        if q == dx.N50_SQL:
            return [{"symbol": s} for s in self.db.get("n50", [])]
        if q == dx.FNO_SQL:
            return [{"symbol": s, "fno_eligible": True} for s in self.db.get("fno", [])]
        if q == dx.INDUSTRY_SQL:
            return [{"symbol": s, "industry": i, "company_name": f"{s} Industries"} for s, i in self.db.get("ind", {}).items() if s in a[0]]
        if q == dx.QUARTERS_SQL:
            return self.db["quarters"]
        if q == dx.FILING_SQL:
            return self.db.get("filings", [])
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

    def _make(db, today=TODAY):
        dx._cache.update({"at": 0.0, "value": None})
        pool = _Pool(db)

        async def _get_pool():
            return pool
        monkeypatch.setattr(dx, "get_pool", _get_pool)
        monkeypatch.setattr(dx, "_today", lambda: today)
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

        app.include_router(dx.router, prefix="/v1")
        client = TestClient(app)
        client.pool = pool
        return client
    return _make


URL = "/v1/desk/events-calendar/expectations"
Q_FULL = rows_for("DECL")                            # 8 quarters through Sep 2026: the target quarter is stored (declared)
Q_PRE = rows_for("PEND", drop=(7,))                  # through Jun 2026: Sep 2026 not stored yet
Q_THIN = rows_for("THIN", drop=(0, 1, 2))            # 5 quarters only
BASE = Q_FULL + Q_PRE + Q_THIN + universe_rows(150)


def get(c, qs, expect=200):
    r = c.get(URL + qs, headers=H)
    assert r.status_code == expect, r.text
    return r.json()


# ── TC-1..3: the window ──────────────────────────────────────────────────────

def test_window_reads_only_results_meetings_inside_it(make_client):
    c = make_client({"cal": [cal("DECL", D(2026, 10, 20)), cal("PEND", TODAY), cal("DECL", D(2026, 10, 23))], "quarters": BASE})
    out = get(c, "?from=2026-10-21&to=2026-10-22&universe=all")
    assert [e["symbol"] for e in out["events"]] == ["PEND"] and out["events"][0]["event_date"] == "2026-10-21"
    q, args = next(x for x in c.pool.conn.calls if x[0] == dx.BATCH_EVENT_SQL)
    assert "event_type = 'quarterly_results'" in q and args == (D(2026, 10, 21), D(2026, 10, 22))


def test_three_day_window_accepted_four_days_rejected(make_client):
    c = make_client({"cal": [], "quarters": BASE})
    assert get(c, "?from=2026-10-21&to=2026-10-23")["count"] == 0
    assert c.get(URL + "?from=2026-10-21&to=2026-10-24", headers=H).status_code == 400


@pytest.mark.parametrize("qs", ["?from=2026-10-22&to=2026-10-21", "?from=21-10-2026&to=2026-10-22", "?from=2026-02-30&to=2026-03-01",
                                "?from=2026-10-21&to=2026-10-22&universe=nifty", "?from=2026-10-21", ""])
def test_bad_window_or_universe_is_400(make_client, qs):
    c = make_client({"cal": [], "quarters": BASE})
    assert c.get(URL + qs, headers=H).status_code == 400
    assert not c.pool.conn.calls                      # rejected before any query


# ── TC-4: universes, names, sector ───────────────────────────────────────────

def test_universe_filters_and_names_and_sector(make_client):
    db = {"cal": [cal("DECL", TODAY, None), cal("PEND", TODAY, "Pending Co"), cal("THIN", TODAY)], "quarters": BASE,
          "n50": ["DECL"], "fno": ["DECL", "PEND"], "ind": {"DECL": "IT", "PEND": "Banks"}}
    c = make_client(db)
    assert [e["symbol"] for e in get(c, "?from=2026-10-21&to=2026-10-21&universe=all")["events"]] == ["DECL", "THIN", "PEND"]   # THIN has the target quarter stored: declared, figures first
    fno = get(c, "?from=2026-10-21&to=2026-10-21&universe=fno")
    assert sorted(e["symbol"] for e in fno["events"]) == ["DECL", "PEND"]
    n50 = get(c, "?from=2026-10-21&to=2026-10-21&universe=n50")
    assert [e["symbol"] for e in n50["events"]] == ["DECL"]
    e = next(e for e in fno["events"] if e["symbol"] == "PEND")
    assert e["name"] == "Pending Co" and e["sector"] == "Banks" and e["universe"] == {"n50": False, "fno": True}


# ── TC-5 / TC-13: declared with stored figures; batch == single endpoint ─────

def test_declared_with_stored_figures_matches_the_single_endpoint_maths(make_client):
    c = make_client({"cal": [cal("DECL", D(2026, 10, 8))], "quarters": BASE, "fno": ["DECL"]})
    out = get(c, "?from=2026-10-08&to=2026-10-09")
    e = out["events"][0]
    assert e["status"] == "declared" and e["filed_state"] == "figures" and e["filing"] is None
    models = dx.build_models(BASE)
    ref = dx.answer(models, "DECL", D(2026, 10, 8), PURPOSE, TODAY, [])
    got = {m["key"]: m for m in e["metrics"]}
    for m in ref["metrics"]:
        for k in ("expected", "filed", "vs_mid_pct", "within_band", "reliable", "same_quarter_last_year", "previous_quarter"):
            assert got[m["key"]][k] == m[k], (m["key"], k)
    assert got["revenue"]["filed"]["value"] == 145.6 and got["revenue"]["vs_mid_pct"] is not None
    assert e["compared_with"] == "vs Nivesh baseline, not vs consensus"


def test_no_leakage_expectation_uses_only_what_was_known_before_the_filing(make_client):
    c = make_client({"cal": [cal("DECL", D(2026, 10, 8))], "quarters": BASE, "fno": ["DECL"]})
    e = get(c, "?from=2026-10-08&to=2026-10-08")["events"][0]
    filed_known = dx.build_store(BASE)["DECL"][True][D(2026, 9, 30)]["known_at"]
    assert e["expected_as_of"] == filed_known.isoformat()


# ── TC-6 / TC-7 / TC-8: today's meetings and the filing evidence ─────────────

def test_today_with_a_filing_but_no_stored_figures_is_declared_pending_and_invents_nothing(make_client):
    c = make_client({"cal": [cal("PEND", TODAY)], "quarters": BASE, "fno": ["PEND"], "filings": [filing("PEND")]})
    out = get(c, "?from=2026-10-21&to=2026-10-22")
    e = out["events"][0]
    assert e["status"] == "declared" and e["filed_state"] == "pending"
    assert e["filing"]["subject"] == "Outcome of Board Meeting" and e["filing"]["filed_at"].startswith("2026-10-21T14:00:00+05:30")
    assert all(m["filed"] is None and m["vs_mid_pct"] is None and m["within_band"] is None for m in e["metrics"])
    assert any(m["expected"] for m in e["metrics"])             # the expectation is still shown
    assert any("not in the stored results yet" in g for g in e["gaps"])
    assert out["counts"] == {"declared_figures": 0, "declared_pending": 1, "upcoming": 0}


def test_today_without_a_filing_is_still_upcoming(make_client):
    c = make_client({"cal": [cal("PEND", TODAY)], "quarters": BASE, "fno": ["PEND"], "filings": []})
    e = get(c, "?from=2026-10-21&to=2026-10-21")["events"][0]
    assert e["status"] == "upcoming" and e["filed_state"] is None and e["filing"] is None


def test_tomorrow_is_upcoming_even_if_a_filing_dated_today_exists(make_client):
    c = make_client({"cal": [cal("PEND", D(2026, 10, 22))], "quarters": BASE, "fno": ["PEND"], "filings": [filing("PEND")]})
    e = get(c, "?from=2026-10-21&to=2026-10-22")["events"][0]
    assert e["status"] == "upcoming" and e["filing"] is None
    assert not any(a[0] == dx.FILING_SQL for a in c.pool.conn.calls)       # only today's symbols are looked up


def test_filing_query_matches_only_the_outcome_subject_exactly():
    sql = dx.FILING_SQL
    assert "lower(btrim(subject)) = 'outcome of board meeting'" in sql
    assert "ILIKE" not in sql.upper() and "%result" not in sql.lower() and "source = 'NSE_ANN'" in sql


# ── TC-9 / TC-10: IST boundaries ─────────────────────────────────────────────

def test_today_is_the_ist_date_not_the_utc_date(monkeypatch):
    class FakeDT(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 10, 21, 18, 40, tzinfo=UTC).astimezone(tz)        # 00:10 IST on 22 Oct
    monkeypatch.setattr(dx, "datetime", FakeDT)
    assert dx._today() == D(2026, 10, 22)


def test_filing_window_is_the_ist_meeting_day():
    lo, hi = dx.ist_day_window(TODAY)
    assert lo == datetime(2026, 10, 20, 18, 30, tzinfo=UTC) and hi == datetime(2026, 10, 21, 18, 30, tzinfo=UTC)
    late = filing("PEND", 23, 50)                 # 23:50 IST on the meeting day → counts
    after = filing("PEND", 0, 5, day=D(2026, 10, 22))          # 00:05 IST next day → does not
    assert dx.pick_filing([late], "PEND", TODAY)["filed_at"].startswith("2026-10-21T23:50:00+05:30")
    assert dx.pick_filing([after], "PEND", TODAY) is None
    early = filing("PEND", 0, 5)                   # 00:05 IST on the meeting day → counts
    assert dx.pick_filing([early], "PEND", TODAY) is not None
    assert dx.pick_filing([late], "OTHER", TODAY) is None


def test_the_earliest_filing_of_the_day_is_the_one_reported():
    rows = [filing("PEND", 9), filing("PEND", 17)]
    assert dx.pick_filing(sorted(rows, key=lambda r: r["filed_at"]), "PEND", TODAY)["filed_at"].startswith("2026-10-21T09:00")


# ── TC-11 / TC-12: ordering, thin history ────────────────────────────────────

def test_order_is_figures_then_pending_then_upcoming_then_date_then_symbol(make_client):
    db = {"cal": [cal("PEND", D(2026, 10, 22)), cal("AAA", TODAY), cal("PEND", TODAY), cal("DECL", D(2026, 10, 21))],
          "quarters": BASE + rows_for("AAA", drop=(7,)), "fno": ["PEND", "DECL", "AAA"], "filings": [filing("PEND")]}
    out = get(make_client(db), "?from=2026-10-21&to=2026-10-22")
    assert [(e["symbol"], e["event_date"], e["filed_state"]) for e in out["events"]] == [
        ("DECL", "2026-10-21", "figures"), ("PEND", "2026-10-21", "pending"), ("AAA", "2026-10-21", None), ("PEND", "2026-10-22", None)]
    assert out["counts"] == {"declared_figures": 1, "declared_pending": 1, "upcoming": 2}


def test_thin_history_keeps_its_unreliable_flag_and_note(make_client):
    c = make_client({"cal": [cal("THIN", D(2026, 10, 22))], "quarters": BASE, "fno": ["THIN"]})
    e = get(c, "?from=2026-10-22&to=2026-10-22")["events"][0]
    for m in e["metrics"]:
        assert m["expected"] is None and m["reliable"] is False and m["note"]


# ── shape: compact, shared blocks once, no sentiment words ───────────────────

def test_compact_shape_has_shared_method_block_and_no_per_event_evidence(make_client):
    c = make_client({"cal": [cal("PEND", TODAY)], "quarters": BASE, "fno": ["PEND"]})
    out = get(c, "?from=2026-10-21&to=2026-10-21")
    assert set(out) == {"from", "to", "universe", "as_of", "count", "counts", "label", "events", "method", "sources", "gaps"}
    assert set(out["method"]) == {"name", "formula", "by_metric"} and set(out["method"]["by_metric"]) == {"revenue", "pat"}
    assert out["as_of"] == "2026-10-21" and out["label"].startswith("A baseline from the company's own published quarters")
    e = out["events"][0]
    assert "evidence" not in e and e["id"] == "2026-10-21|PEND|RESULTS|mtg"
    assert {m["key"] for m in e["metrics"]} == {"revenue", "pat", "eps"}
    text = str(out).lower()
    for word in ("bullish", "bearish", "beat", "miss"):
        assert word not in text.replace("beat the naive", "")
    assert any("Trendlyne / Screener" in g for g in out["gaps"])


def test_the_universe_models_are_built_once_for_the_whole_batch(make_client):
    c = make_client({"cal": [cal("PEND", TODAY), cal("AAA", TODAY), cal("DECL", TODAY)], "quarters": BASE + rows_for("AAA"), "fno": ["PEND", "AAA", "DECL"]})
    get(c, "?from=2026-10-21&to=2026-10-21")
    assert sum(1 for q, _ in c.pool.conn.calls if q == dx.QUARTERS_SQL) == 1
